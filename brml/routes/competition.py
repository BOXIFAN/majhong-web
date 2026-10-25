"""比赛录入、排行榜、玩家档案与 CSV 导出路由。"""

from __future__ import annotations

import csv
import io
import json

from flask import Response, flash, g, redirect, render_template, request, url_for

from brml.analytics import (
    build_finals_status,
    build_placement_trend,
    build_player_radar,
    get_leaderboard,
    season_radar_median,
)
from brml.auth import role_required
from brml.db import get_db, query_all, query_one
from brml.i18n import get_locale, translate
from brml.match_service import (
    create_match_from_form,
    current_season,
    match_type_label,
    parse_match_result_form,
    update_match_from_result,
)
from brml.rules import normalize_rules
from brml.timeutils import current_match_time, weekday_label


def register_routes(app) -> None:
    @app.route("/matches/new", methods=("GET", "POST"))
    @role_required("super_admin", "referee")
    def match_new():
        season = current_season()
        if not season:
            flash(translate("flash.season_required"), "error")
            return redirect(url_for("seasons"))
        players = query_all("select * from users where role in ('referee', 'user') and is_deleted = 0 order by display_name")
        if request.method == "POST":
            result = create_match_from_form(season, request.form)
            if result["ok"]:
                flash(translate("flash.match_created"), "success")
                return redirect(url_for("match_detail", match_id=result["match_id"]))
            for error in result["errors"]:
                flash(error, "error")
        return render_template(
            "match_form.html",
            season=season,
            players=players,
            rules=normalize_rules(json.loads(season["rules_json"])),
            match_time=current_match_time(),
        )

    @app.route("/matches/<int:match_id>")
    def match_detail(match_id: int):
        match = query_one(
            """
            select m.*, s.name as season_name, u.display_name as referee_name
            from matches m
            join seasons s on s.id = m.season_id
            left join users u on u.id = m.referee_id
            where m.id = ?
            """,
            (match_id,),
        )
        if not match:
            return render_template("404.html", not_found_kind="match"), 404
        entries = query_all(
            """
            select me.*, u.display_name
            from match_entries me join users u on u.id = me.user_id
            where me.match_id = ?
            order by me.placement asc, me.final_score desc
            """,
            (match_id,),
        )
        penalties = query_all(
            """
            select p.*, u.display_name
            from penalties p join users u on u.id = p.user_id
            where p.match_id = ?
            order by p.id
            """,
            (match_id,),
        )
        # 详情页需要身份与上下文：前一/后一场、桌型、所属赛季（调研报告可用性 4）。
        neighbours = query_all(
            """
            select id, played_at, table_name from matches
            where played_at < ? or (played_at = ? and id < ?)
            order by played_at desc, id desc limit 1
            """,
            (match["played_at"], match["played_at"], match_id),
        )
        following = query_all(
            """
            select id, played_at, table_name from matches
            where played_at > ? or (played_at = ? and id > ?)
            order by played_at asc, id asc limit 1
            """,
            (match["played_at"], match["played_at"], match_id),
        )
        date_label = match["played_at"][:10]
        date_weekday = weekday_label(date_label, get_locale())
        return render_template(
            "match_detail.html",
            match=match,
            entries=entries,
            penalties=penalties,
            prev_match=neighbours[0] if neighbours else None,
            next_match=following[0] if following else None,
            date_label=date_label,
            weekday_label=date_weekday,
            table_label=match_type_label(match["table_name"]),
            entry_count=len(entries),
        )

    @app.route("/matches/<int:match_id>/edit", methods=("GET", "POST"))
    @role_required("super_admin")
    def match_edit(match_id: int):
        match = query_one(
            """
            select m.*, s.name as season_name, s.rules_json
            from matches m join seasons s on s.id = m.season_id
            where m.id = ?
            """,
            (match_id,),
        )
        if not match:
            flash(translate("flash.match_missing"), "error")
            return redirect(url_for("index"))
        entries = query_all(
            "select * from match_entries where match_id = ? order by id",
            (match_id,),
        )
        involved_ids = [entry["user_id"] for entry in entries]
        if involved_ids:
            placeholders = ",".join("?" for _ in involved_ids)
            players = query_all(
                f"""
                select * from users
                where is_deleted = 0 or id in ({placeholders})
                order by display_name
                """,
                tuple(involved_ids),
            )
        else:
            players = query_all("select * from users where is_deleted = 0 order by display_name")

        if request.method == "POST":
            result = parse_match_result_form(match, request.form)
            if result["ok"]:
                update_match_from_result(match_id, match, request.form, result)
                flash(translate("flash.match_updated"), "success")
                return redirect(url_for("match_detail", match_id=match_id))
            for error in result["errors"]:
                flash(error, "error")

        penalty_lookup = {
            row["user_id"]: row
            for row in query_all(
                """
                select user_id, sum(points) as points,
                       group_concat(penalty_type, ' / ') as penalty_type,
                       group_concat(reason, '；') as reason
                from penalties
                where match_id = ?
                group by user_id
                """,
                (match_id,),
            )
        }
        edit_rows = []
        for entry in entries:
            penalty = penalty_lookup.get(entry["user_id"])
            edit_rows.append({"entry": entry, "penalty": penalty})
        rules = normalize_rules(json.loads(match["rules_json"]))
        return render_template(
            "match_edit.html",
            match=match,
            match_time=match["played_at"].replace(" ", "T")[:16],
            rows=edit_rows,
            players=players,
            rules=rules,
        )

    @app.route("/matches/<int:match_id>/delete", methods=("POST",))
    @role_required("super_admin")
    def match_delete(match_id: int):
        match = query_one("select * from matches where id = ?", (match_id,))
        if not match:
            flash(translate("flash.match_delete_missing"), "error")
            return redirect(url_for("index"))

        db = get_db()
        db.execute("delete from penalties where match_id = ?", (match_id,))
        db.execute("delete from match_entries where match_id = ?", (match_id,))
        db.execute("delete from matches where id = ?", (match_id,))
        db.commit()
        flash(translate("flash.match_deleted"), "success")
        return redirect(url_for("leaderboard", season_id=match["season_id"]))

    @app.route("/leaderboard")
    def leaderboard():
        seasons_data = query_all("select * from seasons order by start_date desc, id desc")
        season_id = request.args.get("season_id", type=int)
        season = query_one("select * from seasons where id = ?", (season_id,)) if season_id else current_season()
        rows = get_leaderboard(season["id"]) if season else []
        finals_status = build_finals_status(season, rows, g.user) if season else None
        # 图例与切线的语义来源：与 build_finals_status 保持一致（前 4 = 决赛席位，
        # 末 4 = 烧鸟区）。行数不足 4 时整行色带没有意义，直接停用。
        top_count = 4 if len(rows) >= 4 else 0
        bottom_count = 4 if len(rows) >= 4 else 0
        legend = {
            "enabled": top_count > 0,
            "top_count": top_count,
            "bottom_count": bottom_count,
            "has_cut_line": len(rows) > 8,
            "is_historical": bool(season and season["status"] != "active"),
            "is_test_season": bool(season and "tester" in season["name"].lower()),
            "row_count": len(rows),
        }
        return render_template(
            "leaderboard.html",
            seasons=seasons_data,
            selected_season=season,
            rows=rows,
            finals_status=finals_status,
            legend=legend,
        )

    @app.route("/players/<int:user_id>")
    def player_profile(user_id: int):
        user = query_one("select * from users where id = ? and is_deleted = 0", (user_id,))
        if not user:
            return render_template("404.html", not_found_kind="player"), 404
        season = current_season()
        leaderboard = get_leaderboard(season["id"]) if season else []
        player_stats = next((row for row in leaderboard if row["user_id"] == user_id), None)
        per_page = 5
        page = max(request.args.get("page", 1, type=int), 1)
        history_total = query_one(
            "select count(*) as c from match_entries where user_id = ?",
            (user_id,),
        )["c"]
        history_pages = max((history_total + per_page - 1) // per_page, 1)
        if page > history_pages:
            return redirect(url_for("player_profile", user_id=user_id, page=history_pages))
        history = query_all(
            """
            select m.id as match_id, m.played_at, me.final_score, me.placement, me.rank_points
            from match_entries me join matches m on m.id = me.match_id
            where me.user_id = ?
            order by m.played_at desc, m.id desc limit ? offset ?
            """,
            (user_id, per_page, (page - 1) * per_page),
        )
        trend_history = query_all(
            """
            select m.id as match_id, m.played_at, me.final_score, me.placement, me.rank_points
            from match_entries me join matches m on m.id = me.match_id
            where me.user_id = ?
            order by m.played_at desc, m.id desc limit 10
            """,
            (user_id,),
        )
        season_entries = query_all(
            """
            select me.final_score, me.placement, me.rank_points, m.played_at, m.id as match_id
            from match_entries me join matches m on m.id = me.match_id
            where me.user_id = ? and m.season_id = ?
            order by m.played_at asc, m.id asc
            """,
            (user_id, season["id"]),
        ) if season else []
        trend = build_placement_trend(trend_history)
        radar = build_player_radar(season_entries)
        radar_median = season_radar_median(season["id"]) if season else {"has_data": False, "points": "", "nodes": [], "display": []}
        pagination = {
            "page": page,
            "pages": history_pages,
            "total": history_total,
            "has_prev": page > 1,
            "has_next": page < history_pages,
            "prev_page": page - 1,
            "next_page": page + 1,
        }
        # 从留言板进来的玩家页，返回按钮应该回留言板而不是排行榜（评审 P1-4）。
        referrer = request.referrer or ""
        if "/board" in referrer:
            back_href = url_for("board")
            back_label = translate("board.back")
        elif "/matches" in referrer:
            back_href = url_for("matches")
            back_label = translate("nav.matches")
        else:
            back_href = url_for("leaderboard")
            back_label = translate("player2.back")
        return render_template(
            "player.html",
            user=user,
            back_href=back_href,
            back_label=back_label,
            stats=player_stats,
            history=history,
            trend=trend,
            radar=radar,
            radar_median=radar_median,
            pagination=pagination,
        )

    @app.route("/export/season/<int:season_id>.csv")
    @role_required("super_admin")
    def export_season(season_id: int):
        rows = get_leaderboard(season_id)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["rank", "player", "points", "matches", "avg_place", "first_rate", "fourth_rate", "penalties"])
        for idx, row in enumerate(rows, start=1):
            writer.writerow([
                idx,
                row["display_name"],
                row["total_points"],
                row["matches"],
                row["avg_place"],
                row["first_rate"],
                row["fourth_rate"],
                row["penalty_points"],
            ])
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename=season-{season_id}-leaderboard.csv"},
        )
