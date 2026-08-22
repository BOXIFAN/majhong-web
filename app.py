from __future__ import annotations

import csv
import functools
import io
import json
import os
import secrets
import sqlite3
import string
from datetime import datetime
from pathlib import Path

from flask import (
    Flask,
    Response,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = Path(__file__).resolve().parent
DATABASE = Path(os.environ.get("DATABASE_PATH", BASE_DIR / "instance" / "mahjong.db"))

ROLES = {
    "super_admin": "超级管理员",
    "referee": "裁判",
    "user": "普通用户",
}

DEFAULT_RULES = {
    "points": {
        "default_starting_points": 25000,
        "return_points": 30000,
        "minimum_points_to_win": 1000,
        "final_required_matches": 8,
        "continue_after_negative": True,
        "riichi_bet_points": 1000,
        "repeat_counter_points": 300,
        "noten_penalty_1_tenpai": 3000,
        "noten_penalty_2_tenpai": 1500,
        "noten_penalty_3_tenpai": 1000,
        "use_a_rules": False,
        "uma_1st": 20,
        "uma_2nd": 10,
        "uma_3rd": -10,
        "uma_4th": -20,
        "a_uma_1_positive_1st": 12,
        "a_uma_1_positive_2nd": -1,
        "a_uma_1_positive_3rd": -3,
        "a_uma_1_positive_4th": -8,
        "a_uma_2_positive_1st": 8,
        "a_uma_2_positive_2nd": 4,
        "a_uma_2_positive_3rd": -4,
        "a_uma_2_positive_4th": -8,
        "a_uma_3_positive_1st": 8,
        "a_uma_3_positive_2nd": 3,
        "a_uma_3_positive_3rd": 1,
        "a_uma_3_positive_4th": -12,
    },
    "dora": {
        "open_dora": True,
        "ura_dora": True,
        "kan_dora": True,
        "reveal_dora_after_open_kan": True,
        "kan_ura_dora": True,
    },
    "dealer_repeats": {
        "dealer_repeats_on_win": True,
        "dealer_repeats_if_tenpai": True,
        "all_last_dealer_win_ends_if_first": True,
        "all_last_dealer_tenpai_ends_if_first": True,
    },
    "common": {
        "open_tanyao": True,
        "red_five": "3赤",
        "han_limit": "1番",
        "kiriage_mangan": True,
        "head_bump": True,
        "busting": True,
    },
    "abortive_draws": {
        "four_kan_draw": True,
        "four_wind_draw": True,
        "four_riichi_draw": True,
        "nine_terminals_draw": True,
        "triple_ron_draw": True,
    },
    "yakuman": {
        "counted_yakuman": True,
        "double_yakuman": True,
        "multiple_yakuman": True,
        "kokushi_13_wait_robbing_kan": False,
    },
    "others": {
        "renhou": "满贯",
        "pay_responsibility": True,
        "mangan_at_draw": True,
        "ippatsu": True,
        "west_extension": False,
        "local_yaku": False,
        "last_turn_riichi": False,
        "double_wind_4_fu": True,
    },
    "penalties": {
        "penalty_policy": "诈和：-4pt\n迟到：-2pt\n终局报分错误：-1pt\n违规操作：由裁判记录原因并按管理决定扣分",
    },
}

RULE_LABELS = {
    "points": "基础分数",
    "dora": "宝牌规则",
    "dealer_repeats": "连庄规则",
    "common": "常用规则",
    "abortive_draws": "中途流局规则",
    "yakuman": "役满规则",
    "others": "其他规则",
    "penalties": "罚则",
}

FIELD_LABELS = {
    "default_starting_points": "四家起始分数 / Default Starting Points",
    "return_points": "原点 / Return Points",
    "minimum_points_to_win": "终场分数最低要求 / Minimum Final Score",
    "final_required_matches": "参与决赛需要场次",
    "continue_after_negative": "负分后是否继续 / Continue After Negative Score",
    "riichi_bet_points": "立直棒点数 / Riichi Bet Points",
    "repeat_counter_points": "本场棒点数 / Repeat Counter Points",
    "noten_penalty_1_tenpai": "流局罚符：1人听牌",
    "noten_penalty_2_tenpai": "流局罚符：2人听牌",
    "noten_penalty_3_tenpai": "流局罚符：3人听牌",
    "use_a_rules": "是否 A 规",
    "uma_1st": "顺位马点：1位",
    "uma_2nd": "顺位马点：2位",
    "uma_3rd": "顺位马点：3位",
    "uma_4th": "顺位马点：4位",
    "a_uma_1_positive_1st": "A规马点：1人正分 1位",
    "a_uma_1_positive_2nd": "A规马点：1人正分 2位",
    "a_uma_1_positive_3rd": "A规马点：1人正分 3位",
    "a_uma_1_positive_4th": "A规马点：1人正分 4位",
    "a_uma_2_positive_1st": "A规马点：2人正分 1位",
    "a_uma_2_positive_2nd": "A规马点：2人正分 2位",
    "a_uma_2_positive_3rd": "A规马点：2人正分 3位",
    "a_uma_2_positive_4th": "A规马点：2人正分 4位",
    "a_uma_3_positive_1st": "A规马点：3人正分 1位",
    "a_uma_3_positive_2nd": "A规马点：3人正分 2位",
    "a_uma_3_positive_3rd": "A规马点：3人正分 3位",
    "a_uma_3_positive_4th": "A规马点：3人正分 4位",
    "open_dora": "开启表宝牌 / Open Dora",
    "ura_dora": "开启里宝牌 / Ura Dora",
    "kan_dora": "开启杠宝牌 / Kan Dora",
    "reveal_dora_after_open_kan": "开杠后立即翻宝牌",
    "kan_ura_dora": "开启杠里宝牌 / Kan-Ura Dora",
    "dealer_repeats_on_win": "庄家和牌连庄",
    "dealer_repeats_if_tenpai": "庄家听牌连庄",
    "all_last_dealer_win_ends_if_first": "南四庄家一位和牌是否结束",
    "all_last_dealer_tenpai_ends_if_first": "南四庄家一位听牌是否结束",
    "open_tanyao": "食断 / Open Tanyao",
    "red_five": "赤宝数量 / Red Five",
    "han_limit": "番缚 / Han Limit",
    "kiriage_mangan": "切上满贯 / Kiriage Mangan",
    "head_bump": "头跳 / Head-Bump",
    "busting": "击飞 / Busting",
    "four_kan_draw": "四杠散了",
    "four_wind_draw": "四风连打",
    "four_riichi_draw": "四家立直",
    "nine_terminals_draw": "九种九牌",
    "triple_ron_draw": "三家和",
    "counted_yakuman": "累计役满",
    "double_yakuman": "双倍役满",
    "multiple_yakuman": "复合役满",
    "kokushi_13_wait_robbing_kan": "抢杠十三面",
    "renhou": "人和 / Hand of Man",
    "pay_responsibility": "包牌 / Pay Responsibility",
    "mangan_at_draw": "流局满贯 / Mangan at Draw",
    "ippatsu": "一发 / Ippatsu",
    "west_extension": "西入 / Extension to South/West",
    "local_yaku": "古役 / Local Yaku",
    "last_turn_riichi": "最后一巡立直",
    "double_wind_4_fu": "双风4符",
    "penalty_policy": "罚则内容",
}


def create_app() -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-change-me"))
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    @app.before_request
    def load_user() -> None:
        ensure_database_initialized()
        ensure_user_soft_delete_columns()
        user_id = session.get("user_id")
        g.user = query_one("select * from users where id = ? and is_deleted = 0", (user_id,)) if user_id else None
        if user_id and g.user is None:
            session.clear()

    @app.context_processor
    def inject_globals() -> dict:
        season = current_season()
        return {
            "current_user": g.get("user"),
            "roles": ROLES,
            "current_season": season,
            "rule_labels": RULE_LABELS,
            "field_labels": FIELD_LABELS,
            "today_date": today_date(),
        }

    @app.cli.command("init-db")
    def init_db_command() -> None:
        init_db()
        print("Initialized the database.")

    @app.route("/")
    def index():
        season = current_season()
        leaderboard = get_leaderboard(season["id"]) if season else []
        recent_per_page = 6
        recent_page = max(request.args.get("recent_page", 1, type=int), 1)
        recent_total = query_one("select count(*) as c from matches")["c"]
        recent_pages = max((recent_total + recent_per_page - 1) // recent_per_page, 1)
        if recent_page > recent_pages:
            return redirect(url_for("index", recent_page=recent_pages))
        recent_offset = (recent_page - 1) * recent_per_page
        recent = query_all(
            """
            select m.*, u.display_name as referee_name
            from matches m left join users u on u.id = m.referee_id
            order by m.played_at desc limit ? offset ?
            """,
            (recent_per_page, recent_offset),
        )
        recent_pagination = {
            "page": recent_page,
            "pages": recent_pages,
            "total": recent_total,
            "has_prev": recent_page > 1,
            "has_next": recent_page < recent_pages,
            "prev_page": recent_page - 1,
            "next_page": recent_page + 1,
        }
        return render_template(
            "index.html",
            leaderboard=leaderboard[:6],
            recent_matches=recent,
            recent_pagination=recent_pagination,
        )

    @app.route("/register", methods=("GET", "POST"))
    def register():
        if request.method == "POST":
            display_name = request.form["display_name"].strip()
            email = request.form["email"].strip().lower()
            password = request.form["password"]
            invite_code = request.form["invite_code"].strip().upper()
            invite = query_one(
                "select * from invite_codes where code = ? and used_by is null",
                (invite_code,),
            )
            error = None
            if not display_name or not email or not password:
                error = "请填写所有注册信息。"
            elif not invite:
                error = "邀请码无效或已被使用。"
            elif query_one("select id from users where email = ? and is_deleted = 0", (email,)):
                error = "该邮箱已注册。"

            if error:
                flash(error, "error")
            else:
                db = get_db()
                cur = db.execute(
                    """
                    insert into users (display_name, email, password_hash, role, created_at)
                    values (?, ?, ?, ?, ?)
                    """,
                    (
                        display_name,
                        email,
                        generate_password_hash(password, method="pbkdf2:sha256"),
                        invite["role"],
                        now(),
                    ),
                )
                db.execute(
                    "update invite_codes set used_by = ?, used_at = ? where id = ?",
                    (cur.lastrowid, now(), invite["id"]),
                )
                db.commit()
                flash("注册成功，请登录。", "success")
                return redirect(url_for("login"))
        return render_template("register.html")

    @app.route("/login", methods=("GET", "POST"))
    def login():
        if request.method == "POST":
            email = request.form["email"].strip().lower()
            password = request.form["password"]
            user = query_one("select * from users where email = ? and is_deleted = 0", (email,))
            if user and check_password_hash(user["password_hash"], password):
                session.clear()
                session["user_id"] = user["id"]
                flash("欢迎回来。", "success")
                return redirect(url_for("index"))
            flash("邮箱或密码不正确。", "error")
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        flash("已退出登录。", "success")
        return redirect(url_for("index"))

    @app.route("/dashboard")
    @login_required
    def dashboard():
        return redirect(url_for("index"))

    @app.route("/admin/invites", methods=("GET", "POST"))
    @role_required("super_admin")
    def invites():
        if request.method == "POST":
            role = request.form["role"]
            if role not in ("referee", "user"):
                flash("邀请码角色不正确。", "error")
            else:
                code = generate_invite_code(role)
                try:
                    execute(
                        "insert into invite_codes (code, role, created_by, created_at) values (?, ?, ?, ?)",
                        (code, role, g.user["id"], now()),
                    )
                    flash(f"邀请码 {code} 已创建。", "success")
                except sqlite3.IntegrityError:
                    flash("邀请码生成冲突，请重试。", "error")
        codes = query_all(
            """
            select i.*, u.display_name as used_by_name
            from invite_codes i left join users u on u.id = i.used_by
            order by i.created_at desc
            """
        )
        return render_template("invites.html", codes=codes)

    @app.route("/admin/users")
    @role_required("super_admin")
    def admin_users():
        users = query_all(
            """
            select u.*
            from users u
            order by u.is_deleted asc, u.role asc, u.created_at desc
            """
        )
        return render_template("admin_users.html", users=users)

    @app.route("/admin/users/<int:user_id>/update", methods=("POST",))
    @role_required("super_admin")
    def admin_user_update(user_id: int):
        display_name = request.form.get("display_name", "").strip()
        role = request.form.get("role", "")
        user = query_one("select * from users where id = ?", (user_id,))
        if not user:
            flash("用户不存在。", "error")
        elif not display_name:
            flash("用户名称不能为空。", "error")
        elif user["is_deleted"]:
            flash("已删除用户不能编辑。", "error")
        elif user["role"] != "super_admin" and role not in ("referee", "user"):
            flash("只能将用户设为裁判或普通用户。", "error")
        elif user["role"] == "super_admin":
            execute("update users set display_name = ? where id = ?", (display_name, user_id))
            flash(f"{display_name} 已更新。", "success")
        else:
            execute("update users set display_name = ?, role = ? where id = ?", (display_name, role, user_id))
            flash(f"{display_name} 已更新。", "success")
        return redirect(url_for("admin_users"))

    @app.route("/admin/users/<int:user_id>/delete", methods=("POST",))
    @role_required("super_admin")
    def admin_user_delete(user_id: int):
        user = query_one("select * from users where id = ?", (user_id,))
        if not user:
            flash("用户不存在。", "error")
        elif user["role"] == "super_admin":
            flash("不能删除超级管理员。", "error")
        else:
            execute("update users set is_deleted = 1, deleted_at = ? where id = ?", (now(), user_id))
            flash(f"{user['display_name']} 已删除，历史战绩已保留。", "success")
        return redirect(url_for("admin_users"))

    @app.route("/admin/users/<int:user_id>/reset-password", methods=("POST",))
    @role_required("super_admin")
    def admin_user_reset_password(user_id: int):
        user = query_one("select * from users where id = ?", (user_id,))
        if not user:
            flash("用户不存在。", "error")
        elif user["is_deleted"]:
            flash("已删除用户不能重置密码。", "error")
        elif user["role"] == "super_admin":
            flash("超级管理员密码请由本人修改，避免误锁定后台。", "error")
        else:
            temporary_password = generate_temporary_password()
            execute(
                "update users set password_hash = ? where id = ?",
                (generate_password_hash(temporary_password, method="pbkdf2:sha256"), user_id),
            )
            flash(f"{user['display_name']} 的临时密码：{temporary_password}。请只告知本人并提醒尽快更改。", "success")
        return redirect(url_for("admin_users"))

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
                flash("请输入赛季名称。", "error")
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
                flash("赛季已创建。", "success")
                return redirect(url_for("seasons"))
        return render_template("season_form.html", season=None, rules=rules)

    @app.route("/seasons/<int:season_id>")
    def season_detail(season_id: int):
        season = query_one("select * from seasons where id = ?", (season_id,))
        if not season:
            flash("赛季不存在。", "error")
            return redirect(url_for("seasons"))
        return render_template("season_detail.html", season=season, rules=normalize_rules(json.loads(season["rules_json"])))

    @app.route("/seasons/<int:season_id>/edit", methods=("GET", "POST"))
    @role_required("super_admin")
    def season_edit(season_id: int):
        season = query_one("select * from seasons where id = ?", (season_id,))
        if not season:
            flash("赛季不存在。", "error")
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
            flash("赛季规则已更新，版本记录已保留。", "success")
            return redirect(url_for("season_detail", season_id=season_id))
        return render_template("season_form.html", season=season, rules=rules)

    @app.route("/matches/new", methods=("GET", "POST"))
    @role_required("super_admin", "referee")
    def match_new():
        season = current_season()
        if not season:
            flash("请先创建并启用赛季。", "error")
            return redirect(url_for("seasons"))
        players = query_all("select * from users where role in ('referee', 'user') and is_deleted = 0 order by display_name")
        if request.method == "POST":
            result = create_match_from_form(season, request.form)
            if result["ok"]:
                flash("比赛已录入，排行榜已自动更新。", "success")
                return redirect(url_for("match_detail", match_id=result["match_id"]))
            for error in result["errors"]:
                flash(error, "error")
        return render_template("match_form.html", season=season, players=players, rules=normalize_rules(json.loads(season["rules_json"])))

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
            flash("比赛不存在。", "error")
            return redirect(url_for("index"))
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
        return render_template("match_detail.html", match=match, entries=entries, penalties=penalties)

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
            flash("比赛不存在。", "error")
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
                flash("比赛结果已更新，并已重新计算积分。", "success")
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

    @app.route("/leaderboard")
    def leaderboard():
        seasons_data = query_all("select * from seasons order by start_date desc, id desc")
        season_id = request.args.get("season_id", type=int)
        season = query_one("select * from seasons where id = ?", (season_id,)) if season_id else current_season()
        rows = get_leaderboard(season["id"]) if season else []
        finals_status = build_finals_status(season, rows, g.user) if season else None
        return render_template(
            "leaderboard.html",
            seasons=seasons_data,
            selected_season=season,
            rows=rows,
            finals_status=finals_status,
        )

    @app.route("/players/<int:user_id>")
    def player_profile(user_id: int):
        user = query_one("select * from users where id = ?", (user_id,))
        if not user:
            flash("玩家不存在。", "error")
            return redirect(url_for("leaderboard"))
        season = current_season()
        leaderboard = get_leaderboard(season["id"]) if season else []
        player_stats = next((row for row in leaderboard if row["user_id"] == user_id), None)
        history = query_all(
            """
            select m.played_at, me.final_score, me.placement, me.rank_points
            from match_entries me join matches m on m.id = me.match_id
            where me.user_id = ?
            order by m.played_at desc limit 10
            """,
            (user_id,),
        )
        penalties = query_all(
            "select * from penalties where user_id = ? order by created_at desc limit 8",
            (user_id,),
        )
        trend = build_placement_trend(history)
        return render_template(
            "player.html",
            user=user,
            stats=player_stats,
            history=history,
            trend=trend,
            penalties=penalties,
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

    @app.teardown_appcontext
    def close_db(_: Exception | None = None) -> None:
        db = g.pop("db", None)
        if db is not None:
            db.close()

    return app


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        ensure_database_initialized()
        DATABASE.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


def ensure_database_initialized() -> None:
    if DATABASE.exists():
        return
    init_db()


def ensure_user_soft_delete_columns() -> None:
    db = get_db()
    columns = {row["name"] for row in db.execute("pragma table_info(users)").fetchall()}
    if "is_deleted" not in columns:
        db.execute("alter table users add column is_deleted integer not null default 0")
    if "deleted_at" not in columns:
        db.execute("alter table users add column deleted_at text")
    db.commit()


def execute(sql: str, params: tuple = ()) -> None:
    db = get_db()
    db.execute(sql, params)
    db.commit()


def query_one(sql: str, params: tuple = ()) -> sqlite3.Row | None:
    return get_db().execute(sql, params).fetchone()


def query_all(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    return get_db().execute(sql, params).fetchall()


def now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def today_date() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def normalize_datetime(value: str) -> str:
    if not value:
        return now()
    return value.replace("T", " ") + (":00" if len(value) == 16 else "")


def generate_temporary_password(length: int = 12) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_invite_code(role: str) -> str:
    prefix = "REF" if role == "referee" else "PLAY"
    alphabet = string.ascii_uppercase + string.digits
    while True:
        token = "".join(secrets.choice(alphabet) for _ in range(6))
        code = f"{prefix}-{token[:3]}-{token[3:]}"
        if not query_one("select id from invite_codes where code = ?", (code,)):
            return code


def login_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            flash("请先登录。", "error")
            return redirect(url_for("login"))
        return view(**kwargs)
    return wrapped_view


def role_required(*roles: str):
    def decorator(view):
        @functools.wraps(view)
        def wrapped_view(**kwargs):
            if g.user is None:
                flash("请先登录。", "error")
                return redirect(url_for("login"))
            if g.user["role"] not in roles:
                flash("当前账号没有操作权限。", "error")
                return redirect(url_for("index"))
            return view(**kwargs)
        return wrapped_view
    return decorator


def current_season() -> sqlite3.Row | None:
    return query_one("select * from seasons where status = 'active' order by id desc limit 1")


def parse_rules_form(form) -> dict:
    parsed = {}
    for group, fields in DEFAULT_RULES.items():
        parsed[group] = {}
        for key, default in fields.items():
            raw = form.get(f"rule__{group}__{key}")
            if isinstance(default, bool):
                parsed[group][key] = raw == "on"
            elif isinstance(default, int):
                parsed[group][key] = int(raw or 0)
            else:
                parsed[group][key] = raw or ""
    return parsed


def normalize_rules(rules: dict) -> dict:
    normalized = json.loads(json.dumps(DEFAULT_RULES))
    for group, fields in rules.items():
        if group not in normalized or not isinstance(fields, dict):
            normalized[group] = fields
            continue
        for key in normalized[group]:
            if key in fields:
                normalized[group][key] = fields[key]
    normalized.get("others", {}).pop("swap_calling", None)
    return normalized


def parse_match_result_form(season, form) -> dict:
    rules = normalize_rules(json.loads(season["rules_json"]))
    start_total = int(rules["points"]["default_starting_points"]) * 4
    players = [int(form.get(f"player_{idx}") or 0) for idx in range(4)]
    scores = [int(form.get(f"score_{idx}") or 0) for idx in range(4)]
    penalty_values = [int(form.get(f"penalty_{idx}") or 0) for idx in range(4)]
    penalty_types = [form.get(f"penalty_type_{idx}", "管理处罚").strip() or "管理处罚" for idx in range(4)]
    penalty_reasons = [form.get(f"penalty_reason_{idx}", "").strip() for idx in range(4)]
    errors = []

    if any(player == 0 for player in players):
        errors.append("必须选择满 4 名玩家。")
    if len(set(players)) != 4:
        errors.append("玩家不可重复。")
    if sum(scores) != start_total:
        errors.append(f"四家总分必须等于当前赛季起始分总和：{start_total}。")
    for value, reason in zip(penalty_values, penalty_reasons):
        if value and not reason:
            errors.append("罚分必须填写原因。")
            break
    if errors:
        return {"ok": False, "errors": errors}

    placements = calculate_placements(scores)
    rank_points = calculate_rank_points(scores, placements, rules, penalty_values)
    return {
        "ok": True,
        "rules": rules,
        "players": players,
        "scores": scores,
        "penalty_values": penalty_values,
        "penalty_types": penalty_types,
        "penalty_reasons": penalty_reasons,
        "placements": placements,
        "rank_points": rank_points,
    }


def create_match_from_form(season, form) -> dict:
    result = parse_match_result_form(season, form)
    if not result["ok"]:
        return result
    db = get_db()
    cur = db.execute(
        "insert into matches (season_id, referee_id, played_at, table_name, memo, created_at) values (?, ?, ?, ?, ?, ?)",
        (
            season["id"],
            g.user["id"],
            normalize_datetime(form.get("played_at", "")),
            form.get("table_name", "").strip(),
            form.get("memo", "").strip(),
            now(),
        ),
    )
    match_id = cur.lastrowid
    insert_match_result_rows(db, match_id, season["id"], result, g.user["id"])
    db.commit()
    return {"ok": True, "match_id": match_id}


def update_match_from_result(match_id: int, match, form, result: dict) -> None:
    db = get_db()
    db.execute(
        """
        update matches
        set played_at = ?, table_name = ?, memo = ?
        where id = ?
        """,
        (
            normalize_datetime(form.get("played_at", "")),
            form.get("table_name", "").strip(),
            form.get("memo", "").strip(),
            match_id,
        ),
    )
    db.execute("delete from penalties where match_id = ?", (match_id,))
    db.execute("delete from match_entries where match_id = ?", (match_id,))
    insert_match_result_rows(db, match_id, match["season_id"], result, g.user["id"])
    db.commit()


def insert_match_result_rows(db: sqlite3.Connection, match_id: int, season_id: int, result: dict, actor_id: int) -> None:
    for idx, user_id in enumerate(result["players"]):
        db.execute(
            """
            insert into match_entries (match_id, user_id, final_score, placement, rank_points, penalty_points)
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                match_id,
                user_id,
                result["scores"][idx],
                result["placements"][idx],
                result["rank_points"][idx],
                result["penalty_values"][idx],
            ),
        )
        if result["penalty_values"][idx]:
            db.execute(
                """
                insert into penalties (match_id, season_id, user_id, penalty_type, points, reason, created_by, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    match_id,
                    season_id,
                    user_id,
                    result["penalty_types"][idx],
                    result["penalty_values"][idx],
                    result["penalty_reasons"][idx],
                    actor_id,
                    now(),
                ),
            )


def calculate_placements(scores: list[int]) -> list[float]:
    placements = []
    sorted_scores = sorted(scores, reverse=True)
    for score in scores:
        indexes = [idx + 1 for idx, item in enumerate(sorted_scores) if item == score]
        placements.append(sum(indexes) / len(indexes))
    return placements


def calculate_rank_points(scores: list[int], placements: list[float], rules: dict, penalties: list[int]) -> list[float]:
    point_rules = rules["points"]
    return_points = int(point_rules.get("return_points", point_rules["default_starting_points"]))
    uma = get_uma_points(scores, return_points, point_rules)
    results = []
    sorted_scores = sorted(scores, reverse=True)
    for score, placement, penalty in zip(scores, placements, penalties):
        tied_places = [idx + 1 for idx, item in enumerate(sorted_scores) if item == score]
        avg_uma = sum(uma[place] for place in tied_places) / len(tied_places)
        base = (score - return_points) / 1000
        results.append(round(base + avg_uma - penalty, 1))
    return results


def get_uma_points(scores: list[int], return_points: int, point_rules: dict) -> dict[int, int]:
    if point_rules.get("use_a_rules"):
        positive_count = max(1, min(3, sum(1 for score in scores if score >= return_points)))
        return {
            place: int(point_rules[f"a_uma_{positive_count}_positive_{place}st"])
            if place == 1
            else int(point_rules[f"a_uma_{positive_count}_positive_{place}nd"])
            if place == 2
            else int(point_rules[f"a_uma_{positive_count}_positive_{place}rd"])
            if place == 3
            else int(point_rules[f"a_uma_{positive_count}_positive_{place}th"])
            for place in range(1, 5)
        }
    return {
        1: int(point_rules["uma_1st"]),
        2: int(point_rules["uma_2nd"]),
        3: int(point_rules["uma_3rd"]),
        4: int(point_rules["uma_4th"]),
    }


def placement_to_places(placement: float) -> list[int]:
    if placement == 1:
        return [1]
    if placement == 2:
        return [2]
    if placement == 3:
        return [3]
    if placement == 4:
        return [4]
    if placement == 1.5:
        return [1, 2]
    if placement == 2.5:
        return [2, 3]
    if placement == 3.5:
        return [3, 4]
    return [1, 2, 3, 4]


def build_placement_trend(history: list[sqlite3.Row]) -> dict:
    ordered = list(reversed(history))
    if not ordered:
        return {"points": "", "nodes": []}
    left, right = 16, 96
    top, bottom = 14, 86
    span_x = right - left
    span_y = bottom - top
    nodes = []
    for idx, row in enumerate(ordered):
        x = (left + span_x / 2) if len(ordered) == 1 else left + (span_x * idx / (len(ordered) - 1))
        placement = float(row["placement"])
        y = top + ((placement - 1) / 3) * span_y
        nodes.append(
            {
                "x": round(x, 2),
                "y": round(y, 2),
                "placement": placement,
                "rank_points": row["rank_points"],
                "played_at": row["played_at"],
            }
        )
    return {
        "points": " ".join(f"{node['x']},{node['y']}" for node in nodes),
        "nodes": nodes,
    }


def get_leaderboard(season_id: int) -> list[dict]:
    rows = query_all(
        """
        select
            u.id as user_id,
            u.display_name,
            count(me.id) as matches,
            round(coalesce(sum(me.rank_points), 0), 1) as total_points,
            round(avg(me.placement), 2) as avg_place,
            round(avg(case when me.placement = 1 then 1.0 else 0 end) * 100, 1) as first_rate,
            round(avg(case when me.placement = 4 then 1.0 else 0 end) * 100, 1) as fourth_rate,
            coalesce(sum(me.penalty_points), 0) as penalty_points
        from users u
        join match_entries me on me.user_id = u.id
        join matches m on m.id = me.match_id
        where m.season_id = ?
        group by u.id, u.display_name
        order by total_points desc, avg_place asc, matches desc
        """,
        (season_id,),
    )
    return [dict(row) for row in rows]


def build_finals_status(season: sqlite3.Row, rows: list[dict], user: sqlite3.Row | None) -> dict:
    rules = normalize_rules(json.loads(season["rules_json"]))
    required_matches = int(rules["points"].get("final_required_matches", 8))
    if user is None:
        return {
            "logged_in": False,
            "required_matches": required_matches,
            "matches": 0,
            "remaining_matches": required_matches,
            "matches_met": False,
            "cup_status": "登录后查看您的决赛资格。",
            "championship_gap": None,
            "yakitori_gap": None,
        }

    user_row = next((row for row in rows if row["user_id"] == user["id"]), None)
    user_rank = next((idx for idx, row in enumerate(rows, start=1) if row["user_id"] == user["id"]), None)
    if user_row is None:
        normalized_name = user["display_name"].strip().lower()
        user_rank, user_row = next(
            (
                (idx, row)
                for idx, row in enumerate(rows, start=1)
                if row["display_name"].strip().lower() == normalized_name
            ),
            (None, None),
        )
    matches = int(user_row["matches"]) if user_row else 0
    points = float(user_row["total_points"]) if user_row else 0.0
    remaining_matches = max(required_matches - matches, 0)
    matches_met = remaining_matches == 0

    bottom_start_rank = max(len(rows) - 3, 1)
    is_top_four = user_rank is not None and user_rank <= 4
    is_bottom_four = user_rank is not None and user_rank >= bottom_start_rank and len(rows) >= 4
    championship_cutoff = float(rows[3]["total_points"]) if len(rows) >= 4 else None
    yakitori_cutoff = float(rows[bottom_start_rank - 1]["total_points"]) if len(rows) >= 4 else None

    if is_top_four:
        cup_status = "您已满足冠军杯决赛标准。"
        championship_gap = 0
        yakitori_gap = None
    elif is_bottom_four:
        cup_status = "您已满足烧鸡杯要求。"
        championship_gap = None
        yakitori_gap = 0
    else:
        championship_gap = max(round((championship_cutoff or 0) - points, 1), 0) if championship_cutoff is not None else None
        yakitori_gap = max(round(points - (yakitori_cutoff or 0), 1), 0) if yakitori_cutoff is not None else None
        if championship_gap is None or yakitori_gap is None:
            cup_status = "该赛季暂时没有足够的排行榜数据计算杯赛分界线。"
        else:
            cup_status = "您尚未满足冠军杯或烧鸡杯标准。"

    return {
        "logged_in": True,
        "required_matches": required_matches,
        "matches": matches,
        "remaining_matches": remaining_matches,
        "matches_met": matches_met,
        "rank": user_rank,
        "points": points,
        "cup_status": cup_status,
        "championship_gap": championship_gap,
        "yakitori_gap": yakitori_gap,
    }


def get_penalty_records(season_id: int) -> list[sqlite3.Row]:
    return query_all(
        """
        select
            p.*,
            u.display_name as player_name,
            m.played_at,
            m.table_name,
            r.display_name as referee_name
        from penalties p
        join users u on u.id = p.user_id
        join matches m on m.id = p.match_id
        left join users r on r.id = p.created_by
        where p.season_id = ?
        order by m.played_at desc, p.id desc
        """,
        (season_id,),
    )


def init_db() -> None:
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATABASE)
    with open(BASE_DIR / "schema.sql", encoding="utf-8") as f:
        db.executescript(f.read())
    db.row_factory = sqlite3.Row
    admin_hash = generate_password_hash("admin1234", method="pbkdf2:sha256")
    admin_id = db.execute(
        """
        insert into users (display_name, email, password_hash, role, created_at)
        values ('Admin', 'admin@example.com', ?, 'super_admin', ?)
        """,
        (admin_hash, now()),
    ).lastrowid
    seed_demo_data(db, admin_id)
    db.execute(
        "insert into invite_codes (code, role, created_by, created_at) values ('REF-2026', 'referee', 1, ?)",
        (now(),),
    )
    db.execute(
        "insert into invite_codes (code, role, created_by, created_at) values ('PLAY-2026', 'user', 1, ?)",
        (now(),),
    )
    db.commit()
    db.close()


def seed_demo_data(db: sqlite3.Connection, admin_id: int) -> None:
    season_1_rules = json.loads(json.dumps(DEFAULT_RULES))
    season_2_rules = json.loads(json.dumps(DEFAULT_RULES))
    season_3_rules = json.loads(json.dumps(DEFAULT_RULES))
    season_2_rules["points"]["uma_2nd"] = 5
    season_2_rules["points"]["uma_3rd"] = -15
    season_2_rules["points"]["uma_4th"] = -30
    season_2_rules["common"]["red_five"] = "4赤"
    season_2_rules["others"]["west_extension"] = True
    season_3_rules["points"]["default_starting_points"] = 30000
    season_3_rules["points"]["uma_1st"] = 20
    season_3_rules["points"]["uma_2nd"] = 5
    season_3_rules["points"]["uma_3rd"] = -15
    season_3_rules["points"]["uma_4th"] = -30
    season_3_rules["common"]["red_five"] = "4赤"

    season_1_id = db.execute(
        """
        insert into seasons (name, status, start_date, rules_json, version, created_at, updated_at)
        values ('Brisbane Riichi 2026 Autumn', 'archived', '2026-04-01', ?, 1, ?, ?)
        """,
        (json.dumps(season_1_rules, ensure_ascii=False), now(), now()),
    ).lastrowid
    season_2_id = db.execute(
        """
        insert into seasons (name, status, start_date, rules_json, version, created_at, updated_at)
        values ('Brisbane Riichi 2026 Winter', 'archived', '2026-07-01', ?, 2, ?, ?)
        """,
        (json.dumps(season_2_rules, ensure_ascii=False), now(), now()),
    ).lastrowid
    season_3_id = db.execute(
        """
        insert into seasons (name, status, start_date, rules_json, version, created_at, updated_at)
        values ('S11', 'active', '2026-08-21', ?, 3, ?, ?)
        """,
        (json.dumps(season_3_rules, ensure_ascii=False), now(), now()),
    ).lastrowid
    db.execute(
        "insert into rule_versions (season_id, rules_json, changed_by, changed_at) values (?, ?, ?, ?)",
        (season_2_id, json.dumps(season_2_rules, ensure_ascii=False), admin_id, now()),
    )
    db.execute(
        "insert into rule_versions (season_id, rules_json, changed_by, changed_at) values (?, ?, ?, ?)",
        (season_3_id, json.dumps(season_3_rules, ensure_ascii=False), admin_id, now()),
    )

    demo_users = [
        ("Mika Chen", "mika@example.com", "referee"),
        ("Daniel Wong", "daniel@example.com", "referee"),
        ("Wang.C", "wangc@example.com", "referee"),
        ("Rua", "3474189100@qq.com", "user"),
        ("Aiko Tan", "aiko@example.com", "user"),
        ("Kenji Sato", "kenji@example.com", "user"),
        ("Liam Brown", "liam@example.com", "user"),
        ("Sophie Lee", "sophie@example.com", "user"),
        ("Noah Smith", "noah@example.com", "user"),
        ("Yuki Mori", "yuki@example.com", "user"),
        ("Emma Davis", "emma@example.com", "user"),
        ("Haru Ito", "haru@example.com", "user"),
    ]
    user_ids = {}
    password_hash = generate_password_hash("demo1234", method="pbkdf2:sha256")
    for display_name, email, role in demo_users:
        user_ids[display_name] = db.execute(
            """
            insert into users (display_name, email, password_hash, role, created_at)
            values (?, ?, ?, ?, ?)
            """,
            (display_name, email, password_hash, role, now()),
        ).lastrowid

    demo_matches = [
        (
            season_1_id,
            season_1_rules,
            "2026-04-05 19:20:00",
            "Autumn A",
            "赛季揭幕桌",
            "Mika Chen",
            [("Aiko Tan", 38200), ("Kenji Sato", 26700), ("Liam Brown", 20400), ("Sophie Lee", 14700)],
            [],
        ),
        (
            season_1_id,
            season_1_rules,
            "2026-04-12 18:40:00",
            "Autumn B",
            "同分顺位演示",
            "Daniel Wong",
            [("Noah Smith", 31000), ("Yuki Mori", 31000), ("Emma Davis", 23000), ("Haru Ito", 15000)],
            [],
        ),
        (
            season_1_id,
            season_1_rules,
            "2026-04-19 19:10:00",
            "Autumn A",
            "含罚则",
            "Mika Chen",
            [("Sophie Lee", 41100), ("Aiko Tan", 28600), ("Haru Ito", 17200), ("Kenji Sato", 13100)],
            [{"player": "Kenji Sato", "points": 2, "type": "终局报分错误", "reason": "复核时发现漏记一本场"}],
        ),
        (
            season_1_id,
            season_1_rules,
            "2026-05-03 18:55:00",
            "Autumn C",
            "常规赛",
            "Daniel Wong",
            [("Liam Brown", 33500), ("Emma Davis", 29200), ("Yuki Mori", 22100), ("Noah Smith", 15200)],
            [],
        ),
        (
            season_1_id,
            season_1_rules,
            "2026-05-17 19:30:00",
            "Autumn B",
            "常规赛",
            "Mika Chen",
            [("Haru Ito", 36000), ("Aiko Tan", 28400), ("Noah Smith", 21600), ("Sophie Lee", 14000)],
            [],
        ),
        (
            season_1_id,
            season_1_rules,
            "2026-06-07 18:30:00",
            "Autumn Final",
            "秋季收官桌",
            "Daniel Wong",
            [("Emma Davis", 39000), ("Liam Brown", 25000), ("Kenji Sato", 23000), ("Yuki Mori", 13000)],
            [{"player": "Yuki Mori", "points": 1, "type": "迟到", "reason": "开赛迟到 12 分钟"}],
        ),
        (
            season_2_id,
            season_2_rules,
            "2026-07-06 19:00:00",
            "Winter A",
            "冬季赛第一轮",
            "Mika Chen",
            [("Aiko Tan", 45200), ("Noah Smith", 25100), ("Emma Davis", 18800), ("Liam Brown", 10900)],
            [],
        ),
        (
            season_2_id,
            season_2_rules,
            "2026-07-13 18:45:00",
            "Winter B",
            "冬季赛第二轮",
            "Daniel Wong",
            [("Kenji Sato", 33100), ("Sophie Lee", 30700), ("Yuki Mori", 21900), ("Haru Ito", 14300)],
            [{"player": "Haru Ito", "points": 1, "type": "误记分", "reason": "对局中少报 1000 点"}],
        ),
        (
            season_2_id,
            season_2_rules,
            "2026-07-20 19:15:00",
            "Winter A",
            "高打点桌",
            "Mika Chen",
            [("Emma Davis", 50600), ("Aiko Tan", 23800), ("Sophie Lee", 15100), ("Noah Smith", 10500)],
            [],
        ),
        (
            season_2_id,
            season_2_rules,
            "2026-07-27 19:05:00",
            "Winter C",
            "常规赛",
            "Daniel Wong",
            [("Liam Brown", 36400), ("Yuki Mori", 27700), ("Kenji Sato", 22800), ("Aiko Tan", 13100)],
            [],
        ),
        (
            season_2_id,
            season_2_rules,
            "2026-08-03 18:50:00",
            "Winter B",
            "含罚则",
            "Mika Chen",
            [("Sophie Lee", 34400), ("Haru Ito", 30600), ("Emma Davis", 20900), ("Liam Brown", 14100)],
            [{"player": "Liam Brown", "points": 2, "type": "违规操作导致重开", "reason": "牌山破坏后按赛季规则扣分"}],
        ),
        (
            season_2_id,
            season_2_rules,
            "2026-08-10 19:35:00",
            "Winter A",
            "常规赛",
            "Daniel Wong",
            [("Noah Smith", 31800), ("Kenji Sato", 31200), ("Yuki Mori", 23000), ("Aiko Tan", 14000)],
            [],
        ),
        (
            season_2_id,
            season_2_rules,
            "2026-08-17 19:05:00",
            "Winter Feature",
            "当前最近比赛",
            "Mika Chen",
            [("Yuki Mori", 37500), ("Sophie Lee", 26200), ("Aiko Tan", 22300), ("Emma Davis", 14000)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-08-21 15:18:00",
            "S11 手打",
            "S11 demo 01",
            "Wang.C",
            [("Rua", 35000), ("Daniel Wong", 34000), ("Kenji Sato", 34000), ("Noah Smith", 17000)],
            [{"player": "Rua", "points": 4, "type": "诈和", "reason": "诈和pt-4"}],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-08-22 19:00:00",
            "S11 机打",
            "S11 demo 02",
            "Mika Chen",
            [("Sophie Lee", 47200), ("Rua", 30600), ("Aiko Tan", 22600), ("Haru Ito", 19600)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-08-24 18:40:00",
            "S11 手打",
            "S11 demo 03",
            "Daniel Wong",
            [("Liam Brown", 41800), ("Yuki Mori", 33400), ("Rua", 25300), ("Emma Davis", 19500)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-08-26 19:20:00",
            "S11 机打",
            "S11 demo 04",
            "Wang.C",
            [("Rua", 50100), ("Noah Smith", 29200), ("Kenji Sato", 21100), ("Aiko Tan", 19600)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-08-28 19:05:00",
            "S11 手打",
            "S11 demo 05",
            "Mika Chen",
            [("Daniel Wong", 45200), ("Sophie Lee", 32700), ("Rua", 24800), ("Haru Ito", 17300)],
            [{"player": "Haru Ito", "points": 2, "type": "迟到", "reason": "迟到 15 分钟"}],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-08-30 18:50:00",
            "S11 机打",
            "S11 demo 06",
            "Daniel Wong",
            [("Yuki Mori", 38900), ("Emma Davis", 32500), ("Kenji Sato", 27800), ("Rua", 20800)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-01 19:15:00",
            "S11 手打",
            "S11 demo 07",
            "Wang.C",
            [("Rua", 41300), ("Liam Brown", 33400), ("Sophie Lee", 24700), ("Noah Smith", 20600)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-03 19:30:00",
            "S11 机打",
            "S11 demo 08",
            "Mika Chen",
            [("Aiko Tan", 36000), ("Rua", 35500), ("Daniel Wong", 27500), ("Yuki Mori", 21000)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-05 18:35:00",
            "S11 手打",
            "S11 demo 09",
            "Daniel Wong",
            [("Kenji Sato", 44800), ("Emma Davis", 31500), ("Rua", 23700), ("Liam Brown", 20000)],
            [{"player": "Rua", "points": 1, "type": "误记分", "reason": "复核后补扣 1pt"}],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-07 19:10:00",
            "S11 机打",
            "S11 demo 10",
            "Wang.C",
            [("Rua", 39800), ("Haru Ito", 34900), ("Noah Smith", 25000), ("Sophie Lee", 20300)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-09 18:45:00",
            "S11 手打",
            "S11 demo 11",
            "Mika Chen",
            [("Daniel Wong", 42100), ("Rua", 31800), ("Aiko Tan", 27200), ("Emma Davis", 18900)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-11 19:25:00",
            "S11 机打",
            "S11 demo 12",
            "Daniel Wong",
            [("Yuki Mori", 44200), ("Kenji Sato", 32600), ("Noah Smith", 23800), ("Rua", 19400)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-13 19:00:00",
            "S11 手打",
            "S11 demo 13",
            "Wang.C",
            [("Rua", 45800), ("Liam Brown", 30400), ("Haru Ito", 23800), ("Aiko Tan", 20000)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-15 18:55:00",
            "S11 机打",
            "S11 demo 14",
            "Mika Chen",
            [("Sophie Lee", 40600), ("Emma Davis", 35600), ("Rua", 24400), ("Kenji Sato", 19400)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-17 19:40:00",
            "S11 手打",
            "S11 demo 15",
            "Daniel Wong",
            [("Rua", 37000), ("Daniel Wong", 34400), ("Noah Smith", 28700), ("Yuki Mori", 19900)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-19 18:30:00",
            "S11 机打",
            "S11 demo 16",
            "Wang.C",
            [("Aiko Tan", 39300), ("Rua", 33100), ("Liam Brown", 26500), ("Haru Ito", 21100)],
            [{"player": "Liam Brown", "points": 2, "type": "违规操作", "reason": "错摸后按规则扣 2pt"}],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-21 19:05:00",
            "S11 手打",
            "S11 demo 17",
            "Mika Chen",
            [("Rua", 42100), ("Kenji Sato", 33300), ("Emma Davis", 24600), ("Sophie Lee", 20000)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-23 19:15:00",
            "S11 机打",
            "S11 demo 18",
            "Daniel Wong",
            [("Noah Smith", 38600), ("Daniel Wong", 34200), ("Rua", 28300), ("Aiko Tan", 18900)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-25 18:50:00",
            "S11 手打",
            "S11 demo 19",
            "Wang.C",
            [("Rua", 48600), ("Yuki Mori", 29600), ("Haru Ito", 22400), ("Liam Brown", 19400)],
            [],
        ),
        (
            season_3_id,
            season_3_rules,
            "2026-09-27 19:30:00",
            "S11 机打",
            "S11 demo 20",
            "Mika Chen",
            [("Sophie Lee", 37200), ("Rua", 34900), ("Kenji Sato", 26700), ("Emma Davis", 21200)],
            [],
        ),
    ]

    for season_id, rules, played_at, table_name, memo, referee, entries, penalties in demo_matches:
        seed_match(db, season_id, rules, played_at, table_name, memo, user_ids[referee], user_ids, entries, penalties)


def seed_match(
    db: sqlite3.Connection,
    season_id: int,
    rules: dict,
    played_at: str,
    table_name: str,
    memo: str,
    referee_id: int,
    user_ids: dict[str, int],
    entries: list[tuple[str, int]],
    penalties: list[dict],
) -> None:
    scores = [score for _, score in entries]
    penalty_values_by_player = {item["player"]: item["points"] for item in penalties}
    penalty_values = [penalty_values_by_player.get(player, 0) for player, _ in entries]
    placements = calculate_placements(scores)
    rank_points = calculate_rank_points(scores, placements, rules, penalty_values)
    match_id = db.execute(
        "insert into matches (season_id, referee_id, played_at, table_name, memo, created_at) values (?, ?, ?, ?, ?, ?)",
        (season_id, referee_id, played_at, table_name, memo, played_at),
    ).lastrowid
    for idx, (player, score) in enumerate(entries):
        db.execute(
            """
            insert into match_entries (match_id, user_id, final_score, placement, rank_points, penalty_points)
            values (?, ?, ?, ?, ?, ?)
            """,
            (match_id, user_ids[player], score, placements[idx], rank_points[idx], penalty_values[idx]),
        )
    for item in penalties:
        db.execute(
            """
            insert into penalties (match_id, season_id, user_id, penalty_type, points, reason, created_by, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                match_id,
                season_id,
                user_ids[item["player"]],
                item["type"],
                item["points"],
                item["reason"],
                referee_id,
                played_at,
            ),
        )


app = create_app()
