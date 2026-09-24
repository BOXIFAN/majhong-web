"""留言板：玩家分享大牌照片，支持点赞、评论与发布者编辑。"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from flask import flash, g, redirect, render_template, request, send_from_directory, url_for

from brml.auth import login_required, role_required
from brml.board_service import (
    BRISBANE,
    COMPRESS_ABOVE_BYTES,
    DAILY_POST_LIMIT,
    DELETION_LOG_TTL_DAYS,
    MAX_UPLOAD_BYTES,
    POST_TTL_DAYS,
    board_dir,
    board_storage_mb,
    cleanup_expired_posts,
    expires_at_from,
    max_upload_mb,
    posts_left_today,
    purge_comment,
    purge_post,
    save_board_image,
    storage_budget_bytes,
    storage_is_full,
)
from brml.db import execute, get_db, query_all, query_one
from brml.i18n import translate
from brml.timeutils import now

PER_PAGE = 10
CAPTION_MAX = 600
COMMENT_MAX = 500
PREVIEW_COMMENTS = 3
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

IMAGE_ERROR_KEYS = {
    "missing": "board.image_required",
    "type_invalid": "board.image_type_invalid",
    "too_large": "board.image_too_large",
    "too_small": "board.image_too_small",
    "invalid": "board.image_invalid",
}


def _image_error_message(error: str) -> str:
    """图片校验失败提示；体积超限时需要带上动态计算的上限。"""
    key = IMAGE_ERROR_KEYS.get(error, "board.image_invalid")
    if error == "too_large":
        return translate(key, max_upload_mb=max_upload_mb())
    return translate(key)


def _safe_back(fallback: str) -> str:
    """优先回跳来源页，但只接受站内相对地址，避免开放重定向。"""
    referrer = request.referrer or ""
    if referrer.startswith("/") and not referrer.startswith("//"):
        return referrer
    return fallback


def _days_left(expires_at: str) -> int:
    """返回距到期还剩多少天（向上取整，最小 0）。"""
    try:
        remaining = datetime.strptime(expires_at, TIME_FORMAT) - datetime.utcnow()
    except (TypeError, ValueError):
        return 0
    return max(math.ceil(remaining.total_seconds() / 86400), 0)


def _local_label(value: str) -> str:
    """把数据库 UTC 文本转换为布里斯班时间标签，避免展示时间差 10 小时。"""
    try:
        moment = datetime.strptime(value, TIME_FORMAT).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return value or ""
    return moment.astimezone(BRISBANE).strftime("%Y-%m-%d %H:%M")


def _short_label(value: str) -> str:
    """卡片上使用的紧凑时间：今天 / 昨天只显示时刻，更早显示月日。

    完整时间仍通过 ``created_label`` 放在 title 里，鼠标悬停可以看到。
    """
    try:
        moment = datetime.strptime(value, TIME_FORMAT).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return value or ""
    local = moment.astimezone(BRISBANE)
    today = datetime.now(BRISBANE).date()
    if local.date() == today:
        return translate("board.time_today", time=local.strftime("%H:%M"))
    if local.date() == today - timedelta(days=1):
        return translate("board.time_yesterday", time=local.strftime("%H:%M"))
    return local.strftime("%m-%d %H:%M")


def _post_select() -> str:
    """留言列表与详情共用的字段集合，保证卡片渲染口径一致。"""
    return """
        select p.*, u.display_name, u.role as author_role, u.avatar, u.avatar_upload,
               (select count(*) from board_likes l where l.post_id = p.id) as like_count,
               (select count(*) from board_comments c
                 where c.post_id = p.id and c.deleted_at is null) as comment_count
        from board_posts p
        join users u on u.id = p.user_id
    """


def _load_comments(post_ids: list[int]) -> dict[int, list[dict]]:
    """一次取回多份留言的评论，避免列表页出现 N+1 查询。"""
    grouped: dict[int, list[dict]] = {post_id: [] for post_id in post_ids}
    if not post_ids:
        return grouped
    placeholders = ",".join("?" for _ in post_ids)
    rows = query_all(
        f"""
        select c.*, u.display_name, u.avatar, u.avatar_upload
        from board_comments c join users u on u.id = c.user_id
        where c.post_id in ({placeholders}) and c.deleted_at is null
        order by c.created_at asc, c.id asc
        """,
        tuple(post_ids),
    )
    for row in rows:
        grouped[row["post_id"]].append(dict(row))
    return grouped


def _decorate(post: dict, comments: list[dict], liked: bool) -> dict:
    """补齐卡片需要的评论预览、点赞状态与剩余天数。"""
    post["comments"] = comments
    post["preview_comments"] = comments[-PREVIEW_COMMENTS:]
    post["hidden_comment_count"] = max(len(comments) - PREVIEW_COMMENTS, 0)
    post["liked"] = liked
    post["days_left"] = _days_left(post["expires_at"])
    post["days_label"] = (
        translate("board.expires_today")
        if post["days_left"] <= 0
        else translate("board.days_left", days=post["days_left"])
    )
    post["created_label"] = _local_label(post["created_at"])
    post["created_short"] = _short_label(post["created_at"])
    post["expires_label"] = _local_label(post["expires_at"])
    return post


def _liked_post_ids(post_ids: list[int], viewer_id: int | None) -> set[int]:
    """一次查询当前用户在这批留言里点过赞的集合。"""
    if not viewer_id or not post_ids:
        return set()
    placeholders = ",".join("?" for _ in post_ids)
    rows = query_all(
        f"select post_id from board_likes where user_id = ? and post_id in ({placeholders})",
        (viewer_id, *post_ids),
    )
    return {row["post_id"] for row in rows}


def _fetch_posts(limit: int, offset: int, viewer_id: int | None) -> list[dict]:
    """分页读取留言，并附带作者、点赞数、评论数与当前用户的点赞状态。"""
    sql = _post_select() + " where p.deleted_at is null order by p.created_at desc, p.id desc limit ? offset ?"
    rows = [dict(row) for row in query_all(sql, (limit, offset))]
    ids = [row["id"] for row in rows]
    comments = _load_comments(ids)
    liked_ids = _liked_post_ids(ids, viewer_id)
    return [
        _decorate(row, comments.get(row["id"], []), row["id"] in liked_ids) for row in rows
    ]


def _fetch_post(post_id: int, viewer_id: int | None) -> dict | None:
    """读取单条有效留言（含全部评论）。"""
    row = query_one(_post_select() + " where p.id = ? and p.deleted_at is null", (post_id,))
    if not row:
        return None
    post = dict(row)
    comments = _load_comments([post_id])[post_id]
    liked = bool(
        viewer_id
        and query_one(
            "select 1 from board_likes where post_id = ? and user_id = ?",
            (post_id, viewer_id),
        )
    )
    return _decorate(post, comments, liked)


def register_routes(app) -> None:
    # ----- 留言板：浏览、发布、编辑、点赞与评论 -----

    @app.route("/board")
    def board():
        cleanup_expired_posts()
        page = max(request.args.get("page", 1, type=int), 1)
        total = query_one(
            "select count(*) as c from board_posts where deleted_at is null"
        )["c"]
        pages = max((total + PER_PAGE - 1) // PER_PAGE, 1)
        if page > pages:
            return redirect(url_for("board", page=pages))
        viewer_id = g.user["id"] if g.user else None
        posts = _fetch_posts(PER_PAGE, (page - 1) * PER_PAGE, viewer_id)
        pagination = {
            "page": page,
            "pages": pages,
            "total": total,
            "has_prev": page > 1,
            "has_next": page < pages,
            "prev_page": page - 1,
            "next_page": page + 1,
        }
        return render_template(
            "board.html",
            posts=posts,
            pagination=pagination,
            per_page=PER_PAGE,
            posts_left=posts_left_today(viewer_id) if viewer_id else None,
            daily_limit=DAILY_POST_LIMIT,
            retention_days=POST_TTL_DAYS,
        )

    @app.route("/board/posts/<int:post_id>")
    def board_post_detail(post_id: int):
        cleanup_expired_posts()
        post = _fetch_post(post_id, g.user["id"] if g.user else None)
        if not post:
            flash(translate("board.missing"), "error")
            return redirect(url_for("board"))
        return render_template("board_detail.html", post=post)

    @app.route("/board/posts/<int:post_id>/image")
    def board_image(post_id: int):
        """按留言编号读取图片，避免暴露磁盘上的随机文件名。"""
        row = query_one("select image from board_posts where id = ?", (post_id,))
        if not row or not row["image"]:
            return redirect(url_for("board"))
        return send_from_directory(board_dir(), row["image"])

    @app.route("/board/new", methods=("GET", "POST"))
    @login_required
    def board_new():
        left = posts_left_today(g.user["id"])
        if request.method == "POST":
            if left <= 0:
                flash(translate("board.limit_reached", limit=DAILY_POST_LIMIT), "error")
                return redirect(url_for("board"))
            if storage_is_full():
                flash(
                    translate(
                        "board.storage_full",
                        used=board_storage_mb(),
                        budget=round(storage_budget_bytes() / 1024 / 1024),
                    ),
                    "error",
                )
                return redirect(url_for("board_new"))
            caption = request.form.get("caption", "").strip()[:CAPTION_MAX]
            filename, error = save_board_image(request.files.get("image"))
            if error:
                flash(_image_error_message(error), "error")
                return redirect(url_for("board_new"))
            timestamp = now()
            execute(
                """
                insert into board_posts
                  (user_id, caption, image, created_at, updated_at, expires_at)
                values (?, ?, ?, ?, ?, ?)
                """,
                (
                    g.user["id"],
                    caption,
                    filename,
                    timestamp,
                    timestamp,
                    expires_at_from(timestamp),
                ),
            )
            flash(translate("board.created_success"), "success")
            return redirect(url_for("board"))
        return render_template(
            "board_form.html",
            post=None,
            posts_left=left,
            daily_limit=DAILY_POST_LIMIT,
            retention_days=POST_TTL_DAYS,
            caption_max=CAPTION_MAX,
            compress_mb=round(COMPRESS_ABOVE_BYTES / 1024 / 1024),
            max_upload_mb=round(MAX_UPLOAD_BYTES / 1024 / 1024),
        )

    @app.route("/board/posts/<int:post_id>/edit", methods=("GET", "POST"))
    @login_required
    def board_post_edit(post_id: int):
        post = query_one(
            "select * from board_posts where id = ? and deleted_at is null", (post_id,)
        )
        if not post:
            flash(translate("board.missing"), "error")
            return redirect(url_for("board"))
        if post["user_id"] != g.user["id"]:
            flash(translate("board.forbidden"), "error")
            return redirect(url_for("board"))
        if request.method == "POST":
            caption = request.form.get("caption", "").strip()[:CAPTION_MAX]
            uploaded = request.files.get("image")
            new_image = None
            if uploaded and uploaded.filename:
                new_image, error = save_board_image(uploaded)
                if error:
                    flash(_image_error_message(error), "error")
                    return redirect(url_for("board_post_edit", post_id=post_id))
            if new_image:
                execute(
                    "update board_posts set caption = ?, image = ?, updated_at = ? where id = ?",
                    (caption, new_image, now(), post_id),
                )
                delete_board_image(post["image"])
            else:
                execute(
                    "update board_posts set caption = ?, updated_at = ? where id = ?",
                    (caption, now(), post_id),
                )
            flash(translate("board.updated_success"), "success")
            return redirect(url_for("board_post_detail", post_id=post_id))
        return render_template(
            "board_form.html",
            post=post,
            posts_left=None,
            daily_limit=DAILY_POST_LIMIT,
            retention_days=POST_TTL_DAYS,
            caption_max=CAPTION_MAX,
            compress_mb=round(COMPRESS_ABOVE_BYTES / 1024 / 1024),
            max_upload_mb=round(MAX_UPLOAD_BYTES / 1024 / 1024),
        )

    @app.route("/board/posts/<int:post_id>/delete", methods=("POST",))
    @login_required
    def board_post_delete(post_id: int):
        """发布者本人或超级管理员删除留言：真删除，内容与图片都不会留在磁盘上。"""
        post = query_one("select * from board_posts where id = ?", (post_id,))
        if not post:
            flash(translate("board.missing"), "error")
            return redirect(url_for("board"))
        is_admin = g.user["role"] == "super_admin"
        if post["user_id"] != g.user["id"] and not is_admin:
            flash(translate("board.forbidden"), "error")
            return redirect(url_for("board"))
        purge_post(
            post_id,
            actor_id=g.user["id"],
            action="post_deleted_by_admin" if is_admin and post["user_id"] != g.user["id"] else "post_deleted",
        )
        flash(translate("board.deleted"), "success")
        return redirect(_safe_back(url_for("board")))

    @app.route("/board/posts/<int:post_id>/like", methods=("POST",))
    @login_required
    def board_like_toggle(post_id: int):
        post = query_one(
            "select id from board_posts where id = ? and deleted_at is null", (post_id,)
        )
        if not post:
            flash(translate("board.missing"), "error")
            return redirect(url_for("board"))
        existing = query_one(
            "select id from board_likes where post_id = ? and user_id = ?",
            (post_id, g.user["id"]),
        )
        if existing:
            execute("delete from board_likes where id = ?", (existing["id"],))
        else:
            execute(
                "insert into board_likes (post_id, user_id, created_at) values (?, ?, ?)",
                (post_id, g.user["id"], now()),
            )
        return redirect(_safe_back(url_for("board")))

    @app.route("/board/posts/<int:post_id>/comments", methods=("POST",))
    @login_required
    def board_comment_add(post_id: int):
        post = query_one(
            "select id from board_posts where id = ? and deleted_at is null", (post_id,)
        )
        if not post:
            flash(translate("board.missing"), "error")
            return redirect(url_for("board"))
        content = request.form.get("content", "").strip()[:COMMENT_MAX]
        if not content:
            flash(translate("board.comment_required"), "error")
        else:
            execute(
                "insert into board_comments (post_id, user_id, content, created_at) values (?, ?, ?, ?)",
                (post_id, g.user["id"], content, now()),
            )
            flash(translate("board.comment_added"), "success")
        return redirect(_safe_back(url_for("board_post_detail", post_id=post_id)))

    @app.route("/board/comments/<int:comment_id>/delete", methods=("POST",))
    @login_required
    def board_comment_delete(comment_id: int):
        """评论作者与超级管理员都可以删除评论；同样是真删除。"""
        comment = query_one("select * from board_comments where id = ?", (comment_id,))
        if not comment:
            flash(translate("board.comment_missing"), "error")
            return redirect(url_for("board"))
        is_admin = g.user["role"] == "super_admin"
        if comment["user_id"] != g.user["id"] and not is_admin:
            flash(translate("board.forbidden"), "error")
            return redirect(_safe_back(url_for("board")))
        purge_comment(
            comment_id,
            actor_id=g.user["id"],
            action="comment_deleted_by_admin" if is_admin and comment["user_id"] != g.user["id"] else "comment_deleted",
        )
        flash(translate("board.comment_deleted"), "success")
        return redirect(_safe_back(url_for("board")))

    @app.route("/admin/board")
    @role_required("super_admin")
    def board_admin():
        """管理视图：集中列出全部有效留言与评论，便于快速清理不合规内容。"""
        db = get_db()
        posts = [
            dict(row)
            for row in db.execute(
                """
                select p.*, u.display_name,
                       (select count(*) from board_comments c
                         where c.post_id = p.id and c.deleted_at is null) as comment_count,
                       (select count(*) from board_likes l where l.post_id = p.id) as like_count
                from board_posts p join users u on u.id = p.user_id
                where p.deleted_at is null
                order by p.created_at desc, p.id desc
                """
            ).fetchall()
        ]
        for post in posts:
            post["created_label"] = _local_label(post["created_at"])
            post["created_short"] = _short_label(post["created_at"])
            post["expires_label"] = _local_label(post["expires_at"])
            days_left = _days_left(post["expires_at"])
            post["days_label"] = (
                translate("board.expires_today")
                if days_left <= 0
                else translate("board.days_left", days=days_left)
            )
            post["comments"] = [
                dict(row)
                for row in db.execute(
                    """
                    select c.*, u.display_name
                    from board_comments c join users u on u.id = c.user_id
                    where c.post_id = ? and c.deleted_at is null
                    order by c.created_at asc, c.id asc
                    """,
                    (post["id"],),
                ).fetchall()
            ]
        return render_template(
            "board_admin.html",
            posts=posts,
            storage_used_mb=board_storage_mb(),
            storage_budget_mb=round(storage_budget_bytes() / 1024 / 1024),
            deletion_log_days=DELETION_LOG_TTL_DAYS,
        )
