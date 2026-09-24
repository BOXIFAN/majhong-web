"""留言板功能回归测试：发布限额、合规校验、编辑、点赞与到期清理。"""

from __future__ import annotations

import io
import os
import sqlite3
import tempfile
import time
import unittest
from unittest import mock
from datetime import datetime, timedelta
from pathlib import Path

import app as application
from PIL import Image
from werkzeug.security import generate_password_hash

from brml.config import ADMIN_PASSWORD_MIGRATION
from brml import board_service

ADMIN_PASSWORD = "test-admin-password"
PLAYER_PASSWORD = "test-player-password"


def image_file(size: tuple[int, int] = (800, 600), fmt: str = "PNG") -> io.BytesIO:
    """生成一张可解码的测试图片，用于模拟合法的手机拍照上传。"""
    image = Image.new("RGB", size, (20, 120, 110))
    buffer = io.BytesIO()
    image.save(buffer, fmt)
    buffer.seek(0)
    return buffer


def oversized_image_file(side: int = 1800) -> io.BytesIO:
    """生成一张超过 6MB 的噪声图，用来验证服务端自动压缩。"""
    noise = Image.frombytes("RGB", (side, side), os.urandom(side * side * 3))
    buffer = io.BytesIO()
    noise.save(buffer, "PNG")
    buffer.seek(0)
    return buffer


class BoardTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "test.db"
        self.original_database = application.app.config["DATABASE_PATH"]
        self.original_seed = application.app.config["SEED_DEMO_DATA"]
        application.app.config.update(DATABASE_PATH=self.database, SEED_DEMO_DATA=False)
        with application.app.app_context():
            application.init_db()
        application.app.config.update(TESTING=True, SECRET_KEY="test-secret")
        with sqlite3.connect(self.database) as db:
            db.execute(
                "update users set password_hash = ? where email = 'admin@example.com'",
                (generate_password_hash(ADMIN_PASSWORD, method="pbkdf2:sha256"),),
            )
            db.execute(
                "insert into users (display_name, email, password_hash, role, created_at) values (?, ?, ?, 'user', ?)",
                (
                    "Player Two",
                    "player@example.com",
                    generate_password_hash(PLAYER_PASSWORD, method="pbkdf2:sha256"),
                    "2026-01-01 00:00:00",
                ),
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
            SEED_DEMO_DATA=self.original_seed,
        )
        self.temp_dir.cleanup()

    # ----- helpers -----

    def login_player(self):
        return self.client.post(
            "/login",
            data={"email": "player@example.com", "password": PLAYER_PASSWORD},
        )

    def login_admin(self):
        return self.client.post(
            "/login",
            data={"email": "admin@example.com", "password": ADMIN_PASSWORD},
        )

    def publish(self, caption: str = "East 1 kokushi", size: tuple[int, int] = (800, 600)):
        return self.client.post(
            "/board/new",
            data={
                "caption": caption,
                "image": (image_file(size), "hand.png"),
            },
            content_type="multipart/form-data",
        )

    def post_id(self) -> int:
        with sqlite3.connect(self.database) as db:
            return db.execute("select id from board_posts order by id desc limit 1").fetchone()[0]

    def upload_dir(self) -> Path:
        """留言图片与数据库同级存放，测试中位于临时目录内。"""
        return Path(self.temp_dir.name) / "board_uploads"

    # ----- tests -----

    def test_guest_can_browse_board_and_sidebar_links_to_it(self) -> None:
        self.assertEqual(self.client.get("/board").status_code, 200)
        self.assertIn('href="/board"', self.client.get("/").get_data(as_text=True))
        # 未登录时点赞会被引导到登录页。
        self.assertEqual(self.client.post("/board/new").status_code, 302)

    def test_player_publishes_post_with_valid_image(self) -> None:
        self.login_player()
        response = self.publish()
        self.assertEqual(response.status_code, 302)
        with sqlite3.connect(self.database) as db:
            row = db.execute(
                "select image, caption, expires_at from board_posts order by id desc limit 1"
            ).fetchone()
        self.assertEqual(row[1], "East 1 kokushi")
        # 图片被重新编码为 JPEG 落盘，且到期日为一个月后。
        self.assertTrue(row[0].endswith(".jpg"))
        stored = self.upload_dir() / row[0]
        self.assertTrue(stored.exists())
        with Image.open(stored) as opened:
            self.assertEqual(opened.format, "JPEG")
        expires = datetime.strptime(row[2], "%Y-%m-%d %H:%M:%S")
        self.assertAlmostEqual((expires - datetime.utcnow()).days, 30, delta=1)

        page = self.client.get("/board").get_data(as_text=True)
        self.assertIn("East 1 kokushi", page)
        self.assertIn(f'/board/posts/{self.post_id()}/image', page)

    def test_daily_limit_allows_two_posts_only(self) -> None:
        self.login_player()
        self.assertEqual(self.publish("first").status_code, 302)
        self.assertEqual(self.publish("second").status_code, 302)
        self.assertEqual(self.publish("third").status_code, 302)
        with sqlite3.connect(self.database) as db:
            count = db.execute("select count(*) from board_posts").fetchone()[0]
        self.assertEqual(count, 2)
        page = self.client.get("/board").get_data(as_text=True)
        self.assertNotIn("third", page)

    def test_non_image_upload_is_rejected(self) -> None:
        self.login_player()
        response = self.client.post(
            "/board/new",
            data={
                "caption": "not an image",
                "image": (io.BytesIO(b"hello world"), "notes.txt"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 302)
        with sqlite3.connect(self.database) as db:
            count = db.execute("select count(*) from board_posts").fetchone()[0]
        self.assertEqual(count, 0)

    def test_tiny_image_is_rejected(self) -> None:
        self.login_player()
        self.publish(size=(80, 80))
        with sqlite3.connect(self.database) as db:
            count = db.execute("select count(*) from board_posts").fetchone()[0]
        self.assertEqual(count, 0)

    def test_oversized_image_is_compressed_not_rejected(self) -> None:
        """超过 6MB 的原图应自动压缩到上限以内，而不是直接拒绝。"""
        self.login_player()
        upload = oversized_image_file()
        self.assertGreater(len(upload.getbuffer()), 6 * 1024 * 1024)
        response = self.client.post(
            "/board/new",
            data={"caption": "big upload", "image": (upload, "big.png")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 302)
        with sqlite3.connect(self.database) as db:
            row = db.execute("select image from board_posts order by id desc limit 1").fetchone()
        self.assertIsNotNone(row)
        stored = self.upload_dir() / row[0]
        self.assertTrue(stored.exists())
        self.assertLessEqual(stored.stat().st_size, 6 * 1024 * 1024)
        # 压缩后仍应是可解码的图片，并保留原始比例。
        with Image.open(stored) as opened:
            self.assertEqual(opened.format, "JPEG")
            self.assertLessEqual(max(opened.size), 1600)

    def test_beyond_hard_limit_is_rejected(self) -> None:
        """超过硬上限的请求直接拒绝，避免超大文件占用服务器内存。"""
        self.login_player()
        with mock.patch.object(board_service, "MAX_UPLOAD_BYTES", 1024):
            response = self.client.post(
                "/board/new",
                data={"caption": "too big", "image": (image_file(), "big.png")},
                content_type="multipart/form-data",
            )
        self.assertEqual(response.status_code, 302)
        with sqlite3.connect(self.database) as db:
            count = db.execute("select count(*) from board_posts").fetchone()[0]
        self.assertEqual(count, 0)

    def test_publishing_no_longer_requires_compliance_checkbox(self) -> None:
        """合规勾选框已下线：只带图片和文案也能发布成功。"""
        self.login_player()
        response = self.client.post(
            "/board/new",
            data={"caption": "no checkbox", "image": (image_file(), "hand.png")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 302)
        with sqlite3.connect(self.database) as db:
            row = db.execute("select caption from board_posts order by id desc limit 1").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "no checkbox")

    def test_author_can_edit_but_others_cannot(self) -> None:
        self.login_player()
        self.publish("before")
        post_id = self.post_id()

        response = self.client.post(
            f"/board/posts/{post_id}/edit",
            data={"caption": "after"},
        )
        self.assertEqual(response.status_code, 302)
        with sqlite3.connect(self.database) as db:
            caption = db.execute(
                "select caption from board_posts where id = ?", (post_id,)
            ).fetchone()[0]
        self.assertEqual(caption, "after")

        other = application.app.test_client()
        other.post("/login", data={"email": "admin@example.com", "password": ADMIN_PASSWORD})
        blocked = other.post(
            f"/board/posts/{post_id}/edit",
            data={"caption": "hijacked"},
        )
        self.assertEqual(blocked.status_code, 302)
        with sqlite3.connect(self.database) as db:
            caption = db.execute(
                "select caption from board_posts where id = ?", (post_id,)
            ).fetchone()[0]
        self.assertEqual(caption, "after")

    def test_like_toggle_and_comment(self) -> None:
        self.login_player()
        self.publish()
        post_id = self.post_id()
        self.client.get("/logout")

        liker = application.app.test_client()
        liker.post("/login", data={"email": "admin@example.com", "password": ADMIN_PASSWORD})
        self.assertEqual(liker.post(f"/board/posts/{post_id}/like").status_code, 302)
        with sqlite3.connect(self.database) as db:
            self.assertEqual(
                db.execute("select count(*) from board_likes where post_id = ?", (post_id,)).fetchone()[0],
                1,
            )
        # 再次点赞取消点赞。
        liker.post(f"/board/posts/{post_id}/like")
        with sqlite3.connect(self.database) as db:
            self.assertEqual(
                db.execute("select count(*) from board_likes where post_id = ?", (post_id,)).fetchone()[0],
                0,
            )

        liker.post(f"/board/posts/{post_id}/comments", data={"content": "Nice hand!"})
        with sqlite3.connect(self.database) as db:
            comment_id = db.execute("select id from board_comments").fetchone()[0]
        page = self.client.get(f"/board/posts/{post_id}").get_data(as_text=True)
        self.assertIn("Nice hand!", page)

        # 管理员可以删除乱发言论（真删除，数据库只留不含内容的审计记录）。
        liker.post(f"/board/comments/{comment_id}/delete")
        with sqlite3.connect(self.database) as db:
            remaining = db.execute(
                "select count(*) from board_comments where id = ?", (comment_id,)
            ).fetchone()[0]
            logged = db.execute(
                "select count(*) from board_deletions where comment_id = ?", (comment_id,)
            ).fetchone()[0]
        self.assertEqual(remaining, 0)
        self.assertEqual(logged, 1)
        self.assertNotIn("Nice hand!", self.client.get("/board").get_data(as_text=True))

    def test_admin_can_delete_post_and_image_is_removed(self) -> None:
        self.login_player()
        self.publish()
        post_id = self.post_id()
        with sqlite3.connect(self.database) as db:
            image_name = db.execute(
                "select image from board_posts where id = ?", (post_id,)
            ).fetchone()[0]
        self.assertTrue((self.upload_dir() / image_name).exists())
        self.client.get("/logout")

        self.login_admin()
        self.client.post(f"/board/posts/{post_id}/delete")
        with sqlite3.connect(self.database) as db:
            post_left = db.execute(
                "select count(*) from board_posts where id = ?", (post_id,)
            ).fetchone()[0]
            comments_left = db.execute(
                "select count(*) from board_comments where post_id = ?", (post_id,)
            ).fetchone()[0]
            likes_left = db.execute(
                "select count(*) from board_likes where post_id = ?", (post_id,)
            ).fetchone()[0]
            logged = db.execute(
                "select action, actor_id from board_deletions where post_id = ?", (post_id,)
            ).fetchone()
        # 真删除：帖子、评论、点赞都不再存在，图片文件也从磁盘移除。
        self.assertEqual(post_left, 0)
        self.assertEqual(comments_left, 0)
        self.assertEqual(likes_left, 0)
        self.assertEqual(logged[0], "post_deleted_by_admin")
        self.assertEqual(logged[1], 1)
        self.assertFalse((self.upload_dir() / image_name).exists())
        self.assertNotIn("East 1 kokushi", self.client.get("/board").get_data(as_text=True))

    def test_author_delete_is_hard_delete(self) -> None:
        """作者自己删除同样是真删除，不保留任何内容行。"""
        self.login_player()
        self.publish("author removes this")
        post_id = self.post_id()
        self.client.post(f"/board/posts/{post_id}/comments", data={"content": "own comment"})
        self.client.post(f"/board/posts/{post_id}/delete")
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute("select count(*) from board_posts").fetchone()[0], 0)
            self.assertEqual(db.execute("select count(*) from board_comments").fetchone()[0], 0)
            self.assertEqual(
                db.execute("select count(*) from board_deletions where post_id = ?", (post_id,)).fetchone()[0],
                1,
            )

    def test_only_author_sees_edit_link_but_admin_sees_delete(self) -> None:
        """权限边界：他人只能看到删除（管理），编辑链接只对作者出现。"""
        self.login_player()
        self.publish("mine")
        post_id = self.post_id()
        own_page = self.client.get("/board").get_data(as_text=True)
        self.assertIn(f'href="/board/posts/{post_id}/edit"', own_page)
        self.assertIn(f'action="/board/posts/{post_id}/delete"', own_page)

        admin = application.app.test_client()
        admin.post("/login", data={"email": "admin@example.com", "password": ADMIN_PASSWORD})
        admin_page = admin.get("/board").get_data(as_text=True)
        self.assertNotIn(f'href="/board/posts/{post_id}/edit"', admin_page)
        self.assertIn(f'action="/board/posts/{post_id}/delete"', admin_page)

    def test_admin_can_delete_other_users_comment(self) -> None:
        """管理员可以删除其他用户的不合规评论。"""
        self.login_player()
        self.publish()
        post_id = self.post_id()
        self.client.post(f"/board/posts/{post_id}/comments", data={"content": "bad words"})
        with sqlite3.connect(self.database) as db:
            comment_id = db.execute("select id from board_comments order by id desc limit 1").fetchone()[0]
        self.client.get("/logout")

        self.login_admin()
        self.client.post(f"/board/comments/{comment_id}/delete")
        with sqlite3.connect(self.database) as db:
            row = db.execute(
                "select count(*) from board_comments where id = ?", (comment_id,)
            ).fetchone()[0]
            action = db.execute(
                "select action from board_deletions where comment_id = ?", (comment_id,)
            ).fetchone()[0]
        self.assertEqual(row, 0)
        self.assertEqual(action, "comment_deleted_by_admin")
        self.assertNotIn("bad words", self.client.get("/board").get_data(as_text=True))

    def test_orphan_images_are_swept(self) -> None:
        """没有任何留言引用的图片会被清理，避免图库目录无限增长。"""
        self.login_player()
        self.publish("kept")
        with sqlite3.connect(self.database) as db:
            kept = db.execute("select image from board_posts").fetchone()[0]
        uploads = self.upload_dir()
        orphan = uploads / "orphan-file.jpg"
        orphan.write_bytes((uploads / kept).read_bytes())
        # 把修改时间拨早，跳过孤儿文件的宽限期。
        old = time.time() - 7200
        os.utime(orphan, (old, old))

        application.app.config["TESTING"] = True
        with application.app.app_context():
            removed = board_service.sweep_orphan_images()
        self.assertEqual(removed, 1)
        self.assertFalse(orphan.exists())
        self.assertTrue((uploads / kept).exists())

    def test_storage_budget_blocks_new_posts(self) -> None:
        """图库达到容量上限后拒绝新留言，避免写满 Render 磁盘。"""
        self.login_player()
        with mock.patch.object(board_service, "BOARD_STORAGE_BUDGET_MB", 0):
            response = self.client.post(
                "/board/new",
                data={"caption": "no room", "image": (image_file(), "hand.png")},
                content_type="multipart/form-data",
            )
        self.assertEqual(response.status_code, 302)
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute("select count(*) from board_posts").fetchone()[0], 0)

    def test_expired_posts_are_cleaned_up_on_visit(self) -> None:
        self.login_player()
        self.publish()
        post_id = self.post_id()
        with sqlite3.connect(self.database) as db:
            image_name = db.execute(
                "select image from board_posts where id = ?", (post_id,)
            ).fetchone()[0]
            db.execute(
                "update board_posts set expires_at = ? where id = ?",
                ((datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"), post_id),
            )
            db.commit()

        self.client.get("/board")
        with sqlite3.connect(self.database) as db:
            remaining = db.execute("select count(*) from board_posts").fetchone()[0]
        self.assertEqual(remaining, 0)
        self.assertFalse((self.upload_dir() / image_name).exists())
        # 清理后图片路由不会再泄露旧文件。
        self.assertEqual(self.client.get(f"/board/posts/{post_id}/image").status_code, 302)

    def test_pagination_shows_ten_posts_per_page(self) -> None:
        self.login_player()
        with sqlite3.connect(self.database) as db:
            user_id = db.execute("select id from users where email = 'player@example.com'").fetchone()[0]
            for index in range(12):
                # 直接写库，避开每日限额，专注验证分页。
                db.execute(
                    """
                    insert into board_posts (user_id, caption, image, created_at, updated_at, expires_at)
                    values (?, ?, 'seed.jpg', ?, ?, ?)
                    """,
                    (
                        user_id,
                        f"post-{index}",
                        f"2026-09-{index + 1:02d} 00:00:00",
                        f"2026-09-{index + 1:02d} 00:00:00",
                        "2026-12-31 00:00:00",
                    ),
                )
            db.commit()

        first = self.client.get("/board").get_data(as_text=True)
        self.assertIn("post-11", first)
        self.assertNotIn("post-1<", first)
        second = self.client.get("/board?page=2").get_data(as_text=True)
        self.assertIn("post-1<", second)
        self.assertIn("/board?page=2", first)


if __name__ == "__main__":
    unittest.main()
