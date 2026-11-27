from datetime import date, datetime
from html import escape
from urllib.parse import urlencode

import activity
import catalog
import profiles
import workflow

TRENDS_PER_PAGE = 25
STATUSES = {"candidate": "Đang xem xét", "converted": "Đã chuyển thành bài"}


def initialize(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS trend_candidates (
            id INTEGER PRIMARY KEY,
            page_id INTEGER NOT NULL REFERENCES pages(id),
            title TEXT NOT NULL,
            source_url TEXT NOT NULL,
            evidence_on TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            post_id INTEGER UNIQUE REFERENCES posts(id)
        )
    """)
    db.execute("""
        CREATE INDEX IF NOT EXISTS trend_candidates_recent
        ON trend_candidates(evidence_on DESC, id DESC)
    """)


def create(db, fields):
    title = fields.get("title", "").strip()
    notes = fields.get("notes", "").strip()
    if not 1 <= len(title) <= 160:
        raise ValueError("Chủ đề cần từ 1 đến 160 ký tự.")
    if len(notes) > 2000:
        raise ValueError("Ghi chú cần tối đa 2.000 ký tự.")
    source = catalog.validate_url(fields.get("source_url", "").strip(), "link nguồn")
    try:
        observed = date.fromisoformat(fields.get("evidence_on", "").strip())
    except ValueError:
        raise ValueError("Chọn ngày ghi nhận hợp lệ.") from None
    if observed > datetime.now(workflow.VIETNAM_TIME).date():
        raise ValueError("Ngày ghi nhận không được ở tương lai.")
    result = db.execute("""
        INSERT INTO trend_candidates(page_id, title, source_url, evidence_on, notes)
        SELECT id, ?, ?, ?, ? FROM pages WHERE id = ? AND state <> 'archived'
    """, (title, source, observed.isoformat(), notes, fields.get("page_id")))
    if result.rowcount != 1:
        raise ValueError("Chọn Fanpage tồn tại và chưa lưu trữ để ghi nhận xu hướng.")
    return f"/trends?trend_id={result.lastrowid}#trend-{result.lastrowid}"


def make_draft(db, fields):
    # Obtain the SQLite write lock before reading so concurrent retries see the same draft.
    if not db.in_transaction:
        db.execute("BEGIN IMMEDIATE")
    candidate = db.execute("""
        SELECT id, page_id, title, post_id FROM trend_candidates WHERE id = ?
    """, (fields.get("id"),)).fetchone()
    if candidate is None:
        raise ValueError("Không tìm thấy mục Radar.")
    if candidate["post_id"] is not None:
        return workflow.post_location(db, candidate["post_id"])
    post_id = workflow.create_draft(db, {"page_id": candidate["page_id"], "body": candidate["title"]})
    db.execute("UPDATE trend_candidates SET post_id = ? WHERE id = ?", (post_id, candidate["id"]))
    activity.record(db, post_id, "trend_promoted")
    return workflow.post_location(db, post_id)


def trend_card(row):
    trend_id = row["id"]
    assigned_page = escape(row["page"])
    observed = date.fromisoformat(row["evidence_on"])
    notes = row["notes"]
    notes_html = f'<p style="white-space: pre-wrap">{escape(notes)}</p>' if notes else ""
    source = escape(row["source_url"])
    if row["post_id"] is not None:
        post_id = row["post_id"]
        status = STATUSES["converted"]
        action = f'<a href="/?page_id={row["page_id"]}&amp;post_id={post_id}#post-{post_id}">Mở bài đã tạo</a>'
    elif row["page_state"] == "archived":
        status = STATUSES["candidate"]
        action = '<p>Fanpage đã lưu trữ.</p>'
    else:
        status = STATUSES["candidate"]
        action = f"""
            <form method="post" action="/trends/draft">
                <button name="id" value="{trend_id}">Tạo bản nháp từ chủ đề</button>
            </form>
        """
    return f"""
        <article id="trend-{trend_id}">
            <h3>{escape(row["title"])}</h3>
            <p>{assigned_page} · {status}</p>
            <p>Ghi nhận <time datetime="{observed.isoformat()}">{observed:%d/%m/%Y}</time> ·
                <a href="{source}" rel="noreferrer">Mở link nguồn</a></p>
            {notes_html}
            {action}
        </article>
    """


def directory(db, filters):
    query = filters.get("q", [""])[-1].strip()[:160]
    page_id = filters.get("page_id", [""])[-1]
    status = filters.get("status", [""])[-1]
    if status not in STATUSES:
        status = ""
    focused = filters.get("trend_id", [""])[-1]
    before = filters.get("before", [""])[-1]
    before_on, _, before_id = before.partition(",")

    pages = db.execute("SELECT id, name, state FROM pages ORDER BY name COLLATE NOCASE, id").fetchall()
    page_choices = [(str(page["id"]), page["name"]) for page in pages]
    if page_id not in {value for value, _ in page_choices}:
        page_id = ""
    writable_pages = [
        (str(page["id"]), page["name"]) for page in pages if page["state"] != "archived"
    ]
    page_options = workflow.options([("", "Tất cả Fanpage"), *page_choices], page_id)
    assignment = workflow.options([("", "Chọn Fanpage"), *writable_pages], page_id)
    status_options = workflow.options([("", "Tất cả trạng thái"), *STATUSES.items()], status)

    db.create_function("casefold", 1, str.casefold, deterministic=True)
    term = query.casefold()
    rows = db.execute("""
        SELECT trend_candidates.*, pages.name AS page, pages.state AS page_state
        FROM trend_candidates JOIN pages ON pages.id = trend_candidates.page_id
        WHERE (? = '' OR trend_candidates.id = ?)
            AND (? = '' OR trend_candidates.page_id = ?)
            AND CASE ? WHEN 'candidate' THEN post_id IS NULL
                       WHEN 'converted' THEN post_id IS NOT NULL ELSE 1 END
            AND (? = '' OR instr(casefold(title), ?) > 0 OR instr(casefold(notes), ?) > 0
                OR instr(casefold(source_url), ?) > 0)
            AND (? = '' OR (evidence_on, trend_candidates.id) < (?, CAST(? AS INTEGER)))
        ORDER BY evidence_on DESC, trend_candidates.id DESC
        LIMIT ?
    """, (focused, focused, page_id, page_id, status, term, term, term, term,
          before_on, before_on, before_id, TRENDS_PER_PAGE + 1)).fetchall()
    visible = rows[:TRENDS_PER_PAGE]
    items = "".join(trend_card(row) for row in visible) or "<p>Chưa có chủ đề phù hợp.</p>"
    params = {"q": query, "page_id": page_id, "status": status}
    links = []
    if before or focused:
        links.append(f'<a href="/trends?{escape(urlencode(params))}">Xem danh sách mới nhất</a>')
    if len(rows) > TRENDS_PER_PAGE:
        last = visible[-1]
        params["before"] = f'{last["evidence_on"]},{last["id"]}'
        links.append(f'<a href="/trends?{escape(urlencode(params))}">Xem mục cũ hơn</a>')
    pagination = f'<nav aria-label="Phân trang Radar">{" · ".join(links)}</nav>' if links else ""
    today = datetime.now(workflow.VIETNAM_TIME).date().isoformat()
    return f"""
        <section><h2>Ghi nhận xu hướng</h2>
            <form method="post" action="/trends">
                <label>Chủ đề <input name="title" maxlength="160" required></label>
                <label>Fanpage <select name="page_id" required>{assignment}</select></label>
                <label>Link nguồn <input name="source_url" type="url" maxlength="2048" required></label>
                <label>Ngày ghi nhận <input name="evidence_on" type="date" value="{today}" max="{today}" required></label>
                <label>Ghi chú về nguồn và góc nội dung <textarea name="notes" rows="3" maxlength="2000"></textarea></label>
                <button>Lưu chủ đề</button>
            </form>
        </section>
        <section><h2>Danh sách chủ đề</h2>
            <form class="form-row" method="get" action="/trends" role="search">
                <label>Tìm chủ đề, ghi chú hoặc link nguồn
                    <input name="q" type="search" maxlength="160" value="{escape(query)}">
                </label>
                <label>Lọc theo Fanpage <select name="page_id">{page_options}</select></label>
                <label>Lọc theo trạng thái <select name="status">{status_options}</select></label>
                <button>Lọc chủ đề</button><a href="/trends">Xóa bộ lọc</a>
            </form>
            {items}{pagination}
        </section>
    """
