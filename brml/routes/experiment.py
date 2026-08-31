"""实验功能路由（不参与上线）。"""

from __future__ import annotations

from flask import g, render_template

from brml.auth import login_required
from brml.stylematch import best_style_match


def register_routes(app) -> None:
    @app.route("/experiment/style-match")
    @login_required
    def style_match():
        result = best_style_match(g.user["id"])
        return render_template("style_match.html", result=result)
