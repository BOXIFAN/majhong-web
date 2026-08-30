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
from brml.routes.accounts import register_routes as register_account_routes
from brml.routes.seasons import register_routes as register_season_routes
from brml.routes.competition import register_routes as register_competition_routes


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

    register_account_routes(app)

    register_season_routes(app)

    register_competition_routes(app)

    app.teardown_appcontext(close_db)

    return app


app = create_app()
