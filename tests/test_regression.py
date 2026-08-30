"""重构期间保护核心行为的回归测试。"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import app as application


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
        for path in ("/", "/about", "/matches", "/seasons", "/leaderboard"):
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
            application.init_db()
        with sqlite3.connect(self.database) as db:
            self.assertGreater(db.execute("select count(*) from users").fetchone()[0], 1)
            self.assertGreater(db.execute("select count(*) from seasons").fetchone()[0], 0)
            self.assertGreater(db.execute("select count(*) from matches").fetchone()[0], 0)
        self.assertEqual(self.client.get("/leaderboard").status_code, 200)


class ScoringRegressionTests(unittest.TestCase):
    """锁定顺位、UMA 和罚分的既有计算方式。"""

    def test_tied_scores_share_placement(self) -> None:
        scores = [35000, 30000, 30000, 5000]
        self.assertEqual(application.calculate_placements(scores), [1.0, 2.5, 2.5, 4.0])

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
        placements = application.calculate_placements(scores)
        points = application.calculate_rank_points(scores, placements, rules, [2, 0, 0, 0])
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
            application.get_uma_points([42000, 30000, 18000, 10000], 30000, point_rules),
            {1: 12, 2: 4, 3: -4, 4: -12},
        )


class AnalyticsRegressionTests(unittest.TestCase):
    """锁定决赛资格判定等排行榜衍生逻辑。"""

    def test_top_four_player_qualifies_for_championship(self) -> None:
        season = {"rules_json": json.dumps(application.DEFAULT_RULES)}
        rows = [
            {"user_id": index, "display_name": f"Player {index}", "matches": 8, "total_points": 100 - index}
            for index in range(1, 9)
        ]
        user = {"id": 2, "display_name": "Player 2"}
        with application.app.test_request_context("/", headers={"Accept-Language": "zh"}):
            status = application.build_finals_status(season, rows, user)
        self.assertTrue(status["matches_met"])
        self.assertEqual(status["championship_gap"], 0)
        self.assertIsNone(status["yakitori_gap"])


if __name__ == "__main__":
    unittest.main()
