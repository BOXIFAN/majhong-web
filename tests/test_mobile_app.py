"""移动端 App（PWA）外壳的回归测试：渲染、权限、清单与录入写入。"""

from __future__ import annotations

import json
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

import app as application
from brml.rules import normalize_rules
from brml.scoring import calculate_placements, calculate_rank_points


class MobileAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "test.db"
        self.original_database = application.app.config["DATABASE_PATH"]
        self.original_seed_setting = application.app.config["SEED_DEMO_DATA"]
        application.app.config.update(DATABASE_PATH=self.database, SEED_DEMO_DATA=True)
        with application.app.app_context():
            application.init_db(force=True)
        application.app.config.update(TESTING=True, SECRET_KEY="test-secret")
        self.client = application.app.test_client()

    def season_rules(self) -> dict:
        """读取当前激活赛季的规则，测试用真实口径而不是默认值。"""
        with sqlite3.connect(self.database) as db:
            row = db.execute(
                "select rules_json from seasons where status = 'active' order by id desc limit 1"
            ).fetchone()
        return normalize_rules(json.loads(row[0]))

    def scores_for(self, rules: dict) -> list[int]:
        total = int(rules["points"]["default_starting_points"]) * 4
        return [total - 68000, 33000, 21000, 14000]

    def tearDown(self) -> None:
        application.app.config.update(
            DATABASE_PATH=self.original_database,
            SEED_DEMO_DATA=self.original_seed_setting,
        )
        self.temp_dir.cleanup()

    def login(self, email: str, password: str = "demo1234") -> None:
        response = self.client.post("/login", data={"email": email, "password": password})
        self.assertEqual(response.status_code, 302)

    def player_ids(self, limit: int = 4) -> list[int]:
        with sqlite3.connect(self.database) as db:
            rows = db.execute(
                "select id from users where role in ('referee', 'user') and is_deleted = 0 order by id limit ?",
                (limit,),
            ).fetchall()
        return [row[0] for row in rows]

    def active_season_id(self) -> int:
        with sqlite3.connect(self.database) as db:
            return db.execute("select id from seasons where status = 'active' order by id desc limit 1").fetchone()[0]

    # ----- 渲染与清单 -----

    def test_shell_renders_for_guest_with_locked_entry(self) -> None:
        response = self.client.get("/app")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("排行榜", html)
        self.assertIn("近期对局", html)
        self.assertIn('class="add-bubble is-locked"', html)
        self.assertNotIn('id="view-entry"', html)
        self.assertIn("mobile_app", application.app.view_functions)

    def test_manifest_and_service_worker_are_served(self) -> None:
        manifest_response = self.client.get("/app/manifest.webmanifest")
        self.assertEqual(manifest_response.status_code, 200)
        self.assertEqual(manifest_response.mimetype, "application/manifest+json")
        manifest = json.loads(manifest_response.get_data(as_text=True))
        self.assertEqual(manifest["start_url"], "/app")
        self.assertEqual(manifest["scope"], "/app/")
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(len(manifest["icons"]), 3)
        self.assertTrue(any(icon.get("purpose") == "maskable" for icon in manifest["icons"]))

        sw_response = self.client.get("/app/sw.js")
        self.assertEqual(sw_response.status_code, 200)
        self.assertEqual(sw_response.headers["Service-Worker-Allowed"], "/app/")
        self.assertIn("caches", sw_response.get_data(as_text=True))

    def test_icons_are_available(self) -> None:
        for name in (
            "pwa/icon-192.png",
            "pwa/icon-512.png",
            "pwa/icon-maskable-512.png",
            "pwa/apple-touch-icon.png",
        ):
            with self.subTest(name=name):
                response = self.client.get(f"/static/{name}")
                self.assertEqual(response.status_code, 200)

    # ----- 权限 -----

    def test_guest_cannot_create_match(self) -> None:
        response = self.client.post("/app/matches", data={})
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_normal_user_gets_locked_entry_and_redirected_post(self) -> None:
        self.login("aiko@example.com")
        html = self.client.get("/app").get_data(as_text=True)
        self.assertIn('class="add-bubble is-locked"', html)
        self.assertNotIn('id="view-entry"', html)
        self.assertIn("需要裁判权限", html)

        response = self.client.post("/app/matches", data={"table_name": "meetup"})
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("/app?created=", response.headers["Location"])

    def test_referee_sees_entry_view(self) -> None:
        self.login("wangc@example.com")
        html = self.client.get("/app").get_data(as_text=True)
        self.assertIn('id="view-entry"', html)
        self.assertIn('id="entryForm"', html)
        self.assertNotIn('class="add-bubble is-locked"', html)

    def test_in_app_pages_replace_desktop_links(self) -> None:
        """「我的」里的入口必须留在 App 内，不能跳回整站页面。"""
        self.login("wangc@example.com")
        html = self.client.get("/app").get_data(as_text=True)
        for view in ("view-profile", "view-rules", "view-meetups", "view-avatar"):
            with self.subTest(view=view):
                self.assertIn(f'id="{view}"', html)
        self.assertIn('data-route="profile"', html)
        for desktop in ('href="/players/', 'href="/seasons"', 'href="/account/avatar"'):
            with self.subTest(desktop=desktop):
                self.assertNotIn(desktop, html)
        self.assertIn("/logout?next=", html)

    def test_matches_view_has_no_meetup_card_and_rows_are_tappable(self) -> None:
        self.login("wangc@example.com")
        html = self.client.get("/app").get_data(as_text=True)
        self.assertNotIn('class="card meetup"', html)
        self.assertIn('id="view-match"', html)
        self.assertGreater(html.count("row tappable"), 0)

    def test_match_detail_payload_breaks_down_points(self) -> None:
        """详情页数据必须与库里存的积分一致：点数 + UMA − 罚分。"""
        self.login("wangc@example.com")
        html = self.client.get("/app").get_data(as_text=True)
        payload = re.search(
            r'<script type="application/json" id="matchData">(.*?)</script>', html, re.S
        )
        self.assertIsNotNone(payload)
        details = json.loads(payload.group(1))
        self.assertTrue(details)

        with sqlite3.connect(self.database) as db:
            for match_id, detail in details.items():
                rows = db.execute(
                    "select user_id, final_score, placement, rank_points, penalty_points"
                    " from match_entries where match_id = ?",
                    (int(match_id),),
                ).fetchall()
                stored = {row[0]: row for row in rows}
                self.assertEqual(detail["total"], sum(row[1] for row in rows))
                for entry in detail["entries"]:
                    row = stored[entry["user_id"]]
                    self.assertEqual(entry["score"], row[1])
                    self.assertEqual(entry["placement"], row[2])
                    self.assertEqual(entry["penalty"], row[4])
                    self.assertAlmostEqual(
                        entry["base"] + entry["uma"] - entry["penalty"], entry["points"], places=1
                    )
                    self.assertAlmostEqual(entry["points"], row[3], places=1)

    def test_meetup_signup_stays_inside_app(self) -> None:
        self.login("wangc@example.com")
        with sqlite3.connect(self.database) as db:
            admin_id = db.execute("select id from users where role = 'super_admin' limit 1").fetchone()[0]
            cursor = db.execute(
                """
                insert into meetups (meetup_at, signup_deadline, venue, created_by, created_at, updated_at)
                values ('2099-01-10 13:00:00', '2099-01-09 20:00:00', 'Test venue', ?, '2026-01-01 00:00:00', '2026-01-01 00:00:00')
                """,
                (admin_id,),
            )
            meetup_id = cursor.lastrowid

        response = self.client.post(f"/app/meetups/{meetup_id}/signup")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/app#/meetups"))
        with sqlite3.connect(self.database) as db:
            count = db.execute(
                "select count(*) from meetup_signups where meetup_id = ?", (meetup_id,)
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_avatar_picker_updates_inside_app(self) -> None:
        self.login("wangc@example.com")
        response = self.client.post("/app/avatar", data={"avatar": "panda"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/app#/avatar"))
        with sqlite3.connect(self.database) as db:
            avatar = db.execute(
                "select avatar from users where email = 'wangc@example.com'"
            ).fetchone()[0]
        self.assertEqual(avatar, "panda")

        # 非法 key 不应写库
        self.client.post("/app/avatar", data={"avatar": "not-a-real-avatar"})
        with sqlite3.connect(self.database) as db:
            avatar = db.execute(
                "select avatar from users where email = 'wangc@example.com'"
            ).fetchone()[0]
        self.assertEqual(avatar, "panda")

    # ----- 录入写入 -----

    def test_referee_creates_match_through_mobile_form(self) -> None:
        self.login("wangc@example.com")
        players = self.player_ids()
        rules = self.season_rules()
        scores = self.scores_for(rules)
        penalty = [0, 0, 10, 0]
        data = {"table_name": "meetup", "memo": "mobile entry"}
        for index in range(4):
            data[f"player_{index}"] = players[index]
            data[f"score_{index}"] = scores[index]
            data[f"penalty_{index}"] = penalty[index]
        data["penalty_reason_2"] = "迟到"

        before = self.match_count()
        response = self.client.post("/app/matches", data=data)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/app?created=", response.headers["Location"])
        self.assertIn("#/matches", response.headers["Location"])
        self.assertEqual(self.match_count(), before + 1)

        with sqlite3.connect(self.database) as db:
            points = db.execute(
                "select rank_points from match_entries order by id desc limit 4"
            ).fetchall()
        expected = calculate_rank_points(
            scores, calculate_placements(scores), rules, penalty
        )
        self.assertEqual([round(row[0], 1) for row in reversed(points)], expected)

    def test_score_total_error_rerenders_entry_view(self) -> None:
        self.login("wangc@example.com")
        players = self.player_ids()
        rules = self.season_rules()
        start_total = int(rules["points"]["default_starting_points"]) * 4
        data = {"table_name": "meetup"}
        for index in range(4):
            data[f"player_{index}"] = players[index]
            data[f"score_{index}"] = 10000
        response = self.client.post("/app/matches", data=data)
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('data-default-view="entry"', html)
        self.assertIn("class=\"banner error\"", html)
        self.assertIn(str(start_total), html)
        self.assertIn(f'data-start-total="{start_total}"', html)

    def test_penalty_without_reason_is_rejected(self) -> None:
        self.login("wangc@example.com")
        players = self.player_ids()
        scores = self.scores_for(self.season_rules())
        data = {"table_name": "meetup"}
        for index in range(4):
            data[f"player_{index}"] = players[index]
            data[f"score_{index}"] = scores[index]
            data[f"penalty_{index}"] = 5 if index == 0 else 0
        response = self.client.post("/app/matches", data=data)
        self.assertEqual(response.status_code, 200)
        self.assertIn('data-default-view="entry"', response.get_data(as_text=True))

    def match_count(self) -> int:
        with sqlite3.connect(self.database) as db:
            return db.execute("select count(*) from matches").fetchone()[0]


class MobileLoginRedirectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "test.db"
        self.original_database = application.app.config["DATABASE_PATH"]
        self.original_seed_setting = application.app.config["SEED_DEMO_DATA"]
        application.app.config.update(DATABASE_PATH=self.database, SEED_DEMO_DATA=True)
        with application.app.app_context():
            application.init_db(force=True)
        application.app.config.update(TESTING=True, SECRET_KEY="test-secret")
        self.client = application.app.test_client()

    def tearDown(self) -> None:
        application.app.config.update(
            DATABASE_PATH=self.original_database,
            SEED_DEMO_DATA=self.original_seed_setting,
        )
        self.temp_dir.cleanup()

    def test_login_returns_to_app_when_next_is_local(self) -> None:
        response = self.client.post(
            "/login",
            data={"email": "wangc@example.com", "password": "demo1234", "next": "/app"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/app"))

    def test_login_ignores_external_next(self) -> None:
        response = self.client.post(
            "/login",
            data={"email": "wangc@example.com", "password": "demo1234", "next": "//evil.example.com"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("evil.example.com", response.headers["Location"])

    def test_logout_can_return_to_app(self) -> None:
        self.client.post("/login", data={"email": "wangc@example.com", "password": "demo1234"})
        response = self.client.get("/logout?next=/app")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/app"))


if __name__ == "__main__":
    unittest.main()
