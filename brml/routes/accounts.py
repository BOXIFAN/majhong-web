"""注册、登录、密码、邀请码与用户管理路由。"""

from __future__ import annotations

import sqlite3

from flask import flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from brml.auth import generate_invite_code, generate_temporary_password, login_required, role_required
from brml.db import execute, get_db, query_all, query_one
from brml.finance import fetch_transactions, member_income_stats, summary
from brml.i18n import SUPPORTED_LOCALES, translate
from brml.timeutils import now


def _active_users() -> list:
    """返回未删除用户（用于后台记账的会员下拉框）。"""
    return query_all(
        "select id, display_name from users where is_deleted = 0 order by display_name"
    )


def register_routes(app) -> None:
    # ----- 登录、账号与后台用户管理 -----

    @app.route("/register", methods=("GET", "POST"))
    def register():
        if request.method == "POST":
            display_name = request.form["display_name"].strip()
            email = request.form["email"].strip().lower()
            password = request.form["password"]
            invite_code = request.form["invite_code"].strip().upper()
            invite = query_one(
                "select * from invite_codes where code = ? and used_by is null",
                (invite_code,),
            )
            error = None
            if not display_name or not email or not password:
                error = translate("flash.register_missing")
            elif not invite:
                error = translate("flash.invite_invalid")
            elif query_one("select id from users where email = ? and is_deleted = 0", (email,)):
                error = translate("flash.email_registered")

            if error:
                flash(error, "error")
            else:
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
                return redirect(url_for("login"))
        return render_template("register.html")

    @app.route("/login", methods=("GET", "POST"))
    def login():
        if request.method == "POST":
            email = request.form["email"].strip().lower()
            password = request.form["password"]
            user = query_one("select * from users where email = ? and is_deleted = 0", (email,))
            if user and check_password_hash(user["password_hash"], password):
                selected_locale = session.get("locale")
                session.clear()
                session.permanent = request.form.get("remember") == "1"
                if selected_locale in SUPPORTED_LOCALES:
                    session["locale"] = selected_locale
                session["user_id"] = user["id"]
                flash(translate("flash.login_success"), "success")
                return redirect(url_for("index"))
            flash(translate("flash.login_invalid"), "error")
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        selected_locale = session.get("locale")
        session.clear()
        if selected_locale in SUPPORTED_LOCALES:
            session["locale"] = selected_locale
        flash(translate("flash.logout_success"), "success")
        return redirect(url_for("index"))

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
