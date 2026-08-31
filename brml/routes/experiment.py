"""实验功能路由（不参与上线）。"""

from __future__ import annotations

from flask import flash, g, redirect, render_template, url_for

from brml.auth import login_required
from brml.db import query_one
from brml.i18n import translate
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
        return render_template(
            "style_match.html",
            result=result,
            target=target,
            is_self=(g.user["id"] == user_id),
        )
