"""实验功能路由（不参与上线）。"""

from __future__ import annotations

from flask import flash, g, redirect, render_template, url_for

from brml.auth import login_required
from brml.analytics import build_player_radar, build_vector_radar
from brml.db import query_all, query_one
from brml.i18n import translate
from brml.match_service import current_season
from brml.stylematch import best_style_match


def register_routes(app) -> None:
    @app.route("/experiment/style-match")
    @login_required
    def style_match():
        return redirect(url_for("style_match_for", user_id=g.user["id"]))

    @app.route("/experiment/style-match/<int:user_id>")
    @login_required
    def style_match_for(user_id: int):
        target = query_one(
            "select id, display_name from users where id = ? and is_deleted = 0",
            (user_id,),
        )
        if not target:
            flash(translate("flash.player_missing"), "error")
            return redirect(url_for("index"))
        result = best_style_match(user_id)
        season = current_season()
        entries = (
            query_all(
                """
                select me.final_score, me.placement, me.rank_points, m.played_at, m.id as match_id
                from match_entries me
                join matches m on m.id = me.match_id
                where me.user_id = ? and m.season_id = ?
                order by m.played_at asc, m.id asc
                """,
                (user_id, season["id"]),
            )
            if season
            else []
        )
        user_radar = build_player_radar(entries) if entries else None
        labels = [metric["label"] for metric in user_radar["metrics"]] if user_radar else []
        best_radar = (
            build_vector_radar(
                result["best"]["vector"],
                labels,
                display_values=result["best"].get("display"),
            )
            if result["has_data"] and labels
            else None
        )
        return render_template(
            "style_match.html",
            result=result,
            target=target,
            is_self=(g.user["id"] == user_id),
            user_radar=user_radar,
            best_radar=best_radar,
        )
