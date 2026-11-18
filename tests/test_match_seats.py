"""比赛初始坐次：固定按卡片位置写入（玩家 1-4 = 东南西北），并覆盖编辑与旧库迁移。"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from werkzeug.security import generate_password_hash

import app as application
from brml.config import ADMIN_PASSWORD_MIGRATION
from brml.db import get_db
from brml.migrations import ensure_match_seat_column
from brml.rules import normalize_rules

ADMIN_PASSWORD = "test-admin-password"
SEATS = ("east", "south", "west", "north")
SEAT_LABELS = ("东家", "南家", "西家", "北家")


class MatchSeatEntryTests(unittest.TestCase):
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

    def player_ids(self) -> list[int]:
        with sqlite3.connect(self.database) as db:
            rows = db.execute(
                "select id from users where role in ('referee', 'user') and is_deleted = 0 "
                "order by id limit 4"
            ).fetchall()
        return [row[0] for row in rows]

    def scores(self) -> list[int]:
        with sqlite3.connect(self.database) as db:
            rules_json = db.execute(
                "select rules_json from seasons where status = 'active' order by id desc limit 1"
            ).fetchone()[0]
        rules = normalize_rules(json.loads(rules_json))
        total = int(rules["points"]["default_starting_points"]) * 4
        return [total - 65000, 32000, 20000, 13000]

    def form_data(self) -> dict:
        players = self.player_ids()
        scores = self.scores()
        data = {"table_name": "meetup", "memo": "seat test"}
        for idx in range(4):
            data[f"player_{idx}"] = players[idx]
            data[f"score_{idx}"] = scores[idx]
        return data

    def latest_entries(self) -> dict[int, str | None]:
        with sqlite3.connect(self.database) as db:
            match_id = db.execute("select max(id) from matches").fetchone()[0]
            rows = db.execute(
                "select user_id, seat from match_entries where match_id = ?",
                (match_id,),
            ).fetchall()
        return {row[0]: row[1] for row in rows}

    def test_desktop_form_shows_fixed_seats(self) -> None:
        self.login()
        html = self.client.get("/matches/new").get_data(as_text=True)
        for label in SEAT_LABELS:
            self.assertIn(label, html)
        self.assertNotIn('name="seat_', html)

    def test_desktop_entry_assigns_seats_by_card_position(self) -> None:
        self.login()
        players = self.player_ids()
        response = self.client.post("/matches/new", data=self.form_data())
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.latest_entries(), dict(zip(players, SEATS)))

    def test_pwa_form_shows_fixed_seats(self) -> None:
        self.login()
        html = self.client.get("/app").get_data(as_text=True)
        for label in SEAT_LABELS:
            self.assertIn(label, html)
        self.assertNotIn('name="seat_', html)

    def test_edit_form_shows_fixed_seats(self) -> None:
        self.login()
        self.client.post("/matches/new", data=self.form_data())
        with sqlite3.connect(self.database) as db:
            match_id = db.execute("select max(id) from matches").fetchone()[0]
        html = self.client.get(f"/matches/{match_id}/edit").get_data(as_text=True)
        for label in SEAT_LABELS:
            self.assertIn(label, html)
        self.assertNotIn('name="seat_', html)

    def test_editing_legacy_match_keeps_seats_null(self) -> None:
        """旧场次没有座位时，编辑保存保持未记录，不按位置猜座次。"""
        self.login()
        self.client.post("/matches/new", data=self.form_data())
        with sqlite3.connect(self.database) as db:
            match_id = db.execute("select max(id) from matches").fetchone()[0]
            db.execute("update match_entries set seat = null where match_id = ?", (match_id,))
            db.commit()
        data = self.form_data()
        data["played_at"] = "2026-11-18T17:00"
        response = self.client.post(f"/matches/{match_id}/edit", data=data)
        self.assertEqual(response.status_code, 302)
        with sqlite3.connect(self.database) as db:
            seats = [
                row[0]
                for row in db.execute(
                    "select seat from match_entries where match_id = ?", (match_id,)
                )
            ]
        self.assertEqual(seats, [None, None, None, None])


class SeatMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.legacy = Path(self.temp_dir.name) / "legacy.db"
        with sqlite3.connect(self.legacy) as db:
            db.execute(
                """
                create table match_entries (
                  id integer primary key autoincrement,
                  match_id integer not null,
                  user_id integer not null,
                  final_score integer not null,
                  placement real not null,
                  rank_points real not null,
                  penalty_points integer not null default 0
                )
                """
            )
            db.execute(
                "insert into match_entries "
                "(match_id, user_id, final_score, placement, rank_points, penalty_points) "
                "values (1, 7, 25000, 1, 10.5, 0)"
            )
            db.commit()
            self.before = db.execute("select * from match_entries").fetchall()
        self.original_database = application.app.config["DATABASE_PATH"]
        application.app.config["DATABASE_PATH"] = self.legacy

    def tearDown(self) -> None:
        application.app.config["DATABASE_PATH"] = self.original_database
        self.temp_dir.cleanup()

    def test_legacy_table_gains_seat_column_without_row_changes(self) -> None:
        with application.app.app_context():
            ensure_match_seat_column()
            ensure_match_seat_column()  # 第二次调用必须幂等
            db = get_db()
            columns = [row["name"] for row in db.execute("pragma table_info(match_entries)")]
            rows = db.execute(
                "select id, match_id, user_id, final_score, placement, rank_points, "
                "penalty_points, seat from match_entries"
            ).fetchall()
            index = db.execute(
                "select name from sqlite_master where type = 'index' "
                "and name = 'ux_match_entries_seat'"
            ).fetchone()

        self.assertIn("seat", columns)
        self.assertEqual([tuple(row) for row in rows], [self.before[0] + (None,)])
        self.assertIsNotNone(index)


if __name__ == "__main__":
    unittest.main()
