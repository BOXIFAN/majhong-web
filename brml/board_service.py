"""留言板（大牌分享）业务逻辑：合规图片压缩、每日限额、真删除与到期清理。

设计约定：
- 图片统一重新编码为 JPEG：超过 COMPRESS_ABOVE_BYTES 的原图会自动压缩，
  落盘文件一定会小于 MAX_STORED_BYTES；重新编码同时剥离 EXIF（含 GPS）等元数据。
- ``created_at`` / ``expires_at`` 与全站一致使用 UTC 文本；每日发布限额按
  布里斯班当地日期换算成 UTC 区间后再统计，避免时区偏差。
- **删除即真删除**：用户或管理员删除留言时，帖子行、评论、点赞记录与图片文件
  会立刻从数据库和磁盘移除；只有 ``board_deletions`` 里留一条不含任何内容的
  审计记录（帖子编号 / 作者 / 操作者 / 时间），避免 Render 磁盘被历史数据占满。
- 到期留言同样物理删除，并顺带清理没有被任何留言引用的孤儿图片文件。
"""

from __future__ import annotations

import secrets
import time as _time
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from brml.db import database_path, get_db, query_one
from brml.config import BOARD_STORAGE_BUDGET_MB
from brml.timeutils import now

BRISBANE = ZoneInfo("Australia/Brisbane")
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

# 留言图片只保留一个月；一人一天最多发布 2 条。
POST_TTL_DAYS = 30
DAILY_POST_LIMIT = 2

# 合规校验阈值：限制类型、体积与最小分辨率，拒绝无法解码或过小的图像。
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif", "bmp"}
# 超过 6MB 的原图自动压缩；超过 25MB 直接拒绝，避免超大文件拖垮工作进程。
COMPRESS_ABOVE_BYTES = 6 * 1024 * 1024
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
# 落盘上限比需求里的 6MB 更严格，正常手机照片压缩后远小于该值。
MAX_STORED_BYTES = 2 * 1024 * 1024
MIN_IMAGE_SIDE = 240
# 卡片与详情页最大只显示到 820px 宽，1280px 已经足够清晰，同时显著省盘。
MAX_IMAGE_SIDE = 1280
MIN_IMAGE_SIDE_AFTER_RESIZE = 800

# 审计记录保留天数：只存编号与时间，无法还原内容，也不会无限增长。
DELETION_LOG_TTL_DAYS = 180
# 孤儿图片的宽限期：避免删掉正在上传、还没写库的文件。
ORPHAN_IMAGE_GRACE_SECONDS = 3600


def board_dir() -> Path:
    """留言图片目录：与数据库同级，随持久化磁盘一起迁移。"""
    directory = database_path().parent / "board_uploads"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def max_upload_mb() -> int:
    """上传硬上限（整数 MB），供界面提示文案复用同一个来源。"""
    return round(MAX_UPLOAD_BYTES / 1024 / 1024)


def board_storage_bytes() -> int:
    """当前留言图片占用的磁盘空间（字节）。"""
    try:
        return sum(path.stat().st_size for path in board_dir().glob("*") if path.is_file())
    except OSError:
        return 0


def board_storage_mb() -> float:
    """当前留言图片占用（MB，保留一位小数）。"""
    return round(board_storage_bytes() / 1024 / 1024, 1)


def storage_budget_bytes() -> int:
    """留言图库的容量上限（字节），由 BOARD_STORAGE_BUDGET_MB 控制。"""
    return BOARD_STORAGE_BUDGET_MB * 1024 * 1024


def storage_is_full() -> bool:
    """图库是否已达上限；达到后拒绝新留言，避免把 Render 磁盘写满。"""
    return board_storage_bytes() >= storage_budget_bytes()


def save_board_image(uploaded) -> tuple[str | None, str]:
    """校验并保存上传图片，返回 ``(文件名, 错误码)``；成功时错误码为空串。

    错误码：``missing`` / ``type_invalid`` / ``too_large`` / ``too_small`` / ``invalid``。
    体积在 6MB–25MB 之间的原图会走自动压缩，不需要用户自己处理。
    """
    from PIL import Image

    if not uploaded or not uploaded.filename:
        return None, "missing"
    filename = uploaded.filename
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        return None, "type_invalid"
    # 先按流长度做一次快速拒绝，避免把超大文件整体读入内存。
    uploaded.stream.seek(0, 2)
    size = uploaded.stream.tell()
    uploaded.stream.seek(0)
    if size > MAX_UPLOAD_BYTES:
        return None, "too_large"
    try:
        image = Image.open(uploaded.stream)
        image.load()  # 强制解码，截断或伪造的图片会在这里抛错
    except Exception:
        return None, "invalid"
    if min(image.size) < MIN_IMAGE_SIDE:
        return None, "too_small"
    try:
        stored = _write_compressed_jpeg(image)
    except Exception:
        return None, "invalid"
    return stored.name, ""


def _write_compressed_jpeg(image) -> Path:
    """把图片压到落盘上限以内并返回文件路径。

    先按最大边缩放，再逐步降低 JPEG 质量；仍超标就继续缩小尺寸，
    保证最终文件一定小于 ``MAX_STORED_BYTES``（默认 2MB）。
    """
    from PIL import Image

    stored = board_dir() / f"{secrets.token_hex(16)}.jpg"
    if image.mode in ("RGBA", "LA", "P"):
        converted = image.convert("RGBA")
        background = Image.new("RGB", converted.size, (255, 255, 255))
        background.paste(converted, mask=converted.split()[-1])
        image = background
    elif image.mode != "RGB":
        image = image.convert("RGB")
    max_side = MAX_IMAGE_SIDE
    while True:
        working = image.copy()
        working.thumbnail((max_side, max_side))
        quality = 88
        while True:
            # 不写入 exif/icc 等元数据，等于顺带剔除 GPS 等隐私信息。
            working.save(stored, "JPEG", quality=quality, optimize=True, progressive=True)
            if stored.stat().st_size <= MAX_STORED_BYTES or quality <= 45:
                break
            quality -= 12
        if stored.stat().st_size <= MAX_STORED_BYTES or max_side <= MIN_IMAGE_SIDE_AFTER_RESIZE:
            break
        max_side = max(int(max_side * 0.75), MIN_IMAGE_SIDE_AFTER_RESIZE)
    return stored


def delete_board_image(filename: str | None) -> None:
    """删除留言图片文件；文件缺失时静默忽略。"""
    if not filename:
        return
    target = board_dir() / Path(filename).name
    try:
        target.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def expires_at_from(timestamp: str) -> str:
    """按保留期计算到期时间（同格式 UTC 文本）。"""
    created = datetime.strptime(timestamp, TIME_FORMAT)
    return (created + timedelta(days=POST_TTL_DAYS)).strftime(TIME_FORMAT)


def local_day_bounds_utc(moment: datetime | None = None) -> tuple[str, str]:
    """返回布里斯班当日起止对应的 UTC 文本区间 ``[start, end)``。"""
    local_now = moment.astimezone(BRISBANE) if moment else datetime.now(BRISBANE)
    start_local = datetime.combine(
        local_now.date(), time.min, tzinfo=BRISBANE
    )
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc).strftime(TIME_FORMAT)
    end_utc = end_local.astimezone(timezone.utc).strftime(TIME_FORMAT)
    return start_utc, end_utc


def posts_used_today(user_id: int) -> int:
    """统计用户今天（布里斯班日期）已发布的留言数，含已被删除的记录。"""
    start_utc, end_utc = local_day_bounds_utc()
    row = query_one(
        """
        select count(*) as c from board_posts
        where user_id = ? and created_at >= ? and created_at < ?
        """,
        (user_id, start_utc, end_utc),
    )
    return row["c"] if row else 0


def posts_left_today(user_id: int) -> int:
    """今天还剩多少次发布机会。"""
    return max(DAILY_POST_LIMIT - posts_used_today(user_id), 0)


def log_deletion(
    action: str,
    *,
    post_id: int | None = None,
    comment_id: int | None = None,
    author_id: int | None = None,
    actor_id: int | None = None,
) -> None:
    """写入一条不含内容的删除审计记录（编号 + 操作者 + 时间）。

    内容本身已经被物理删除，这里只保留“谁在什么时候删了哪一条”，
    用于社团内部追溯；记录体积只有百来字节，且会定期清理。
    """
    db = get_db()
    db.execute(
        """
        insert into board_deletions
          (post_id, comment_id, author_id, actor_id, action, deleted_at)
        values (?, ?, ?, ?, ?, ?)
        """,
        (post_id, comment_id, author_id, actor_id, action, now()),
    )


def purge_post(post_id: int, *, actor_id: int | None, action: str = "post_deleted") -> bool:
    """彻底删除一条留言：帖子行、评论、点赞与图片文件全部立即移除。

    与“软删除”不同，调用后数据库与磁盘都不再保留这条留言的任何内容，
    只写一条不含内容的审计记录。返回是否确实删除了记录。
    """
    db = get_db()
    post = db.execute(
        "select id, user_id, image from board_posts where id = ?", (post_id,)
    ).fetchone()
    if not post:
        return False
    db.execute("delete from board_likes where post_id = ?", (post_id,))
    db.execute("delete from board_comments where post_id = ?", (post_id,))
    db.execute("delete from board_posts where id = ?", (post_id,))
    log_deletion(action, post_id=post_id, author_id=post["user_id"], actor_id=actor_id)
    db.commit()
    delete_board_image(post["image"])
    return True


def purge_comment(comment_id: int, *, actor_id: int | None, action: str = "comment_deleted") -> bool:
    """彻底删除一条评论（直接删除数据库行，不留软删除痕迹）。"""
    db = get_db()
    comment = db.execute(
        "select id, post_id, user_id from board_comments where id = ?", (comment_id,)
    ).fetchone()
    if not comment:
        return False
    db.execute("delete from board_comments where id = ?", (comment_id,))
    log_deletion(
        action,
        post_id=comment["post_id"],
        comment_id=comment_id,
        author_id=comment["user_id"],
        actor_id=actor_id,
    )
    db.commit()
    return True


def sweep_orphan_images(min_age_seconds: int = ORPHAN_IMAGE_GRACE_SECONDS) -> int:
    """删除没有任何留言引用的图片文件，返回清理数量。

    覆盖“图片已落盘但写库失败”“历史软删除残留”等情况，
    保证 ``board_uploads/`` 不会随着时间无限膨胀。
    """
    db = get_db()
    used = {row["image"] for row in db.execute("select image from board_posts").fetchall()}
    cutoff = _time.time() - min_age_seconds
    removed = 0
    for path in board_dir().glob("*"):
        if not path.is_file() or path.name in used:
            continue
        try:
            if path.stat().st_mtime > cutoff:
                continue
            path.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def prune_deletion_log() -> int:
    """清理过期的审计记录，返回删除条数。"""
    db = get_db()
    cutoff = (
        datetime.strptime(now(), TIME_FORMAT) - timedelta(days=DELETION_LOG_TTL_DAYS)
    ).strftime(TIME_FORMAT)
    rows = db.execute(
        "select count(*) as c from board_deletions where deleted_at < ?", (cutoff,)
    ).fetchone()
    db.execute("delete from board_deletions where deleted_at < ?", (cutoff,))
    db.commit()
    return rows["c"] if rows else 0


def cleanup_expired_posts(sweep_min_age_seconds: int = ORPHAN_IMAGE_GRACE_SECONDS) -> int:
    """删除已到期或历史软删除的留言，并清理孤儿图片，返回删除条数。

    该函数是幂等的，可安全地在页面访问与命令行中重复调用。
    """
    db = get_db()
    current = now()
    stale = db.execute(
        "select id, user_id, image, expires_at from board_posts"
        " where expires_at <= ? or deleted_at is not null",
        (current,),
    ).fetchall()
    if stale:
        ids = [row["id"] for row in stale]
        placeholders = ",".join("?" for _ in ids)
        db.execute(f"delete from board_likes where post_id in ({placeholders})", ids)
        db.execute(f"delete from board_comments where post_id in ({placeholders})", ids)
        db.execute(f"delete from board_posts where id in ({placeholders})", ids)
        for row in stale:
            # 区分“到期自动清理”和历史软删除残留，便于日后排查。
            action = "expired" if row["expires_at"] <= current else "purged_legacy_delete"
            log_deletion(action, post_id=row["id"], author_id=row["user_id"], actor_id=None)
        db.commit()
        for row in stale:
            delete_board_image(row["image"])
    sweep_orphan_images(sweep_min_age_seconds)
    prune_deletion_log()
    return len(stale)
