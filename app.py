"""BRML 的 Flask 应用工厂和 WSGI 入口。"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import click
from flask import Flask, g, session

from brml.config import (
    DATABASE,
    DEFAULT_MEETUP_VENUE,
    SEED_DEMO_DATA,
)
from brml.db import close_db, ensure_database_initialized, init_db, query_one
from brml.i18n import ROLE_LABELS, get_locale, translate
from brml.migrations import (
    ensure_admin_password,
    ensure_announcements_table,
    ensure_match_type_values,
    ensure_meetups_tables,
    ensure_transactions_table,
    ensure_user_soft_delete_columns,
)
from brml.routes.finance import register_routes as register_finance_routes
from brml.routes.accounts import register_routes as register_account_routes
from brml.routes.community import register_routes as register_community_routes
from brml.routes.competition import register_routes as register_competition_routes
from brml.routes.content import register_routes as register_content_routes
from brml.routes.experiment import register_routes as register_experiment_routes
from brml.routes.seasons import register_routes as register_season_routes
from brml.match_service import current_season, match_type_label
from brml.rules import FIELD_LABELS, RULE_LABELS
from brml.timeutils import today_date


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
        ensure_transactions_table()
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
    @click.option("--force", is_flag=True, help="Overwrite an existing database after taking a backup.")
    def init_db_command(force: bool) -> None:
        try:
            init_db(force=force)
        except FileExistsError as error:
            raise click.ClickException(str(error)) from error
        print("Initialized the database.")

    register_community_routes(app)

    register_content_routes(app)

    register_account_routes(app)

    register_season_routes(app)

    register_competition_routes(app)

    register_finance_routes(app)

    register_experiment_routes(app)

    app.teardown_appcontext(close_db)

    return app


app = create_app()
