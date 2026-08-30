"""数据库审计时间与布里斯班本地业务时间的转换。"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


def now() -> str:
    """返回 created_at/updated_at 等审计字段使用的 UTC 时间文本。"""
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def current_match_time() -> str:
    """返回比赛表单默认使用的布里斯班当地时间。"""
    return datetime.now(ZoneInfo("Australia/Brisbane")).strftime("%Y-%m-%d %H:%M:%S")


def today_date() -> str:
    return datetime.now().strftime("%Y-%m-%d")


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
