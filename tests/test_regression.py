"""重构期间保护核心行为的回归测试。"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import app as application
from werkzeug.security import generate_password_hash

from brml.analytics import build_finals_status
from brml.config import ADMIN_PASSWORD_MIGRATION
from brml.db import get_db
from brml.rules import DEFAULT_RULES
from brml.scoring import calculate_placements, calculate_rank_points, get_uma_points


class PublicPageSmokeTests(unittest.TestCase):
    """确认全新数据库可以启动并渲染所有公开入口。"""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "test.db"
        self.original_database = application.app.config["DATABASE_PATH"]
        self.original_seed_setting = application.app.config["SEED_DEMO_DATA"]
        application.app.config.update(DATABASE_PATH=self.database, SEED_DEMO_DATA=False)
        with application.app.app_context():
            application.init_db()
        application.app.config.update(TESTING=True, SECRET_KEY="test-secret")
        self.client = application.app.test_client()

    def tearDown(self) -> None:
        application.app.config.update(
            DATABASE_PATH=self.original_database,
            SEED_DEMO_DATA=self.original_seed_setting,
        )
        self.temp_dir.cleanup()

    def test_public_pages_render_from_empty_database(self) -> None:
        for path in ("/", "/about", "/matches", "/seasons", "/leaderboard", "/login", "/register"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)

    def test_protected_page_redirects_to_login(self) -> None:
        response = self.client.get("/meetups")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/login"))

    def test_language_switch_is_stored_in_session(self) -> None:
        response = self.client.get("/language/en")
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as session:
            self.assertEqual(session["locale"], "en")

    def test_demo_seed_populates_users_seasons_and_matches(self) -> None:
        application.app.config["SEED_DEMO_DATA"] = True
        with application.app.app_context():
            application.init_db(force=True)
        with sqlite3.connect(self.database) as db:
            self.assertGreater(db.execute("select count(*) from users").fetchone()[0], 1)
            self.assertGreater(db.execute("select count(*) from seasons").fetchone()[0], 0)
            self.assertGreater(db.execute("select count(*) from matches").fetchone()[0], 0)
            season_id = db.execute("select id from seasons order by id desc limit 1").fetchone()[0]
            match_id = db.execute("select id from matches order by id desc limit 1").fetchone()[0]
            player_id = db.execute("select id from users where role = 'user' order by id limit 1").fetchone()[0]
            db.execute(
                "update users set password_hash = ? where email = 'admin@example.com'",
                (generate_password_hash("test-admin-password", method="pbkdf2:sha256"),),
            )
            db.execute(
                "insert or replace into app_migrations (name, applied_at) values (?, 'test')",
                (ADMIN_PASSWORD_MIGRATION,),
            )
            db.commit()
        self.assertEqual(self.client.get("/leaderboard").status_code, 200)
        for path in (
            f"/seasons/{season_id}",
            f"/matches/{match_id}",
            f"/players/{player_id}",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

        login = self.client.post(
            "/login",
            data={"email": "admin@example.com", "password": "test-admin-password"},
        )
        self.assertEqual(login.status_code, 302)
        for path in (
            "/admin/announcements",
            "/admin/invites",
            "/admin/users",
            "/seasons/new",
            f"/seasons/{season_id}/edit",
            "/matches/new",
            f"/matches/{match_id}/edit",
            f"/export/season/{season_id}.csv",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_route_endpoint_names_are_preserved(self) -> None:
        expected = {
            "index", "about", "meetups", "meetup_detail", "meetup_new", "meetup_edit",
            "meetup_signup", "meetup_archive", "meetup_delete", "meetup_attendee_add",
            "meetup_attendee_remove", "matches", "announcements", "announcement_edit",
            "announcement_delete", "favicon", "set_language", "register", "login", "logout",
            "account_password_update", "dashboard", "invites", "admin_users", "admin_user_update",
            "admin_user_delete", "admin_user_reset_password", "seasons", "season_new", "season_detail",
            "season_edit", "season_delete", "match_new", "match_detail", "match_edit", "match_delete",
            "leaderboard", "player_profile", "export_season",
        }
        actual = {rule.endpoint for rule in application.app.url_map.iter_rules()}
        self.assertTrue(expected.issubset(actual))

    def test_existing_database_is_not_overwritten_without_force(self) -> None:
        with application.app.app_context():
            with self.assertRaises(FileExistsError):
                application.init_db()
            user_count = get_db().execute("select count(*) from users").fetchone()[0]
        self.assertEqual(user_count, 1)

    def test_foreign_keys_are_enabled_for_request_connections(self) -> None:
        with application.app.app_context():
            enabled = get_db().execute("pragma foreign_keys").fetchone()[0]
        self.assertEqual(enabled, 1)


class ScoringRegressionTests(unittest.TestCase):
    """锁定顺位、UMA 和罚分的既有计算方式。"""

    def test_tied_scores_share_placement(self) -> None:
        scores = [35000, 30000, 30000, 5000]
        self.assertEqual(calculate_placements(scores), [1.0, 2.5, 2.5, 4.0])

    def test_standard_uma_and_penalty(self) -> None:
        rules = {
            "points": {
                "default_starting_points": 25000,
                "return_points": 30000,
                "use_a_rules": False,
                "uma_1st": 15,
                "uma_2nd": 5,
                "uma_3rd": -5,
                "uma_4th": -15,
            }
        }
        scores = [40000, 30000, 20000, 10000]
        placements = calculate_placements(scores)
        points = calculate_rank_points(scores, placements, rules, [2, 0, 0, 0])
        self.assertEqual(points, [23.0, 5.0, -15.0, -35.0])

    def test_a_rules_select_uma_by_positive_player_count(self) -> None:
        point_rules = {
            "use_a_rules": True,
            "a_uma_2_positive_1st": 12,
            "a_uma_2_positive_2nd": 4,
            "a_uma_2_positive_3rd": -4,
            "a_uma_2_positive_4th": -12,
        }
        self.assertEqual(
            get_uma_points([42000, 30000, 18000, 10000], 30000, point_rules),
            {1: 12, 2: 4, 3: -4, 4: -12},
        )


class AnalyticsRegressionTests(unittest.TestCase):
    """锁定决赛资格判定等排行榜衍生逻辑。"""

    def test_top_four_player_qualifies_for_championship(self) -> None:
        season = {"rules_json": json.dumps(DEFAULT_RULES)}
        rows = [
            {"user_id": index, "display_name": f"Player {index}", "matches": 8, "total_points": 100 - index}
            for index in range(1, 9)
        ]
        user = {"id": 2, "display_name": "Player 2"}
        with application.app.test_request_context("/", headers={"Accept-Language": "zh"}):
            status = build_finals_status(season, rows, user)
        self.assertTrue(status["matches_met"])
        self.assertEqual(status["championship_gap"], 0)
        self.assertIsNone(status["yakitori_gap"])


if __name__ == "__main__":
    unittest.main()
