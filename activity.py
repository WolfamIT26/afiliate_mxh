from datetime import datetime, timedelta, timezone
from html import escape

RECENT_LIMIT = 20
EVENT_LABELS = {
    "draft_created": "Tạo bản nháp",
    "scene_added": "Thêm cảnh Reel",
    "post_approved": "Duyệt bài",
    "post_scheduled": "Lưu lịch đăng",
    "post_unscheduled": "Hủy lịch đăng",
}
VIETNAM_TIME = timezone(timedelta(hours=7))


def initialize(db):
    schema = db.execute("SELECT sql FROM sqlite_master WHERE name = 'editorial_activity'").fetchone()
    legacy = schema is not None and "post_unscheduled" not in schema["sql"]
    if legacy:
        db.execute("ALTER TABLE editorial_activity RENAME TO editorial_activity_legacy")
    db.execute("""
        CREATE TABLE IF NOT EXISTS editorial_activity (
            id INTEGER PRIMARY KEY,
            post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
            event TEXT NOT NULL CHECK (
                event IN ('draft_created', 'scene_added', 'post_approved', 'post_scheduled', 'post_unscheduled')
            ),
            occurred_at TEXT NOT NULL
        )
    """)
    if legacy:
        db.execute("""
            INSERT INTO editorial_activity(id, post_id, event, occurred_at)
            SELECT id, post_id, event, occurred_at FROM editorial_activity_legacy
        """)
        db.execute("DROP TABLE editorial_activity_legacy")


def record(db, post_id, event):
    occurred_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    db.execute(
        "INSERT INTO editorial_activity(post_id, event, occurred_at) VALUES (?, ?, ?)",
        (post_id, event, occurred_at),
    )


def section(db):
    rows = db.execute("""
        SELECT activity.post_id, activity.event, activity.occurred_at, pages.name
        FROM editorial_activity AS activity
        JOIN posts ON posts.id = activity.post_id
        JOIN pages ON pages.id = posts.page_id
        ORDER BY activity.id DESC
        LIMIT ?
    """, (RECENT_LIMIT,))

    items = []
    for row in rows:
        timestamp = datetime.fromisoformat(row["occurred_at"]).astimezone(VIETNAM_TIME)
        label = EVENT_LABELS[row["event"]]
        page_name = escape(row["name"])
        items.append(
            f'<li><time datetime="{timestamp.isoformat()}">{timestamp:%d/%m/%Y %H:%M:%S}</time>'
            f' · {page_name} · {label} · Bài #{row["post_id"]}</li>'
        )
    content = f'<ol>{"".join(items)}</ol>' if items else "<p>Chưa có hoạt động biên tập.</p>"
    return f"""
        <section aria-labelledby="activity-heading">
            <h2 id="activity-heading">Hoạt động dự án</h2>
            <p>Tối đa {RECENT_LIMIT} thao tác biên tập gần nhất trên ứng dụng · giờ Việt Nam</p>
            {content}
        </section>
    """
