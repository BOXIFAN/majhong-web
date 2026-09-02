"""用于本地开发的可选演示数据。"""

from __future__ import annotations

import json
import sqlite3

from werkzeug.security import generate_password_hash

from brml.rules import DEFAULT_RULES
from brml.scoring import calculate_placements, calculate_rank_points
from brml.timeutils import now

def seed_demo_data(db: sqlite3.Connection, admin_id: int) -> None:
    """写入覆盖多赛季、同分和罚则场景的本地演示数据。"""
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
    demo_avatars = ["dragon", "fox", "panda", "cat", "rabbit", "tiger", "koala", "frog", "penguin", "flower", "star", "paw"]
    password_hash = generate_password_hash("demo1234", method="pbkdf2:sha256")
    for index, (display_name, email, role) in enumerate(demo_users):
        avatar = demo_avatars[index] if index < len(demo_avatars) else None
        user_ids[display_name] = db.execute(
            """
            insert into users (display_name, email, password_hash, role, created_at, avatar)
            values (?, ?, ?, ?, ?, ?)
            """,
            (display_name, email, password_hash, role, now(), avatar),
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
    """使用正式积分函数写入一场演示比赛，防止样例积分与业务规则漂移。"""
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

