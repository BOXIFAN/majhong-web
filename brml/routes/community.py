"""首页、关于页面与 Meetup 业务路由。"""

from __future__ import annotations

import sqlite3

from flask import flash, g, redirect, render_template, request, url_for

from brml.auth import login_required, role_required
from brml.config import DEFAULT_MEETUP_VENUE, SITE_VERSION
from brml.db import execute, get_db, query_all, query_one
from brml.i18n import translate
from brml.match_service import current_season
from brml.meetup_service import auto_archive_expired_meetups, meetup_status
from brml.timeutils import now, parse_local_datetime


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
        return render_template(
            "index.html",
            current_season=season,
            season_match_count=season_match_count,
            current_member_count=current_member_count,
            site_version=SITE_VERSION,
            latest_announcement=announcements[0] if announcements else None,
            past_announcements=announcements[1:],
        )

    @app.route("/about")
    def about():
        return render_template("about.html")

    @app.route("/meetups")
    @login_required
    def meetups():
        auto_archive_expired_meetups()
        per_page = 8
        page = max(request.args.get("page", 1, type=int), 1)
        total = query_one("select count(*) as c from meetups")["c"]
        pages = max((total + per_page - 1) // per_page, 1)
        if page > pages:
            return redirect(url_for("meetups", page=pages))
        meetup_rows = query_all(
            """
            select m.*, u.display_name as creator_name, count(ms.id) as attendee_count
            from meetups m
            left join users u on u.id = m.created_by
            left join meetup_signups ms on ms.meetup_id = m.id
            group by m.id
            order by m.meetup_at desc, m.id desc
            limit ? offset ?
            """,
            (per_page, (page - 1) * per_page),
        )
        meetup_items = []
        for meetup in meetup_rows:
            item = dict(meetup)
            item["status"] = meetup_status(meetup)
            meetup_items.append(item)
        pagination = {
            "page": page,
            "pages": pages,
            "total": total,
            "has_prev": page > 1,
            "has_next": page < pages,
            "prev_page": page - 1,
            "next_page": page + 1,
        }
        return render_template("meetups.html", meetups=meetup_items, pagination=pagination)

    @app.route("/meetups/<int:meetup_id>")
    @login_required
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
            flash(translate("meetup.missing"), "error")
            return redirect(url_for("meetups"))
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
        if g.user["role"] == "super_admin":
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
        is_signed_up = any(attendee["user_id"] == g.user["id"] for attendee in attendees)
        return render_template(
            "meetup_detail.html",
            meetup=meetup,
            attendees=attendees,
            eligible_users=eligible_users,
            status=status,
            is_signed_up=is_signed_up,
        )

    @app.route("/admin/meetups/new", methods=("POST",))
    @role_required("super_admin")
    def meetup_new():
        meetup_at = parse_local_datetime(request.form.get("meetup_at", ""))
        signup_deadline = parse_local_datetime(request.form.get("signup_deadline", ""))
        venue = request.form.get("venue", "").strip() or DEFAULT_MEETUP_VENUE
        if not meetup_at or not signup_deadline:
            flash(translate("meetup.time_required"), "error")
        elif signup_deadline > meetup_at:
            flash(translate("meetup.deadline_order"), "error")
        else:
            timestamp = now()
            execute(
                "insert into meetups (meetup_at, signup_deadline, venue, created_by, created_at, updated_at) values (?, ?, ?, ?, ?, ?)",
                (meetup_at, signup_deadline, venue, g.user["id"], timestamp, timestamp),
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
            if not meetup_at or not signup_deadline:
                flash(translate("meetup.time_required"), "error")
            elif signup_deadline > meetup_at:
                flash(translate("meetup.deadline_order"), "error")
            else:
                execute(
                    "update meetups set meetup_at = ?, signup_deadline = ?, venue = ?, updated_at = ? where id = ?",
                    (meetup_at, signup_deadline, venue, now(), meetup_id),
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
        auto_archive_expired_meetups()
        meetup = query_one("select * from meetups where id = ?", (meetup_id,))
        if not meetup:
            flash(translate("meetup.missing"), "error")
            return redirect(url_for("meetups"))
        if meetup_status(meetup) != "open":
            flash(translate("meetup.signup_closed"), "error")
            return redirect(url_for("meetup_detail", meetup_id=meetup_id))
        try:
            execute(
                "insert into meetup_signups (meetup_id, user_id, created_at) values (?, ?, ?)",
                (meetup_id, g.user["id"], now()),
            )
            flash(translate("meetup.signup_success"), "success")
        except sqlite3.IntegrityError:
            flash(translate("meetup.signup_duplicate"), "error")
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
