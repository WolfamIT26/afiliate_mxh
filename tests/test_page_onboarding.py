import sqlite3
import unittest

import facebook_connection
import page_directory
import profiles


class PageOnboardingTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        profiles.initialize(self.db)
        facebook_connection.initialize(self.db)

    def add_page(self, name, **fields):
        location = page_directory.create(self.db, {"name": name, **fields})
        return int(location.rsplit("=", 1)[1])

    def test_template_fields_are_reported_on_the_page_that_received_them(self):
        one = self.add_page("Page có hồ sơ", facebook_id="123")
        profiles.save(self.db, {"page_id": one, "audience": "Người mới", "voice": "Gần gũi",
                                "sources": "Ảnh sản phẩm của shop", "logo_url": "https://example.test/logo.png"})
        page_directory.save_template(self.db, {"page_id": one, "template_name": "Mẫu nội dung"})
        two = self.add_page("Page dùng mẫu", template_id=1)
        three = self.add_page("Page mới")

        original = page_directory.settings(self.db, profiles.require_page(self.db, one))
        self.assertIn('id="page-onboarding"', original)
        self.assertIn("Nhận diện hình ảnh</th><td>Còn trống · Màu thương hiệu", original)
        self.assertIn('href="#profile-brand_colors"', original)
        self.assertEqual(original.count('id="profile-brand_colors"'), 1)
        self.assertIn(f'href="/trends?page_id={one}"', original)
        self.assertIn(f'href="{page_directory.settings_url(one)}"', page_directory.directory(self.db, {}))

        configured = page_directory.onboarding(self.db, profiles.require_page(self.db, two))
        self.assertIn("Người xem và giọng văn</th><td>Đã lưu", configured)
        self.assertIn("Nguồn tư liệu</th><td>Đã lưu", configured)
        self.assertIn("Nhận diện hình ảnh</th><td>Còn trống · Đường dẫn logo, Màu thương hiệu", configured)
        self.assertIn("Facebook Page ID</th><td>Chưa nhập", configured)

        empty = page_directory.onboarding(self.db, profiles.require_page(self.db, three))
        self.assertIn("Còn trống · Đối tượng người xem, Giọng văn", empty)
        self.assertIn("Chăm sóc khách hàng</th><td>Còn trống", empty)

    def test_connection_status_is_tied_to_the_current_page_id(self):
        page_id = self.add_page("Page kết nối", facebook_id="123")
        self.assertIn("Chưa kiểm tra", page_directory.onboarding(self.db, profiles.require_page(self.db, page_id)))
        self.db.execute("""
            INSERT INTO facebook_checks VALUES (?, '123', '2026-11-27T02:00:00+00:00', 0, 'Lỗi', '[]')
        """, (page_id,))
        self.assertIn("Lần kiểm tra gần nhất chưa đạt",
                      page_directory.onboarding(self.db, profiles.require_page(self.db, page_id)))
        self.db.execute("UPDATE facebook_checks SET passed = 1 WHERE page_id = ?", (page_id,))
        self.assertIn("Đã xác minh Page ID ở lần kiểm tra gần nhất",
                      page_directory.onboarding(self.db, profiles.require_page(self.db, page_id)))
        page_directory.save(self.db, {"page_id": page_id, "name": "Page kết nối", "state": "paused",
                                      "facebook_id": "456"})
        changed = page_directory.onboarding(self.db, profiles.require_page(self.db, page_id))
        self.assertIn("Chưa kiểm tra", changed)
        self.assertNotIn("Đã xác minh Page ID", changed)

    def test_seeded_page_keeps_previous_profile_fields_and_reports_missing_ones(self):
        existing = self.db.execute("SELECT id FROM pages WHERE name = 'Trạm AI'").fetchone()["id"]
        rendered = page_directory.settings(self.db, profiles.require_page(self.db, existing))
        self.assertIn("Hướng dẫn công cụ AI và thông tin gói đã xác minh.", rendered)
        self.assertIn("Kế hoạch nội dung</th><td>Còn trống · Lịch và tần suất đăng, Mẫu CTA", rendered)
        self.assertIn('href="#profile-cadence"', rendered)
        self.assertIn('id="profile-cadence"', rendered)
        self.assertIn('href="#facebook-page-id"', rendered)
        self.assertIn('id="facebook-page-id"', rendered)

    def test_legacy_profile_migration_fills_only_the_fields_that_were_saved(self):
        legacy = sqlite3.connect(":memory:")
        self.addCleanup(legacy.close)
        legacy.row_factory = sqlite3.Row
        legacy.executescript("""
            CREATE TABLE pages(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
            CREATE TABLE page_profiles(page_id INTEGER PRIMARY KEY REFERENCES pages(id),
                audience TEXT NOT NULL DEFAULT '', voice TEXT NOT NULL DEFAULT '', cadence TEXT NOT NULL DEFAULT '');
            INSERT INTO pages VALUES (7, 'Fanpage cũ');
            INSERT INTO page_profiles VALUES (7, 'Người xem lâu năm', 'Giọng văn cũ', 'Mỗi thứ ba');
        """)
        profiles.initialize(legacy)
        facebook_connection.initialize(legacy)
        rendered = page_directory.settings(legacy, profiles.require_page(legacy, 7))
        self.assertIn("Người xem và giọng văn</th><td>Đã lưu", rendered)
        self.assertIn("Kế hoạch nội dung</th><td>Còn trống · Chủ đề và series, Định dạng nội dung, Mẫu CTA", rendered)
        self.assertIn("Mỗi thứ ba", rendered)
