"""比赛列表、公告、语言切换和静态辅助路由。"""

from __future__ import annotations

from datetime import datetime

from flask import flash, g, redirect, render_template, request, session, url_for

from brml.auth import role_required
from brml.db import execute, query_all, query_one
from brml.i18n import SUPPORTED_LOCALES, get_locale, translate
from brml.match_service import current_season
from brml.timeutils import WEEKDAY_LABELS, now, weekday_label


def _attach_match_entries(rows: list[dict]) -> list[dict]:
    """给对局列表补上牌手与得分摘要（调研报告 P1-7 / 可用性 4）。

    列表页原本只有「类型 + 时间 + 裁判」，玩家与结果必须点进详情才能看到。
    这里一次性批量查询，避免 N+1。
    """
    if not rows:
        return rows
    placeholders = ",".join("?" for _ in rows)
    entries_map: dict[int, list[dict]] = {}
    for entry in query_all(
        f"""
        select me.match_id, me.placement, me.final_score, me.rank_points, me.penalty_points,
               u.display_name, u.id as user_id
        from match_entries me join users u on u.id = me.user_id
        where me.match_id in ({placeholders})
        order by me.match_id, me.placement asc, me.final_score desc
        """,
        tuple(row["id"] for row in rows),
    ):
        entries_map.setdefault(entry["match_id"], []).append(dict(entry))

    locale = get_locale() if get_locale() in WEEKDAY_LABELS else "zh"
    for row in rows:
        entries = entries_map.get(row["id"], [])
        row["entries"] = entries
        row["winner"] = entries[0] if entries else None
        row["player_names"] = " / ".join(entry["display_name"] for entry in entries)
        row["date_key"] = row["played_at"][:10]
        row["time_label"] = row["played_at"][11:16]
        row["entry_count"] = len(entries)
        row["weekday_label"] = weekday_label(row["date_key"], locale)
        row["date_label"] = f"{row['date_key'][5:]} {row['weekday_label']}".strip()
    return rows


def _group_matches_by_day(rows: list[dict]) -> list[dict]:
    """把对局按日期分组，让列表变成可扫读的时间线。"""
    groups: list[dict] = []
    for row in rows:
        if not groups or groups[-1]["date"] != row["date_key"]:
            groups.append(
                {
                    "date": row["date_key"],
                    "label": row.get("date_label") or row["date_key"],
                    "matches": [],
                }
            )
        groups[-1]["matches"].append(row)
    return groups


def register_routes(app) -> None:
    # ----- 对局、公告与静态辅助路由 -----

    @app.route("/matches")
    def matches():
        per_page = 20
        page = max(request.args.get("page", 1, type=int), 1)
        raw_season_id = request.args.get("season_id")
        season_id = request.args.get("season_id", type=int)
        if raw_season_id is None:
            # 未指定赛季（默认进入首页入口）时按当前激活赛季展示；
            # 显式选择“全部赛季”（season_id 为空串）时保持 season_id=None，展示所有赛季。
            season = current_season()
            season_id = season["id"] if season else None
        seasons_data = query_all("select * from seasons order by start_date desc, id desc")
        selected_season = (
            query_one("select * from seasons where id = ?", (season_id,)) if season_id else None
        )
        filters = ""
        params: tuple = ()
        if season_id:
            filters = "where m.season_id = ?"
            params = (season_id,)
        total = query_one(f"select count(*) as c from matches m {filters}", params)["c"]
        pages = max((total + per_page - 1) // per_page, 1)
        # 分页链接需要用空串保留“全部赛季”状态（url_for 会输出 season_id=），
        # 否则跳页时会退回到默认的“当前赛季”。
        season_param = season_id if season_id else ""
        if page > pages:
            return redirect(url_for("matches", page=pages, season_id=season_param))
        rows = [
            dict(row)
            for row in query_all(
                f"""
                select m.*, u.display_name as referee_name
                from matches m left join users u on u.id = m.referee_id
                {filters}
                order by m.played_at desc, m.id desc limit ? offset ?
                """,
                params + (per_page, (page - 1) * per_page),
            )
        ]
        _attach_match_entries(rows)
        match_groups = _group_matches_by_day(rows)
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
            "matches.html",
            matches=rows,
            match_groups=match_groups,
            pagination=pagination,
            seasons=seasons_data,
            selected_season=selected_season,
            season_id=season_param,
        )

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
            return render_template("404.html", not_found_kind="announcement"), 404
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
