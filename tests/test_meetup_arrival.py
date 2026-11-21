"""活动报名预计到达时间：必选校验、写入、桌面与 PWA 展示。"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from werkzeug.security import generate_password_hash

import app as application
from brml.config import ADMIN_PASSWORD_MIGRATION

ADMIN_PASSWORD = "test-admin-password"


class MeetupArrivalTests(unittest.TestCase):
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

    def create_meetup(self) -> int:
        with sqlite3.connect(self.database) as db:
            admin_id = db.execute(
                "select id from users where role = 'super_admin' limit 1"
            ).fetchone()[0]
            cursor = db.execute(
                """
                insert into meetups
                  (meetup_at, signup_deadline, venue, created_by, created_at, updated_at)
                values
                  ('2099-01-10 13:00:00', '2099-01-09 20:00:00', 'Arrival test venue', ?, '2026-01-01 00:00:00', '2026-01-01 00:00:00')
                """,
                (admin_id,),
            )
            db.commit()
            return cursor.lastrowid

    def signup_count(self, meetup_id: int) -> int:
        with sqlite3.connect(self.database) as db:
            return db.execute(
                "select count(*) from meetup_signups where meetup_id = ?", (meetup_id,)
            ).fetchone()[0]

    def signup_arrival(self, meetup_id: int) -> str | None:
        with sqlite3.connect(self.database) as db:
            row = db.execute(
                "select arrival from meetup_signups where meetup_id = ?", (meetup_id,)
            ).fetchone()
        return row[0] if row else None

    def test_desktop_signup_requires_arrival(self) -> None:
        self.login()
        meetup_id = self.create_meetup()
        response = self.client.post(
            f"/meetups/{meetup_id}/signup", follow_redirects=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("请选择预计到达时间", response.get_data(as_text=True))
        self.assertEqual(self.signup_count(meetup_id), 0)

    def test_desktop_signup_records_arrival_and_shows_chip(self) -> None:
        self.login()
        meetup_id = self.create_meetup()
        response = self.client.post(
            f"/meetups/{meetup_id}/signup",
            data={"arrival": "by_14"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.signup_arrival(meetup_id), "by_14")
        html = response.get_data(as_text=True)
        self.assertIn("已报名", html)
        self.assertIn("2:00 前可到", html)

    def test_invalid_arrival_is_rejected(self) -> None:
        self.login()
        meetup_id = self.create_meetup()
        self.client.post(f"/meetups/{meetup_id}/signup", data={"arrival": "noon"})
        self.assertEqual(self.signup_count(meetup_id), 0)

    def test_pwa_signup_requires_arrival(self) -> None:
        self.login()
        meetup_id = self.create_meetup()
        response = self.client.post(
            f"/app/meetups/{meetup_id}/signup", follow_redirects=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.signup_count(meetup_id), 0)

    def test_pwa_signup_records_arrival(self) -> None:
        self.login()
        meetup_id = self.create_meetup()
        response = self.client.post(
            f"/app/meetups/{meetup_id}/signup",
            data={"arrival": "by_15"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.signup_arrival(meetup_id), "by_15")
        html = response.get_data(as_text=True)
        self.assertIn("已报名 · 3:00 前可到", html)

    def test_list_shows_own_arrival(self) -> None:
        self.login()
        meetup_id = self.create_meetup()
        self.client.post(f"/meetups/{meetup_id}/signup", data={"arrival": "by_16"})
        html = self.client.get("/meetups").get_data(as_text=True)
        self.assertIn("4:00 前可到", html)

    def test_admin_add_member_requires_and_records_arrival(self) -> None:
        self.login()
        meetup_id = self.create_meetup()
        with sqlite3.connect(self.database) as db:
            member_id = db.execute(
                "select id from users where role = 'user' and is_deleted = 0 limit 1"
            ).fetchone()[0]
        self.client.post(
            f"/admin/meetups/{meetup_id}/attendees/add",
            data={"user_id": member_id},
        )
        self.assertEqual(self.signup_count(meetup_id), 0)

        response = self.client.post(
            f"/admin/meetups/{meetup_id}/attendees/add",
            data={"user_id": member_id, "arrival": "by_14"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.signup_arrival(meetup_id), "by_14")


if __name__ == "__main__":
    unittest.main()
