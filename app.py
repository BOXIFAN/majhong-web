"""BRML 联赛网站的 Flask 应用。

项目目前采用单文件后端：路由集中在 ``create_app`` 中，数据库兼容逻辑、
积分计算和演示数据位于其后。维护时应优先把业务规则保留在本文件的纯函数中，
模板只负责展示，避免同一套积分规则在多个页面重复实现。
"""

from __future__ import annotations

import csv
import functools
import io
import json
import math
import os
import secrets
import sqlite3
import string
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import (
    Flask,
    Response,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from brml.config import (
    ADMIN_PASSWORD_HASH,
    ADMIN_PASSWORD_MIGRATION,
    BASE_DIR,
    DATABASE,
    DEFAULT_MEETUP_VENUE,
    SEED_DEMO_DATA,
)
from brml.i18n import ROLE_LABELS, ROLES, TRANSLATIONS, get_locale, translate
from brml.scoring import (
    calculate_placements,
    calculate_rank_points,
    get_uma_points,
    placement_to_places,
)
from brml.rules import (
    DEFAULT_RULES,
    FIELD_LABELS,
    RULE_LABELS,
    normalize_rules,
    parse_rules_form,
)


def create_app() -> Flask:
    """创建并配置应用；所有路由在此注册，便于 WSGI 与测试复用。"""
    app = Flask(__name__, instance_relative_config=True)
    is_render = os.environ.get("RENDER", "false").lower() in {"1", "true", "yes", "on"}
    secure_cookie = os.environ.get(
        "SESSION_COOKIE_SECURE",
        "true" if is_render else "false",
    ).lower() in {"1", "true", "yes", "on"}
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-change-me"),
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=secure_cookie,
        SESSION_REFRESH_EACH_REQUEST=True,
    )
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    @app.before_request
    def load_user() -> None:
        # 这些 ensure_* 操作必须保持幂等，用来兼容没有独立迁移工具的旧数据库。
        ensure_database_initialized()
        ensure_user_soft_delete_columns()
        ensure_announcements_table()
        ensure_meetups_tables()
        ensure_admin_password()
        ensure_match_type_values()
        user_id = session.get("user_id")
        g.user = query_one("select * from users where id = ? and is_deleted = 0", (user_id,)) if user_id else None
        if user_id and g.user is None:
            session.clear()

    @app.context_processor
    def inject_globals() -> dict:
        season = current_season()
        locale = get_locale()
        return {
            "current_user": g.get("user"),
            "roles": ROLE_LABELS[locale],
            "current_season": season,
            "rule_labels": RULE_LABELS,
            "field_labels": FIELD_LABELS,
            "today_date": today_date(),
            "locale": locale,
            "t": translate,
            "match_type_label": match_type_label,
            "default_meetup_venue": DEFAULT_MEETUP_VENUE,
        }

    @app.cli.command("init-db")
    def init_db_command() -> None:
        init_db()
        print("Initialized the database.")

    # ----- 公共页面与活动报名 -----

    @app.route("/")
    def index():
        season = current_season()
        announcements = query_all(
            """
            select a.*, u.display_name as author_name
            from announcements a left join users u on u.id = a.author_id
            order by a.created_at desc, a.id desc
            """
        )
        season_match_count = 0
        if season:
            season_match_count = query_one(
                "select count(*) as c from matches where season_id = ?",
                (season["id"],),
            )["c"]
        current_member_count = query_one(
            "select count(*) as c from users where is_deleted = 0"
        )["c"]
        return render_template(
            "index.html",
            current_season=season,
            season_match_count=season_match_count,
            current_member_count=current_member_count,
            latest_announcement=announcements[0] if announcements else None,
            past_announcements=announcements[1:],
        )

    @app.route("/about")
    def about():
        return render_template("about.html")

    @app.route("/meetups")
    @login_required
    def meetups():
        auto_archive_expired_meetups()
        per_page = 8
        page = max(request.args.get("page", 1, type=int), 1)
        total = query_one("select count(*) as c from meetups")["c"]
        pages = max((total + per_page - 1) // per_page, 1)
        if page > pages:
            return redirect(url_for("meetups", page=pages))
        meetup_rows = query_all(
            """
            select m.*, u.display_name as creator_name, count(ms.id) as attendee_count
            from meetups m
            left join users u on u.id = m.created_by
            left join meetup_signups ms on ms.meetup_id = m.id
            group by m.id
            order by m.meetup_at desc, m.id desc
            limit ? offset ?
            """,
            (per_page, (page - 1) * per_page),
        )
        meetup_items = []
        for meetup in meetup_rows:
            item = dict(meetup)
            item["status"] = meetup_status(meetup)
            meetup_items.append(item)
        pagination = {
            "page": page,
            "pages": pages,
            "total": total,
            "has_prev": page > 1,
            "has_next": page < pages,
            "prev_page": page - 1,
            "next_page": page + 1,
        }
        return render_template("meetups.html", meetups=meetup_items, pagination=pagination)

    @app.route("/meetups/<int:meetup_id>")
    @login_required
    def meetup_detail(meetup_id: int):
        auto_archive_expired_meetups()
        meetup = query_one(
            """
            select m.*, u.display_name as creator_name
            from meetups m left join users u on u.id = m.created_by
            where m.id = ?
            """,
            (meetup_id,),
        )
        if not meetup:
            flash(translate("meetup.missing"), "error")
            return redirect(url_for("meetups"))
        attendees = query_all(
            """
            select ms.user_id, ms.created_at, u.display_name, u.role
            from meetup_signups ms join users u on u.id = ms.user_id
            where ms.meetup_id = ?
            order by ms.created_at asc, ms.id asc
            """,
            (meetup_id,),
        )
        eligible_users = []
        if g.user["role"] == "super_admin":
            eligible_users = query_all(
                """
                select u.id, u.display_name, u.role
                from users u
                where u.is_deleted = 0
                  and not exists (
                    select 1 from meetup_signups ms
                    where ms.meetup_id = ? and ms.user_id = u.id
                  )
                order by u.display_name
                """,
                (meetup_id,),
            )
        status = meetup_status(meetup)
        is_signed_up = any(attendee["user_id"] == g.user["id"] for attendee in attendees)
        return render_template(
            "meetup_detail.html",
            meetup=meetup,
            attendees=attendees,
            eligible_users=eligible_users,
            status=status,
            is_signed_up=is_signed_up,
        )

    @app.route("/admin/meetups/new", methods=("POST",))
    @role_required("super_admin")
    def meetup_new():
        meetup_at = parse_local_datetime(request.form.get("meetup_at", ""))
        signup_deadline = parse_local_datetime(request.form.get("signup_deadline", ""))
        venue = request.form.get("venue", "").strip() or DEFAULT_MEETUP_VENUE
        if not meetup_at or not signup_deadline:
            flash(translate("meetup.time_required"), "error")
        elif signup_deadline > meetup_at:
            flash(translate("meetup.deadline_order"), "error")
        else:
            timestamp = now()
            execute(
                "insert into meetups (meetup_at, signup_deadline, venue, created_by, created_at, updated_at) values (?, ?, ?, ?, ?, ?)",
                (meetup_at, signup_deadline, venue, g.user["id"], timestamp, timestamp),
            )
            flash(translate("meetup.created"), "success")
        return redirect(url_for("meetups"))

    @app.route("/admin/meetups/<int:meetup_id>/edit", methods=("GET", "POST"))
    @role_required("super_admin")
    def meetup_edit(meetup_id: int):
        meetup = query_one("select * from meetups where id = ?", (meetup_id,))
        if not meetup:
            flash(translate("meetup.missing"), "error")
            return redirect(url_for("meetups"))
        if request.method == "POST":
            meetup_at = parse_local_datetime(request.form.get("meetup_at", ""))
            signup_deadline = parse_local_datetime(request.form.get("signup_deadline", ""))
            venue = request.form.get("venue", "").strip() or DEFAULT_MEETUP_VENUE
            if not meetup_at or not signup_deadline:
                flash(translate("meetup.time_required"), "error")
            elif signup_deadline > meetup_at:
                flash(translate("meetup.deadline_order"), "error")
            else:
                execute(
                    "update meetups set meetup_at = ?, signup_deadline = ?, venue = ?, updated_at = ? where id = ?",
                    (meetup_at, signup_deadline, venue, now(), meetup_id),
                )
                flash(translate("meetup.updated"), "success")
                return redirect(url_for("meetup_detail", meetup_id=meetup_id))
        return render_template(
            "meetup_form.html",
            meetup=meetup,
            meetup_time=meetup["meetup_at"].replace(" ", "T")[:16],
            signup_deadline=meetup["signup_deadline"].replace(" ", "T")[:16],
            meetup_venue=meetup["venue"],
        )

    @app.route("/meetups/<int:meetup_id>/signup", methods=("POST",))
    @login_required
    def meetup_signup(meetup_id: int):
        auto_archive_expired_meetups()
        meetup = query_one("select * from meetups where id = ?", (meetup_id,))
        if not meetup:
            flash(translate("meetup.missing"), "error")
            return redirect(url_for("meetups"))
        if meetup_status(meetup) != "open":
            flash(translate("meetup.signup_closed"), "error")
            return redirect(url_for("meetup_detail", meetup_id=meetup_id))
        try:
            execute(
                "insert into meetup_signups (meetup_id, user_id, created_at) values (?, ?, ?)",
                (meetup_id, g.user["id"], now()),
            )
            flash(translate("meetup.signup_success"), "success")
        except sqlite3.IntegrityError:
            flash(translate("meetup.signup_duplicate"), "error")
        return redirect(url_for("meetup_detail", meetup_id=meetup_id))

    @app.route("/admin/meetups/<int:meetup_id>/archive", methods=("POST",))
    @role_required("super_admin")
    def meetup_archive(meetup_id: int):
        meetup = query_one("select id from meetups where id = ?", (meetup_id,))
        if not meetup:
            flash(translate("meetup.missing"), "error")
            return redirect(url_for("meetups"))
        execute(
            "update meetups set archived_at = coalesce(archived_at, ?), archived_by = coalesce(archived_by, ?), updated_at = ? where id = ?",
            (now(), g.user["id"], now(), meetup_id),
        )
        flash(translate("meetup.archived_success"), "success")
        return redirect(url_for("meetup_detail", meetup_id=meetup_id))

    @app.route("/admin/meetups/<int:meetup_id>/delete", methods=("POST",))
    @role_required("super_admin")
    def meetup_delete(meetup_id: int):
        meetup = query_one("select id from meetups where id = ?", (meetup_id,))
        if not meetup:
            flash(translate("meetup.missing"), "error")
            return redirect(url_for("meetups"))
        db = get_db()
        db.execute("delete from meetup_signups where meetup_id = ?", (meetup_id,))
        db.execute("delete from meetups where id = ?", (meetup_id,))
        db.commit()
        flash(translate("meetup.deleted_success"), "success")
        return redirect(url_for("meetups"))

    @app.route("/admin/meetups/<int:meetup_id>/attendees/add", methods=("POST",))
    @role_required("super_admin")
    def meetup_attendee_add(meetup_id: int):
        meetup = query_one("select id from meetups where id = ?", (meetup_id,))
        user_id = request.form.get("user_id", type=int)
        user = query_one("select id from users where id = ? and is_deleted = 0", (user_id,)) if user_id else None
        if not meetup:
            flash(translate("meetup.missing"), "error")
            return redirect(url_for("meetups"))
        if not user:
            flash(translate("meetup.member_missing"), "error")
        else:
            try:
                execute(
                    "insert into meetup_signups (meetup_id, user_id, created_at) values (?, ?, ?)",
                    (meetup_id, user_id, now()),
                )
                flash(translate("meetup.member_added"), "success")
            except sqlite3.IntegrityError:
                flash(translate("meetup.signup_duplicate"), "error")
        return redirect(url_for("meetup_detail", meetup_id=meetup_id))

    @app.route("/admin/meetups/<int:meetup_id>/attendees/<int:user_id>/remove", methods=("POST",))
    @role_required("super_admin")
    def meetup_attendee_remove(meetup_id: int, user_id: int):
        meetup = query_one("select id from meetups where id = ?", (meetup_id,))
        if not meetup:
            flash(translate("meetup.missing"), "error")
            return redirect(url_for("meetups"))
        signup = query_one(
            "select id from meetup_signups where meetup_id = ? and user_id = ?",
            (meetup_id, user_id),
        )
        if not signup:
            flash(translate("meetup.member_missing"), "error")
        else:
            execute("delete from meetup_signups where id = ?", (signup["id"],))
            flash(translate("meetup.member_removed"), "success")
        return redirect(url_for("meetup_detail", meetup_id=meetup_id))

    # ----- 对局、公告与静态辅助路由 -----

    @app.route("/matches")
    def matches():
        per_page = 20
        page = max(request.args.get("page", 1, type=int), 1)
        total = query_one("select count(*) as c from matches")["c"]
        pages = max((total + per_page - 1) // per_page, 1)
        if page > pages:
            return redirect(url_for("matches", page=pages))
        rows = query_all(
            """
            select m.*, u.display_name as referee_name
            from matches m left join users u on u.id = m.referee_id
            order by m.played_at desc, m.id desc limit ? offset ?
            """,
            (per_page, (page - 1) * per_page),
        )
        pagination = {
            "page": page,
            "pages": pages,
            "total": total,
            "has_prev": page > 1,
            "has_next": page < pages,
            "prev_page": page - 1,
            "next_page": page + 1,
        }
        return render_template("matches.html", matches=rows, pagination=pagination)

    @app.route("/admin/announcements", methods=("GET", "POST"))
    @role_required("super_admin")
    def announcements():
        if request.method == "POST":
            title = request.form.get("title", "").strip()
            content = request.form.get("content", "").strip()
            if not title or not content:
                flash(translate("announcement.required"), "error")
            else:
                timestamp = now()
                execute(
                    "insert into announcements (title, content, author_id, created_at, updated_at) values (?, ?, ?, ?, ?)",
                    (title, content, g.user["id"], timestamp, timestamp),
                )
                flash(translate("announcement.created"), "success")
                return redirect(url_for("announcements"))
        rows = query_all(
            """
            select a.*, u.display_name as author_name
            from announcements a left join users u on u.id = a.author_id
            order by a.created_at desc, a.id desc
            """
        )
        return render_template("announcements.html", announcements=rows)

    @app.route("/admin/announcements/<int:announcement_id>/edit", methods=("GET", "POST"))
    @role_required("super_admin")
    def announcement_edit(announcement_id: int):
        announcement = query_one("select * from announcements where id = ?", (announcement_id,))
        if not announcement:
            flash(translate("announcement.missing"), "error")
            return redirect(url_for("announcements"))
        if request.method == "POST":
            title = request.form.get("title", "").strip()
            content = request.form.get("content", "").strip()
            if not title or not content:
                flash(translate("announcement.required"), "error")
            else:
                execute(
                    "update announcements set title = ?, content = ?, updated_at = ? where id = ?",
                    (title, content, now(), announcement_id),
                )
                flash(translate("announcement.updated"), "success")
                return redirect(url_for("announcements"))
        return render_template("announcement_form.html", announcement=announcement)

    @app.route("/admin/announcements/<int:announcement_id>/delete", methods=("POST",))
    @role_required("super_admin")
    def announcement_delete(announcement_id: int):
        announcement = query_one("select id from announcements where id = ?", (announcement_id,))
        if not announcement:
            flash(translate("announcement.missing"), "error")
        else:
            execute("delete from announcements where id = ?", (announcement_id,))
            flash(translate("announcement.deleted"), "success")
        return redirect(url_for("announcements"))

    @app.route("/favicon.ico")
    def favicon():
        return redirect(url_for("static", filename="web_logo.jpg"))

    @app.route("/language/<locale>")
    def set_language(locale: str):
        if locale in SUPPORTED_LOCALES:
            session["locale"] = locale
        return redirect(request.referrer or url_for("index"))

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
        codes = query_all(
            """
            select i.*, u.display_name as used_by_name
            from invite_codes i left join users u on u.id = i.used_by
            order by i.created_at desc
            """
        )
        return render_template("invites.html", codes=codes)

    @app.route("/admin/users")
    @role_required("super_admin")
    def admin_users():
        users = query_all(
            """
            select u.*
            from users u
            order by u.is_deleted asc, u.role asc, u.created_at desc
            """
        )
        return render_template("admin_users.html", users=users)

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

    # ----- 赛季、成绩、排行榜与导出 -----

    @app.route("/seasons")
    def seasons():
        seasons_data = query_all("select * from seasons order by start_date desc, id desc")
        active_season = query_one("select * from seasons where status = 'active' order by id desc limit 1")
        if not active_season and seasons_data:
            active_season = seasons_data[0]
        active_rules = normalize_rules(json.loads(active_season["rules_json"])) if active_season else None
        past_seasons = [season for season in seasons_data if not active_season or season["id"] != active_season["id"]]
        return render_template(
            "seasons.html",
            seasons=seasons_data,
            active_season=active_season,
            active_rules=active_rules,
            past_seasons=past_seasons,
        )

    @app.route("/seasons/new", methods=("GET", "POST"))
    @role_required("super_admin")
    def season_new():
        source_id = request.args.get("copy")
        source = query_one("select * from seasons where id = ?", (source_id,)) if source_id else None
        rules = normalize_rules(json.loads(source["rules_json"])) if source else DEFAULT_RULES
        if request.method == "POST":
            name = request.form["name"].strip()
            status = request.form["status"]
            parsed_rules = parse_rules_form(request.form)
            if not name:
                flash(translate("flash.season_name_required"), "error")
            else:
                if status == "active":
                    execute("update seasons set status = 'archived' where status = 'active'")
                execute(
                    """
                    insert into seasons (name, status, start_date, rules_json, version, created_at, updated_at)
                    values (?, ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        name,
                        status,
                        request.form["start_date"],
                        json.dumps(parsed_rules, ensure_ascii=False),
                        now(),
                        now(),
                    ),
                )
                flash(translate("flash.season_created"), "success")
                return redirect(url_for("seasons"))
        return render_template("season_form.html", season=None, rules=rules)

    @app.route("/seasons/<int:season_id>")
    def season_detail(season_id: int):
        season = query_one("select * from seasons where id = ?", (season_id,))
        if not season:
            flash(translate("flash.season_missing"), "error")
            return redirect(url_for("seasons"))
        return render_template("season_detail.html", season=season, rules=normalize_rules(json.loads(season["rules_json"])))

    @app.route("/seasons/<int:season_id>/edit", methods=("GET", "POST"))
    @role_required("super_admin")
    def season_edit(season_id: int):
        season = query_one("select * from seasons where id = ?", (season_id,))
        if not season:
            flash(translate("flash.season_missing"), "error")
            return redirect(url_for("seasons"))
        rules = normalize_rules(json.loads(season["rules_json"]))
        if request.method == "POST":
            parsed_rules = parse_rules_form(request.form)
            if request.form["status"] == "active":
                execute("update seasons set status = 'archived' where status = 'active' and id != ?", (season_id,))
            execute(
                """
                update seasons
                set name = ?, status = ?, start_date = ?, rules_json = ?, version = version + 1, updated_at = ?
                where id = ?
                """,
                (
                    request.form["name"].strip(),
                    request.form["status"],
                    request.form["start_date"],
                    json.dumps(parsed_rules, ensure_ascii=False),
                    now(),
                    season_id,
                ),
            )
            execute(
                "insert into rule_versions (season_id, rules_json, changed_by, changed_at) values (?, ?, ?, ?)",
                (season_id, json.dumps(parsed_rules, ensure_ascii=False), g.user["id"], now()),
            )
            flash(translate("flash.season_updated"), "success")
            return redirect(url_for("season_detail", season_id=season_id))
        return render_template("season_form.html", season=season, rules=rules)

    @app.route("/seasons/<int:season_id>/delete", methods=("POST",))
    @role_required("super_admin")
    def season_delete(season_id: int):
        season = query_one("select * from seasons where id = ?", (season_id,))
        if not season:
            flash(translate("flash.season_missing"), "error")
            return redirect(url_for("seasons"))

        password = request.form.get("password", "")
        if not check_password_hash(g.user["password_hash"], password):
            flash(translate("flash.season_password_invalid"), "error")
            return redirect(url_for("season_detail", season_id=season_id))

        db = get_db()
        try:
            db.execute(
                "delete from match_entries where match_id in (select id from matches where season_id = ?)",
                (season_id,),
            )
            db.execute("delete from penalties where season_id = ?", (season_id,))
            db.execute("delete from matches where season_id = ?", (season_id,))
            db.execute("delete from rule_versions where season_id = ?", (season_id,))
            db.execute("delete from seasons where id = ?", (season_id,))
            db.commit()
        except Exception:
            db.rollback()
            raise

        flash(translate("flash.season_deleted", name=season["name"]), "success")
        return redirect(url_for("seasons"))

    @app.route("/matches/new", methods=("GET", "POST"))
    @role_required("super_admin", "referee")
    def match_new():
        season = current_season()
        if not season:
            flash(translate("flash.season_required"), "error")
            return redirect(url_for("seasons"))
        players = query_all("select * from users where role in ('referee', 'user') and is_deleted = 0 order by display_name")
        if request.method == "POST":
            result = create_match_from_form(season, request.form)
            if result["ok"]:
                flash(translate("flash.match_created"), "success")
                return redirect(url_for("match_detail", match_id=result["match_id"]))
            for error in result["errors"]:
                flash(error, "error")
        return render_template(
            "match_form.html",
            season=season,
            players=players,
            rules=normalize_rules(json.loads(season["rules_json"])),
            match_time=current_match_time(),
        )

    @app.route("/matches/<int:match_id>")
    def match_detail(match_id: int):
        match = query_one(
            """
            select m.*, s.name as season_name, u.display_name as referee_name
            from matches m
            join seasons s on s.id = m.season_id
            left join users u on u.id = m.referee_id
            where m.id = ?
            """,
            (match_id,),
        )
        if not match:
            flash(translate("flash.match_missing"), "error")
            return redirect(url_for("index"))
        entries = query_all(
            """
            select me.*, u.display_name
            from match_entries me join users u on u.id = me.user_id
            where me.match_id = ?
            order by me.placement asc, me.final_score desc
            """,
            (match_id,),
        )
        penalties = query_all(
            """
            select p.*, u.display_name
            from penalties p join users u on u.id = p.user_id
            where p.match_id = ?
            order by p.id
            """,
            (match_id,),
        )
        return render_template("match_detail.html", match=match, entries=entries, penalties=penalties)

    @app.route("/matches/<int:match_id>/edit", methods=("GET", "POST"))
    @role_required("super_admin")
    def match_edit(match_id: int):
        match = query_one(
            """
            select m.*, s.name as season_name, s.rules_json
            from matches m join seasons s on s.id = m.season_id
            where m.id = ?
            """,
            (match_id,),
        )
        if not match:
            flash(translate("flash.match_missing"), "error")
            return redirect(url_for("index"))
        entries = query_all(
            "select * from match_entries where match_id = ? order by id",
            (match_id,),
        )
        involved_ids = [entry["user_id"] for entry in entries]
        if involved_ids:
            placeholders = ",".join("?" for _ in involved_ids)
            players = query_all(
                f"""
                select * from users
                where is_deleted = 0 or id in ({placeholders})
                order by display_name
                """,
                tuple(involved_ids),
            )
        else:
            players = query_all("select * from users where is_deleted = 0 order by display_name")

        if request.method == "POST":
            result = parse_match_result_form(match, request.form)
            if result["ok"]:
                update_match_from_result(match_id, match, request.form, result)
                flash(translate("flash.match_updated"), "success")
                return redirect(url_for("match_detail", match_id=match_id))
            for error in result["errors"]:
                flash(error, "error")

        penalty_lookup = {
            row["user_id"]: row
            for row in query_all(
                """
                select user_id, sum(points) as points,
                       group_concat(penalty_type, ' / ') as penalty_type,
                       group_concat(reason, '；') as reason
                from penalties
                where match_id = ?
                group by user_id
                """,
                (match_id,),
            )
        }
        edit_rows = []
        for entry in entries:
            penalty = penalty_lookup.get(entry["user_id"])
            edit_rows.append({"entry": entry, "penalty": penalty})
        rules = normalize_rules(json.loads(match["rules_json"]))
        return render_template(
            "match_edit.html",
            match=match,
            match_time=match["played_at"].replace(" ", "T")[:16],
            rows=edit_rows,
            players=players,
            rules=rules,
        )

    @app.route("/matches/<int:match_id>/delete", methods=("POST",))
    @role_required("super_admin")
    def match_delete(match_id: int):
        match = query_one("select * from matches where id = ?", (match_id,))
        if not match:
            flash(translate("flash.match_delete_missing"), "error")
            return redirect(url_for("index"))

        db = get_db()
        db.execute("delete from penalties where match_id = ?", (match_id,))
        db.execute("delete from match_entries where match_id = ?", (match_id,))
        db.execute("delete from matches where id = ?", (match_id,))
        db.commit()
        flash(translate("flash.match_deleted"), "success")
        return redirect(url_for("leaderboard", season_id=match["season_id"]))

    @app.route("/leaderboard")
    def leaderboard():
        seasons_data = query_all("select * from seasons order by start_date desc, id desc")
        season_id = request.args.get("season_id", type=int)
        season = query_one("select * from seasons where id = ?", (season_id,)) if season_id else current_season()
        rows = get_leaderboard(season["id"]) if season else []
        finals_status = build_finals_status(season, rows, g.user) if season else None
        return render_template(
            "leaderboard.html",
            seasons=seasons_data,
            selected_season=season,
            rows=rows,
            finals_status=finals_status,
        )

    @app.route("/players/<int:user_id>")
    def player_profile(user_id: int):
        user = query_one("select * from users where id = ?", (user_id,))
        if not user:
            flash(translate("flash.player_missing"), "error")
            return redirect(url_for("leaderboard"))
        season = current_season()
        leaderboard = get_leaderboard(season["id"]) if season else []
        player_stats = next((row for row in leaderboard if row["user_id"] == user_id), None)
        per_page = 5
        page = max(request.args.get("page", 1, type=int), 1)
        history_total = query_one(
            "select count(*) as c from match_entries where user_id = ?",
            (user_id,),
        )["c"]
        history_pages = max((history_total + per_page - 1) // per_page, 1)
        if page > history_pages:
            return redirect(url_for("player_profile", user_id=user_id, page=history_pages))
        history = query_all(
            """
            select m.id as match_id, m.played_at, me.final_score, me.placement, me.rank_points
            from match_entries me join matches m on m.id = me.match_id
            where me.user_id = ?
            order by m.played_at desc, m.id desc limit ? offset ?
            """,
            (user_id, per_page, (page - 1) * per_page),
        )
        trend_history = query_all(
            """
            select m.id as match_id, m.played_at, me.final_score, me.placement, me.rank_points
            from match_entries me join matches m on m.id = me.match_id
            where me.user_id = ?
            order by m.played_at desc, m.id desc limit 10
            """,
            (user_id,),
        )
        season_entries = query_all(
            """
            select me.final_score, me.placement, me.rank_points, m.played_at, m.id as match_id
            from match_entries me join matches m on m.id = me.match_id
            where me.user_id = ? and m.season_id = ?
            order by m.played_at asc, m.id asc
            """,
            (user_id, season["id"]),
        ) if season else []
        trend = build_placement_trend(trend_history)
        radar = build_player_radar(season_entries)
        pagination = {
            "page": page,
            "pages": history_pages,
            "total": history_total,
            "has_prev": page > 1,
            "has_next": page < history_pages,
            "prev_page": page - 1,
            "next_page": page + 1,
        }
        return render_template(
            "player.html",
            user=user,
            stats=player_stats,
            history=history,
            trend=trend,
            radar=radar,
            pagination=pagination,
        )

    @app.route("/export/season/<int:season_id>.csv")
    @role_required("super_admin")
    def export_season(season_id: int):
        rows = get_leaderboard(season_id)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["rank", "player", "points", "matches", "avg_place", "first_rate", "fourth_rate", "penalties"])
        for idx, row in enumerate(rows, start=1):
            writer.writerow([
                idx,
                row["display_name"],
                row["total_points"],
                row["matches"],
                row["avg_place"],
                row["first_rate"],
                row["fourth_rate"],
                row["penalty_points"],
            ])
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename=season-{season_id}-leaderboard.csv"},
        )

    @app.teardown_appcontext
    def close_db(_: Exception | None = None) -> None:
        db = g.pop("db", None)
        if db is not None:
            db.close()

    return app


def get_db() -> sqlite3.Connection:
    """返回当前请求独享的连接，并让查询结果支持按列名读取。"""
    if "db" not in g:
        ensure_database_initialized()
        DATABASE.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


def ensure_database_initialized() -> None:
    """首次启动时创建数据库；已有数据库交给后续兼容函数升级。"""
    if DATABASE.exists():
        return
    init_db()


def ensure_user_soft_delete_columns() -> None:
    """为早期数据库补齐用户软删除字段。"""
    db = get_db()
    columns = {row["name"] for row in db.execute("pragma table_info(users)").fetchall()}
    if "is_deleted" not in columns:
        db.execute("alter table users add column is_deleted integer not null default 0")
    if "deleted_at" not in columns:
        db.execute("alter table users add column deleted_at text")
    db.commit()


def ensure_announcements_table() -> None:
    """为部署中的旧数据库补建公告表。"""
    db = get_db()
    db.execute(
        """
        create table if not exists announcements (
          id integer primary key autoincrement,
          title text not null,
          content text not null,
          author_id integer not null,
          created_at text not null,
          updated_at text not null,
          foreign key (author_id) references users(id)
        )
        """
    )
    db.commit()


def ensure_meetups_tables() -> None:
    """补齐活动相关表和字段，并回填旧记录需要的非空业务值。"""
    db = get_db()
    db.execute(
        """
        create table if not exists meetups (
          id integer primary key autoincrement,
          meetup_at text not null,
          signup_deadline text not null,
          venue text not null default 'upc 8 Gillingham street, QLD4102',
          archived_at text,
          archived_by integer,
          created_by integer not null,
          created_at text not null,
          updated_at text not null,
          foreign key (created_by) references users(id)
        )
        """
    )
    columns = {row["name"] for row in db.execute("pragma table_info(meetups)").fetchall()}
    if "signup_deadline" not in columns:
        db.execute("alter table meetups add column signup_deadline text")
    if "venue" not in columns:
        db.execute(
            "alter table meetups add column venue text not null default 'upc 8 Gillingham street, QLD4102'"
        )
    if "archived_at" not in columns:
        db.execute("alter table meetups add column archived_at text")
    if "archived_by" not in columns:
        db.execute("alter table meetups add column archived_by integer")
    db.execute("update meetups set signup_deadline = meetup_at where signup_deadline is null")
    db.execute(
        "update meetups set venue = ? where venue is null or trim(venue) = ''",
        (DEFAULT_MEETUP_VENUE,),
    )
    db.execute(
        """
        create table if not exists meetup_signups (
          id integer primary key autoincrement,
          meetup_id integer not null,
          user_id integer not null,
          created_at text not null,
          unique (meetup_id, user_id),
          foreign key (meetup_id) references meetups(id),
          foreign key (user_id) references users(id)
        )
        """
    )
    db.commit()


def ensure_admin_password() -> None:
    """仅在系统恰有一个有效管理员时执行一次默认密码迁移。

    多管理员场景无法判断目标账号，因此宁可跳过，避免意外重置真实用户密码。
    """
    db = get_db()
    db.execute(
        """
        create table if not exists app_migrations (
          name text primary key,
          applied_at text not null
        )
        """
    )
    applied = db.execute(
        "select 1 from app_migrations where name = ?",
        (ADMIN_PASSWORD_MIGRATION,),
    ).fetchone()
    if applied:
        db.commit()
        return

    admins = db.execute(
        "select id from users where role = 'super_admin' and is_deleted = 0"
    ).fetchall()
    if len(admins) != 1:
        db.commit()
        return

    db.execute(
        "update users set password_hash = ? where id = ?",
        (ADMIN_PASSWORD_HASH, admins[0]["id"]),
    )
    db.execute(
        "insert into app_migrations (name, applied_at) values (?, ?)",
        (ADMIN_PASSWORD_MIGRATION, now()),
    )
    db.commit()


def ensure_match_type_values() -> None:
    """一次性把旧版自由文本桌型归一化为当前枚举值。"""
    migration_name = "normalize_match_types_v2"
    db = get_db()
    applied = db.execute(
        "select 1 from app_migrations where name = ?",
        (migration_name,),
    ).fetchone()
    if applied:
        return
    db.execute(
        """
        update matches
        set table_name = case
          when lower(trim(table_name)) = 'meetup' then 'meetup'
          when lower(trim(table_name)) in ('casual', 'casual match', 'private', 'private game') then 'casual'
          when instr(table_name, '机打') > 0 or instr(table_name, '手打') > 0 then 'casual'
          else table_name
        end
        """
    )
    db.execute(
        "insert into app_migrations (name, applied_at) values (?, ?)",
        (migration_name, now()),
    )
    db.commit()


def execute(sql: str, params: tuple = ()) -> None:
    """执行单条写语句并立即提交；多语句事务应直接使用 ``get_db``。"""
    db = get_db()
    db.execute(sql, params)
    db.commit()


def query_one(sql: str, params: tuple = ()) -> sqlite3.Row | None:
    """执行查询并返回第一行，没有结果时返回 ``None``。"""
    return get_db().execute(sql, params).fetchone()


def query_all(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    """执行查询并返回全部结果。"""
    return get_db().execute(sql, params).fetchall()


def now() -> str:
    """返回 created_at/updated_at 等审计字段使用的 UTC 时间文本。"""
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def current_match_time() -> str:
    """返回比赛表单默认使用的布里斯班当地时间。"""
    return datetime.now(ZoneInfo("Australia/Brisbane")).strftime("%Y-%m-%d %H:%M:%S")


def today_date() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def normalize_match_type(value: str) -> str:
    """把表单和历史别名转换为数据库使用的 ``meetup``/``casual``。"""
    normalized = value.strip().lower()
    if normalized == "meetup":
        return "meetup"
    return "casual"


def match_type_label(value: str | None) -> str:
    """将数据库桌型转换为当前语言的展示文案，并兼容旧自由文本。"""
    if not value:
        return translate("home.unnamed_match")
    if value.strip().lower() == "meetup":
        return translate("match.type_meetup")
    if value.strip().lower() in {"casual", "casual match", "private", "private game", "机打", "手打"}:
        return translate("match.type_casual")
    return value


def normalize_datetime(value: str) -> str:
    """把 ``datetime-local`` 表单值整理为 SQLite 使用的秒级文本。"""
    if not value:
        return now()
    return value.replace("T", " ") + (":00" if len(value) == 16 else "")


def parse_local_datetime(value: str) -> str | None:
    """严格解析本地日期时间；格式无效时返回 ``None`` 交给路由提示。"""
    value = value.strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.strftime("%Y-%m-%d %H:%M:%S")


def brisbane_local_now() -> datetime:
    """返回无时区标记的布里斯班时间，以匹配数据库中的本地时间文本。"""
    return datetime.now(ZoneInfo("Australia/Brisbane")).replace(tzinfo=None)


def meetup_status(meetup) -> str:
    """按手动归档标记和报名截止时间计算活动状态。"""
    if meetup["archived_at"]:
        return "archived"
    deadline = datetime.fromisoformat(meetup["signup_deadline"] or meetup["meetup_at"])
    return "closed" if brisbane_local_now() > deadline else "open"


def auto_archive_expired_meetups() -> None:
    """自动归档已结束 24 小时的活动，给管理员保留赛后处理窗口。"""
    cutoff = (brisbane_local_now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    db = get_db()
    db.execute(
        """
        update meetups
        set archived_at = ?, updated_at = ?
        where archived_at is null and meetup_at <= ?
        """,
        (now(), now(), cutoff),
    )
    db.commit()


def generate_temporary_password(length: int = 12) -> str:
    """生成避开易混淆字符的临时密码。"""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_invite_code(role: str) -> str:
    """生成带角色前缀的邀请码，并在数据库中确保唯一。"""
    prefix = "REF" if role == "referee" else "PLAY"
    alphabet = string.ascii_uppercase + string.digits
    while True:
        token = "".join(secrets.choice(alphabet) for _ in range(6))
        code = f"{prefix}-{token[:3]}-{token[3:]}"
        if not query_one("select id from invite_codes where code = ?", (code,)):
            return code


def login_required(view):
    """要求会话中存在未删除用户。"""
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            flash(translate("flash.login_required"), "error")
            return redirect(url_for("login"))
        return view(**kwargs)
    return wrapped_view


def role_required(*roles: str):
    """限制路由角色；未登录和权限不足使用不同提示。"""
    def decorator(view):
        @functools.wraps(view)
        def wrapped_view(**kwargs):
            if g.user is None:
                flash(translate("flash.login_required"), "error")
                return redirect(url_for("login"))
            if g.user["role"] not in roles:
                flash(translate("flash.permission_denied"), "error")
                return redirect(url_for("index"))
            return view(**kwargs)
        return wrapped_view
    return decorator


def current_season() -> sqlite3.Row | None:
    """返回最新的启用赛季；业务约定同一时刻最多一个 active 赛季。"""
    return query_one("select * from seasons where status = 'active' order by id desc limit 1")


def parse_match_result_form(season, form) -> dict:
    """验证四人终局点数并计算顺位、UMA 和罚分后的赛季积分。"""
    rules = normalize_rules(json.loads(season["rules_json"]))
    start_total = int(rules["points"]["default_starting_points"]) * 4
    players = [int(form.get(f"player_{idx}") or 0) for idx in range(4)]
    scores = [int(form.get(f"score_{idx}") or 0) for idx in range(4)]
    penalty_values = [int(form.get(f"penalty_{idx}") or 0) for idx in range(4)]
    default_penalty_type = translate("match.default_penalty_type")
    penalty_types = [form.get(f"penalty_type_{idx}", default_penalty_type).strip() or default_penalty_type for idx in range(4)]
    penalty_reasons = [form.get(f"penalty_reason_{idx}", "").strip() for idx in range(4)]
    errors = []

    if any(player == 0 for player in players):
        errors.append(translate("validation.players_required"))
    if len(set(players)) != 4:
        errors.append(translate("validation.players_unique"))
    if sum(scores) != start_total:
        errors.append(translate("validation.score_total", total=start_total))
    for value, reason in zip(penalty_values, penalty_reasons):
        if value and not reason:
            errors.append(translate("validation.penalty_reason_required"))
            break
    if errors:
        return {"ok": False, "errors": errors}

    placements = calculate_placements(scores)
    rank_points = calculate_rank_points(scores, placements, rules, penalty_values)
    return {
        "ok": True,
        "rules": rules,
        "players": players,
        "scores": scores,
        "penalty_values": penalty_values,
        "penalty_types": penalty_types,
        "penalty_reasons": penalty_reasons,
        "placements": placements,
        "rank_points": rank_points,
    }


def create_match_from_form(season, form) -> dict:
    """在一个事务中新增对局、四条成绩和对应罚则。"""
    result = parse_match_result_form(season, form)
    if not result["ok"]:
        return result
    db = get_db()
    cur = db.execute(
        "insert into matches (season_id, referee_id, played_at, table_name, memo, created_at) values (?, ?, ?, ?, ?, ?)",
        (
            season["id"],
            g.user["id"],
            current_match_time(),
            normalize_match_type(form.get("table_name", "")),
            form.get("memo", "").strip(),
            now(),
        ),
    )
    match_id = cur.lastrowid
    insert_match_result_rows(db, match_id, season["id"], result, g.user["id"])
    db.commit()
    return {"ok": True, "match_id": match_id}


def update_match_from_result(match_id: int, match, form, result: dict) -> None:
    """重建指定对局的成绩与罚则，避免编辑后残留旧明细。"""
    db = get_db()
    db.execute(
        """
        update matches
        set played_at = ?, table_name = ?, memo = ?
        where id = ?
        """,
        (
            normalize_datetime(form.get("played_at", "")),
            normalize_match_type(form.get("table_name", "")),
            form.get("memo", "").strip(),
            match_id,
        ),
    )
    db.execute("delete from penalties where match_id = ?", (match_id,))
    db.execute("delete from match_entries where match_id = ?", (match_id,))
    insert_match_result_rows(db, match_id, match["season_id"], result, g.user["id"])
    db.commit()


def insert_match_result_rows(db: sqlite3.Connection, match_id: int, season_id: int, result: dict, actor_id: int) -> None:
    """写入四条成绩，并只为非零罚分创建罚则记录。"""
    for idx, user_id in enumerate(result["players"]):
        db.execute(
            """
            insert into match_entries (match_id, user_id, final_score, placement, rank_points, penalty_points)
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                match_id,
                user_id,
                result["scores"][idx],
                result["placements"][idx],
                result["rank_points"][idx],
                result["penalty_values"][idx],
            ),
        )
        if result["penalty_values"][idx]:
            db.execute(
                """
                insert into penalties (match_id, season_id, user_id, penalty_type, points, reason, created_by, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    match_id,
                    season_id,
                    user_id,
                    result["penalty_types"][idx],
                    result["penalty_values"][idx],
                    result["penalty_reasons"][idx],
                    actor_id,
                    now(),
                ),
            )


def build_placement_trend(history: list[sqlite3.Row]) -> dict:
    """把新到旧的成绩历史转换为模板可直接绘制的 SVG 折线坐标。"""
    ordered = list(reversed(history))
    if not ordered:
        return {"points": "", "nodes": []}
    left, right = 16, 96
    top, bottom = 14, 86
    span_x = right - left
    span_y = bottom - top
    nodes = []
    for idx, row in enumerate(ordered):
        x = (left + span_x / 2) if len(ordered) == 1 else left + (span_x * idx / (len(ordered) - 1))
        placement = float(row["placement"])
        y = top + ((placement - 1) / 3) * span_y
        nodes.append(
            {
                "x": round(x, 2),
                "y": round(y, 2),
                "placement": placement,
                "rank_points": row["rank_points"],
                "played_at": row["played_at"],
            }
        )
    return {
        "points": " ".join(f"{node['x']},{node['y']}" for node in nodes),
        "nodes": nodes,
    }


def build_player_radar(entries: list[sqlite3.Row]) -> dict:
    """计算个人雷达图指标，并产出模板绘制所需的 SVG 几何数据。

    平均点数和火力使用固定上限做展示归一化；修改上限只影响图形比例，
    不影响旁边显示的真实数值。
    """
    match_count = len(entries)
    first_count = sum(1 for row in entries if float(row["placement"]) == 1)
    positive_count = sum(1 for row in entries if float(row["rank_points"]) > 0)
    fourth_avoid_count = sum(1 for row in entries if float(row["placement"]) != 4)
    bust_avoid_count = sum(1 for row in entries if int(row["final_score"]) >= 0)
    average_score = sum(int(row["final_score"]) for row in entries) / match_count if match_count else 0
    first_scores = [int(row["final_score"]) for row in entries if float(row["placement"]) == 1]
    firepower = sum(first_scores) / len(first_scores) if first_scores else 0

    def percentage(count: int) -> float:
        return round(count / match_count * 100, 1) if match_count else 0.0

    first_rate = percentage(first_count)
    positive_rate = percentage(positive_count)
    fourth_avoidance = percentage(fourth_avoid_count)
    bust_avoidance = percentage(bust_avoid_count)
    metric_specs = [
        ("player.first_rate", "player.first_rate_desc", first_rate, f"{first_rate:.1f}%"),
        ("player.positive_rate", "player.positive_rate_desc", positive_rate, f"{positive_rate:.1f}%"),
        ("player.average_score", "player.average_score_desc", min(average_score / 50000 * 100, 100), f"{average_score:,.0f}"),
        ("player.fourth_avoidance", "player.fourth_avoidance_desc", fourth_avoidance, f"{fourth_avoidance:.1f}%"),
        ("player.bust_avoidance", "player.bust_avoidance_desc", bust_avoidance, f"{bust_avoidance:.1f}%"),
        ("player.firepower", "player.firepower_desc", min(firepower / 60000 * 100, 100), f"{firepower:,.0f}"),
    ]

    center_x, center_y, radius = 180, 166, 92
    grid_polygons = []
    for factor in (0.25, 0.5, 0.75, 1.0):
        points = []
        for index in range(6):
            angle = -math.pi / 2 + index * math.pi / 3
            points.append(f"{center_x + math.cos(angle) * radius * factor:.1f},{center_y + math.sin(angle) * radius * factor:.1f}")
        grid_polygons.append(" ".join(points))

    metrics = []
    data_points = []
    for index, (label_key, description_key, normalized, display_value) in enumerate(metric_specs):
        label = translate(label_key)
        label_lines = (
            label.split(" ")
            if label_key in {"player.fourth_avoidance", "player.bust_avoidance"} and " " in label
            else [label]
        )
        angle = -math.pi / 2 + index * math.pi / 3
        axis_x = center_x + math.cos(angle) * radius
        axis_y = center_y + math.sin(angle) * radius
        value_radius = radius * max(0, min(float(normalized), 100)) / 100
        data_points.append(f"{center_x + math.cos(angle) * value_radius:.1f},{center_y + math.sin(angle) * value_radius:.1f}")
        label_radius = 126
        label_x = center_x + math.cos(angle) * label_radius
        label_y = center_y + math.sin(angle) * label_radius
        horizontal = math.cos(angle)
        anchor = "start" if horizontal > 0.35 else "end" if horizontal < -0.35 else "middle"
        metrics.append(
            {
                "label": label,
                "label_lines": label_lines,
                "description": translate(description_key),
                "value": display_value,
                "normalized": round(float(normalized), 1),
                "axis_x": round(axis_x, 1),
                "axis_y": round(axis_y, 1),
                "label_x": round(label_x, 1),
                "label_y": round(label_y, 1),
                "anchor": anchor,
            }
        )

    return {
        "has_data": match_count > 0,
        "match_count": match_count,
        "center_x": center_x,
        "center_y": center_y,
        "grid_polygons": grid_polygons,
        "data_points": " ".join(data_points),
        "metrics": metrics,
    }


def get_leaderboard(season_id: int) -> list[dict]:
    """聚合指定赛季的成绩；罚分已包含在 ``rank_points`` 中。"""
    rows = query_all(
        """
        select
            u.id as user_id,
            u.display_name,
            count(me.id) as matches,
            round(coalesce(sum(me.rank_points), 0), 1) as total_points,
            round(avg(me.placement), 2) as avg_place,
            round(avg(case when me.placement = 1 then 1.0 else 0 end) * 100, 1) as first_rate,
            round(avg(case when me.placement = 4 then 1.0 else 0 end) * 100, 1) as fourth_rate,
            coalesce(sum(me.penalty_points), 0) as penalty_points
        from users u
        join match_entries me on me.user_id = u.id
        join matches m on m.id = me.match_id
        where m.season_id = ?
        group by u.id, u.display_name
        order by total_points desc, avg_place asc, matches desc
        """,
        (season_id,),
    )
    return [dict(row) for row in rows]


def build_finals_status(season: sqlite3.Row, rows: list[dict], user: sqlite3.Row | None) -> dict:
    """根据排行榜前四/后四和最低局数计算当前用户的杯赛资格。"""
    rules = normalize_rules(json.loads(season["rules_json"]))
    required_matches = int(rules["points"].get("final_required_matches", 8))
    if user is None:
        return {
            "logged_in": False,
            "required_matches": required_matches,
            "matches": 0,
            "remaining_matches": required_matches,
            "matches_met": False,
            "cup_status": translate("finals.login_to_view"),
            "championship_gap": None,
            "yakitori_gap": None,
        }

    user_row = next((row for row in rows if row["user_id"] == user["id"]), None)
    user_rank = next((idx for idx, row in enumerate(rows, start=1) if row["user_id"] == user["id"]), None)
    if user_row is None:
        normalized_name = user["display_name"].strip().lower()
        user_rank, user_row = next(
            (
                (idx, row)
                for idx, row in enumerate(rows, start=1)
                if row["display_name"].strip().lower() == normalized_name
            ),
            (None, None),
        )
    matches = int(user_row["matches"]) if user_row else 0
    points = float(user_row["total_points"]) if user_row else 0.0
    remaining_matches = max(required_matches - matches, 0)
    matches_met = remaining_matches == 0

    bottom_start_rank = max(len(rows) - 3, 1)
    is_top_four = user_rank is not None and user_rank <= 4
    is_bottom_four = user_rank is not None and user_rank >= bottom_start_rank and len(rows) >= 4
    championship_cutoff = float(rows[3]["total_points"]) if len(rows) >= 4 else None
    yakitori_cutoff = float(rows[bottom_start_rank - 1]["total_points"]) if len(rows) >= 4 else None

    if is_top_four:
        cup_status = translate("finals.championship_met")
        championship_gap = 0
        yakitori_gap = None
    elif is_bottom_four:
        cup_status = translate("finals.yakitori_met")
        championship_gap = None
        yakitori_gap = 0
    else:
        championship_gap = max(round((championship_cutoff or 0) - points, 1), 0) if championship_cutoff is not None else None
        yakitori_gap = max(round(points - (yakitori_cutoff or 0), 1), 0) if yakitori_cutoff is not None else None
        if championship_gap is None or yakitori_gap is None:
            cup_status = translate("finals.not_enough_data")
        else:
            cup_status = translate("finals.not_met")

    return {
        "logged_in": True,
        "required_matches": required_matches,
        "matches": matches,
        "remaining_matches": remaining_matches,
        "matches_met": matches_met,
        "rank": user_rank,
        "points": points,
        "cup_status": cup_status,
        "championship_gap": championship_gap,
        "yakitori_gap": yakitori_gap,
    }


def get_penalty_records(season_id: int) -> list[sqlite3.Row]:
    """返回赛季罚则明细，供规则页审计展示。"""
    return query_all(
        """
        select
            p.*,
            u.display_name as player_name,
            m.played_at,
            m.table_name,
            r.display_name as referee_name
        from penalties p
        join users u on u.id = p.user_id
        join matches m on m.id = p.match_id
        left join users r on r.id = p.created_by
        where p.season_id = ?
        order by m.played_at desc, p.id desc
        """,
        (season_id,),
    )


def init_db() -> None:
    """按 schema 重建空数据库，并按环境开关选择是否写入演示数据。

    ``schema.sql`` 开头包含 drop table，因此此函数不是无损迁移入口。
    """
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATABASE)
    with open(BASE_DIR / "schema.sql", encoding="utf-8") as f:
        db.executescript(f.read())
    db.row_factory = sqlite3.Row
    admin_id = db.execute(
        """
        insert into users (display_name, email, password_hash, role, created_at)
        values ('Admin', 'admin@example.com', ?, 'super_admin', ?)
        """,
        (ADMIN_PASSWORD_HASH, now()),
    ).lastrowid
    if SEED_DEMO_DATA:
        seed_demo_data(db, admin_id)
    db.commit()
    db.close()


def seed_demo_data(db: sqlite3.Connection, admin_id: int) -> None:
    """写入覆盖多赛季、同分和罚则场景的本地演示数据。"""
    season_1_rules = json.loads(json.dumps(DEFAULT_RULES))
    season_2_rules = json.loads(json.dumps(DEFAULT_RULES))
    season_3_rules = json.loads(json.dumps(DEFAULT_RULES))
    season_2_rules["points"]["uma_2nd"] = 5
    season_2_rules["points"]["uma_3rd"] = -15
    season_2_rules["points"]["uma_4th"] = -30
    season_2_rules["common"]["red_five"] = "4赤"
    season_2_rules["others"]["west_extension"] = True
    season_3_rules["points"]["default_starting_points"] = 30000
    season_3_rules["points"]["uma_1st"] = 20
    season_3_rules["points"]["uma_2nd"] = 5
    season_3_rules["points"]["uma_3rd"] = -15
    season_3_rules["points"]["uma_4th"] = -30
    season_3_rules["common"]["red_five"] = "4赤"

    season_1_id = db.execute(
        """
        insert into seasons (name, status, start_date, rules_json, version, created_at, updated_at)
        values ('Brisbane Riichi 2026 Autumn', 'archived', '2026-04-01', ?, 1, ?, ?)
        """,
        (json.dumps(season_1_rules, ensure_ascii=False), now(), now()),
    ).lastrowid
    season_2_id = db.execute(
        """
        insert into seasons (name, status, start_date, rules_json, version, created_at, updated_at)
        values ('Brisbane Riichi 2026 Winter', 'archived', '2026-07-01', ?, 2, ?, ?)
        """,
        (json.dumps(season_2_rules, ensure_ascii=False), now(), now()),
    ).lastrowid
    season_3_id = db.execute(
        """
        insert into seasons (name, status, start_date, rules_json, version, created_at, updated_at)
        values ('S11', 'active', '2026-08-21', ?, 3, ?, ?)
        """,
        (json.dumps(season_3_rules, ensure_ascii=False), now(), now()),
    ).lastrowid
    db.execute(
        "insert into rule_versions (season_id, rules_json, changed_by, changed_at) values (?, ?, ?, ?)",
        (season_2_id, json.dumps(season_2_rules, ensure_ascii=False), admin_id, now()),
    )
    db.execute(
        "insert into rule_versions (season_id, rules_json, changed_by, changed_at) values (?, ?, ?, ?)",
        (season_3_id, json.dumps(season_3_rules, ensure_ascii=False), admin_id, now()),
    )

    demo_users = [
        ("Mika Chen", "mika@example.com", "referee"),
        ("Daniel Wong", "daniel@example.com", "referee"),
        ("Wang.C", "wangc@example.com", "referee"),
        ("Rua", "3474189100@qq.com", "user"),
        ("Aiko Tan", "aiko@example.com", "user"),
        ("Kenji Sato", "kenji@example.com", "user"),
        ("Liam Brown", "liam@example.com", "user"),
        ("Sophie Lee", "sophie@example.com", "user"),
        ("Noah Smith", "noah@example.com", "user"),
        ("Yuki Mori", "yuki@example.com", "user"),
        ("Emma Davis", "emma@example.com", "user"),
        ("Haru Ito", "haru@example.com", "user"),
    ]
    user_ids = {}
    password_hash = generate_password_hash("demo1234", method="pbkdf2:sha256")
    for display_name, email, role in demo_users:
        user_ids[display_name] = db.execute(
            """
            insert into users (display_name, email, password_hash, role, created_at)
            values (?, ?, ?, ?, ?)
            """,
            (display_name, email, password_hash, role, now()),
        ).lastrowid

    demo_matches = [
        (
            season_1_id,
            season_1_rules,
            "2026-04-05 19:20:00",
            "Autumn A",
            "赛季揭幕桌",
            "Mika Chen",
            [("Aiko Tan", 38200), ("Kenji Sato", 26700), ("Liam Brown", 20400), ("Sophie Lee", 14700)],
            [],
        ),
        (
            season_1_id,
            season_1_rules,
            "2026-04-12 18:40:00",
            "Autumn B",
            "同分顺位演示",
            "Daniel Wong",
            [("Noah Smith", 31000), ("Yuki Mori", 31000), ("Emma Davis", 23000), ("Haru Ito", 15000)],
            [],
        ),
        (
            season_1_id,
            season_1_rules,
            "2026-04-19 19:10:00",
            "Autumn A",
            "含罚则",
            "Mika Chen",
            [("Sophie Lee", 41100), ("Aiko Tan", 28600), ("Haru Ito", 17200), ("Kenji Sato", 13100)],
            [{"player": "Kenji Sato", "points": 2, "type": "终局报分错误", "reason": "复核时发现漏记一本场"}],
        ),
        (
            season_1_id,
            season_1_rules,
            "2026-05-03 18:55:00",
            "Autumn C",
            "常规赛",
            "Daniel Wong",
            [("Liam Brown", 33500), ("Emma Davis", 29200), ("Yuki Mori", 22100), ("Noah Smith", 15200)],
            [],
        ),
        (
            season_1_id,
            season_1_rules,
            "2026-05-17 19:30:00",
            "Autumn B",
            "常规赛",
            "Mika Chen",
            [("Haru Ito", 36000), ("Aiko Tan", 28400), ("Noah Smith", 21600), ("Sophie Lee", 14000)],
            [],
        ),
        (
            season_1_id,
            season_1_rules,
            "2026-06-07 18:30:00",
            "Autumn Final",
            "秋季收官桌",
            "Daniel Wong",
            [("Emma Davis", 39000), ("Liam Brown", 25000), ("Kenji Sato", 23000), ("Yuki Mori", 13000)],
            [{"player": "Yuki Mori", "points": 1, "type": "迟到", "reason": "开赛迟到 12 分钟"}],
        ),
        (
            season_2_id,
            season_2_rules,
            "2026-07-06 19:00:00",
            "Winter A",
            "冬季赛第一轮",
            "Mika Chen",
            [("Aiko Tan", 45200), ("Noah Smith", 25100), ("Emma Davis", 18800), ("Liam Brown", 10900)],
            [],
        ),
        (
            season_2_id,
            season_2_rules,
            "2026-07-13 18:45:00",
            "Winter B",
            "冬季赛第二轮",
            "Daniel Wong",
            [("Kenji Sato", 33100), ("Sophie Lee", 30700), ("Yuki Mori", 21900), ("Haru Ito", 14300)],
            [{"player": "Haru Ito", "points": 1, "type": "误记分", "reason": "对局中少报 1000 点"}],
        ),
        (
            season_2_id,
            season_2_rules,
            "2026-07-20 19:15:00",
            "Winter A",
            "高打点桌",
            "Mika Chen",
            [("Emma Davis", 50600), ("Aiko Tan", 23800), ("Sophie Lee", 15100), ("Noah Smith", 10500)],
            [],
        ),
        (
            season_2_id,
            season_2_rules,
            "2026-07-27 19:05:00",
            "Winter C",
            "常规赛",
            "Daniel Wong",
            [("Liam Brown", 36400), ("Yuki Mori", 27700), ("Kenji Sato", 22800), ("Aiko Tan", 13100)],
            [],
        ),
        (
            season_2_id,
            season_2_rules,
            "2026-08-03 18:50:00",
            "Winter B",
            "含罚则",
            "Mika Chen",
            [("Sophie Lee", 34400), ("Haru Ito", 30600), ("Emma Davis", 20900), ("Liam Brown", 14100)],
            [{"player": "Liam Brown", "points": 2, "type": "违规操作导致重开", "reason": "牌山破坏后按赛季规则扣分"}],
        ),
        (
            season_2_id,
            season_2_rules,
            "2026-08-10 19:35:00",
            "Winter A",
            "常规赛",
            "Daniel Wong",
            [("Noah Smith", 31800), ("Kenji Sato", 31200), ("Yuki Mori", 23000), ("Aiko Tan", 14000)],
            [],
        ),
        (
            season_2_id,
            season_2_rules,
            "2026-08-17 19:05:00",
            "Winter Feature",
            "当前最近比赛",
            "Mika Chen",
            [("Yuki Mori", 37500), ("Sophie Lee", 26200), ("Aiko Tan", 22300), ("Emma Davis", 14000)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-08-21 15:18:00",
            "S11 手打",
            "S11 demo 01",
            "Wang.C",
            [("Rua", 35000), ("Daniel Wong", 34000), ("Kenji Sato", 34000), ("Noah Smith", 17000)],
            [{"player": "Rua", "points": 4, "type": "诈和", "reason": "诈和pt-4"}],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-08-22 19:00:00",
            "S11 机打",
            "S11 demo 02",
            "Mika Chen",
            [("Sophie Lee", 47200), ("Rua", 30600), ("Aiko Tan", 22600), ("Haru Ito", 19600)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-08-24 18:40:00",
            "S11 手打",
            "S11 demo 03",
            "Daniel Wong",
            [("Liam Brown", 41800), ("Yuki Mori", 33400), ("Rua", 25300), ("Emma Davis", 19500)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-08-26 19:20:00",
            "S11 机打",
            "S11 demo 04",
            "Wang.C",
            [("Rua", 50100), ("Noah Smith", 29200), ("Kenji Sato", 21100), ("Aiko Tan", 19600)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-08-28 19:05:00",
            "S11 手打",
            "S11 demo 05",
            "Mika Chen",
            [("Daniel Wong", 45200), ("Sophie Lee", 32700), ("Rua", 24800), ("Haru Ito", 17300)],
            [{"player": "Haru Ito", "points": 2, "type": "迟到", "reason": "迟到 15 分钟"}],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-08-30 18:50:00",
            "S11 机打",
            "S11 demo 06",
            "Daniel Wong",
            [("Yuki Mori", 38900), ("Emma Davis", 32500), ("Kenji Sato", 27800), ("Rua", 20800)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-01 19:15:00",
            "S11 手打",
            "S11 demo 07",
            "Wang.C",
            [("Rua", 41300), ("Liam Brown", 33400), ("Sophie Lee", 24700), ("Noah Smith", 20600)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-03 19:30:00",
            "S11 机打",
            "S11 demo 08",
            "Mika Chen",
            [("Aiko Tan", 36000), ("Rua", 35500), ("Daniel Wong", 27500), ("Yuki Mori", 21000)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-05 18:35:00",
            "S11 手打",
            "S11 demo 09",
            "Daniel Wong",
            [("Kenji Sato", 44800), ("Emma Davis", 31500), ("Rua", 23700), ("Liam Brown", 20000)],
            [{"player": "Rua", "points": 1, "type": "误记分", "reason": "复核后补扣 1pt"}],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-07 19:10:00",
            "S11 机打",
            "S11 demo 10",
            "Wang.C",
            [("Rua", 39800), ("Haru Ito", 34900), ("Noah Smith", 25000), ("Sophie Lee", 20300)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-09 18:45:00",
            "S11 手打",
            "S11 demo 11",
            "Mika Chen",
            [("Daniel Wong", 42100), ("Rua", 31800), ("Aiko Tan", 27200), ("Emma Davis", 18900)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-11 19:25:00",
            "S11 机打",
            "S11 demo 12",
            "Daniel Wong",
            [("Yuki Mori", 44200), ("Kenji Sato", 32600), ("Noah Smith", 23800), ("Rua", 19400)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-13 19:00:00",
            "S11 手打",
            "S11 demo 13",
            "Wang.C",
            [("Rua", 45800), ("Liam Brown", 30400), ("Haru Ito", 23800), ("Aiko Tan", 20000)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-15 18:55:00",
            "S11 机打",
            "S11 demo 14",
            "Mika Chen",
            [("Sophie Lee", 40600), ("Emma Davis", 35600), ("Rua", 24400), ("Kenji Sato", 19400)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-17 19:40:00",
            "S11 手打",
            "S11 demo 15",
            "Daniel Wong",
            [("Rua", 37000), ("Daniel Wong", 34400), ("Noah Smith", 28700), ("Yuki Mori", 19900)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-19 18:30:00",
            "S11 机打",
            "S11 demo 16",
            "Wang.C",
            [("Aiko Tan", 39300), ("Rua", 33100), ("Liam Brown", 26500), ("Haru Ito", 21100)],
            [{"player": "Liam Brown", "points": 2, "type": "违规操作", "reason": "错摸后按规则扣 2pt"}],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-21 19:05:00",
            "S11 手打",
            "S11 demo 17",
            "Mika Chen",
            [("Rua", 42100), ("Kenji Sato", 33300), ("Emma Davis", 24600), ("Sophie Lee", 20000)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-23 19:15:00",
            "S11 机打",
            "S11 demo 18",
            "Daniel Wong",
            [("Noah Smith", 38600), ("Daniel Wong", 34200), ("Rua", 28300), ("Aiko Tan", 18900)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-25 18:50:00",
            "S11 手打",
            "S11 demo 19",
            "Wang.C",
            [("Rua", 48600), ("Yuki Mori", 29600), ("Haru Ito", 22400), ("Liam Brown", 19400)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-27 19:30:00",
            "S11 机打",
            "S11 demo 20",
            "Mika Chen",
            [("Sophie Lee", 37200), ("Rua", 34900), ("Kenji Sato", 26700), ("Emma Davis", 21200)],
            [],
        ),
    ]

    for season_id, rules, played_at, table_name, memo, referee, entries, penalties in demo_matches:
        seed_match(db, season_id, rules, played_at, table_name, memo, user_ids[referee], user_ids, entries, penalties)


def seed_match(
    db: sqlite3.Connection,
    season_id: int,
    rules: dict,
    played_at: str,
    table_name: str,
    memo: str,
    referee_id: int,
    user_ids: dict[str, int],
    entries: list[tuple[str, int]],
    penalties: list[dict],
) -> None:
    """使用正式积分函数写入一场演示比赛，防止样例积分与业务规则漂移。"""
    scores = [score for _, score in entries]
    penalty_values_by_player = {item["player"]: item["points"] for item in penalties}
    penalty_values = [penalty_values_by_player.get(player, 0) for player, _ in entries]
    placements = calculate_placements(scores)
    rank_points = calculate_rank_points(scores, placements, rules, penalty_values)
    match_id = db.execute(
        "insert into matches (season_id, referee_id, played_at, table_name, memo, created_at) values (?, ?, ?, ?, ?, ?)",
        (season_id, referee_id, played_at, table_name, memo, played_at),
    ).lastrowid
    for idx, (player, score) in enumerate(entries):
        db.execute(
            """
            insert into match_entries (match_id, user_id, final_score, placement, rank_points, penalty_points)
            values (?, ?, ?, ?, ?, ?)
            """,
            (match_id, user_ids[player], score, placements[idx], rank_points[idx], penalty_values[idx]),
        )
    for item in penalties:
        db.execute(
            """
            insert into penalties (match_id, season_id, user_id, penalty_type, points, reason, created_by, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                match_id,
                season_id,
                user_ids[item["player"]],
                item["type"],
                item["points"],
                item["reason"],
                referee_id,
                played_at,
            ),
        )


app = create_app()
