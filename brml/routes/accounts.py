"""注册、登录、密码、邀请码与用户管理路由。"""

from __future__ import annotations

import re
import sqlite3
from urllib.parse import parse_qs, quote, urlsplit

from flask import flash, g, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from brml.auth import generate_invite_code, generate_temporary_password, login_required, role_required
from brml.avatars import avatar_dir, avatar_meta, is_valid_avatar_key, save_uploaded_avatar
from brml.db import execute, get_db, query_all, query_one
from brml.finance import fetch_transactions, member_income_stats, summary
from brml.i18n import SUPPORTED_LOCALES, translate
from brml.timeutils import now

# 登录/注册共用的邮箱校验：与浏览器 type=email 一致的最低限度检查，
# 服务端永远兜底（前端 novalidate + 自带提示，见模板）。
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# 不回跳这些自身页面，避免登录/注册循环。
NEXT_BLOCKLIST = ("/login", "/register", "/logout")


def _active_users() -> list:
    """返回未删除用户（用于后台记账的会员下拉框）。"""
    return query_all(
        "select id, display_name from users where is_deleted = 0 order by display_name"
    )


def register_routes(app) -> None:
    def _same_site_path(candidate: str | None) -> str | None:
        """把回跳候选值归一化为站内相对路径；站外地址一律拒绝。

        接受 ``/board/new``、``/board/new?x=1`` 以及同站绝对 URL
        （后者用于 Referer 兜底），拒绝 ``//evil.example.com`` 与其它协议。
        """
        if not candidate:
            return None
        candidate = candidate.strip()
        if not candidate or candidate.startswith("//"):
            return None
        if candidate.startswith("/"):
            path = candidate
        else:
            parsed = urlsplit(candidate)
            if parsed.scheme not in ("http", "https") or parsed.netloc != request.host:
                return None
            path = parsed.path or "/"
            if parsed.query:
                path = f"{path}?{parsed.query}"
        bare = path.split("?", 1)[0]
        if bare in NEXT_BLOCKLIST or bare.startswith("/account/password"):
            return None
        return path

    def _referer_next() -> str | None:
        """从来源页推导回跳目标，作为入口没写 ``?next=`` 时的兜底。

        - 来源页是站内普通页面 → 回该页；
        - 来源页是 ``/login?next=...`` 或 ``/register?next=...`` → 继续沿用里面的 next，
          这样 登录 ⇄ 注册 互跳时回跳地址不会丢。
        """
        referer = request.referrer
        if not referer:
            return None
        parsed = urlsplit(referer)
        if parsed.netloc != request.host:
            return None
        if parsed.path in ("/login", "/register"):
            carried = (parse_qs(parsed.query).get("next") or [""])[0]
            return _same_site_path(carried)
        return _same_site_path(referer)

    def safe_next_url() -> str | None:
        """登录后回跳地址：优先表单/查询参数，其次同站来源页。

        Referer 兜底让「由 login_required 触发的裸 /login 跳转」也能回到原页，
        即使入口模板忘了写 ``?next=``（调研报告 A-3 / T7）。
        """
        explicit = request.form.get("next") or request.args.get("next")
        target = _same_site_path(explicit)
        if target:
            return target
        return _referer_next()

    def _login_url(next_url: str | None) -> str:
        """登录地址：带 next 时显式拼接（不依赖 url_for 对 None 的处理）。"""
        base = url_for("login")
        return f"{base}?next={quote(next_url, safe='')}" if next_url else base

    def safe_stay_url(endpoint: str) -> str:
        """表单处理后的回跳地址：带 next 时回到指定页面，否则回到默认端点。"""
        return safe_next_url() or url_for(endpoint)

    # ----- 登录、账号与后台用户管理 -----

    @app.route("/register", methods=("GET", "POST"))
    def register():
        next_url = safe_next_url()
        form_values = {"display_name": "", "email": "", "invite_code": ""}
        if request.method == "POST":
            display_name = (request.form.get("display_name") or "").strip()
            email = (request.form.get("email") or "").strip().lower()
            password = request.form.get("password") or ""
            invite_code = (request.form.get("invite_code") or "").strip().upper()
            form_values = {
                "display_name": display_name,
                "email": email,
                "invite_code": invite_code,
            }
            errors: dict[str, str] = {}
            if not display_name:
                errors["display_name"] = "auth2.err_display_name_required"
            elif len(display_name) > 40:
                errors["display_name"] = "auth2.err_display_name_long"
            if not email:
                errors["email"] = "auth2.err_email_required"
            elif not EMAIL_PATTERN.match(email):
                errors["email"] = "auth2.err_email_invalid"
            elif query_one("select id from users where email = ? and is_deleted = 0", (email,)):
                errors["email"] = "auth2.err_email_registered"
            if not password:
                errors["password"] = "auth2.err_password_required"
            elif len(password) < 8:
                errors["password"] = "auth2.err_password_short"
            elif len(password) > 128:
                errors["password"] = "auth2.err_password_long"
            invite = None
            if not invite_code:
                errors["invite_code"] = "auth2.err_invite_required"
            elif "email" not in errors:
                invite = query_one(
                    "select * from invite_codes where code = ? and used_by is null",
                    (invite_code,),
                )
                if not invite:
                    errors["invite_code"] = "auth2.err_invite_invalid"

            if not errors and invite:
                db = get_db()
                cur = db.execute(
                    """
                    insert into users (display_name, email, password_hash, role, created_at)
                    values (?, ?, ?, ?, ?)
                    """,
                    (
                        display_name,
                        email,
                        generate_password_hash(password, method="pbkdf2:sha256"),
                        invite["role"],
                        now(),
                    ),
                )
                db.execute(
                    "update invite_codes set used_by = ?, used_at = ? where id = ?",
                    (cur.lastrowid, now(), invite["id"]),
                )
                db.commit()
                flash(translate("flash.register_success"), "success")
                return redirect(_login_url(next_url))
            # 失败时保留已填内容（密码除外），错误逐字段显示在输入框下方。
            return render_template(
                "register.html",
                next_url=next_url,
                errors=errors,
                form_values=form_values,
            )
        return render_template("register.html", next_url=next_url, errors={}, form_values=form_values)

    @app.route("/login", methods=("GET", "POST"))
    def login():
        next_url = safe_next_url()
        email = ""
        if request.method == "POST":
            email = (request.form.get("email") or "").strip().lower()
            password = request.form.get("password") or ""
            errors: dict[str, str] = {}
            if not email:
                errors["email"] = "auth2.err_email_required"
            elif not EMAIL_PATTERN.match(email):
                errors["email"] = "auth2.err_email_invalid"
            if not password:
                errors["password"] = "auth2.err_password_required"
            user = None
            if not errors:
                user = query_one("select * from users where email = ? and is_deleted = 0", (email,))
                if not (user and check_password_hash(user["password_hash"], password)):
                    # 不区分邮箱/密码哪个错；邮箱仍回填，密码不保留。
                    errors["password"] = "auth2.err_credentials"
            if errors:
                return render_template(
                    "login.html",
                    next_url=next_url,
                    email=email,
                    errors=errors,
                )
            selected_locale = session.get("locale")
            session.clear()
            session.permanent = request.form.get("remember") == "1"
            if selected_locale in SUPPORTED_LOCALES:
                session["locale"] = selected_locale
            session["user_id"] = user["id"]
            flash(translate("flash.login_success"), "success")
            return redirect(next_url or url_for("index"))
        # 已登录用户不再展示登录表单，直接回到目标页（或首页）。
        if getattr(g, "user", None):
            return redirect(next_url or url_for("index"))
        return render_template("login.html", next_url=next_url, email=email, errors={})

    @app.route("/logout")
    def logout():
        selected_locale = session.get("locale")
        session.clear()
        if selected_locale in SUPPORTED_LOCALES:
            session["locale"] = selected_locale
        flash(translate("flash.logout_success"), "success")
        return redirect(safe_next_url() or url_for("index"))

    @app.route("/account/password", methods=("POST",))
    @login_required
    def account_password_update():
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        if not new_password or not confirm_password:
            flash(translate("flash.password_missing"), "error")
        elif new_password != confirm_password:
            flash(translate("flash.password_mismatch"), "error")
        elif not 8 <= len(new_password) <= 128:
            flash(translate("flash.password_invalid_length"), "error")
        else:
            execute(
                "update users set password_hash = ? where id = ?",
                (generate_password_hash(new_password, method="pbkdf2:sha256"), g.user["id"]),
            )
            flash(translate("flash.password_updated"), "success")
        return redirect(url_for("player_profile", user_id=g.user["id"]))

    @app.route("/account/avatar", methods=("GET", "POST"))
    @login_required
    def account_avatar():
        if request.method == "POST":
            avatar = request.form.get("avatar", "").strip()
            if avatar and not is_valid_avatar_key(avatar):
                flash(translate("flash.avatar_invalid"), "error")
            else:
                execute(
                    "update users set avatar = ?, avatar_upload = null where id = ?",
                    (avatar or None, g.user["id"]),
                )
                flash(translate("flash.avatar_updated"), "success")
            return redirect(safe_stay_url("account_avatar"))
        return render_template("avatar.html")

    @app.route("/account/avatar/upload", methods=("POST",))
    @login_required
    def account_avatar_upload():
        result = save_uploaded_avatar(g.user["id"], request.files.get("avatar_file"))
        if result == "missing":
            flash(translate("flash.avatar_missing"), "error")
        elif result == "type_invalid":
            flash(translate("flash.avatar_type_invalid"), "error")
        elif result == "invalid":
            flash(translate("flash.avatar_invalid"), "error")
        else:
            flash(translate("flash.avatar_updated"), "success")
        return redirect(safe_stay_url("account_avatar"))

    @app.route("/avatars/<path:filename>")
    def avatar_file(filename: str):
        return send_from_directory(avatar_dir(), filename)

    @app.route("/dashboard")
    @login_required
    def dashboard():
        return redirect(url_for("index"))

    @app.route("/admin/invites", methods=("GET", "POST"))
    @role_required("super_admin")
    def invites():
        if request.method == "POST":
            role = request.form["role"]
            if role not in ("referee", "user"):
                flash(translate("flash.invite_role_invalid"), "error")
            else:
                code = generate_invite_code(role)
                try:
                    execute(
                        "insert into invite_codes (code, role, created_by, created_at) values (?, ?, ?, ?)",
                        (code, role, g.user["id"], now()),
                    )
                    flash(translate("flash.invite_created", code=code), "success")
                except sqlite3.IntegrityError:
                    flash(translate("flash.invite_conflict"), "error")
            return redirect(url_for("admin_users", tab="invites"))
        return redirect(url_for("admin_users", tab="invites"))

    @app.route("/admin/users")
    @role_required("super_admin")
    def admin_users():
        tab = request.args.get("tab", "users")
        if tab not in ("users", "finance", "invites"):
            tab = "users"
        users = query_all(
            """
            select u.*
            from users u
            order by u.is_deleted asc, u.role asc, u.created_at desc
            """
        )
        active_count = sum(1 for user in users if not user["is_deleted"])
        context = {
            "users": users,
            "tab": tab,
            "active_count": active_count,
            "deleted_count": len(users) - active_count,
        }
        if tab == "finance":
            context.update(
                data=summary(),
                transactions=fetch_transactions(),
                members=_active_users(),
                member_stats=member_income_stats(),
            )
        elif tab == "invites":
            context["codes"] = query_all(
                """
                select i.*, u.display_name as used_by_name
                from invite_codes i left join users u on u.id = i.used_by
                order by i.created_at desc
                """
            )
        return render_template("admin.html", **context)

    @app.route("/admin/users/<int:user_id>/update", methods=("POST",))
    @role_required("super_admin")
    def admin_user_update(user_id: int):
        display_name = request.form.get("display_name", "").strip()
        role = request.form.get("role", "")
        user = query_one("select * from users where id = ?", (user_id,))
        if not user:
            flash(translate("flash.user_missing"), "error")
        elif not display_name:
            flash(translate("flash.user_name_required"), "error")
        elif user["is_deleted"]:
            flash(translate("flash.deleted_user_locked"), "error")
        elif user["role"] != "super_admin" and role not in ("referee", "user"):
            flash(translate("flash.user_role_invalid"), "error")
        elif user["role"] == "super_admin":
            execute("update users set display_name = ? where id = ?", (display_name, user_id))
            flash(translate("flash.user_updated", name=display_name), "success")
        else:
            execute("update users set display_name = ?, role = ? where id = ?", (display_name, role, user_id))
            flash(translate("flash.user_updated", name=display_name), "success")
        return redirect(url_for("admin_users"))

    @app.route("/admin/users/<int:user_id>/delete", methods=("POST",))
    @role_required("super_admin")
    def admin_user_delete(user_id: int):
        user = query_one("select * from users where id = ?", (user_id,))
        if not user:
            flash(translate("flash.user_missing"), "error")
        elif user["role"] == "super_admin":
            flash(translate("flash.super_admin_delete_denied"), "error")
        else:
            execute("update users set is_deleted = 1, deleted_at = ? where id = ?", (now(), user_id))
            flash(translate("flash.user_deleted", name=user["display_name"]), "success")
        return redirect(url_for("admin_users"))

    @app.route("/admin/users/<int:user_id>/reactivate", methods=("POST",))
    @role_required("super_admin")
    def admin_user_reactivate(user_id: int):
        user = query_one("select * from users where id = ?", (user_id,))
        if not user:
            flash(translate("flash.user_missing"), "error")
        elif not user["is_deleted"]:
            flash(translate("flash.user_already_active"), "error")
        else:
            execute(
                "update users set is_deleted = 0, deleted_at = null where id = ?",
                (user_id,),
            )
            flash(translate("flash.user_reactivated", name=user["display_name"]), "success")
        return redirect(url_for("admin_users", tab="users"))

    @app.route("/admin/users/<int:user_id>/reset-password", methods=("POST",))
    @role_required("super_admin")
    def admin_user_reset_password(user_id: int):
        user = query_one("select * from users where id = ?", (user_id,))
        if not user:
            flash(translate("flash.user_missing"), "error")
        elif user["is_deleted"]:
            flash(translate("flash.deleted_user_password_locked"), "error")
        elif user["role"] == "super_admin":
            flash(translate("flash.super_admin_password_locked"), "error")
        else:
            temporary_password = generate_temporary_password()
            execute(
                "update users set password_hash = ? where id = ?",
                (generate_password_hash(temporary_password, method="pbkdf2:sha256"), user_id),
            )
            flash(
                translate("flash.temporary_password", name=user["display_name"], password=temporary_password),
                "success",
            )
        return redirect(url_for("admin_users"))
