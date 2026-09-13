"""移动端 App（PWA）外壳：一屏一页的排行榜、近期对局、我的与录入比赛。"""

from __future__ import annotations

import json
from datetime import datetime

from flask import (
    Response,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)

from brml.analytics import build_finals_status, get_leaderboard
from brml.avatars import AVATARS, is_valid_avatar_key, save_uploaded_avatar
from brml.auth import login_required, role_required
from brml.db import execute, query_all, query_one
from brml.i18n import get_locale, translate
from brml.match_service import create_match_from_form, current_season, match_type_label
from brml.meetup_service import auto_archive_expired_meetups, meetup_status, signup_member
from brml.rules import FIELD_LABELS, normalize_rules
from brml.scoring import calculate_placements, get_uma_points
from brml.timeutils import brisbane_local_now, current_match_time

# 录入比赛需要裁判及以上权限；与现有 Web 端保持一致。
ENTRY_ROLES = ("super_admin", "referee")

# 移动端规则页展示的字段顺序；O 与 UMA 是玩家最关心的部分。
RULE_KEYS = (
    "default_starting_points",
    "return_points",
    "minimum_points_to_win",
    "final_required_matches",
    "riichi_bet_points",
    "repeat_counter_points",
    "noten_penalty_1_tenpai",
    "noten_penalty_2_tenpai",
    "noten_penalty_3_tenpai",
    "use_a_rules",
    "uma_1st",
    "uma_2nd",
    "uma_3rd",
    "uma_4th",
)

WEEKDAYS_ZH = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
WEEKDAYS_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHS_EN = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


def _format_when(value: str) -> dict:
    """把本地时间文本拆成移动端列表用的日期、星期与时间片段。"""
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return {"weekday": "", "date_label": value or "", "time_label": ""}
    if get_locale() == "zh":
        return {
            "weekday": WEEKDAYS_ZH[parsed.weekday()],
            "date_label": f"{parsed.month}月{parsed.day}日",
            "time_label": parsed.strftime("%H:%M"),
            "day_label": f"{parsed.day}",
            "month_label": f"{parsed.month}月",
        }
    return {
        "weekday": WEEKDAYS_EN[parsed.weekday()],
        "date_label": f"{MONTHS_EN[parsed.month - 1]} {parsed.day}",
        "time_label": parsed.strftime("%H:%M"),
        "day_label": f"{parsed.day}",
        "month_label": MONTHS_EN[parsed.month - 1],
    }


def _recent_matches(season_id: int, limit: int = 12) -> list[dict]:
    """返回赛季最近对局，并把每个半庄的四个座位挂在 ``entries`` 上。"""
    matches = query_all(
        """
        select m.id, m.played_at, m.table_name, m.memo, u.display_name as referee_name
        from matches m left join users u on u.id = m.referee_id
        where m.season_id = ?
        order by m.played_at desc, m.id desc
        limit ?
        """,
        (season_id, limit),
    )
    if not matches:
        return []
    match_ids = [row["id"] for row in matches]
    placeholders = ",".join("?" for _ in match_ids)
    entry_rows = query_all(
        f"""
        select me.match_id, me.user_id, me.final_score, me.placement, me.rank_points,
               me.penalty_points, u.display_name
        from match_entries me join users u on u.id = me.user_id
        where me.match_id in ({placeholders})
        order by me.placement asc, me.final_score desc
        """,
        tuple(match_ids),
    )
    grouped: dict[int, list[dict]] = {}
    for entry in entry_rows:
        grouped.setdefault(entry["match_id"], []).append(dict(entry))

    viewer_id = g.user["id"] if g.user else None
    items = []
    for row in matches:
        item = dict(row)
        item["entries"] = grouped.get(row["id"], [])
        item.update(_format_when(row["played_at"]))
        item["my_entry"] = next(
            (entry for entry in item["entries"] if entry["user_id"] == viewer_id),
            None,
        )
        items.append(item)
    return items


def _my_recent_form(user_id: int, season_id: int, limit: int = 5) -> list[dict]:
    """当前用户本赛季最近几场的顺位与得分，用于首页的走势标签。"""
    return [
        dict(row)
        for row in query_all(
            """
            select me.placement, me.rank_points, m.played_at
            from match_entries me join matches m on m.id = me.match_id
            where me.user_id = ? and m.season_id = ?
            order by m.played_at desc, m.id desc
            limit ?
            """,
            (user_id, season_id, limit),
        )
    ]


def _group_by_day(matches: list[dict]) -> list[dict]:
    """把「近期对局」按日期分组，供 iPad 双栏排版使用。"""
    groups: list[dict] = []
    for match in matches:
        if not groups or groups[-1]["date_label"] != match["date_label"]:
            groups.append(
                {
                    "date_label": match["date_label"],
                    "weekday": match["weekday"],
                    "matches": [],
                }
            )
        groups[-1]["matches"].append(match)
    return groups


def _match_details(matches: list[dict], rules: dict | None) -> dict:
    """把近期对局整理成详情页需要的 JSON：含点数 / UMA / 罚分的拆解。"""
    if not matches:
        return {}
    match_ids = [match["id"] for match in matches]
    placeholders = ",".join("?" for _ in match_ids)
    penalty_rows = query_all(
        f"""
        select match_id, user_id, penalty_type, points, reason
        from penalties
        where match_id in ({placeholders})
        """,
        tuple(match_ids),
    )
    penalties: dict[tuple[int, int], list[dict]] = {}
    for row in penalty_rows:
        penalties.setdefault((row["match_id"], row["user_id"]), []).append(dict(row))

    points_rules = (rules or {}).get("points") or {}
    return_points = int(
        points_rules.get("return_points", points_rules.get("default_starting_points", 30000))
    )

    details: dict[str, dict] = {}
    for match in matches:
        entries = match["entries"]
        scores = [entry["final_score"] for entry in entries]
        placements = calculate_placements(scores)
        uma = get_uma_points(scores, return_points, points_rules) if points_rules else {}
        sorted_scores = sorted(scores, reverse=True)
        detail_entries = []
        for entry, placement in zip(entries, placements):
            tied = [index + 1 for index, value in enumerate(sorted_scores) if value == entry["final_score"]]
            uma_points = (
                sum(uma.get(place, 0) for place in tied) / len(tied) if uma and tied else 0
            )
            base_points = (entry["final_score"] - return_points) / 1000
            entry_penalties = penalties.get((match["id"], entry["user_id"]), [])
            detail_entries.append(
                {
                    "user_id": entry["user_id"],
                    "name": entry["display_name"],
                    "score": entry["final_score"],
                    "placement": placement,
                    "base": round(base_points, 1),
                    "uma": round(uma_points, 1),
                    "penalty": int(entry["penalty_points"] or 0),
                    "points": round(float(entry["rank_points"]), 1),
                    "penalty_reason": "、".join(
                        item["reason"] for item in entry_penalties if item.get("reason")
                    ),
                }
            )
        details[str(match["id"])] = {
            "id": match["id"],
            "date_label": match["date_label"],
            "weekday": match["weekday"],
            "time_label": match["time_label"],
            "type": match_type_label(match["table_name"]),
            "referee": match["referee_name"],
            "memo": match["memo"],
            "return_points": return_points,
            "total": sum(scores),
            "entries": detail_entries,
        }
    return details


def _next_meetup(user_id: int | None) -> dict | None:
    """返回最近一场未归档、尚未开始的活动，并附带当前用户的报名状态。"""
    auto_archive_expired_meetups()
    meetup = query_one(
        """
        select m.*, count(ms.id) as attendee_count
        from meetups m
        left join meetup_signups ms on ms.meetup_id = m.id
        where m.archived_at is null and m.meetup_at >= ?
        group by m.id
        order by m.meetup_at asc
        limit 1
        """,
        (brisbane_local_now().strftime("%Y-%m-%d %H:%M:%S"),),
    )
    if not meetup:
        return None
    item = dict(meetup)
    item["status"] = meetup_status(meetup)
    item.update(_format_when(meetup["meetup_at"]))
    item["venue"] = meetup["venue"]
    item["signed_up"] = bool(
        user_id
        and query_one(
            "select 1 as ok from meetup_signups where meetup_id = ? and user_id = ?",
            (meetup["id"], user_id),
        )
    )
    return item


def _meetups(user_id: int | None, past_limit: int = 6) -> dict:
    """返回即将开始与最近结束的活动，供报名页使用。"""
    auto_archive_expired_meetups()
    rows = query_all(
        """
        select m.*, count(ms.id) as attendee_count
        from meetups m
        left join meetup_signups ms on ms.meetup_id = m.id
        where m.archived_at is null
        group by m.id
        order by m.meetup_at desc
        """
    )
    signed_ids = set()
    if user_id:
        signed_ids = {
            row["meetup_id"]
            for row in query_all(
                "select meetup_id from meetup_signups where user_id = ?", (user_id,)
            )
        }
    upcoming, past = [], []
    for row in rows:
        item = dict(row)
        item.update(_format_when(row["meetup_at"]))
        item["status"] = meetup_status(row)
        item["signed_up"] = row["id"] in signed_ids
        (upcoming if item["status"] == "open" else past).append(item)
    upcoming.sort(key=lambda item: item["meetup_at"])
    return {"upcoming": upcoming, "past": past[:past_limit]}


def _my_games(user_id: int, season_id: int, limit: int = 8) -> list[dict]:
    """当前用户本赛季最近几场的完整记录，用于「我的」与个人页。"""
    rows = query_all(
        """
        select m.id as match_id, m.played_at, m.table_name, me.placement, me.rank_points, me.final_score
        from match_entries me join matches m on m.id = me.match_id
        where me.user_id = ? and m.season_id = ?
        order by m.played_at desc, m.id desc
        limit ?
        """,
        (user_id, season_id, limit),
    )
    return [{**dict(row), **_format_when(row["played_at"])} for row in rows]


def _placement_counts(user_id: int, season_id: int) -> dict:
    """按顺位统计本赛季场次；并列顺位四舍五入到最近名次。"""
    counts = {1: 0, 2: 0, 3: 0, 4: 0}
    for row in query_all(
        """
        select me.placement, count(*) as total
        from match_entries me join matches m on m.id = me.match_id
        where me.user_id = ? and m.season_id = ?
        group by me.placement
        """,
        (user_id, season_id),
    ):
        place = int(round(float(row["placement"])))
        counts[min(max(place, 1), 4)] += int(row["total"])
    return counts


def _rule_rows(rules: dict | None) -> list[dict]:
    """把赛季规则里的 points 段整理成移动端可直接渲染的标签/值列表。"""
    if not rules:
        return []
    points = rules.get("points", {})
    rows = []
    for key in RULE_KEYS:
        if key not in points:
            continue
        value = points[key]
        if isinstance(value, bool):
            display = translate("mobile.yes") if value else translate("mobile.no")
        elif key.startswith("uma") or key.startswith("a_uma"):
            display = f"{int(value):+d}"
        else:
            display = f"{int(value):,}"
        rows.append({"key": key, "label": FIELD_LABELS.get(key, key), "value": display})
    return rows


def _shell_context(*, entry_errors=None, form_values=None) -> dict:
    """汇总移动端外壳需要的全部数据；缺少赛季时各区块自行降级为空。"""
    user = g.user
    season = current_season()
    rows = get_leaderboard(season["id"]) if season else []
    rank_of = {row["user_id"]: index for index, row in enumerate(rows, start=1)}
    my_row = next((row for row in rows if user and row["user_id"] == user["id"]), None)
    finals = build_finals_status(season, rows, user) if season else None
    rules = normalize_rules(json.loads(season["rules_json"])) if season else None
    start_total = int(rules["points"]["default_starting_points"]) * 4 if rules else 100000
    recent_matches = _recent_matches(season["id"]) if season else []

    return {
        "season": season,
        "leaderboard": rows,
        "rank_of": rank_of,
        "my_row": my_row,
        "finals": finals,
        "rules": rules,
        "start_total": start_total,
        "recent_matches": recent_matches,
        "match_days": _group_by_day(recent_matches),
        "match_details": _match_details(recent_matches, rules),
        "my_form": _my_recent_form(user["id"], season["id"]) if (user and season) else [],
        "my_games": _my_games(user["id"], season["id"]) if (user and season) else [],
        "placement_counts": _placement_counts(user["id"], season["id"]) if (user and season) else {},
        "next_meetup": _next_meetup(user["id"] if user else None),
        "meetups": _meetups(user["id"] if user else None),
        "rule_rows": _rule_rows(rules),
        "avatars": AVATARS,
        "players": query_all(
            "select id, display_name, role from users where role in ('referee', 'user') and is_deleted = 0 order by display_name"
        )
        if user
        else [],
        "match_time": current_match_time(),
        "can_enter_match": bool(user and user["role"] in ENTRY_ROLES),
        "entry_errors": entry_errors or [],
        "form_values": form_values or {},
        "locale": get_locale(),
        "seats": [
            translate("mobile.seat_east"),
            translate("mobile.seat_south"),
            translate("mobile.seat_west"),
            translate("mobile.seat_north"),
        ],
        "active_view": "entry" if entry_errors else "leaderboard",
    }


def register_routes(app) -> None:
    @app.route("/app")
    def mobile_app():
        """移动端外壳：四个独立视图由前端 hash 路由切换，数据全部服务端渲染。"""
        return render_template("app_shell.html", **_shell_context())

    @app.route("/app/matches", methods=("POST",))
    @role_required(*ENTRY_ROLES)
    def mobile_match_create():
        """复用 Web 端同一套校验与写入逻辑，避免移动端出现第二份积分实现。"""
        season = current_season()
        if not season:
            flash(translate("flash.season_required"), "error")
            return redirect(url_for("mobile_app"))
        result = create_match_from_form(season, request.form)
        if result["ok"]:
            flash(translate("flash.match_created"), "success")
            return redirect(f"{url_for('mobile_app')}?created={result['match_id']}#/matches")
        return render_template(
            "app_shell.html",
            **_shell_context(entry_errors=result["errors"], form_values=request.form),
        )

    def app_redirect(view: str) -> str:
        """回到 App 内的指定页面并发出一条可提示的 flash。"""
        return redirect(f"{url_for('mobile_app')}#/{view}")

    @app.route("/app/meetups/<int:meetup_id>/signup", methods=("POST",))
    @login_required
    def mobile_meetup_signup(meetup_id: int):
        """活动报名：复用与网页端相同的报名服务，仅把回跳指向 App。"""
        result = signup_member(meetup_id, g.user["id"])
        if result == "missing":
            flash(translate("meetup.missing"), "error")
        elif result == "closed":
            flash(translate("meetup.signup_closed"), "error")
        elif result == "duplicate":
            flash(translate("meetup.signup_duplicate"), "error")
        else:
            flash(translate("meetup.signup_success"), "success")
        return app_redirect("meetups")

    @app.route("/app/avatar", methods=("POST",))
    @login_required
    def mobile_avatar_update():
        """预设头像切换：与网页端写同一列，但停留在 App 内。"""
        avatar = request.form.get("avatar", "").strip()
        if avatar and not is_valid_avatar_key(avatar):
            flash(translate("flash.avatar_invalid"), "error")
        else:
            execute(
                "update users set avatar = ?, avatar_upload = null where id = ?",
                (avatar or None, g.user["id"]),
            )
            flash(translate("flash.avatar_updated"), "success")
        return app_redirect("avatar")

    @app.route("/app/avatar/upload", methods=("POST",))
    @login_required
    def mobile_avatar_upload():
        result = save_uploaded_avatar(g.user["id"], request.files.get("avatar_file"))
        if result == "missing":
            flash(translate("flash.avatar_missing"), "error")
        elif result == "type_invalid":
            flash(translate("flash.avatar_type_invalid"), "error")
        elif result == "invalid":
            flash(translate("flash.avatar_invalid"), "error")
        else:
            flash(translate("flash.avatar_updated"), "success")
        return app_redirect("avatar")

    @app.route("/app/manifest.webmanifest")
    def mobile_manifest():
        """PWA 清单；作用域限定在 /app，不影响现有 Web 端。"""
        manifest = {
            "id": "/app",
            "name": "Brisbane Riichi Mahjong",
            "short_name": "BRML",
            "description": translate("home.portal_subtitle"),
            "start_url": "/app",
            "scope": "/app/",
            "display": "standalone",
            "orientation": "any",
            "background_color": "#eef1f7",
            "theme_color": "#0f766e",
            "lang": "zh-CN" if get_locale() == "zh" else "en",
            "icons": [
                {
                    "src": url_for("static", filename="pwa/icon-192.png"),
                    "sizes": "192x192",
                    "type": "image/png",
                },
                {
                    "src": url_for("static", filename="pwa/icon-512.png"),
                    "sizes": "512x512",
                    "type": "image/png",
                },
                {
                    "src": url_for("static", filename="pwa/icon-maskable-512.png"),
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "maskable",
                },
            ],
        }
        return Response(
            json.dumps(manifest, ensure_ascii=False),
            mimetype="application/manifest+json",
        )

    @app.route("/app/sw.js")
    def mobile_service_worker():
        """Service Worker 必须从 /app 下发，才能获得 /app/ 作用域。"""
        response = send_from_directory(
            current_app.static_folder,
            "pwa/sw.js",
            mimetype="application/javascript",
        )
        response.headers["Service-Worker-Allowed"] = "/app/"
        response.headers["Cache-Control"] = "no-cache"
        return response
