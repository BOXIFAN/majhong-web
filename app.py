"""BRML 联赛网站的 Flask 应用。

项目目前采用单文件后端：路由集中在 ``create_app`` 中，数据库兼容逻辑、
积分计算和演示数据位于其后。维护时应优先把业务规则保留在本文件的纯函数中，
模板只负责展示，避免同一套积分规则在多个页面重复实现。
"""

from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
from datetime import timedelta
from pathlib import Path

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

from brml.auth import generate_invite_code, generate_temporary_password, login_required, role_required
from brml.config import (
    DATABASE,
    DEFAULT_MEETUP_VENUE,
    SEED_DEMO_DATA,
)
from brml.analytics import (
    build_finals_status,
    build_placement_trend,
    build_player_radar,
    get_leaderboard,
    get_penalty_records,
)
from brml.db import close_db, ensure_database_initialized, execute, get_db, init_db, query_all, query_one
from brml.i18n import ROLE_LABELS, ROLES, TRANSLATIONS, get_locale, translate
from brml.migrations import (
    ensure_admin_password,
    ensure_announcements_table,
    ensure_match_type_values,
    ensure_meetups_tables,
    ensure_user_soft_delete_columns,
)
from brml.meetup_service import auto_archive_expired_meetups, meetup_status
from brml.match_service import (
    create_match_from_form,
    current_season,
    match_type_label,
    normalize_match_type,
    parse_match_result_form,
    update_match_from_result,
)
from brml.scoring import (
    calculate_placements,
    calculate_rank_points,
    get_uma_points,
    placement_to_places,
)
from brml.timeutils import (
    current_match_time,
    normalize_datetime,
    now,
    parse_local_datetime,
    today_date,
)
from brml.rules import (
    DEFAULT_RULES,
    FIELD_LABELS,
    RULE_LABELS,
    normalize_rules,
    parse_rules_form,
)
from brml.routes.community import register_routes as register_community_routes
from brml.routes.content import register_routes as register_content_routes


def create_app() -> Flask:
    """创建并配置应用；所有路由在此注册，便于 WSGI 与测试复用。"""
    app = Flask(__name__, instance_relative_config=True)
    is_render = os.environ.get("RENDER", "false").lower() in {"1", "true", "yes", "on"}
    secure_cookie = os.environ.get(
        "SESSION_COOKIE_SECURE",
        "true" if is_render else "false",
    ).lower() in {"1", "true", "yes", "on"}
    app.config.from_mapping(
        DATABASE_PATH=DATABASE,
        SEED_DEMO_DATA=SEED_DEMO_DATA,
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

    register_community_routes(app)

    register_content_routes(app)

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

    app.teardown_appcontext(close_db)

    return app


app = create_app()
