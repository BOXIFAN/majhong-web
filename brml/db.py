"""SQLite 连接、基础查询与全新数据库初始化。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from flask import current_app, g, has_app_context

from brml.config import (
    ADMIN_PASSWORD_HASH,
    BASE_DIR,
    DATABASE,
    SEED_DEMO_DATA,
)
from brml.seed import seed_demo_data
from brml.timeutils import now


def database_path() -> Path:
    """读取当前应用的数据库路径；应用上下文外回退到环境配置。"""
    if has_app_context():
        return Path(current_app.config.get("DATABASE_PATH", DATABASE))
    return DATABASE


def get_db() -> sqlite3.Connection:
    """返回当前请求独享的连接，并让查询结果支持按列名读取。"""
    if "db" not in g:
        ensure_database_initialized()
        path = database_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(path)
        # 旧库可能已有孤儿记录，但启用约束仍可阻止后续写入制造新的孤儿记录。
        g.db.execute("pragma foreign_keys = on")
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(_: Exception | None = None) -> None:
    """在应用上下文结束时关闭本次请求创建的连接。"""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def ensure_database_initialized() -> None:
    """首次启动时创建数据库；已有数据库交给兼容迁移函数升级。"""
    if database_path().exists():
        return
    init_db()


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


def init_db(*, force: bool = False) -> None:
    """按 schema 重建数据库，并按环境开关选择是否写入演示数据。

    ``schema.sql`` 开头包含 drop table，因此已有数据库默认拒绝重建；只有调用方
    明确传入 ``force=True`` 才允许覆盖。
    """
    path = database_path()
    if path.exists() and not force:
        raise FileExistsError(f"Database already exists: {path}. Use --force only after creating a backup.")
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("pragma foreign_keys = on")
    with open(BASE_DIR / "schema.sql", encoding="utf-8") as schema_file:
        db.executescript(schema_file.read())
    db.row_factory = sqlite3.Row
    admin_id = db.execute(
        """
        insert into users (display_name, email, password_hash, role, created_at)
        values ('Admin', 'admin@example.com', ?, 'super_admin', ?)
        """,
        (ADMIN_PASSWORD_HASH, now()),
    ).lastrowid
    should_seed = current_app.config.get("SEED_DEMO_DATA", SEED_DEMO_DATA) if has_app_context() else SEED_DEMO_DATA
    if should_seed:
        seed_demo_data(db, admin_id)
    db.commit()
    db.close()
