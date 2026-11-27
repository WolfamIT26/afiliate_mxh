import json
from pathlib import Path

from tasks import STATUS_LABELS


ROOMS = (
    "Điều hành", "Nghiên cứu", "Chiến lược", "Sản phẩm", "Kiến trúc",
    "Thiết kế", "Lập trình", "QA", "Bảo mật", "DevOps",
    "Marketing", "Kinh doanh", "Affiliate", "CSKH", "Dữ liệu",
    "Bảo trì", "Tài chính", "Tri thức", "Quản lý Agent", "Kiểm toán",
    "Chưa xếp phòng",
)
ROOM_INDEX = {name.casefold(): index for index, name in enumerate(ROOMS)}
UNASSIGNED = len(ROOMS) - 1
ROOM_TASK_LIMIT = 12


def department_index(assignee):
    return ROOM_INDEX.get(assignee.strip().casefold(), UNASSIGNED)


def task_snapshot(db):
    db.create_function("office_department", 1, department_index, deterministic=True)
    rooms = [{"name": name, "pending": 0, "running": 0, "done": 0, "tasks": []} for name in ROOMS]
    rows = db.execute("""
        WITH assigned AS (
            SELECT work_tasks.id, work_tasks.title, work_tasks.status, work_tasks.output,
                   work_tasks.assignee, pages.name AS page, office_department(work_tasks.assignee) AS room
            FROM work_tasks LEFT JOIN pages ON pages.id = work_tasks.page_id
        ), ranked AS (
            SELECT *, SUM(status = 'pending') OVER (PARTITION BY room) AS pending_count,
                   SUM(status = 'running') OVER (PARTITION BY room) AS running_count,
                   SUM(status = 'done') OVER (PARTITION BY room) AS done_count,
                   ROW_NUMBER() OVER (
                       PARTITION BY room
                       ORDER BY CASE status WHEN 'running' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END, id DESC
                   ) AS position
            FROM assigned
        )
        SELECT * FROM ranked WHERE position <= ? ORDER BY room, position
    """, (ROOM_TASK_LIMIT,))
    for row in rows:
        room = rooms[row["room"]]
        room["pending"] = row["pending_count"]
        room["running"] = row["running_count"]
        room["done"] = row["done_count"]
        room["tasks"].append({
            "id": row["id"],
            "title": row["title"],
            "assignee": row["assignee"],
            "page": row["page"] or "Toàn dự án",
            "status": STATUS_LABELS[row["status"]],
            "output": row["output"],
        })
    return {"rooms": rooms}


def render(db):
    template = Path(__file__).with_name("office.html").read_text(encoding="utf-8")
    data = json.dumps(task_snapshot(db), ensure_ascii=False).replace("<", "\\u003c")
    return template.replace("<!--OFFICE_DATA-->", data)
