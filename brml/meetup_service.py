"""Meetup 状态计算与自动归档。"""

from __future__ import annotations

from datetime import datetime, timedelta

from brml.db import get_db
from brml.timeutils import brisbane_local_now, now

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

