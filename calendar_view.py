from datetime import date, datetime, time, timedelta, timezone
from html import escape
from urllib.parse import urlencode

import profiles
from workflow import VIETNAM_TIME, options


def post_link(post):
    return f"/?page_id={post['page_id']}&amp;post_id={post['id']}#post-{post['id']}"


def utc_start(day):
    return datetime.combine(day, time.min, VIETNAM_TIME).astimezone(timezone.utc).isoformat()


def local_day():
    return datetime.now(VIETNAM_TIME).date()


def today(db):
    day = local_day()
    start = utc_start(day)
    end = utc_start(day + timedelta(days=1))
    pending = db.execute("""
        SELECT COUNT(*) FROM posts JOIN pages ON pages.id = posts.page_id
        WHERE posts.status = 'draft' AND pages.state <> 'archived'
    """).fetchone()[0]
    due = db.execute("""
        SELECT COUNT(*) FROM posts JOIN pages ON pages.id = posts.page_id
        WHERE posts.status = 'scheduled' AND scheduled_at >= ? AND scheduled_at < ? AND pages.state = 'active'
    """, (start, end)).fetchone()[0]
    held = db.execute("""
        SELECT COUNT(*) FROM posts JOIN pages ON pages.id = posts.page_id
        WHERE posts.status = 'scheduled' AND pages.state <> 'active'
    """).fetchone()[0]
    drafts = db.execute("""
        SELECT posts.id, posts.page_id, posts.body, pages.name
        FROM posts JOIN pages ON pages.id = posts.page_id
        WHERE posts.status = 'draft' AND pages.state <> 'archived'
        ORDER BY posts.id DESC LIMIT 5
    """).fetchall()
    upcoming = db.execute("""
        SELECT posts.id, posts.page_id, posts.body, posts.scheduled_at, pages.name, pages.state
        FROM posts JOIN pages ON pages.id = posts.page_id
        WHERE posts.status = 'scheduled' AND posts.scheduled_at >= ? AND pages.state = 'active'
        ORDER BY posts.scheduled_at, posts.id LIMIT 5
    """, (datetime.now(timezone.utc).isoformat(),)).fetchall()
    draft_items = "".join(f'<li><a href="{post_link(post)}">{escape(post["name"])} · '
                          f'{escape(post["body"][:70])}</a></li>' for post in drafts)
    scheduled_items = "".join(schedule_item(post) for post in upcoming)
    failed_checks = db.execute("""
        SELECT pages.id, pages.name, facebook_checks.message
        FROM facebook_checks JOIN pages ON pages.id = facebook_checks.page_id
        WHERE facebook_checks.passed = 0 AND pages.state <> 'archived'
        ORDER BY facebook_checks.checked_at DESC, pages.id LIMIT 5
    """).fetchall()
    alerts = "".join(f'<li><a href="/pages/settings?page_id={row["id"]}#facebook">'
                     f'{escape(row["name"])} · {escape(row["message"])}</a></li>' for row in failed_checks)
    return f"""
        <section>
            <h2>Hôm nay</h2>
            <div class="form-row">
                <a href="/?status=draft&amp;page_state=available#posts">{pending} bản nháp chờ duyệt</a>
                <a href="/calendar">{due} lịch hôm nay</a>
                <a href="/?status=scheduled&amp;page_state=held#posts">{held} lịch đang giữ</a>
            </div>
            {f'<h3>Cảnh báo kết nối Facebook</h3><ul>{alerts}</ul>' if alerts else ''}
            <div class="profile-fields">
                <div><h3>Chờ duyệt gần đây</h3>{f'<ul>{draft_items}</ul>' if draft_items else '<p>Không có bài chờ duyệt.</p>'}</div>
                <div><h3>Sắp đến giờ</h3>{f'<ul>{scheduled_items}</ul>' if scheduled_items else '<p>Chưa có lịch sắp tới.</p>'}</div>
            </div>
        </section>
    """


def schedule_item(post):
    moment = datetime.fromisoformat(post["scheduled_at"]).astimezone(VIETNAM_TIME)
    hold = f' · Giữ lịch ({profiles.PAGE_STATES[post["state"]]})' if post["state"] != "active" else ""
    return (f'<li><time datetime="{moment.isoformat()}">{moment:%d/%m %H:%M}</time> · '
            f'<a href="{post_link(post)}">{escape(post["name"])} · {escape(post["body"][:70])}</a>{hold}</li>')


def calendar(db, filters):
    selected = filters.get("page_id", [""])[-1]
    day = local_day()
    try:
        requested = date.fromisoformat(filters.get("start", [""])[-1])
        if 1 < requested.year < 9999:
            day = requested
    except ValueError:
        pass
    days = timedelta(days=7)
    pages = db.execute("SELECT id, name FROM pages ORDER BY name COLLATE NOCASE").fetchall()
    if selected not in {str(row["id"]) for row in pages}:
        selected = ""
    page_options = options([("", "Tất cả Fanpage"), *pages], selected)
    rows = db.execute("""
        SELECT posts.id, posts.page_id, posts.body, posts.scheduled_at, pages.name, pages.state
        FROM posts JOIN pages ON pages.id = posts.page_id
        WHERE posts.status = 'scheduled' AND posts.scheduled_at >= ? AND posts.scheduled_at < ?
            AND (? = '' OR posts.page_id = ?)
        ORDER BY posts.scheduled_at, posts.id
    """, (utc_start(day), utc_start(day + days), selected, selected))
    items = "".join(schedule_item(row) for row in rows)
    previous = urlencode({"page_id": selected, "start": day - days})
    following = urlencode({"page_id": selected, "start": day + days})
    return f"""
        <section>
            <form class="form-row" method="get" action="/calendar">
                <label>Fanpage <select name="page_id">{page_options}</select></label>
                <label>Từ ngày <input type="date" name="start" value="{day.isoformat()}"></label>
                <button>Xem lịch</button>
            </form>
            <nav aria-label="Tuần lịch đăng">
                <a href="/calendar?{escape(previous)}">7 ngày trước</a> ·
                <strong>{day:%d/%m/%Y} – {day + timedelta(days=6):%d/%m/%Y}</strong> ·
                <a href="/calendar?{escape(following)}">7 ngày sau</a>
            </nav>
            <p>Giờ Việt Nam. Lịch được lưu trên ứng dụng.</p>
            {f'<ul>{items}</ul>' if items else '<p>Không có bài đã lên lịch trong khoảng này.</p>'}
        </section>
    """
