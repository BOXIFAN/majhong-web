"""对已部署 SQLite 数据库执行幂等的轻量兼容迁移。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from brml.config import ADMIN_PASSWORD_HASH, ADMIN_PASSWORD_MIGRATION, DATABASE, DEFAULT_MEETUP_VENUE
from brml.db import get_db
from brml.timeutils import now


def _ensure_column(db, table: str, column: str, ddl: str) -> None:
    """幂等新增列；并发部署时另一个进程可能已加过，捕获后继续。

    Render 等平台在多实例滚动部署时，新旧实例可能几乎同时执行 before_request
    迁移。SQLite 的 ``ALTER TABLE ADD COLUMN`` 是 O(1) 元数据操作，但并发下
    后到者会收到 "duplicate column name"，这里吞掉该错误，保证请求不 500。
    """
    columns = {row["name"] for row in db.execute(f"pragma table_info({table})").fetchall()}
    if column in columns:
        return
    try:
        db.execute(f"alter table {table} add column {ddl}")
    except sqlite3.Error as error:  # pragma: no cover - 依赖并发时序
        if "duplicate column" not in str(error).lower():
            raise


def ensure_user_soft_delete_columns() -> None:
    """为早期数据库补齐用户软删除字段。"""
    db = get_db()
    columns = {row["name"] for row in db.execute("pragma table_info(users)").fetchall()}
    if "is_deleted" not in columns:
        db.execute("alter table users add column is_deleted integer not null default 0")
    if "deleted_at" not in columns:
        db.execute("alter table users add column deleted_at text")
    db.commit()


def ensure_user_avatar_column() -> None:
    """为早期数据库补齐用户自定义头像字段。"""
    db = get_db()
    columns = {row["name"] for row in db.execute("pragma table_info(users)").fetchall()}
    if "avatar" not in columns:
        db.execute("alter table users add column avatar text")
    db.commit()


def ensure_user_avatar_upload_column() -> None:
    """为早期数据库补齐用户上传头像文件名。"""
    db = get_db()
    columns = {row["name"] for row in db.execute("pragma table_info(users)").fetchall()}
    if "avatar_upload" not in columns:
        db.execute("alter table users add column avatar_upload text")
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
          venue text not null default 'UPC · 8 Gillingham Street, QLD 4102',
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
            "alter table meetups add column venue text not null default 'UPC · 8 Gillingham Street, QLD 4102'"
        )
    if "archived_at" not in columns:
        db.execute("alter table meetups add column archived_at text")
    if "archived_by" not in columns:
        db.execute("alter table meetups add column archived_by integer")
    # 调研报告 P1-7：活动详情 H1 只有日期。补一个可选的活动名与人数上限，
    # 旧记录保持 null，模板层回退到「周六例行对局」这类默认文案。
    _ensure_column(db, "meetups", "title", "title text")
    _ensure_column(db, "meetups", "capacity", "capacity integer")
    _ensure_column(db, "meetups", "note", "note text")
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


def ensure_transactions_table() -> None:
    """为部署中的旧数据库补建记账表（幂等）。"""
    db = get_db()
    db.execute(
        """
        create table if not exists transactions (
          id integer primary key autoincrement,
          kind text not null check (kind in ('income', 'expense')),
          category text not null,
          description text not null,
          amount real not null check (amount > 0),
          user_id integer,
          recorded_by integer not null,
          occurred_at text not null,
          recorded_at text not null,
          deleted_at text,
          foreign key (user_id) references users(id),
          foreign key (recorded_by) references users(id)
        )
        """
    )
    columns = {row["name"] for row in db.execute("pragma table_info(transactions)").fetchall()}
    if "deleted_at" not in columns:
        db.execute("alter table transactions add column deleted_at text")
    db.commit()


def _backfill_board_image_sizes(db) -> None:
    """为旧留言回填图片原始宽高。

    模板据此按图片真实比例渲染（``aspect-ratio``），避免 4:3 容器把横构图
    大牌照片裁掉两侧牌面；读不到文件时保持 null，模板回退 4:3。
    """
    try:
        from PIL import Image
    except Exception:  # pragma: no cover - Pillow 缺失时跳过
        return
    from flask import current_app

    database_path = Path(current_app.config.get("DATABASE_PATH", DATABASE))
    directory = database_path.parent / "board_uploads"
    rows = db.execute(
        "select id, image from board_posts"
        " where image is not null and (image_width is null or image_height is null)"
    ).fetchall()
    for row in rows:
        try:
            with Image.open(directory / Path(row["image"]).name) as image:
                width, height = image.size
        except Exception:
            continue
        db.execute(
            "update board_posts set image_width = ?, image_height = ? where id = ?",
            (width, height, row["id"]),
        )


def ensure_board_tables() -> None:
    """为部署中的旧数据库补建留言板相关表（幂等）。"""
    db = get_db()
    db.execute(
        """
        create table if not exists board_posts (
          id integer primary key autoincrement,
          user_id integer not null,
          caption text,
          image text not null,
          created_at text not null,
          updated_at text not null,
          expires_at text not null,
          deleted_at text,
          deleted_by integer,
          foreign key (user_id) references users(id),
          foreign key (deleted_by) references users(id)
        )
        """
    )
    # 图片原始尺寸：模板用它设置 aspect-ratio，横/竖构图都完整显示，不再被 4:3 容器裁切。
    _ensure_column(db, "board_posts", "image_width", "image_width integer")
    _ensure_column(db, "board_posts", "image_height", "image_height integer")
    _backfill_board_image_sizes(db)
    db.execute(
        """
        create table if not exists board_comments (
          id integer primary key autoincrement,
          post_id integer not null,
          user_id integer not null,
          content text not null,
          created_at text not null,
          deleted_at text,
          deleted_by integer,
          foreign key (post_id) references board_posts(id),
          foreign key (user_id) references users(id),
          foreign key (deleted_by) references users(id)
        )
        """
    )
    db.execute(
        """
        create table if not exists board_likes (
          id integer primary key autoincrement,
          post_id integer not null,
          user_id integer not null,
          created_at text not null,
          unique (post_id, user_id),
          foreign key (post_id) references board_posts(id),
          foreign key (user_id) references users(id)
        )
        """
    )
    db.execute(
        """
        create table if not exists board_deletions (
          id integer primary key autoincrement,
          post_id integer,
          comment_id integer,
          author_id integer,
          actor_id integer,
          action text not null,
          deleted_at text not null
        )
        """
    )
    # 为早期数据回填到期时间，保证列表渲染不依赖空值判断。
    db.execute(
        "update board_posts set expires_at = datetime(created_at, '+30 days') where expires_at is null or expires_at = ''"
    )
    db.commit()
