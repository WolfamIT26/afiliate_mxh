from datetime import datetime, timedelta, timezone
from html import escape
from urllib.parse import urlencode

import activity
import profiles
import reel_review
import reels

VIETNAM_TIME = timezone(timedelta(hours=7))
STATUS_LABELS = {"draft": "Bản nháp", "approved": "Đã duyệt", "scheduled": "Đã lên lịch"}
POSTS_PER_PAGE = 25


def initialize(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY,
            page_id INTEGER NOT NULL REFERENCES pages(id),
            product_id INTEGER REFERENCES products(id),
            body TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft'
                CHECK(status IN ('draft', 'approved', 'scheduled')),
            scheduled_at TEXT
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS posts_calendar ON posts(status, scheduled_at, page_id)")


def add_post(db, fields):
    body = fields.get("body", "").strip()
    if not 1 <= len(body) <= 5000:
        raise ValueError("Nội dung cần từ 1 đến 5000 ký tự.")
    result = db.execute("""
        INSERT INTO posts(page_id, product_id, body)
        SELECT id, ?, ? FROM pages WHERE id = ? AND state <> 'archived'
    """, (fields.get("product_id") or None, body, fields.get("page_id")))
    if result.rowcount != 1:
        raise ValueError("Chọn Fanpage tồn tại và chưa lưu trữ để tạo bản nháp.")
    activity.record(db, result.lastrowid, "draft_created")
    return post_location(db, result.lastrowid)


def approve(db, fields):
    reel_review.require_for_approval(db, fields.get("id"))
    result = db.execute("""
        UPDATE posts SET status = 'approved'
        WHERE id = ? AND status = 'draft'
            AND page_id IN (SELECT id FROM pages WHERE state <> 'archived')
    """, (fields.get("id"),))
    if result.rowcount != 1:
        raise ValueError("Chỉ duyệt được bài nháp của Fanpage chưa lưu trữ.")
    activity.record(db, fields["id"], "post_approved")
    return post_location(db, fields["id"])


def schedule(db, fields):
    try:
        local = datetime.strptime(fields.get("when", ""), "%Y-%m-%dT%H:%M")
    except ValueError:
        raise ValueError("Chọn thời gian lên lịch hợp lệ.") from None
    local = local.replace(tzinfo=VIETNAM_TIME)
    if local <= datetime.now(VIETNAM_TIME):
        raise ValueError("Thời gian lên lịch phải ở tương lai.")
    result = db.execute("""
        UPDATE posts SET status = 'scheduled', scheduled_at = ?
        WHERE id = ? AND status = 'approved'
            AND page_id IN (SELECT id FROM pages WHERE state = 'active')
    """, (local.astimezone(timezone.utc).isoformat(), fields.get("id")))
    if result.rowcount != 1:
        raise ValueError("Chỉ lên lịch được bài đã duyệt của Fanpage đang hoạt động.")
    activity.record(db, fields["id"], "post_scheduled")
    return post_location(db, fields["id"])


def cancel_schedule(db, fields):
    post_id = fields.get("id")
    result = db.execute("""
        UPDATE posts SET status = 'approved', scheduled_at = NULL
        WHERE id = ? AND status = 'scheduled'
    """, (post_id,))
    if result.rowcount != 1:
        raise ValueError("Bài này không còn lịch để hủy.")
    activity.record(db, post_id, "post_unscheduled")
    return post_location(db, post_id)


def post_location(db, post_id):
    post = db.execute("SELECT id, page_id FROM posts WHERE id = ?", (post_id,)).fetchone()
    return f"/?page_id={post['page_id']}&post_id={post['id']}#post-{post['id']}"


def options(choices, selected=None):
    items = []
    for value, label in choices:
        selection = " selected" if value == selected else ""
        items.append(f'<option value="{escape(str(value))}"{selection}>{escape(label)}</option>')
    return "".join(items)


def reel_brief(db, post_id):
    rows = db.execute("""
        SELECT posts.id AS post_id, posts.body, posts.status,
               pages.name AS page, products.name AS product, products.url AS affiliate_url,
               reel_scenes.id AS scene_id, reel_scenes.prompt, reel_scenes.seconds
        FROM posts JOIN pages ON pages.id = posts.page_id
        LEFT JOIN products ON products.id = posts.product_id
        LEFT JOIN reel_scenes ON reel_scenes.post_id = posts.id
        WHERE posts.id = ?
        ORDER BY reel_scenes.position
    """, (post_id,)).fetchall()
    if not rows:
        return None

    post = rows[0]
    product = None
    if post["product"] is not None:
        product = {"name": post["product"], "affiliate_url": post["affiliate_url"]}
    scene_rows = (row for row in rows if row["scene_id"] is not None)
    scenes = [
        {"position": position, "prompt": row["prompt"], "duration_seconds": row["seconds"]}
        for position, row in enumerate(scene_rows, start=1)
    ]
    return {
        "post_id": post["post_id"],
        "status": post["status"],
        "fanpage": post["page"],
        "caption": post["body"],
        "product": product,
        "aspect_ratio": "9:16",
        "total_duration_seconds": sum(scene["duration_seconds"] for scene in scenes),
        "scenes": scenes,
    }


def post_card(db, row):
    post_id = row["id"]
    action = ""
    if row["status"] == "draft" and row["page_state"] != "archived":
        action = f'<form method="post" action="/posts/approve"><button name="id" value="{post_id}">Duyệt bài</button></form>'
    elif row["status"] == "approved" and row["page_state"] == "active":
        action = f"""
            <form method="post" action="/posts/schedule">
                <label>Giờ Việt Nam <input name="when" type="datetime-local" required></label>
                <button name="id" value="{post_id}">Lên lịch</button>
            </form>
        """
    elif row["status"] == "scheduled":
        scheduled = datetime.fromisoformat(row["scheduled_at"]).astimezone(VIETNAM_TIME)
        state = profiles.PAGE_STATES[row["page_state"]]
        hold = f" · Giữ lịch ({state})" if row["page_state"] != "active" else ""
        action = f"""
            <p>{scheduled:%d/%m/%Y %H:%M} (giờ Việt Nam){hold}</p>
            <form method="post" action="/posts/unschedule">
                <button name="id" value="{post_id}">Hủy lịch</button>
            </form>
        """
    product = ""
    if row["product_url"] is not None:
        url = escape(row["product_url"])
        name = escape(row["product"])
        product = f'<p><a href="{url}" rel="noreferrer">{name}</a><br>{url}</p>'
    return f"""
        <article id="post-{post_id}"><strong>{escape(row["page"])} · {STATUS_LABELS[row["status"]]}</strong>
        <p style="white-space: pre-wrap">{escape(row["body"])}</p>
        {product}{reels.render_plan(db, post_id, row["status"])}
        <p><a href="/reels/brief?post_id={post_id}">Tải kế hoạch Reel (JSON)</a></p>
        {action}</article>
    """


def section(db, filters=None):
    filters = filters or {}
    page_choices = list(db.execute("SELECT id, name, state FROM pages ORDER BY id"))
    pages_by_value = {str(row["id"]): row["id"] for row in page_choices}
    page_id = pages_by_value.get(filters.get("page_id", [""])[-1])
    status = filters.get("status", [""])[-1]
    if status not in STATUS_LABELS:
        status = None
    page_state = filters.get("page_state", [""])[-1]
    if page_state not in ("available", "held"):
        page_state = ""
    post_id = filters.get("post_id", [""])[-1]
    before = filters.get("post_before", [""])[-1]

    writable_pages = [(row["id"], row["name"]) for row in page_choices if row["state"] != "archived"]
    pages = options([("", "Chọn Fanpage"), *writable_pages], page_id)
    filter_pages = options([("", "Tất cả Fanpage"), *((row["id"], row["name"]) for row in page_choices)],
                           page_id if page_id is not None else "")
    filter_statuses = options([("", "Tất cả trạng thái"), *STATUS_LABELS.items()],
                              status or "")
    products = options(
        (product["id"], f'{product["name"]} · {product["url"]}')
        for product in db.execute("SELECT id, name, url FROM products ORDER BY name, id")
    )
    rows = db.execute("""
        SELECT posts.*, pages.name AS page, pages.state AS page_state,
               products.name AS product, products.url AS product_url
        FROM posts JOIN pages ON pages.id = posts.page_id
        LEFT JOIN products ON products.id = posts.product_id
        WHERE (? IS NULL OR posts.page_id = ?) AND (? IS NULL OR posts.status = ?)
            AND (? = '' OR posts.id = ?)
            AND (? = '' OR posts.id < CAST(? AS INTEGER))
            AND CASE ? WHEN 'available' THEN pages.state <> 'archived'
                       WHEN 'held' THEN pages.state <> 'active' ELSE 1 END
        ORDER BY posts.id DESC
        LIMIT ?
    """, (page_id, page_id, status, status, post_id, post_id, before, before, page_state, POSTS_PER_PAGE + 1)).fetchall()
    visible = rows[:POSTS_PER_PAGE]
    posts = "".join(post_card(db, row) for row in visible) or "<p>Chưa có bài viết phù hợp.</p>"
    page_queries = {"page_id": page_id or "", "status": status or "", "page_state": page_state}
    navigation = []
    if before or post_id:
        navigation.append(f'<a href="/?{escape(urlencode(page_queries))}#posts">Xem bài mới nhất</a>')
    if len(rows) > POSTS_PER_PAGE:
        page_queries["post_before"] = visible[-1]["id"]
        navigation.append(f'<a href="/?{escape(urlencode(page_queries))}#posts">Xem bài cũ hơn</a>')
    pagination = f'<nav aria-label="Phân trang bài viết">{" · ".join(navigation)}</nav>' if navigation else ""
    return f"""
        <section id="posts"><h2>Bài viết</h2>
        <p>Lịch được lưu tại đây. Tính năng đăng lên Facebook chưa được kết nối.</p>
        <form method="post" action="/posts">
            <label>Fanpage <select name="page_id" required>{pages}</select></label>
            <label>Sản phẩm <select name="product_id"><option value="">Không gắn</option>{products}</select></label>
            <label>Nội dung <textarea name="body" required maxlength="5000" rows="4"></textarea></label>
            <button>Tạo bản nháp</button>
        </form>
        <h3>Danh sách bài viết</h3>
        <form method="get" action="/">
            <label>Lọc theo Fanpage <select name="page_id">{filter_pages}</select></label>
            <label>Lọc theo trạng thái <select name="status">{filter_statuses}</select></label>
            <button>Lọc bài viết</button>
            <a href="/">Xóa bộ lọc</a>
        </form>
        {posts}{pagination}</section>
    """
