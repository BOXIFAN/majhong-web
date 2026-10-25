"""首页、关于页面与 Meetup 业务路由。"""

from __future__ import annotations

import sqlite3

from flask import flash, g, redirect, render_template, request, url_for

from brml.auth import login_required, role_required
from brml.config import (
    DEFAULT_MEETUP_VENUE,
    MEETUP_DEFAULT_TITLE,
    MEETUP_FEE_NOTE,
    MEETUP_MAP_URL,
    SITE_VERSION,
)
from brml.db import execute, get_db, query_all, query_one
from brml.i18n import translate
from brml.match_service import current_season
from brml.meetup_service import auto_archive_expired_meetups, meetup_status, signup_member
from brml.timeutils import brisbane_local_now, now, parse_local_datetime


def _is_mostly_english(text: str | None) -> bool:
    """判断公告正文是否基本是英文，用于在中文界面标注「英文原文」。

    只做粗略判断：无 CJK 字符且拉丁字母足够多即视为英文；中英混排不标注。
    """
    if not text:
        return False
    cjk = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    latin = sum(1 for char in text if char.isascii() and char.isalpha())
    return cjk == 0 and latin > 40


def _with_status(row) -> dict:
    """把数据库行转成模板可直接使用的 dict，并补上计算状态。"""
    item = dict(row)
    item["status"] = meetup_status(row)
    item["display_title"] = item.get("title") or MEETUP_DEFAULT_TITLE
    return item


def _load_next_meetup() -> dict | None:
    """首页「下一场活动」模块的数据（调研报告：最高杠杆修复 1）。

    只读查询：首页不触发自动归档等写操作，保证浏览首页不会改动任何现有数据。
    取「尚未归档且尚未开始」的最近一场；优先推仍可报名的场次，
    没有可报名场次时再退回最近一场（即使报名已截止），保证状态说真话。
    """
    now_text = brisbane_local_now().strftime("%Y-%m-%d %H:%M:%S")
    row = query_one(
        """
        select m.*, count(ms.id) as attendee_count
        from meetups m left join meetup_signups ms on ms.meetup_id = m.id
        where m.archived_at is null and m.meetup_at >= ?
        group by m.id
        order by case when m.signup_deadline >= ? then 0 else 1 end, m.meetup_at asc
        limit 1
        """,
        (now_text, now_text),
    )
    if not row:
        return None
    item = _with_status(row)
    item["attendee_count"] = row["attendee_count"]
    return item


def register_routes(app) -> None:
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
        announcement_items = [dict(row) for row in announcements]
        for item in announcement_items:
            item["is_english"] = _is_mostly_english(item.get("content"))
        return render_template(
            "index.html",
            current_season=season,
            season_match_count=season_match_count,
            current_member_count=current_member_count,
            site_version=SITE_VERSION,
            next_meetup=_load_next_meetup(),
            latest_announcement=announcement_items[0] if announcement_items else None,
            past_announcements=announcement_items[1:],
        )

    @app.route("/about")
    def about():
        return render_template("about.html")

    @app.route("/meetups")
    def meetups():
        auto_archive_expired_meetups()
        per_page = 8
        page = max(request.args.get("page", 1, type=int), 1)
        meetup_rows = query_all(
            """
            select m.*, u.display_name as creator_name, count(ms.id) as attendee_count
            from meetups m
            left join users u on u.id = m.created_by
            left join meetup_signups ms on ms.meetup_id = m.id
            group by m.id
            order by m.meetup_at asc, m.id asc
            """
        )
        signed_up_ids: set[int] = set()
        if g.user:
            signed_up_ids = {
                row["meetup_id"]
                for row in query_all(
                    "select meetup_id from meetup_signups where user_id = ?",
                    (g.user["id"],),
                )
            }
        items = []
        for meetup in meetup_rows:
            item = _with_status(meetup)
            item["attendee_count"] = meetup["attendee_count"]
            item["signed_up"] = meetup["id"] in signed_up_ids
            items.append(item)
        # 报名页分「即将开始 / 已结束」两段：过期活动不再与可报名活动抢注意力，
        # 且每段都有明确的状态与 CTA（调研报告 A-1、P0-2、移动端专项 5）。
        upcoming = [item for item in items if item["archived_at"] is None]
        past = [item for item in items if item["archived_at"] is not None]
        total = len(past)
        pages = max((total + per_page - 1) // per_page, 1)
        if page > pages:
            return redirect(url_for("meetups", page=pages))
        past_page = past[(page - 1) * per_page : page * per_page]
        pagination = {
            "page": page,
            "pages": pages,
            "total": total,
            "has_prev": page > 1,
            "has_next": page < pages,
            "prev_page": page - 1,
            "next_page": page + 1,
            "page_numbers": list(range(max(1, page - 2), min(pages, page + 2) + 1)),
        }
        return render_template(
            "meetups.html",
            meetups=upcoming + past_page,
            upcoming_meetups=upcoming,
            past_meetups=past_page,
            next_meetup=upcoming[0] if upcoming else None,
            pagination=pagination,
        )

    @app.route("/meetups/<int:meetup_id>")
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
            return render_template("404.html", not_found_kind="meetup"), 404
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
        if g.user and g.user["role"] == "super_admin":
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
        is_signed_up = g.user is not None and any(
            attendee["user_id"] == g.user["id"] for attendee in attendees
        )
        return render_template(
            "meetup_detail.html",
            meetup=meetup,
            attendees=attendees,
            eligible_users=eligible_users,
            status=status,
            is_signed_up=is_signed_up,
            display_title=meetup["title"] or MEETUP_DEFAULT_TITLE,
            fee_note=translate("meetup2.fee_value"),
            map_url=MEETUP_MAP_URL,
            # 「查看下一场」优先推荐仍可报名的场次，其次才是最近一场（可能已截止）。
            next_upcoming=query_one(
                """
                select * from meetups
                where archived_at is null and id != ? and meetup_at >= ?
                order by case when signup_deadline >= ? then 0 else 1 end, meetup_at asc
                limit 1
                """,
                (
                    meetup_id,
                    brisbane_local_now().strftime("%Y-%m-%d %H:%M:%S"),
                    brisbane_local_now().strftime("%Y-%m-%d %H:%M:%S"),
                ),
            ),
        )

    @app.route("/admin/meetups/new", methods=("POST",))
    @role_required("super_admin")
    def meetup_new():
        meetup_at = parse_local_datetime(request.form.get("meetup_at", ""))
        signup_deadline = parse_local_datetime(request.form.get("signup_deadline", ""))
        venue = request.form.get("venue", "").strip() or DEFAULT_MEETUP_VENUE
        title = request.form.get("title", "").strip() or None
        note = request.form.get("note", "").strip() or None
        capacity = request.form.get("capacity", type=int)
        if not meetup_at or not signup_deadline:
            flash(translate("meetup.time_required"), "error")
        elif signup_deadline > meetup_at:
            flash(translate("meetup.deadline_order"), "error")
        else:
            timestamp = now()
            execute(
                """
                insert into meetups (meetup_at, signup_deadline, venue, title, capacity, note, created_by, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (meetup_at, signup_deadline, venue, title, capacity, note, g.user["id"], timestamp, timestamp),
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
            title = request.form.get("title", "").strip() or None
            note = request.form.get("note", "").strip() or None
            capacity = request.form.get("capacity", type=int)
            if not meetup_at or not signup_deadline:
                flash(translate("meetup.time_required"), "error")
            elif signup_deadline > meetup_at:
                flash(translate("meetup.deadline_order"), "error")
            else:
                execute(
                    """
                    update meetups
                    set meetup_at = ?, signup_deadline = ?, venue = ?, title = ?, capacity = ?, note = ?, updated_at = ?
                    where id = ?
                    """,
                    (meetup_at, signup_deadline, venue, title, capacity, note, now(), meetup_id),
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
        result = signup_member(meetup_id, g.user["id"])
        if result == "missing":
            flash(translate("meetup.missing"), "error")
            return redirect(url_for("meetups"))
        if result == "closed":
            flash(translate("meetup.signup_closed"), "error")
            return redirect(url_for("meetup_detail", meetup_id=meetup_id))
        if result == "duplicate":
            # 已经报名过：不是失败操作，给中性提示而不是红色报错。
            flash(translate("meetup2.duplicate_info"), "info")
        else:
            flash(translate("meetup.signup_success"), "success")
        return redirect(url_for("meetup_detail", meetup_id=meetup_id))

    @app.route("/meetups/<int:meetup_id>/signup/cancel", methods=("POST",))
    @login_required
    def meetup_signup_cancel(meetup_id: int):
        """取消自己的活动报名：只删除本人在该活动的报名行，不触碰其他数据。"""
        meetup = query_one("select id from meetups where id = ?", (meetup_id,))
        if not meetup:
            flash(translate("meetup.missing"), "error")
            return redirect(url_for("meetups"))
        db = get_db()
        cursor = db.execute(
            "delete from meetup_signups where meetup_id = ? and user_id = ?",
            (meetup_id, g.user["id"]),
        )
        db.commit()
        if cursor.rowcount:
            flash(translate("meetup2.cancel_success"), "success")
        else:
            flash(translate("meetup2.cancel_missing"), "info")
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
