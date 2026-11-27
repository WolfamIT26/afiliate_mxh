import hashlib
import json
from datetime import datetime, timezone
from html import escape
from uuid import uuid4

import reel_media
import reels
from reel_render import render_reel


def initialize(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS reel_reviews (
            post_id INTEGER PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
            revision TEXT NOT NULL,
            filename TEXT NOT NULL UNIQUE,
            checked_at TEXT
        )
    """)


def snapshot(db, post_id):
    post = db.execute("""
        SELECT posts.id, posts.status, posts.body, pages.name AS fanpage,
               products.name AS product, products.url AS affiliate_url
        FROM posts JOIN pages ON pages.id = posts.page_id
        LEFT JOIN products ON products.id = posts.product_id
        WHERE posts.id = ?
    """, (post_id,)).fetchone()
    if post is None:
        return None, [], None
    scenes = reels.scene_rows(db, post_id)
    # Status changes at approval and scheduling. The reviewed content stays the same.
    content = [post["fanpage"], post["body"], post["product"], post["affiliate_url"],
               [tuple(scene) for scene in scenes]]
    revision = hashlib.sha256(json.dumps(content, ensure_ascii=False).encode("utf-8")).hexdigest()
    return post, scenes, revision


def current(db, post_id, revision):
    review = db.execute("""
        SELECT filename, checked_at FROM reel_reviews WHERE post_id = ? AND revision = ?
    """, (post_id, revision)).fetchone()
    if review and reel_media.media_path(review["filename"]).is_file():
        return review
    return None


def generate(database, post_id, requested_revision):
    with database() as db:
        post, scenes, revision = snapshot(db, post_id)
        if not scenes or any(not scene["filename"] for scene in scenes):
            raise ValueError("Cần nhập đủ clip trước khi dựng bản xem trước.")
        if revision != requested_revision:
            raise ValueError("Bản Reel đã thay đổi. Mở lại trang kiểm tra rồi dựng lại.")
        if current(db, post_id, revision):
            return post["id"]

    filename = uuid4().hex + ".mp4"
    output = reel_media.media_path(filename)
    output.parent.mkdir(parents=True, exist_ok=True)
    saved = False
    try:
        render_reel([reel_media.media_path(scene["filename"]) for scene in scenes], output)
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            _, _, latest_revision = snapshot(db, post_id)
            if latest_revision != revision:
                raise ValueError("Bản Reel đã thay đổi. Mở lại trang kiểm tra rồi dựng lại.")
            if current(db, post_id, revision):
                return post["id"]
            previous = db.execute(
                "SELECT filename FROM reel_reviews WHERE post_id = ?", (post_id,)
            ).fetchone()
            db.execute("""
                INSERT INTO reel_reviews(post_id, revision, filename)
                VALUES (?, ?, ?)
                ON CONFLICT(post_id) DO UPDATE SET
                    revision = excluded.revision, filename = excluded.filename, checked_at = NULL
            """, (post_id, revision, filename))
        saved = True
    finally:
        if not saved:
            reel_media.discard(filename)
    if previous:
        reel_media.discard(previous["filename"])
    return post["id"]


def confirm(db, fields):
    if fields.get("checked") != "yes":
        raise ValueError("Xác nhận đã kiểm tra nội dung và clip Reel.")
    if not db.in_transaction:
        db.execute("BEGIN IMMEDIATE")
    post, scenes, revision = snapshot(db, fields.get("post_id"))
    if not scenes or post["status"] != "draft" or revision != fields.get("revision"):
        raise ValueError("Bản Reel đã thay đổi hoặc đã duyệt. Mở lại trang kiểm tra.")
    if current(db, post["id"], revision) is None:
        raise ValueError("Dựng và xem bản Reel hiện tại trước khi xác nhận.")
    db.execute("""
        UPDATE reel_reviews SET checked_at = COALESCE(checked_at, ?)
        WHERE post_id = ? AND revision = ?
    """, (datetime.now(timezone.utc).isoformat(timespec="seconds"), post["id"], revision))


def require_for_approval(db, post_id):
    if not db.in_transaction:
        db.execute("BEGIN IMMEDIATE")
    post, scenes, revision = snapshot(db, post_id)
    if scenes and post["status"] == "draft":
        review = current(db, post_id, revision)
        if review is None or review["checked_at"] is None:
            raise ValueError("Mở Kiểm tra Reel và xác nhận bản dựng hiện tại trước khi duyệt bài.")


def section(post, scenes, revision, review):
    post_id = post["id"]
    checks = ""
    preview = ""
    items = []
    for scene in scenes:
        duration = f'{scene["duration_ms"] / 1000:g} giây' if scene["filename"] else "Thiếu clip"
        items.append(
            f'<li>{escape(scene["prompt"])} · Dự kiến {scene["seconds"]} giây · {duration}</li>'
        )
    if review:
        preview = f"""
            <video controls preload="metadata" playsinline
                style="width: min(100%, 22rem); background: #131a16"
                src="/reels/review/video?post_id={post_id}&amp;revision={revision}"></video>
            <form method="post" action="/reels/render?post_id={post_id}&amp;revision={revision}">
                <button>Tải Reel MP4 không âm thanh</button>
            </form>
        """
        if review["checked_at"]:
            checks = "<p>Đã xác nhận kiểm tra bản dựng này.</p>"
        elif post["status"] == "draft":
            checks = f"""
                <ul>
                    <li>Đúng cảnh, thứ tự, thời lượng và khung hình khi xem trên điện thoại.</li>
                    <li>Clip và caption khớp tư liệu, sản phẩm, biến thể và link affiliate nếu có.</li>
                    <li>Đã kiểm tra chữ, phụ đề trong clip và lưu ý về nguồn, nội dung minh họa.</li>
                </ul>
                <form method="post" action="/reels/review/confirm">
                    <input type="hidden" name="post_id" value="{post_id}">
                    <input type="hidden" name="revision" value="{revision}">
                    <label><input type="checkbox" name="checked" value="yes" required>
                        Tôi đã xem bản dựng và kiểm tra các mục trên.
                    </label>
                    <button>Xác nhận kiểm tra Reel</button>
                </form>
            """
    elif all(scene["filename"] for scene in scenes):
        preview = f"""
            <form method="post"
                action="/reels/review/generate?post_id={post_id}&amp;revision={revision}">
                <button>Dựng bản xem trước</button>
            </form>
        """
    else:
        preview = "<p>Nhập clip cho các cảnh còn thiếu để dựng bản xem trước.</p>"
    product = ""
    if post["affiliate_url"]:
        url = escape(post["affiliate_url"])
        product = (
            f'<p>{escape(post["product"])}<br><a href="{url}" rel="noreferrer">{url}</a></p>'
        )
    return f"""
        <section>
            <h2>{escape(post["fanpage"])} · Bài #{post_id}</h2>
            <p style="white-space: pre-wrap">{escape(post["body"])}</p>
            {product}
            <h3>Cảnh Reel 9:16</h3><ol>{"".join(items)}</ol>
            {preview}{checks}
        </section>
    """
