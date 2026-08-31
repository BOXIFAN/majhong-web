"""比赛列表、公告、语言切换和静态辅助路由。"""

from __future__ import annotations

from flask import flash, g, redirect, render_template, request, session, url_for

from brml.auth import role_required
from brml.db import execute, query_all, query_one
from brml.i18n import SUPPORTED_LOCALES, translate
from brml.timeutils import now


def register_routes(app) -> None:
    # ----- 对局、公告与静态辅助路由 -----

    @app.route("/matches")
    def matches():
        per_page = 20
        page = max(request.args.get("page", 1, type=int), 1)
        total = query_one("select count(*) as c from matches")["c"]
        pages = max((total + per_page - 1) // per_page, 1)
        if page > pages:
            return redirect(url_for("matches", page=pages))
        rows = query_all(
            """
            select m.*, u.display_name as referee_name
            from matches m left join users u on u.id = m.referee_id
            order by m.played_at desc, m.id desc limit ? offset ?
            """,
            (per_page, (page - 1) * per_page),
        )
        pagination = {
            "page": page,
            "pages": pages,
            "total": total,
            "has_prev": page > 1,
            "has_next": page < pages,
            "prev_page": page - 1,
            "next_page": page + 1,
        }
        return render_template("matches.html", matches=rows, pagination=pagination)

    @app.route("/announcements/<int:announcement_id>")
    def announcement_view(announcement_id: int):
        announcement = query_one(
            """
            select a.*, u.display_name as author_name
            from announcements a
            left join users u on u.id = a.author_id
            where a.id = ?
            """,
            (announcement_id,),
        )
        if not announcement:
            flash(translate("announcement.missing"), "error")
            return redirect(url_for("index"))
        return render_template("announcement_detail.html", announcement=announcement)

    @app.route("/admin/announcements", methods=("GET", "POST"))
    @role_required("super_admin")
    def announcements():
        if request.method == "POST":
            title = request.form.get("title", "").strip()
            content = request.form.get("content", "").strip()
            if not title or not content:
                flash(translate("announcement.required"), "error")
            else:
                timestamp = now()
                execute(
                    "insert into announcements (title, content, author_id, created_at, updated_at) values (?, ?, ?, ?, ?)",
                    (title, content, g.user["id"], timestamp, timestamp),
                )
                flash(translate("announcement.created"), "success")
                return redirect(url_for("announcements"))
        rows = query_all(
            """
            select a.*, u.display_name as author_name
            from announcements a left join users u on u.id = a.author_id
            order by a.created_at desc, a.id desc
            """
        )
        return render_template("announcements.html", announcements=rows)

    @app.route("/admin/announcements/<int:announcement_id>/edit", methods=("GET", "POST"))
    @role_required("super_admin")
    def announcement_edit(announcement_id: int):
        announcement = query_one("select * from announcements where id = ?", (announcement_id,))
        if not announcement:
            flash(translate("announcement.missing"), "error")
            return redirect(url_for("announcements"))
        if request.method == "POST":
            title = request.form.get("title", "").strip()
            content = request.form.get("content", "").strip()
            if not title or not content:
                flash(translate("announcement.required"), "error")
            else:
                execute(
                    "update announcements set title = ?, content = ?, updated_at = ? where id = ?",
                    (title, content, now(), announcement_id),
                )
                flash(translate("announcement.updated"), "success")
                return redirect(url_for("announcements"))
        return render_template("announcement_form.html", announcement=announcement)

    @app.route("/admin/announcements/<int:announcement_id>/delete", methods=("POST",))
    @role_required("super_admin")
    def announcement_delete(announcement_id: int):
        announcement = query_one("select id from announcements where id = ?", (announcement_id,))
        if not announcement:
            flash(translate("announcement.missing"), "error")
        else:
            execute("delete from announcements where id = ?", (announcement_id,))
            flash(translate("announcement.deleted"), "success")
        return redirect(url_for("announcements"))

    @app.route("/favicon.ico")
    def favicon():
        return redirect(url_for("static", filename="web_logo.jpg"))

    @app.route("/language/<locale>")
    def set_language(locale: str):
        if locale in SUPPORTED_LOCALES:
            session["locale"] = locale
        return redirect(request.referrer or url_for("index"))
