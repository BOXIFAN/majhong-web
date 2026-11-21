"""个人页「风向起始」：按座位汇总 1-4 位率与平均终局点数。"""

from __future__ import annotations

import json
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

from werkzeug.security import generate_password_hash

import app as application
from brml.analytics import build_seat_stats
from brml.config import ADMIN_PASSWORD_MIGRATION
from brml.rules import normalize_rules

ADMIN_PASSWORD = "test-admin-password"


class SeatStatsFunctionTests(unittest.TestCase):
    def test_rates_and_average_by_seat(self) -> None:
        entries = [
            {"seat": "east", "placement": 1, "final_score": 40000},
            {"seat": "south", "placement": 2, "final_score": 32000},
            {"seat": "west", "placement": 3, "final_score": 25000},
            {"seat": "north", "placement": 4, "final_score": 18000},
            {"seat": "east", "placement": 4, "final_score": 20000},
            {"seat": None, "placement": 1, "final_score": 50000},
        ]
        stats = build_seat_stats(entries)
        self.assertTrue(stats["has_data"])
        self.assertEqual(stats["games"], 5)
        east = stats["rows"][0]
        self.assertEqual(east["games"], 2)
        self.assertEqual(east["first_rate"], 50.0)
        self.assertEqual(east["fourth_rate"], 50.0)
        self.assertEqual(east["avg_score"], 30000)
        self.assertEqual(stats["rows"][1]["avg_score"], 32000)
        self.assertEqual(stats["rows"][3]["fourth_rate"], 100.0)

    def test_empty_entries_have_no_data(self) -> None:
        stats = build_seat_stats([])
        self.assertFalse(stats["has_data"])
        self.assertEqual(stats["games"], 0)
        self.assertEqual([row["games"] for row in stats["rows"]], [0, 0, 0, 0])

    def test_tied_placement_does_not_fill_a_position(self) -> None:
        stats = build_seat_stats(
            [
                {"seat": "east", "placement": 1.5, "final_score": 30000},
                {"seat": "east", "placement": 1, "final_score": 36000},
            ]
        )
        east = stats["rows"][0]
        self.assertEqual(east["games"], 2)
        self.assertEqual(east["first_rate"], 50.0)
        self.assertEqual(east["second_rate"], 0.0)
        self.assertEqual(sum(east[key] for key in ("first_rate", "second_rate", "third_rate", "fourth_rate")), 50.0)


class PlayerSeatPageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "test.db"
        self.original_database = application.app.config["DATABASE_PATH"]
        self.original_seed_setting = application.app.config["SEED_DEMO_DATA"]
        application.app.config.update(DATABASE_PATH=self.database, SEED_DEMO_DATA=True)
        with application.app.app_context():
            application.init_db(force=True)
        application.app.config.update(TESTING=True, SECRET_KEY="test-secret")
        with sqlite3.connect(self.database) as db:
            db.execute(
                "update users set password_hash = ? where email = 'admin@example.com'",
                (generate_password_hash(ADMIN_PASSWORD, method="pbkdf2:sha256"),),
            )
            db.execute(
                "insert or replace into app_migrations (name, applied_at) values (?, 'test')",
                (ADMIN_PASSWORD_MIGRATION,),
            )
            db.commit()
        self.client = application.app.test_client()

    def tearDown(self) -> None:
        application.app.config.update(
            DATABASE_PATH=self.original_database,
            SEED_DEMO_DATA=self.original_seed_setting,
        )
        self.temp_dir.cleanup()

    def login(self) -> None:
        response = self.client.post(
            "/login",
            data={"email": "admin@example.com", "password": ADMIN_PASSWORD},
        )
        self.assertEqual(response.status_code, 302)

    def players(self) -> list[tuple[int, str]]:
        with sqlite3.connect(self.database) as db:
            rows = db.execute(
                "select id, display_name from users "
                "where role in ('referee', 'user') and is_deleted = 0 order by id limit 4"
            ).fetchall()
        return [(row[0], row[1]) for row in rows]

    def start_total(self) -> int:
        with sqlite3.connect(self.database) as db:
            rules_json = db.execute(
                "select rules_json from seasons where status = 'active' order by id desc limit 1"
            ).fetchone()[0]
        return int(normalize_rules(json.loads(rules_json))["points"]["default_starting_points"]) * 4

    def test_player_page_renders_seat_cards(self) -> None:
        """同一玩家依次坐东/南/西/北并拿到 1/2/3/4 位，页面应逐座位显示 100%。"""
        self.login()
        players = self.players()
        target_id, target_name = players[0]
        # 四场里目标玩家分别落在东、南、西、北，其余三人顺序轮换。
        rotations = [
            [players[0], players[1], players[2], players[3]],
            [players[1], players[0], players[2], players[3]],
            [players[1], players[2], players[0], players[3]],
            [players[1], players[2], players[3], players[0]],
        ]
        scores = [
            [45000, 30000, 25000, 20000],
            [45000, 30000, 25000, 20000],
            [45000, 30000, 25000, 20000],
            [45000, 30000, 25000, 20000],
        ]
        for order, row_scores in zip(rotations, scores):
            data = {"table_name": "meetup", "memo": "seat page test"}
            for idx in range(4):
                data[f"player_{idx}"] = order[idx][0]
                data[f"score_{idx}"] = row_scores[idx]
            response = self.client.post("/matches/new", data=data)
            self.assertEqual(response.status_code, 302)

        page = self.client.get(f"/players/{target_id}")
        html = page.get_data(as_text=True)
        self.assertEqual(page.status_code, 200)
        self.assertIn("风向起始", html)
        self.assertIn("已记录 4 场", html)
        for label in ("东家", "南家", "西家", "北家"):
            self.assertIn(label, html)
        blocks = dict(
            re.findall(
                r'<article class="player-seat-item" data-seat="(\w+)">(.*?)</article>',
                html,
                re.S,
            )
        )
        self.assertEqual(set(blocks), {"east", "south", "west", "north"})
        for seat, block in blocks.items():
            with self.subTest(seat=seat):
                self.assertIn("100.0", block)
        self.assertIn("45,000", blocks["east"])
        self.assertIn("30,000", blocks["south"])
        self.assertIn("25,000", blocks["west"])
        self.assertIn("20,000", blocks["north"])

    def test_player_page_shows_empty_state_without_recorded_seats(self) -> None:
        target_id, _ = self.players()[0]
        page = self.client.get(f"/players/{target_id}")
        html = page.get_data(as_text=True)
        self.assertEqual(page.status_code, 200)
        self.assertIn("所选范围还没有记录座位的场（半庄）", html)


if __name__ == "__main__":
    unittest.main()


class PlayerRangeTests(unittest.TestCase):
    """个人页数据范围：默认当前赛季，可切指定赛季或全赛季。"""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "test.db"
        self.original_database = application.app.config["DATABASE_PATH"]
        self.original_seed_setting = application.app.config["SEED_DEMO_DATA"]
        application.app.config.update(DATABASE_PATH=self.database, SEED_DEMO_DATA=True)
        with application.app.app_context():
            application.init_db(force=True)
        application.app.config.update(TESTING=True, SECRET_KEY="test-secret")
        with sqlite3.connect(self.database) as db:
            db.execute(
                "update users set password_hash = ? where email = 'admin@example.com'",
                (generate_password_hash(ADMIN_PASSWORD, method="pbkdf2:sha256"),),
            )
            db.execute(
                "insert or replace into app_migrations (name, applied_at) values (?, 'test')",
                (ADMIN_PASSWORD_MIGRATION,),
            )
            db.commit()
        self.client = application.app.test_client()

    def tearDown(self) -> None:
        application.app.config.update(
            DATABASE_PATH=self.original_database,
            SEED_DEMO_DATA=self.original_seed_setting,
        )
        self.temp_dir.cleanup()

    def login(self) -> None:
        self.client.post(
            "/login",
            data={"email": "admin@example.com", "password": ADMIN_PASSWORD},
        )

    def players(self) -> list[tuple[int, str]]:
        with sqlite3.connect(self.database) as db:
            rows = db.execute(
                "select id, display_name from users "
                "where role in ('referee', 'user') and is_deleted = 0 order by id limit 4"
            ).fetchall()
        return [(row[0], row[1]) for row in rows]

    def seed_four_seated_matches(self) -> None:
        self.login()
        players = self.players()
        rotations = [
            [players[0], players[1], players[2], players[3]],
            [players[1], players[0], players[2], players[3]],
            [players[1], players[2], players[0], players[3]],
            [players[1], players[2], players[3], players[0]],
        ]
        for order in rotations:
            data = {"table_name": "meetup", "memo": "range test"}
            for idx in range(4):
                data[f"player_{idx}"] = order[idx][0]
                data[f"score_{idx}"] = [45000, 30000, 25000, 20000][idx]
            self.client.post("/matches/new", data=data)

    def season_facts(self, user_id: int) -> tuple[int, int, dict[int, int]]:
        with sqlite3.connect(self.database) as db:
            current_id = db.execute(
                "select id from seasons where status = 'active' order by id desc limit 1"
            ).fetchone()[0]
            old_id = db.execute(
                "select id from seasons where status = 'archived' order by id desc limit 1"
            ).fetchone()[0]
            rows = db.execute(
                """
                select m.season_id, count(*) from match_entries me
                join matches m on m.id = me.match_id
                where me.user_id = ? group by m.season_id
                """,
                (user_id,),
            ).fetchall()
        counts = {row[0]: row[1] for row in rows}
        return current_id, old_id, counts

    def metric_matches(self, html: str) -> str:
        match = re.search(r"场（半庄）</span>\s*<strong[^>]*>([^<]+)</strong>", html, re.S)
        self.assertIsNotNone(match)
        return match.group(1).strip()

    def test_default_range_is_current_season(self) -> None:
        self.seed_four_seated_matches()
        target_id = self.players()[0][0]
        current_id, _, counts = self.season_facts(target_id)
        html = self.client.get(f"/players/{target_id}").get_data(as_text=True)
        self.assertIn(f'value="{current_id}" selected', html)
        self.assertIn("已记录 4 场", html)
        self.assertEqual(self.metric_matches(html), str(counts[current_id]))

    def test_switch_to_archived_season_hides_seated_sample(self) -> None:
        self.seed_four_seated_matches()
        target_id = self.players()[0][0]
        _, old_id, counts = self.season_facts(target_id)
        html = self.client.get(f"/players/{target_id}?season={old_id}").get_data(as_text=True)
        self.assertIn(f'value="{old_id}" selected', html)
        self.assertIn("所选范围还没有记录座位的场（半庄）", html)
        expected = str(counts[old_id]) if counts.get(old_id) else "—"
        self.assertEqual(self.metric_matches(html), expected)

    def test_all_seasons_include_current_seated_sample(self) -> None:
        self.seed_four_seated_matches()
        target_id, _ = self.players()[0]
        current_id, old_id, counts = self.season_facts(target_id)
        html = self.client.get(f"/players/{target_id}?season=all").get_data(as_text=True)
        self.assertIn('value="all" selected', html)
        self.assertIn("已记录 4 场", html)
        self.assertEqual(self.metric_matches(html), str(sum(counts.values())))
        self.assertIn("season=all", html)

    def test_unknown_season_falls_back_to_current(self) -> None:
        self.seed_four_seated_matches()
        target_id = self.players()[0][0]
        current_id, _, _ = self.season_facts(target_id)
        html = self.client.get(f"/players/{target_id}?season=9999").get_data(as_text=True)
        self.assertIn(f'value="{current_id}" selected', html)
