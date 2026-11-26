from html import escape
from pathlib import Path

ROOMS = (
    "Điều hành", "Nghiên cứu", "Chiến lược", "Sản phẩm", "Kiến trúc",
    "Thiết kế", "Lập trình", "QA", "Bảo mật", "DevOps",
    "Marketing", "Kinh doanh", "Affiliate", "CSKH", "Dữ liệu",
    "Bảo trì", "Tài chính", "Tri thức", "Quản lý Agent", "Kiểm toán",
)
ROOM_KEYS = {name.casefold(): name for name in ROOMS}


def render(db):
    from tasks import STATUS_LABELS

    groups = {name: [] for name in (*ROOMS, "Chưa xếp phòng")}
    for row in db.execute("""
        SELECT work_tasks.*, pages.name AS page
        FROM work_tasks LEFT JOIN pages ON pages.id = work_tasks.page_id
        ORDER BY work_tasks.id DESC
    """):
        room = ROOM_KEYS.get(row["assignee"].strip().casefold(), "Chưa xếp phòng")
        groups[room].append(row)

    tiles = []
    panels = []
    for index, (name, rows) in enumerate(groups.items()):
        active = sum(row["status"] == "running" for row in rows)
        tiles.append(f"""
            <button class="room {'busy' if active else ''}" data-room="{index}"
                    type="button" aria-controls="room-{index}" aria-pressed="false">
                <span class="desk" aria-hidden="true"></span>
                <strong>{name}</strong><small>{active} đang làm · {len(rows)} phiếu</small>
            </button>
        """)
        items = []
        for row in rows:
            output = f'<p>{escape(row["output"])}</p>' if row["output"] else ""
            items.append(f"""
                <li><strong>{escape(row["title"])}</strong>
                <small>{escape(row["assignee"])} · {escape(row["page"] or "Toàn dự án")}
                · {STATUS_LABELS[row["status"]]}</small>{output}</li>
            """)
        content = f'<ul>{"".join(items)}</ul>' if items else "<p>Phòng này chưa có phiếu.</p>"
        panels.append(f'<section class="panel" id="room-{index}" hidden><h2>{name}</h2>{content}</section>')

    template = Path(__file__).with_name("office.html").read_text(encoding="utf-8")
    return (template.replace("<!--ROOM_TILES-->", "".join(tiles))
            .replace("<!--ROOM_PANELS-->", "".join(panels)))
