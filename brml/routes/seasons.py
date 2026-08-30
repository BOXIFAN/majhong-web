"""赛季列表、规则版本管理与赛季删除路由。"""

from __future__ import annotations

import json

from flask import flash, g, redirect, render_template, request, url_for
from werkzeug.security import check_password_hash

from brml.auth import role_required
from brml.db import execute, get_db, query_all, query_one
from brml.i18n import translate
from brml.rules import DEFAULT_RULES, normalize_rules, parse_rules_form
from brml.timeutils import now


def register_routes(app) -> None:
    # ----- 赛季、成绩、排行榜与导出 -----

    @app.route("/seasons")
    def seasons():
        seasons_data = query_all("select * from seasons order by start_date desc, id desc")
        active_season = query_one("select * from seasons where status = 'active' order by id desc limit 1")
        if not active_season and seasons_data:
            active_season = seasons_data[0]
        active_rules = normalize_rules(json.loads(active_season["rules_json"])) if active_season else None
        past_seasons = [season for season in seasons_data if not active_season or season["id"] != active_season["id"]]
        return render_template(
            "seasons.html",
            seasons=seasons_data,
            active_season=active_season,
            active_rules=active_rules,
            past_seasons=past_seasons,
        )

    @app.route("/seasons/new", methods=("GET", "POST"))
    @role_required("super_admin")
    def season_new():
        source_id = request.args.get("copy")
        source = query_one("select * from seasons where id = ?", (source_id,)) if source_id else None
        rules = normalize_rules(json.loads(source["rules_json"])) if source else DEFAULT_RULES
        if request.method == "POST":
            name = request.form["name"].strip()
            status = request.form["status"]
            parsed_rules = parse_rules_form(request.form)
            if not name:
                flash(translate("flash.season_name_required"), "error")
            else:
                if status == "active":
                    execute("update seasons set status = 'archived' where status = 'active'")
                execute(
                    """
                    insert into seasons (name, status, start_date, rules_json, version, created_at, updated_at)
                    values (?, ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        name,
                        status,
                        request.form["start_date"],
                        json.dumps(parsed_rules, ensure_ascii=False),
                        now(),
                        now(),
                    ),
                )
                flash(translate("flash.season_created"), "success")
                return redirect(url_for("seasons"))
        return render_template("season_form.html", season=None, rules=rules)

    @app.route("/seasons/<int:season_id>")
    def season_detail(season_id: int):
        season = query_one("select * from seasons where id = ?", (season_id,))
        if not season:
            flash(translate("flash.season_missing"), "error")
            return redirect(url_for("seasons"))
        return render_template("season_detail.html", season=season, rules=normalize_rules(json.loads(season["rules_json"])))

    @app.route("/seasons/<int:season_id>/edit", methods=("GET", "POST"))
    @role_required("super_admin")
    def season_edit(season_id: int):
        season = query_one("select * from seasons where id = ?", (season_id,))
        if not season:
            flash(translate("flash.season_missing"), "error")
            return redirect(url_for("seasons"))
        rules = normalize_rules(json.loads(season["rules_json"]))
        if request.method == "POST":
            parsed_rules = parse_rules_form(request.form)
            if request.form["status"] == "active":
                execute("update seasons set status = 'archived' where status = 'active' and id != ?", (season_id,))
            execute(
                """
                update seasons
                set name = ?, status = ?, start_date = ?, rules_json = ?, version = version + 1, updated_at = ?
                where id = ?
                """,
                (
                    request.form["name"].strip(),
                    request.form["status"],
                    request.form["start_date"],
                    json.dumps(parsed_rules, ensure_ascii=False),
                    now(),
                    season_id,
                ),
            )
            execute(
                "insert into rule_versions (season_id, rules_json, changed_by, changed_at) values (?, ?, ?, ?)",
                (season_id, json.dumps(parsed_rules, ensure_ascii=False), g.user["id"], now()),
            )
            flash(translate("flash.season_updated"), "success")
            return redirect(url_for("season_detail", season_id=season_id))
        return render_template("season_form.html", season=season, rules=rules)

    @app.route("/seasons/<int:season_id>/delete", methods=("POST",))
    @role_required("super_admin")
    def season_delete(season_id: int):
        season = query_one("select * from seasons where id = ?", (season_id,))
        if not season:
            flash(translate("flash.season_missing"), "error")
            return redirect(url_for("seasons"))

        password = request.form.get("password", "")
        if not check_password_hash(g.user["password_hash"], password):
            flash(translate("flash.season_password_invalid"), "error")
            return redirect(url_for("season_detail", season_id=season_id))

        db = get_db()
        try:
            db.execute(
                "delete from match_entries where match_id in (select id from matches where season_id = ?)",
                (season_id,),
            )
            db.execute("delete from penalties where season_id = ?", (season_id,))
            db.execute("delete from matches where season_id = ?", (season_id,))
            db.execute("delete from rule_versions where season_id = ?", (season_id,))
            db.execute("delete from seasons where id = ?", (season_id,))
            db.commit()
        except Exception:
            db.rollback()
            raise

        flash(translate("flash.season_deleted", name=season["name"]), "success")
        return redirect(url_for("seasons"))

