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
VERSIONS_PER_PAGE = 10


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
    db.execute("""
        CREATE TABLE IF NOT EXISTS post_versions (
            post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
            version INTEGER NOT NULL CHECK (version > 0),
            body TEXT NOT NULL,
            product_name TEXT,
            affiliate_url TEXT,
            saved_at TEXT,
            PRIMARY KEY (post_id, version)
        )
    """)
    db.execute("""
        INSERT INTO post_versions(post_id, version, body, product_name, affiliate_url)
        SELECT posts.id, 1, posts.body, products.name, products.url
        FROM posts LEFT JOIN products ON products.id = posts.product_id
        WHERE NOT EXISTS (SELECT 1 FROM post_versions WHERE post_versions.post_id = posts.id)
    """)


def post_body(fields):
    body = fields.get("body", "").strip()
    if not 1 <= len(body) <= 5000:
        raise ValueError("Nội dung cần từ 1 đến 5000 ký tự.")
    return body


def append_version(db, post_id, version):
    saved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    db.execute("""
        INSERT INTO post_versions(post_id, version, body, product_name, affiliate_url, saved_at)
        SELECT posts.id, ?, posts.body, products.name, products.url, ?
        FROM posts LEFT JOIN products ON products.id = posts.product_id
        WHERE posts.id = ?
    """, (version, saved_at, post_id))


def create_draft(db, fields):
    body = post_body(fields)
    result = db.execute("""
        INSERT INTO posts(page_id, product_id, body)
        SELECT id, ?, ? FROM pages WHERE id = ? AND state <> 'archived'
    """, (fields.get("product_id") or None, body, fields.get("page_id")))
    if result.rowcount != 1:
        raise ValueError("Chọn Fanpage tồn tại và chưa lưu trữ để tạo bản nháp.")
    post_id = result.lastrowid
    append_version(db, post_id, 1)
    activity.record(db, post_id, "draft_created")
    return post_id


def add_post(db, fields):
    return post_location(db, create_draft(db, fields))


def latest_version(db, post_id):
    return db.execute(
        "SELECT MAX(version) FROM post_versions WHERE post_id = ?", (post_id,)
    ).fetchone()[0]


def edit_post(db, fields):
    body = post_body(fields)
    if not db.in_transaction:
        db.execute("BEGIN IMMEDIATE")
    post = db.execute("""
        SELECT posts.id, posts.body, posts.product_id
        FROM posts JOIN pages ON pages.id = posts.page_id
        WHERE posts.id = ? AND posts.status = 'draft' AND pages.state <> 'archived'
    """, (fields.get("id"),)).fetchone()
    if post is None:
        raise ValueError("Chỉ sửa được bản nháp của Fanpage chưa lưu trữ.")
    post_id = post["id"]
    version = latest_version(db, post_id)
    if str(version) != fields.get("version"):
        raise ValueError("Bản nháp đã thay đổi. Mở lại bài để sửa phiên bản hiện tại.")

    product_id = post["product_id"]
    if fields.get("product_id") == "":
        product_id = None
    elif fields.get("product_id"):
        product = db.execute("SELECT id FROM products WHERE id = ?", (fields["product_id"],)).fetchone()
        if product is None:
            raise ValueError("Không tìm thấy sản phẩm đã chọn.")
        product_id = product["id"]
    if body != post["body"] or product_id != post["product_id"]:
        db.execute("UPDATE posts SET body = ?, product_id = ? WHERE id = ?", (body, product_id, post_id))
        append_version(db, post_id, version + 1)
        db.execute("UPDATE reel_reviews SET checked_at = NULL WHERE post_id = ?", (post_id,))
        activity.record(db, post_id, "draft_edited")
    return post_location(db, post_id)


def approve(db, fields):
    post_id = fields.get("id")
    if not db.in_transaction:
        db.execute("BEGIN IMMEDIATE")
    if "version" in fields and str(latest_version(db, post_id)) != fields["version"]:
        raise ValueError("Bản nháp đã thay đổi. Mở lại bài để duyệt phiên bản hiện tại.")
    if "reel_revision" in fields:
        _, _, reel_revision = reel_review.snapshot(db, post_id)
        if fields["reel_revision"] != reel_revision:
            raise ValueError("Kế hoạch hoặc clip Reel đã thay đổi. Mở lại bài trước khi duyệt.")
    reel_review.require_for_approval(db, post_id)
    result = db.execute("""
        UPDATE posts SET status = 'approved'
        WHERE id = ? AND status = 'draft'
            AND page_id IN (SELECT id FROM pages WHERE state <> 'archived')
    """, (post_id,))
    if result.rowcount != 1:
        raise ValueError("Chỉ duyệt được bài nháp của Fanpage chưa lưu trữ.")
    activity.record(db, post_id, "post_approved")
    return post_location(db, post_id)


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


def version_history(db, post_id, previous_url, before):
    versions = db.execute("""
        SELECT version, body, product_name, affiliate_url, saved_at
        FROM post_versions
        WHERE post_id = ? AND (? = '' OR version < CAST(? AS INTEGER))
        ORDER BY version DESC LIMIT ?
    """, (post_id, before, before, VERSIONS_PER_PAGE + 1)).fetchall()
    items = []
    for version in versions[:VERSIONS_PER_PAGE]:
        timestamp = "Đã có trước khi lưu lịch sử"
        if version["saved_at"]:
            local = datetime.fromisoformat(version["saved_at"]).astimezone(VIETNAM_TIME)
            timestamp = f'<time datetime="{local.isoformat()}">{local:%d/%m/%Y %H:%M:%S}</time>'
        product = ""
        if version["affiliate_url"] is not None:
            product = f'<p>{escape(version["product_name"])}<br>{escape(version["affiliate_url"])}</p>'
        items.append(f"""
            <li><strong>Phiên bản {version['version']}</strong> · {timestamp}
                <p style="white-space: pre-wrap">{escape(version['body'])}</p>
                {product}
            </li>
        """)
    navigation = []
    if before:
        navigation.append(f'<a href="{previous_url}#post-versions-{post_id}">Phiên bản mới nhất</a>')
    if len(versions) > VERSIONS_PER_PAGE:
        older = versions[VERSIONS_PER_PAGE - 1]["version"]
        navigation.append(
            f'<a href="{previous_url}&amp;revision_before={older}#post-versions-{post_id}">Phiên bản cũ hơn</a>'
        )
    return f"""
        <details id="post-versions-{post_id}" {'open' if before else ''}>
            <summary>Lịch sử chỉnh sửa</summary>
            {f'<ol>{"".join(items)}</ol>' if items else '<p>Không có phiên bản trong khoảng này.</p>'}
            {" · ".join(navigation)}
        </details>
    """


def post_card(db, row, product_choices, focused, revision_before):
    post_id = row["id"]
    post_url = f'/?page_id={row["page_id"]}&amp;post_id={post_id}'
    action = ""
    editable = row["status"] == "draft" and row["page_state"] != "archived"
    revisions = ""
    if editable:
        reel_revision = reel_review.content_revision(row, reels.scene_rows(db, post_id), row["page_id"])
        action = f"""
            <form method="post" action="/posts/approve">
                <input type="hidden" name="version" value="{row['version']}">
                <input type="hidden" name="reel_revision" value="{reel_revision}">
                <button name="id" value="{post_id}">Duyệt bài</button>
            </form>
        """
        if focused:
            selected = row["product_id"] if row["product_id"] is not None else ""
            products = options([("", "Không gắn"), *product_choices], selected)
            revisions = f"""
                <details open>
                    <summary>Chỉnh sửa bản nháp</summary>
                    <form method="post" action="/posts/edit">
                        <input type="hidden" name="id" value="{post_id}">
                        <input type="hidden" name="version" value="{row['version']}">
                        <label>Nội dung bản nháp
                            <textarea name="body" required maxlength="5000" rows="4">{escape(row['body'])}</textarea>
                        </label>
                        <label>Sản phẩm của bản nháp <select name="product_id">{products}</select></label>
                        <button>Lưu phiên bản</button>
                    </form>
                </details>
            """
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
    if row["affiliate_url"] is not None:
        url = escape(row["affiliate_url"])
        name = escape(row["product"])
        product = f'<p><a href="{url}" rel="noreferrer">{name}</a><br>{url}</p>'
    if focused:
        revisions += version_history(db, post_id, post_url, revision_before)
    else:
        label = "Chỉnh sửa bản nháp và xem lịch sử" if editable else "Xem lịch sử chỉnh sửa"
        revisions = f'<p><a href="{post_url}#post-{post_id}">{label}</a></p>'
    radar_source = ""
    if row["trend_id"] is not None:
        trend_id = row["trend_id"]
        radar_source = f'<p><a href="/trends?trend_id={trend_id}#trend-{trend_id}">Xem nguồn trên Radar</a></p>'
    return f"""
        <article id="post-{post_id}"><strong>{escape(row["page"])} · {STATUS_LABELS[row["status"]]}</strong>
        <p style="white-space: pre-wrap">{escape(row["body"])}</p>
        {product}{radar_source}{revisions}{reels.render_plan(db, post_id, row["status"])}
        <p><a href="/reels/brief?post_id={post_id}">Tải kế hoạch Reel (JSON)</a></p>
        {action}</article>
    """


def section(db, filters=None):
    if not db.in_transaction:
        db.execute("BEGIN")
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
    revision_before = filters.get("revision_before", [""])[-1]

    writable_pages = [(row["id"], row["name"]) for row in page_choices if row["state"] != "archived"]
    pages = options([("", "Chọn Fanpage"), *writable_pages], page_id)
    filter_pages = options([("", "Tất cả Fanpage"), *((row["id"], row["name"]) for row in page_choices)],
                           page_id if page_id is not None else "")
    filter_statuses = options([("", "Tất cả trạng thái"), *STATUS_LABELS.items()],
                              status or "")
    product_choices = [
        (product["id"], f'{product["name"]} · {product["url"]}')
        for product in db.execute("SELECT id, name, url FROM products ORDER BY name, id")
    ]
    rows = db.execute("""
        SELECT posts.*, pages.name AS page, pages.state AS page_state,
               products.name AS product, products.url AS affiliate_url,
               (SELECT MAX(version) FROM post_versions WHERE post_versions.post_id = posts.id) AS version,
               trend_candidates.id AS trend_id
        FROM posts JOIN pages ON pages.id = posts.page_id
        LEFT JOIN products ON products.id = posts.product_id
        LEFT JOIN trend_candidates ON trend_candidates.post_id = posts.id
        WHERE (? IS NULL OR posts.page_id = ?) AND (? IS NULL OR posts.status = ?)
            AND (? = '' OR posts.id = ?)
            AND (? = '' OR posts.id < CAST(? AS INTEGER))
            AND CASE ? WHEN 'available' THEN pages.state <> 'archived'
                       WHEN 'held' THEN pages.state <> 'active' ELSE 1 END
        ORDER BY posts.id DESC
        LIMIT ?
    """, (page_id, page_id, status, status, post_id, post_id, before, before, page_state, POSTS_PER_PAGE + 1)).fetchall()
    visible = rows[:POSTS_PER_PAGE]
    posts = "".join(
        post_card(db, row, product_choices, bool(post_id), revision_before) for row in visible
    ) or "<p>Chưa có bài viết phù hợp.</p>"
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
            <label>Sản phẩm <select name="product_id"><option value="">Không gắn</option>{options(product_choices)}</select></label>
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
