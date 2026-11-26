from datetime import datetime, timedelta, timezone
from html import escape

import reels

VIETNAM_TIME = timezone(timedelta(hours=7))
STATUS_LABELS = {"draft": "Bản nháp", "approved": "Đã duyệt", "scheduled": "Đã lên lịch"}


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


def add_post(db, fields):
    body = fields.get("body", "").strip()
    if not 1 <= len(body) <= 5000:
        raise ValueError("Nội dung cần từ 1 đến 5000 ký tự.")
    db.execute("INSERT INTO posts(page_id, product_id, body) VALUES (?, ?, ?)",
               (fields.get("page_id"), fields.get("product_id") or None, body))


def approve(db, fields):
    result = db.execute("UPDATE posts SET status = 'approved' WHERE id = ? AND status = 'draft'",
                        (fields.get("id"),))
    if result.rowcount != 1:
        raise ValueError("Chỉ duyệt được bài đang ở trạng thái bản nháp.")


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
    """, (local.astimezone(timezone.utc).isoformat(), fields.get("id")))
    if result.rowcount != 1:
        raise ValueError("Chỉ lên lịch được bài đã duyệt.")


def options(choices, selected=None):
    items = []
    for value, label in choices:
        selection = " selected" if value == selected else ""
        items.append(f'<option value="{escape(str(value))}"{selection}>{escape(label)}</option>')
    return "".join(items)


def post_card(db, row):
    post_id = row["id"]
    action = ""
    if row["status"] == "draft":
        action = f'<form method="post" action="/posts/approve"><button name="id" value="{post_id}">Duyệt bài</button></form>'
    elif row["status"] == "approved":
        action = f"""
            <form method="post" action="/posts/schedule">
                <label>Giờ Việt Nam <input name="when" type="datetime-local" required></label>
                <button name="id" value="{post_id}">Lên lịch</button>
            </form>
        """
    else:
        scheduled = datetime.fromisoformat(row["scheduled_at"]).astimezone(VIETNAM_TIME)
        action = f'<p>{scheduled:%d/%m/%Y %H:%M} (giờ Việt Nam)</p>'
    product = escape(row["product"] or "")
    return f"""
        <article><strong>{escape(row["page"])} · {STATUS_LABELS[row["status"]]}</strong>
        <p style="white-space: pre-wrap">{escape(row["body"])}</p>
        <p>{product}</p>{reels.render_plan(db, post_id, row["status"])}{action}</article>
    """


def section(db, filters=None):
    filters = filters or {}
    page_choices = list(db.execute("SELECT id, name FROM pages ORDER BY id"))
    pages_by_value = {str(row["id"]): row["id"] for row in page_choices}
    page_id = pages_by_value.get(filters.get("page_id", [""])[-1])
    status = filters.get("status", [""])[-1]
    if status not in STATUS_LABELS:
        status = None

    pages = options(page_choices, page_id)
    filter_pages = options([("", "Tất cả Fanpage"), *page_choices],
                           page_id if page_id is not None else "")
    filter_statuses = options([("", "Tất cả trạng thái"), *STATUS_LABELS.items()],
                              status or "")
    products = options(db.execute("SELECT id, name FROM products ORDER BY name"))
    posts = "".join(post_card(db, row) for row in db.execute("""
        SELECT posts.*, pages.name AS page, products.name AS product
        FROM posts JOIN pages ON pages.id = posts.page_id
        LEFT JOIN products ON products.id = posts.product_id
        WHERE (? IS NULL OR posts.page_id = ?) AND (? IS NULL OR posts.status = ?)
        ORDER BY posts.id DESC
    """, (page_id, page_id, status, status)))
    if not posts:
        posts = "<p>Chưa có bài viết phù hợp.</p>"
    return f"""
        <section><h2>Bài viết</h2>
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
        {posts}</section>
    """
