"""排行榜、个人图表与决赛资格等只读统计逻辑。"""

from __future__ import annotations

import json
import math
import sqlite3

from brml.db import query_all
from brml.i18n import translate
from brml.rules import normalize_rules

def build_placement_trend(history: list[sqlite3.Row]) -> dict:
    """把新到旧的成绩历史转换为模板可直接绘制的 SVG 折线坐标。"""
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


def build_player_radar(entries: list[sqlite3.Row]) -> dict:
    """计算个人雷达图六维指标，并产出模板绘制所需的 SVG 几何数据。

    归一化口径：一位率 ×2、四位回避率 = 100 − 4位率×2、
    低分回避率 = 终局持点 ≥ 10,000 的对局占比；其余三维（正分率、平均打点、火力）维持原口径。
    原始击飞次数与击飞回避率单独在页面展示。
    """
    match_count = len(entries)
    raw = _raw_metrics(entries)
    values = _radar_values(raw)
    display = _radar_display(raw)
    metric_specs = [
        ("player.first_rate", "player.first_rate_desc", values[0], display[0]),
        ("player.positive_rate", "player.positive_rate_desc", values[1], display[1]),
        ("player.average_score", "player.average_score_desc", values[2], display[2]),
        ("player.fourth_avoidance", "player.fourth_avoidance_desc", values[3], display[3]),
        ("player.bust_avoidance", "player.bust_avoidance_desc", values[4], display[4]),
        ("player.firepower", "player.firepower_desc", values[5], display[5]),
    ]

    center_x, center_y, radius = 180, 166, 92
    grid_polygons = []
    for factor in (0.25, 0.5, 0.75, 1.0):
        points = []
        for index in range(6):
            angle = -math.pi / 2 + index * math.pi / 3
            points.append(f"{center_x + math.cos(angle) * radius * factor:.1f},{center_y + math.sin(angle) * radius * factor:.1f}")
        grid_polygons.append(" ".join(points))

    metrics = []
    data_points = []
    for index, (label_key, description_key, normalized, display_value) in enumerate(metric_specs):
        label = translate(label_key)
        label_lines = (
            label.split(" ")
            if label_key in {"player.fourth_avoidance", "player.bust_avoidance"} and " " in label
            else [label]
        )
        angle = -math.pi / 2 + index * math.pi / 3
        axis_x = center_x + math.cos(angle) * radius
        axis_y = center_y + math.sin(angle) * radius
        value_radius = radius * max(0, min(float(normalized), 100)) / 100
        data_points.append(f"{center_x + math.cos(angle) * value_radius:.1f},{center_y + math.sin(angle) * value_radius:.1f}")
        label_radius = 126
        label_x = center_x + math.cos(angle) * label_radius
        label_y = center_y + math.sin(angle) * label_radius
        horizontal = math.cos(angle)
        anchor = "start" if horizontal > 0.35 else "end" if horizontal < -0.35 else "middle"
        metrics.append(
            {
                "label": label,
                "label_lines": label_lines,
                "description": translate(description_key),
                "value": display_value,
                "normalized": round(float(normalized), 1),
                "axis_x": round(axis_x, 1),
                "axis_y": round(axis_y, 1),
                "label_x": round(label_x, 1),
                "label_y": round(label_y, 1),
                "anchor": anchor,
            }
        )

    return {
        "has_data": match_count > 0,
        "match_count": match_count,
        "center_x": center_x,
        "center_y": center_y,
        "grid_polygons": grid_polygons,
        "data_points": " ".join(data_points),
        "metrics": metrics,
        "tobi_count": int(raw["tobi_count"]),
        "tobi_note": translate(
            "player.tobi_note",
            count=int(raw["tobi_count"]),
            rate=f"{raw['bust_avoidance']:.1f}",
        ),
    }


def build_vector_radar(values: list[float], labels: list[str]) -> dict:
    """根据六个 0-100 的雷达值直接生成与 build_player_radar 相同的 SVG 几何。"""
    center_x, center_y, radius = 180, 166, 92
    grid_polygons = []
    for factor in (0.25, 0.5, 0.75, 1.0):
        points = []
        for index in range(6):
            angle = -math.pi / 2 + index * math.pi / 3
            points.append(
                f"{center_x + math.cos(angle) * radius * factor:.1f},"
                f"{center_y + math.sin(angle) * radius * factor:.1f}"
            )
        grid_polygons.append(" ".join(points))

    metrics = []
    data_points = []
    for index in range(6):
        value = max(0.0, min(float(values[index]), 100.0))
        angle = -math.pi / 2 + index * math.pi / 3
        axis_x = center_x + math.cos(angle) * radius
        axis_y = center_y + math.sin(angle) * radius
        value_radius = radius * value / 100
        data_points.append(
            f"{center_x + math.cos(angle) * value_radius:.1f},"
            f"{center_y + math.sin(angle) * value_radius:.1f}"
        )
        label_radius = 126
        label_x = center_x + math.cos(angle) * label_radius
        label_y = center_y + math.sin(angle) * label_radius
        horizontal = math.cos(angle)
        anchor = "start" if horizontal > 0.35 else "end" if horizontal < -0.35 else "middle"
        label = labels[index] if index < len(labels) else ""
        metrics.append(
            {
                "label": label,
                "label_lines": [label],
                "value": f"{value:.1f}",
                "normalized": round(value, 1),
                "axis_x": round(axis_x, 1),
                "axis_y": round(axis_y, 1),
                "label_x": round(label_x, 1),
                "label_y": round(label_y, 1),
                "anchor": anchor,
            }
        )
    return {
        "has_data": True,
        "center_x": center_x,
        "center_y": center_y,
        "grid_polygons": grid_polygons,
        "data_points": " ".join(data_points),
        "metrics": metrics,
    }


def _raw_metrics(entries: list[sqlite3.Row]) -> dict:
    """计算单个选手的六维原始指标（百分率、均分与火力原始值）。

    其中 ``fourth_rate`` 为四位率，``hazard`` 为加权生存风险
    （(1.0·B + 0.5·L10 + 0.2·L20)/N），供生存指数换算；
    另附原始 ``tobi_count`` 与 ``bust_avoidance``（击飞次数与原始击飞回避率）供页面展示。
    """
    count = len(entries)

    def pct(value: int) -> float:
        return round(value / count * 100, 1) if count else 0.0

    first_count = sum(1 for row in entries if float(row["placement"]) == 1)
    positive_count = sum(1 for row in entries if float(row["rank_points"]) > 0)
    fourth_count = sum(1 for row in entries if float(row["placement"]) == 4)
    busted_count = sum(1 for row in entries if int(row["final_score"]) < 0)
    low_score_count = sum(1 for row in entries if 0 <= int(row["final_score"]) < 10000)
    mid_score_count = sum(1 for row in entries if 10000 <= int(row["final_score"]) < 20000)
    bust_avoid_count = sum(1 for row in entries if int(row["final_score"]) >= 0)
    average_score = (
        sum(int(row["final_score"]) for row in entries) / count
        if count
        else 0
    )
    first_scores = [int(row["final_score"]) for row in entries if float(row["placement"]) == 1]
    firepower = sum(first_scores) / len(first_scores) if first_scores else 0
    hazard = (
        (1.0 * busted_count + 0.5 * low_score_count + 0.2 * mid_score_count) / count
        if count
        else 0.0
    )
    return {
        "first_rate": pct(first_count),
        "positive_rate": pct(positive_count),
        "average_score": average_score,
        "fourth_rate": pct(fourth_count),
        "hazard": hazard,
        "tobi_count": busted_count,
        "bust_avoidance": pct(bust_avoid_count),
        "firepower": firepower,
        "count": count,
    }


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    size = len(ordered)
    if size == 0:
        return 0.0
    midpoint = size // 2
    if size % 2 == 1:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2


def _clip100(value: float) -> float:
    return max(0.0, min(float(value), 100.0))


def _radar_values(metrics: dict) -> list[float]:
    """按给定口径计算六个雷达轴的值（0-100，用于图形形状）。"""
    return [
        _clip100(metrics["first_rate"] * 2),
        _clip100(metrics["positive_rate"]),
        _clip100(metrics["average_score"] / 50000 * 100),
        _clip100(100 - metrics["fourth_rate"] * 2),
        _clip100(100 * (1 - metrics["hazard"])),
        _clip100(metrics["firepower"] / 60000 * 100),
    ]


def _radar_display(metrics: dict) -> list[str]:
    """按给定口径生成六个雷达轴的展示数值（与 _radar_values 同口径）。"""
    return [
        f"{metrics['first_rate']:.1f}%",
        f"{metrics['positive_rate']:.1f}%",
        f"{metrics['average_score']:,.0f}",
        f"{_clip100(100 - metrics['fourth_rate'] * 2):.1f}%",
        f"{_clip100(100 * (1 - metrics['hazard'])):.1f}%",
        f"{metrics['firepower']:,.0f}",
    ]


def _season_players(season_id: int) -> list[dict]:
    """返回当前赛季每位选手的六维原始指标。"""
    rows = query_all(
        """
        select me.user_id, me.final_score, me.placement, me.rank_points
        from match_entries me
        join matches m on m.id = me.match_id
        where m.season_id = ?
        order by me.user_id, m.played_at asc, m.id asc
        """,
        (season_id,),
    )
    by_user: dict[int, list] = {}
    for row in rows:
        by_user.setdefault(row["user_id"], []).append(row)
    return [_raw_metrics(entries) for entries in by_user.values()]


def season_radar_median(season_id: int) -> dict:
    """计算当前赛季所有选手六维指标的中位数，用于雷达图红色对比轮廓。"""
    players = _season_players(season_id)
    if not players:
        return {"has_data": False, "points": "", "nodes": [], "display": []}

    keys = ("first_rate", "positive_rate", "average_score", "fourth_rate", "hazard", "firepower")
    buckets = {key: [] for key in keys}
    for player in players:
        for key in keys:
            buckets[key].append(player[key])
    median_raw = {key: _median(values) for key, values in buckets.items()}
    normalized = _radar_values(median_raw)
    display = _radar_display(median_raw)

    center_x, center_y, radius = 180, 166, 92
    points: list[str] = []
    nodes: list[dict] = []
    for index, value in enumerate(normalized):
        angle = -math.pi / 2 + index * math.pi / 3
        value_radius = radius * max(0, min(float(value), 100)) / 100
        x = round(center_x + math.cos(angle) * value_radius, 1)
        y = round(center_y + math.sin(angle) * value_radius, 1)
        points.append(f"{x},{y}")
        nodes.append({"x": x, "y": y})

    return {
        "has_data": True,
        "points": " ".join(points),
        "nodes": nodes,
        "display": display,
    }


def get_leaderboard(season_id: int) -> list[dict]:
    """聚合指定赛季的成绩；罚分已包含在 ``rank_points`` 中。"""
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
    """根据排行榜前四/后四和最低局数计算当前用户的杯赛资格。"""
    rules = normalize_rules(json.loads(season["rules_json"]))
    required_matches = int(rules["points"].get("final_required_matches", 8))
    if user is None:
        return {
            "logged_in": False,
            "required_matches": required_matches,
            "matches": 0,
            "remaining_matches": required_matches,
            "matches_met": False,
            "cup_status": translate("finals.login_to_view"),
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
        cup_status = translate("finals.championship_met")
        championship_gap = 0
        yakitori_gap = None
    elif is_bottom_four:
        cup_status = translate("finals.yakitori_met")
        championship_gap = None
        yakitori_gap = 0
    else:
        championship_gap = max(round((championship_cutoff or 0) - points, 1), 0) if championship_cutoff is not None else None
        yakitori_gap = max(round(points - (yakitori_cutoff or 0), 1), 0) if yakitori_cutoff is not None else None
        if championship_gap is None or yakitori_gap is None:
            cup_status = translate("finals.not_enough_data")
        else:
            cup_status = translate("finals.not_met")

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
    """返回赛季罚则明细，供规则页审计展示。"""
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
