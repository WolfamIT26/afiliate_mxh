from datetime import datetime, timedelta
from io import BytesIO
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
from wsgiref.util import setup_testing_defaults

import app
import facebook_connection
import reel_review
from workflow import VIETNAM_TIME


class MultiFanpageTest(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.database = Path(temporary.name) / "affiliate.sqlite3"
        mock_database = patch.object(app, "DATABASE", str(self.database))
        mock_database.start()
        self.addCleanup(mock_database.stop)

    def request(self, path, fields=None):
        environ = {}
        setup_testing_defaults(environ)
        route, _, query = path.partition("?")
        payload = urlencode(fields or {}, doseq=True).encode()
        environ.update({"PATH_INFO": route, "QUERY_STRING": query,
                        "REQUEST_METHOD": "POST" if fields is not None else "GET",
                        "CONTENT_TYPE": "application/x-www-form-urlencoded",
                        "CONTENT_LENGTH": str(len(payload)), "wsgi.input": BytesIO(payload)})
        response = {}

        def start_response(status, headers):
            response.update(status=int(status.split()[0]), headers=dict(headers))

        response["body"] = b"".join(app.application(environ, start_response)).decode()
        return response

    def submit(self, path, fields, status=303):
        response = self.request(path, fields)
        self.assertEqual(response["status"], status, response["body"])
        return response

    def add_page(self, name, **fields):
        response = self.submit("/pages", {"name": name, **fields})
        return int(response["headers"]["Location"].rsplit("=", 1)[-1])

    def test_legacy_database_and_renamed_seed_preserve_data(self):
        with sqlite3.connect(self.database) as legacy:
            legacy.executescript("""
                CREATE TABLE pages(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
                CREATE TABLE page_profiles(page_id INTEGER PRIMARY KEY REFERENCES pages(id),
                    audience TEXT NOT NULL DEFAULT '', voice TEXT NOT NULL DEFAULT '', cadence TEXT NOT NULL DEFAULT '');
                CREATE TABLE posts(id INTEGER PRIMARY KEY, page_id INTEGER NOT NULL REFERENCES pages(id),
                    product_id INTEGER, body TEXT NOT NULL, status TEXT NOT NULL, scheduled_at TEXT);
                CREATE TABLE editorial_activity(id INTEGER PRIMARY KEY, post_id INTEGER NOT NULL REFERENCES posts(id),
                    event TEXT NOT NULL, occurred_at TEXT NOT NULL);
                INSERT INTO pages VALUES (7, 'Trạm AI');
                INSERT INTO page_profiles VALUES (7, 'Độc giả cũ', 'Giọng cũ', 'Lịch cũ');
                INSERT INTO posts VALUES (8, 7, NULL, 'Bài cũ', 'scheduled', '2027-01-01T12:00:00+00:00');
                INSERT INTO editorial_activity VALUES (9, 8, 'post_scheduled', '2026-11-25T12:00:00+00:00');
            """)
        app.initialize()
        self.assertIn("Giọng cũ", self.request("/pages/settings?page_id=7")["body"])
        self.submit("/pages/settings", {"page_id": 7, "name": "Trạm AI Mới", "state": "active"})
        self.submit("/posts/unschedule", {"id": 8})
        app.initialize()
        with app.database() as database:
            self.assertEqual(database.execute("SELECT COUNT(*) FROM pages").fetchone()[0], 3)
            self.assertIsNone(database.execute("SELECT id FROM pages WHERE name = 'Trạm AI'").fetchone())
            self.assertEqual(database.execute("SELECT page_id FROM posts WHERE id = 8").fetchone()[0], 7)
            events = database.execute("SELECT event FROM editorial_activity ORDER BY id").fetchall()
            self.assertEqual([row[0] for row in events], ["post_scheduled", "post_unscheduled"])

    def test_fifty_pages_bulk_actions_and_independent_templates(self):
        app.initialize()
        for index in range(50):
            self.add_page(f"Đồ nhà {index:02}", category="Gia dụng")
        listing = self.request("/pages?category=Gia+d%E1%BB%A5ng&p=3")["body"]
        self.assertIn("50 / 53 Fanpage", listing)
        self.assertIn("Trang 3/3", listing)
        self.assertIn("Đồ nhà 49", listing)
        self.assertNotIn("Đồ nhà 00", listing)
        self.assertIn("Đồ nhà 12", self.request("/pages?" + urlencode({"q": "ĐỒ NHÀ 12"}))["body"])
        self.submit("/pages/settings", {"page_id": 1, "name": "Trạm AI", "state": "active",
                                        "ai_prompt": "Nội dung gốc", "logo_url": "https://example.test/logo.png",
                                        "category": "Công nghệ", "facebook_id": "201"})
        self.submit("/pages/templates", {"page_id": 1, "template_name": "Mẫu công nghệ"})
        child = self.add_page("Page từ mẫu", template_id=1, facebook_id="202")
        settings = self.request(f"/pages/settings?page_id={child}")["body"]
        self.assertIn("Nội dung gốc", settings)
        self.assertIn("Công nghệ", settings)
        self.assertNotIn("example.test/logo.png", settings)
        self.submit("/pages/settings", {"page_id": child, "name": "Page từ mẫu", "state": "active",
                                         "ai_prompt": "", "facebook_id": "202"})
        self.assertNotIn("Nội dung gốc", self.request(f"/pages/settings?page_id={child}")["body"])
        self.assertIn("Nội dung gốc", self.request("/pages/settings?page_id=1")["body"])
        self.submit("/pages/bulk", {"page_ids": [2, child], "state": "paused", "category": "Tạm nghỉ"})
        self.submit("/pages/bulk", {"page_ids": [2, 9999], "state": "archived"}, status=400)
        with app.database() as database:
            states = database.execute("SELECT state, category FROM pages WHERE id IN (?, ?)", (2, child)).fetchall()
            self.assertEqual([tuple(row) for row in states], [("paused", "Tạm nghỉ")] * 2)

    def test_calendar_holds_and_link_to_post(self):
        app.initialize()
        self.submit("/posts", {"page_id": 1, "body": "Bài A"})
        self.submit("/posts", {"page_id": 2, "body": "Bài B"})
        self.submit("/posts/approve", {"id": 1})
        self.submit("/posts/approve", {"id": 2})
        scheduled = datetime.now(VIETNAM_TIME) + timedelta(days=1)
        when = scheduled.strftime("%Y-%m-%dT%H:%M")
        self.submit("/posts/schedule", {"id": 1, "when": when})
        self.submit("/pages/bulk", {"page_ids": [1, 2], "state": "paused"})
        self.submit("/posts/schedule", {"id": 2, "when": when}, status=400)
        self.assertIn("1 lịch đang giữ", self.request("/")["body"])
        calendar = self.request(f"/calendar?start={scheduled.date()}&page_id=1")["body"]
        self.assertIn("Giữ lịch (Tạm dừng)", calendar)
        self.assertIn("post_id=1#post-1", calendar)
        self.assertNotIn("Bài A", self.request(f"/calendar?start={scheduled.date()}&page_id=2")["body"])
        self.assertIn('id="post-1"', self.request("/?page_id=1&post_id=1")["body"])
        self.submit("/posts/unschedule", {"id": 1})
        self.assertNotIn("Bài A", self.request(f"/calendar?start={scheduled.date()}&page_id=1")["body"])
        self.submit("/pages/bulk", {"page_ids": [2], "state": "archived"})
        self.submit("/posts", {"page_id": 2, "body": "Không tạo"}, status=400)
        self.submit("/tasks", {"page_id": 2, "title": "Không tạo", "assignee": "QA"}, status=400)
        self.assertIn("Bài B", self.request("/?page_id=2")["body"])

    def test_facebook_check_matches_page_and_limits_granular_scopes(self):
        app.initialize()
        one = self.add_page("Kênh một", facebook_id="301")
        two = self.add_page("Kênh hai", facebook_id="302")
        self.submit("/pages", {"name": "Kênh trùng", "facebook_id": "301"}, status=400)
        env = {"AFFILIATE_FB_GRAPH_VERSION": "v99.0", "AFFILIATE_FB_APP_TOKEN": "dummy-app-token",
               "AFFILIATE_FB_PAGE_TOKEN_301": "dummy-one-token", "AFFILIATE_FB_PAGE_TOKEN_302": "dummy-two-token"}
        token_data = {"type": "PAGE", "is_valid": True, "profile_id": "301",
                      "scopes": ["pages_read_engagement", "pages_show_list", "read_insights"],
                      "granular_scopes": [{"scope": "read_insights", "target_ids": ["302"]}]}
        with patch.dict(os.environ, env), patch.object(facebook_connection, "graph_get") as provider:
            provider.side_effect = [{"data": token_data}, {"id": "301"}, {"data": token_data}]
            self.submit("/pages/facebook-check", {"page_id": one})
            self.submit("/pages/facebook-check", {"page_id": two})
            report = self.request(f"/pages/settings?page_id={one}")["body"]
            self.assertIn("Meta xác nhận token thuộc đúng Page ID", report)
            self.assertIn("Đọc số liệu · Thiếu read_insights", report)
            self.assertNotIn("dummy-one-token", report)
            self.assertIn("Cảnh báo kết nối Facebook", self.request("/")["body"])
            self.assertEqual(provider.call_count, 3)
        self.assertNotIn(b"dummy-one-token", self.database.read_bytes())

    def test_existing_reel_review_survives_migration_and_page_rename(self):
        app.initialize()
        self.submit("/posts", {"page_id": 1, "body": "Reel đã kiểm tra"})
        self.submit("/reels/scenes", {"post_id": 1, "prompt": "Demo", "seconds": 2})
        filename = "a" * 32 + ".mp4"
        (self.database.parent / filename).write_bytes(b"saved preview")
        with app.database() as database:
            post, scenes, _ = reel_review.snapshot(database, 1)
            old_revision = reel_review.content_revision(post, scenes, post["fanpage"])
            database.execute("""
                INSERT INTO reel_reviews(post_id, revision, filename, checked_at) VALUES (1, ?, ?, 'checked')
            """, (old_revision, filename))
            database.execute("PRAGMA user_version = 0")
        app.initialize()
        self.submit("/pages/settings", {"page_id": 1, "name": "Trạm AI Mới", "state": "active"})
        with patch.dict(os.environ, {"AFFILIATE_MEDIA_DIR": str(self.database.parent)}):
            self.submit("/posts/approve", {"id": 1})


if __name__ == "__main__":
    unittest.main()
