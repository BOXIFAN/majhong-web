"""比赛类型、表单校验与成绩写入事务。"""

from __future__ import annotations

import json
import sqlite3

from flask import g

from brml.db import get_db, query_one
from brml.i18n import translate
from brml.rules import normalize_rules
from brml.scoring import calculate_placements, calculate_rank_points
from brml.timeutils import current_match_time, normalize_datetime, now

def normalize_match_type(value: str) -> str:
    """把表单和历史别名转换为数据库使用的 ``meetup``/``casual``。"""
    normalized = value.strip().lower()
    if normalized == "meetup":
        return "meetup"
    return "casual"


def match_type_label(value: str | None) -> str:
    """将数据库桌型转换为当前语言的展示文案，并兼容旧自由文本。"""
    if not value:
        return translate("home.unnamed_match")
    if value.strip().lower() == "meetup":
        return translate("match.type_meetup")
    if value.strip().lower() in {"casual", "casual match", "private", "private game", "机打", "手打"}:
        return translate("match.type_casual")
    return value


def current_season() -> sqlite3.Row | None:
    """返回最新的启用赛季；业务约定同一时刻最多一个 active 赛季。"""
    return query_one("select * from seasons where status = 'active' order by id desc limit 1")


def parse_match_result_form(season, form) -> dict:
    """验证四人终局点数并计算顺位、UMA 和罚分后的赛季积分。"""
    rules = normalize_rules(json.loads(season["rules_json"]))
    start_total = int(rules["points"]["default_starting_points"]) * 4
    players = [int(form.get(f"player_{idx}") or 0) for idx in range(4)]
    scores = [int(form.get(f"score_{idx}") or 0) for idx in range(4)]
    penalty_values = [int(form.get(f"penalty_{idx}") or 0) for idx in range(4)]
    default_penalty_type = translate("match.default_penalty_type")
    penalty_types = [form.get(f"penalty_type_{idx}", default_penalty_type).strip() or default_penalty_type for idx in range(4)]
    penalty_reasons = [form.get(f"penalty_reason_{idx}", "").strip() for idx in range(4)]
    errors = []

    if any(player == 0 for player in players):
        errors.append(translate("validation.players_required"))
    if len(set(players)) != 4:
        errors.append(translate("validation.players_unique"))
    if sum(scores) != start_total:
        errors.append(translate("validation.score_total", total=start_total))
    for value, reason in zip(penalty_values, penalty_reasons):
        if value and not reason:
            errors.append(translate("validation.penalty_reason_required"))
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
    """在一个事务中新增对局、四条成绩和对应罚则。"""
    result = parse_match_result_form(season, form)
    if not result["ok"]:
        return result
    db = get_db()
    cur = db.execute(
        "insert into matches (season_id, referee_id, played_at, table_name, memo, created_at) values (?, ?, ?, ?, ?, ?)",
        (
            season["id"],
            g.user["id"],
            current_match_time(),
            normalize_match_type(form.get("table_name", "")),
            form.get("memo", "").strip(),
            now(),
        ),
    )
    match_id = cur.lastrowid
    insert_match_result_rows(db, match_id, season["id"], result, g.user["id"])
    db.commit()
    return {"ok": True, "match_id": match_id}


def update_match_from_result(match_id: int, match, form, result: dict) -> None:
    """重建指定对局的成绩与罚则，避免编辑后残留旧明细。"""
    db = get_db()
    db.execute(
        """
        update matches
        set played_at = ?, table_name = ?, memo = ?
        where id = ?
        """,
        (
            normalize_datetime(form.get("played_at", "")),
            normalize_match_type(form.get("table_name", "")),
            form.get("memo", "").strip(),
            match_id,
        ),
    )
    db.execute("delete from penalties where match_id = ?", (match_id,))
    db.execute("delete from match_entries where match_id = ?", (match_id,))
    insert_match_result_rows(db, match_id, match["season_id"], result, g.user["id"])
    db.commit()


def insert_match_result_rows(db: sqlite3.Connection, match_id: int, season_id: int, result: dict, actor_id: int) -> None:
    """写入四条成绩，并只为非零罚分创建罚则记录。"""
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


