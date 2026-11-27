from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
from wsgiref.util import setup_testing_defaults

import app
import reel_review
import workflow
from workflow import VIETNAM_TIME


class DraftRevisionsTest(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        database = patch.object(app, "DATABASE", str(self.directory / "affiliate.sqlite3"))
        database.start()
        self.addCleanup(database.stop)
        app.initialize()

    def request(self, path, fields=None, expected=200):
        environ = {}
        setup_testing_defaults(environ)
        route, _, query = path.partition("?")
        payload = urlencode(fields or {}).encode()
        environ.update({
            "PATH_INFO": route,
            "QUERY_STRING": query,
            "REQUEST_METHOD": "POST" if fields is not None else "GET",
            "CONTENT_LENGTH": str(len(payload)),
            "wsgi.input": BytesIO(payload),
        })
        response = {}

        def start_response(status, headers):
            response.update(status=int(status.split()[0]), headers=dict(headers))

        body = b"".join(app.application(environ, start_response)).decode()
        self.assertEqual(response["status"], expected, body)
        return body

    def test_revision_history_stale_actions_and_exact_product_links(self):
        self.request("/products", {"name": "Đèn", "url": "https://example.test/den?ref=old&x=1"}, 303)
        self.request("/products", {"name": "Bàn", "url": "https://example.test/ban?ref=new"}, 303)
        self.request("/posts", {"page_id": 1, "product_id": 1, "body": "Nội dung đầu <b>."}, 303)
        self.assertIn("Chỉnh sửa bản nháp và xem lịch sử", self.request("/"))
        detail = self.request("/?page_id=1&post_id=1")
        self.assertIn('action="/posts/edit"', detail)
        self.assertIn('name="version" value="1"', detail)
        self.assertIn("Nội dung đầu &lt;b&gt;.", detail)
        edit = {"id": 1, "version": 1, "body": "Nội dung sau", "product_id": 2}
        self.request("/posts/edit", edit, 303)
        self.assertIn("Bản nháp đã thay đổi", self.request("/posts/edit", edit, 400))
        self.assertIn("Bản nháp đã thay đổi", self.request("/posts/approve", {"id": 1, "version": 1}, 400))
        self.request("/posts/edit", {"id": 1, "version": 2, "body": "Nội dung sau"}, 303)
        with app.database() as db:
            versions = db.execute("""
                SELECT version, body, affiliate_url FROM post_versions WHERE post_id = 1 ORDER BY version
            """).fetchall()
            self.assertEqual([tuple(row) for row in versions], [
                (1, "Nội dung đầu <b>.", "https://example.test/den?ref=old&x=1"),
                (2, "Nội dung sau", "https://example.test/ban?ref=new"),
            ])
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM editorial_activity WHERE event = 'draft_edited'"
            ).fetchone()[0], 1)
        self.request("/posts/approve", {"id": 1, "version": 2}, 303)
        self.request("/posts/edit", {**edit, "version": 2, "body": "Không sửa được"}, 400)
        scheduled = (datetime.now(VIETNAM_TIME) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        self.request("/posts/schedule", {"id": 1, "when": scheduled}, 303)
        self.request("/posts/edit", {**edit, "version": 2, "body": "Không sửa được"}, 400)
        detail = self.request("/?page_id=1&post_id=1")
        self.assertNotIn('action="/posts/edit"', detail)
        self.assertIn("https://example.test/den?ref=old&amp;x=1", detail)

    def test_legacy_migration_and_archived_draft(self):
        with app.database() as db:
            db.execute("DROP TABLE post_versions")
            db.execute("INSERT INTO posts(id, page_id, body) VALUES (8, 1, 'Bản nháp cũ')")
        app.initialize()
        app.initialize()
        detail = self.request("/?post_id=8")
        self.assertIn("Đã có trước khi lưu lịch sử", detail)
        self.assertIn('name="version" value="1"', detail)
        with app.database() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM post_versions").fetchone()[0], 1)
        self.request("/pages/settings", {"page_id": 1, "name": "Trạm AI", "state": "archived"}, 303)
        self.request("/posts/edit", {"id": 8, "version": 1, "body": "Không sửa được"}, 400)
        self.assertNotIn('action="/posts/edit"', self.request("/?post_id=8"))

    def test_reel_confirmation_resets_after_an_edit_and_stays_reset_on_revert(self):
        self.request("/posts", {"page_id": 1, "body": "Caption đã kiểm tra"}, 303)
        self.request("/reels/scenes", {"post_id": 1, "prompt": "Cảnh mẫu", "seconds": 3}, 303)
        filename = "a" * 32 + ".mp4"
        (self.directory / filename).write_bytes(b"already rendered")
        with patch.dict("os.environ", {"AFFILIATE_MEDIA_DIR": str(self.directory)}):
            with app.database() as db:
                _, _, revision = reel_review.snapshot(db, 1)
                db.execute("INSERT INTO reel_reviews VALUES (1, ?, ?, 'checked')", (revision, filename))
            self.request("/posts/edit", {"id": 1, "version": 1, "body": "Caption đã kiểm tra"}, 303)
            with app.database() as db:
                self.assertEqual(reel_review.current(db, 1, revision)["checked_at"], "checked")
            self.request("/posts/edit", {"id": 1, "version": 1, "body": "Caption mới"}, 303)
            self.request("/posts/edit", {"id": 1, "version": 2, "body": "Caption đã kiểm tra"}, 303)
            self.assertIn("xác nhận bản dựng hiện tại", self.request("/posts/approve", {"id": 1, "version": 3}, 400))
            self.request("/reels/review/confirm", {"post_id": 1, "revision": revision, "checked": "yes"}, 303)
            self.request("/posts/approve", {"id": 1, "version": 3}, 303)

    def test_approval_form_rejects_a_changed_reel_even_after_new_confirmation(self):
        self.request("/posts", {"page_id": 1, "body": "Caption Reel"}, 303)
        self.request("/reels/scenes", {"post_id": 1, "prompt": "Cảnh đầu", "seconds": 3}, 303)
        form = self.request("/?post_id=1")
        previous = re.search(r'name="reel_revision" value="([a-f0-9]{64})"', form)
        self.assertIsNotNone(previous)
        self.request("/reels/scenes/edit", {"id": 1, "prompt": "Đổi cảnh", "seconds": 3}, 303)
        filename = "a" * 32 + ".mp4"
        (self.directory / filename).touch()
        with patch.dict("os.environ", {"AFFILIATE_MEDIA_DIR": str(self.directory)}):
            with app.database() as db:
                _, _, current = reel_review.snapshot(db, 1)
                db.execute("INSERT INTO reel_reviews VALUES (1, ?, ?, 'checked')", (current, filename))
            approval = {"id": 1, "version": 1, "reel_revision": previous.group(1)}
            message = self.request("/posts/approve", approval, 400)
            self.assertIn("Kế hoạch hoặc clip Reel đã thay đổi", message)
            self.request("/posts/approve", {**approval, "reel_revision": current}, 303)

    def test_concurrent_edit_and_approval_allow_only_one_write(self):
        self.request("/products", {"name": "Đèn", "url": "https://example.test/den"}, 303)
        self.request("/posts", {"page_id": 1, "body": "Caption gốc", "product_id": 1}, 303)
        barrier = Barrier(2)

        def submit(handler, fields):
            barrier.wait(timeout=5)
            try:
                with app.database() as db:
                    handler(db, fields)
            except ValueError:
                return False
            return True

        approval = {"id": "1", "version": "1"}
        with ThreadPoolExecutor(max_workers=2) as pool:
            edit = pool.submit(submit, workflow.edit_post, {**approval, "body": "Caption mới"})
            approve = pool.submit(submit, workflow.approve, approval)
            did_edit = edit.result(timeout=5)
            did_approve = approve.result(timeout=5)
        self.assertNotEqual(did_edit, did_approve)
        with app.database() as db:
            post = db.execute("SELECT status, body, product_id FROM posts WHERE id = 1").fetchone()
            if did_edit:
                self.assertEqual(tuple(post), ("draft", "Caption mới", 1))
                self.assertEqual(workflow.latest_version(db, 1), 2)
            else:
                self.assertEqual(tuple(post), ("approved", "Caption gốc", 1))
                self.assertEqual(workflow.latest_version(db, 1), 1)

    def test_history_paginates_beyond_the_latest_ten_versions(self):
        self.request("/posts", {"page_id": 1, "body": "Phiên bản đầu"}, 303)
        for version in range(1, 12):
            self.request("/posts/edit", {"id": 1, "version": version, "body": f"Nội dung {version}"}, 303)
        current = self.request("/?post_id=1")
        self.assertIn("revision_before=3#post-versions-1", current)
        self.assertNotIn("Phiên bản đầu", current)
        older = self.request("/?page_id=1&post_id=1&revision_before=3")
        self.assertIn("Phiên bản đầu", older)
        self.assertIn("Phiên bản mới nhất", older)
