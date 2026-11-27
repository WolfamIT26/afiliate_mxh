from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest import TestCase
from unittest.mock import patch

import activity
import app
import trend_radar as radar
from workflow import VIETNAM_TIME


class TrendRadarTest(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        database = patch.object(app, "DATABASE", str(Path(temporary.name) / "affiliate.sqlite3"))
        database.start()
        self.addCleanup(database.stop)
        app.initialize()

    def candidate(self, **fields):
        values = {
            "page_id": "1", "title": "Góc nội dung", "source_url": "https://example.test/reference",
            "evidence_on": "2026-01-01", "notes": "Ghi chú nguồn",
        }
        with app.database() as db:
            return radar.create(db, {**values, **fields})

    def test_sources_filters_and_notes_are_scoped_to_selected_page(self):
        link = self.candidate(title="Góc <mới>", notes="Có sản phẩm NỔI BẬT", source_url="https://example.test/?a=1&b=2")
        self.candidate(page_id="2", title="Chủ đề khác")
        self.assertEqual(link, "/trends?trend_id=1#trend-1")
        with app.database() as db:
            html = radar.directory(db, {"page_id": ["1"], "q": ["nổi bật"], "status": ["candidate"]})
        self.assertIn("Góc &lt;mới&gt;", html)
        self.assertIn("https://example.test/?a=1&amp;b=2", html)
        self.assertIn("Có sản phẩm NỔI BẬT", html)
        self.assertNotIn("Chủ đề khác", html)

    def test_rejects_bad_evidence_and_archived_pages(self):
        future = (datetime.now(VIETNAM_TIME).date() + timedelta(days=1)).isoformat()
        with self.assertRaisesRegex(ValueError, "tương lai"):
            self.candidate(evidence_on=future)
        with self.assertRaisesRegex(ValueError, "link nguồn"):
            self.candidate(source_url="javascript:alert(1)")
        self.candidate(page_id="2")
        with app.database() as db:
            db.execute("UPDATE pages SET state = 'archived' WHERE id = 2")
        with self.assertRaisesRegex(ValueError, "lưu trữ"):
            self.candidate(page_id="2")
        with self.assertRaisesRegex(ValueError, "lưu trữ"), app.database() as db:
            radar.make_draft(db, {"id": "1"})
        with app.database() as db:
            self.assertIsNone(db.execute("SELECT post_id FROM trend_candidates").fetchone()["post_id"])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM posts").fetchone()[0], 0)

    def test_simultaneous_conversion_only_creates_one_draft_and_one_source_event(self):
        self.candidate()
        start = Barrier(2, timeout=5)

        def promote():
            with app.database() as db:
                start.wait()
                return radar.make_draft(db, {"id": "1"})

        with ThreadPoolExecutor(max_workers=2) as workers:
            first = workers.submit(promote)
            second = workers.submit(promote)
            self.assertEqual(first.result(), second.result())
        with app.database() as db:
            posts = db.execute("SELECT body, status, page_id FROM posts").fetchall()
            self.assertEqual([tuple(post) for post in posts], [("Góc nội dung", "draft", 1)])
            events = db.execute("SELECT event FROM editorial_activity ORDER BY id").fetchall()
            self.assertEqual([row["event"] for row in events], ["draft_created", "trend_promoted"])
            self.assertIn("Mở bài đã tạo", radar.directory(db, {"status": ["converted"]}))
            self.assertNotIn("Mở bài đã tạo", radar.directory(db, {"status": ["candidate"]}))

    def test_conversion_rolls_back_draft_when_recording_source_fails(self):
        self.candidate()
        record = activity.record

        def record_event(db, post_id, event):
            if event == "trend_promoted":
                raise ValueError("Lỗi ghi hoạt động")
            record(db, post_id, event)

        with patch.object(activity, "record", side_effect=record_event):
            with self.assertRaisesRegex(ValueError, "Lỗi ghi hoạt động"), app.database() as db:
                radar.make_draft(db, {"id": "1"})
        with app.database() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM posts").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM editorial_activity").fetchone()[0], 0)
            self.assertIsNone(db.execute("SELECT post_id FROM trend_candidates").fetchone()["post_id"])
