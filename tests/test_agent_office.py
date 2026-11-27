import json
import sqlite3
import unittest

import office
import profiles
import tasks


class AgentOfficeTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        profiles.initialize(self.db)
        tasks.initialize(self.db)

    def add_task(self, title, assignee, page_id=""):
        tasks.create(self.db, {"title": title, "assignee": assignee, "page_id": page_id})
        return self.db.execute("SELECT last_insert_rowid()").fetchone()[0]

    def test_snapshot_tracks_real_tasks_and_keeps_counts_beyond_display_limit(self):
        running_id = self.add_task("Kiểm tra Reel", "  NGHIÊN CỨU  ", "1")
        done_id = self.add_task("Rà soát đã xong", "Nghiên cứu")
        for index in range(office.ROOM_TASK_LIMIT):
            self.add_task(f"Kiểm tra nguồn {index}", "Nghiên cứu")
        unknown_id = self.add_task("Đối chiếu cửa hàng", "Nhóm riêng")
        tasks.advance(self.db, {"id": running_id, "status": "running"})
        tasks.advance(self.db, {"id": done_id, "status": "running"})
        tasks.advance(self.db, {"id": done_id, "status": "done", "output": "Đã bàn giao"})

        rooms = {room["name"]: room for room in office.task_snapshot(self.db)["rooms"]}
        research = rooms["Nghiên cứu"]
        self.assertEqual((research["running"], research["pending"], research["done"]), (1, office.ROOM_TASK_LIMIT, 1))
        self.assertEqual(len(research["tasks"]), office.ROOM_TASK_LIMIT)
        first = research["tasks"][0]
        self.assertEqual((first["id"], first["page"], first["status"]), (running_id, "Trạm AI", "Đang thực hiện"))
        self.assertEqual(rooms["Chưa xếp phòng"]["tasks"][0]["id"], unknown_id)
        self.assertFalse(rooms["Điều hành"]["tasks"])

        tasks.advance(self.db, {"id": running_id, "status": "done", "output": "Đã xác minh nguồn"})
        research = next(room for room in office.task_snapshot(self.db)["rooms"] if room["name"] == "Nghiên cứu")
        self.assertEqual((research["running"], research["done"]), (0, 2))

    def test_render_quotes_task_content_in_embedded_snapshot(self):
        title = "</script><p>Nội dung phiếu</p>"
        task_id = self.add_task(title, "QA")
        output = office.render(self.db)
        start = '<script type="application/json" id="office-data">'
        embedded = output.split(start, 1)[1].split("</script>", 1)[0]
        self.assertNotIn("<", embedded)
        snapshot = json.loads(embedded)
        qa = next(room for room in snapshot["rooms"] if room["name"] == "QA")
        self.assertEqual((qa["tasks"][0]["id"], qa["tasks"][0]["title"]), (task_id, title))


if __name__ == "__main__":
    unittest.main()
