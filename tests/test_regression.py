"""重构期间保护核心行为的回归测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import app as application


class PublicPageSmokeTests(unittest.TestCase):
    """确认全新数据库可以启动并渲染所有公开入口。"""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_database = application.DATABASE
        application.DATABASE = Path(self.temp_dir.name) / "test.db"
        application.init_db()
        application.app.config.update(TESTING=True, SECRET_KEY="test-secret")
        self.client = application.app.test_client()

    def tearDown(self) -> None:
        application.DATABASE = self.original_database
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


if __name__ == "__main__":
    unittest.main()
