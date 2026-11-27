from datetime import datetime, timezone
from html import escape
import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

import profiles

PERMISSIONS = {
    "Đọc nội dung": ("pages_read_engagement",),
    "Đăng bài": ("pages_manage_posts", "pages_read_engagement", "pages_show_list"),
    "Đọc bình luận": ("pages_read_engagement", "pages_read_user_content"),
    "Trả lời bình luận": ("pages_manage_engagement",),
    "Đọc số liệu": ("read_insights", "pages_read_engagement", "pages_show_list"),
}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def initialize(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS facebook_checks (
            page_id INTEGER PRIMARY KEY REFERENCES pages(id) ON DELETE CASCADE,
            facebook_id TEXT NOT NULL,
            checked_at TEXT NOT NULL,
            passed INTEGER NOT NULL CHECK (passed IN (0, 1)),
            message TEXT NOT NULL,
            permissions TEXT NOT NULL
        )
    """)


def credentials(page_id):
    token_name = f"AFFILIATE_FB_PAGE_TOKEN_{page_id}"
    app_token_name = f"AFFILIATE_FB_APP_TOKEN_{page_id}"
    app_token = os.environ.get(app_token_name) or os.environ.get("AFFILIATE_FB_APP_TOKEN")
    return os.environ.get("AFFILIATE_FB_GRAPH_VERSION", ""), os.environ.get(token_name), app_token


def graph_get(version, endpoint, token, parameters):
    url = f"https://graph.facebook.com/{version}/{endpoint}?{urlencode(parameters)}"
    request = Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    try:
        with build_opener(NoRedirect()).open(request, timeout=5) as response:
            payload = response.read(262145)
            if len(payload) > 262144:
                raise ValueError("Oversized response")
            result = json.loads(payload)
    except HTTPError as error:
        code = error.code
        error.close()
        raise ValueError(f"Meta từ chối yêu cầu kiểm tra (HTTP {code}).") from None
    except (URLError, OSError, UnicodeError, ValueError):
        raise ValueError("Không đọc được phản hồi Meta. Kiểm tra mạng và phiên bản Graph API.") from None
    if not isinstance(result, dict) or "error" in result:
        raise ValueError("Meta trả về lỗi khi kiểm tra kết nối.")
    return result


def confirmed_scopes(data, page_id):
    granted = data.get("scopes") or []
    granular = data.get("granular_scopes") or []
    if not isinstance(granted, list) or not isinstance(granular, list):
        raise ValueError("Meta trả về thông tin quyền không đúng định dạng.")
    scopes = {scope for scope in granted if isinstance(scope, str)}
    targets = {}
    for entry in granular:
        if isinstance(entry, dict) and isinstance(entry.get("scope"), str) and isinstance(entry.get("target_ids"), list):
            targets.setdefault(entry["scope"], set()).update(str(value) for value in entry["target_ids"])
    return {scope for scope in scopes if scope not in targets or page_id in targets[scope]}


def check(db, fields):
    page = profiles.require_page(db, fields.get("page_id"))
    page_id = page["facebook_id"]
    if page_id is None:
        raise ValueError("Lưu Facebook Page ID trước khi kiểm tra kết nối.")
    version, page_token, app_token = credentials(page_id)
    if not (re.fullmatch(r"v[0-9]+\.[0-9]+", version) and page_token and app_token):
        raise ValueError("Thiếu Page token, app token hoặc phiên bản Graph API hợp lệ.")
    passed = False
    scopes = []
    try:
        data = graph_get(version, "debug_token", app_token, {"input_token": page_token}).get("data")
        if not isinstance(data, dict) or data.get("is_valid") is not True:
            raise ValueError("Meta báo token không hợp lệ hoặc đã hết hạn.")
        if data.get("type") != "PAGE" or (data.get("profile_id") and str(data["profile_id"]) != page_id):
            raise ValueError("Token phải thuộc đúng Facebook Page ID đã lưu.")
        identity = graph_get(version, "me", page_token, {"fields": "id,name"})
        if str(identity.get("id")) != page_id:
            raise ValueError("Facebook Page ID trả về khác Page ID đã lưu.")
        scopes = sorted(confirmed_scopes(data, page_id))
        passed = True
        message = "Meta xác nhận token thuộc đúng Page ID."
    except ValueError as error:
        message = str(error)
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result = db.execute("""
        INSERT INTO facebook_checks(page_id, facebook_id, checked_at, passed, message, permissions)
        SELECT id, facebook_id, ?, ?, ?, ? FROM pages WHERE id = ? AND facebook_id = ?
        ON CONFLICT(page_id) DO UPDATE SET
            facebook_id = excluded.facebook_id, checked_at = excluded.checked_at,
            passed = excluded.passed, message = excluded.message, permissions = excluded.permissions
    """, (checked_at, passed, message, json.dumps(scopes), page["id"], page_id))
    if result.rowcount != 1:
        raise ValueError("Page ID đã thay đổi. Mở lại trang cài đặt và thử lại.")
    return f"/pages/settings?page_id={page['id']}#facebook"


def section(db, page):
    facebook_id = page["facebook_id"]
    if not facebook_id:
        return '<section id="facebook"><h2>Kết nối Facebook</h2><p>Lưu Facebook Page ID để bắt đầu.</p></section>'
    version, page_token, app_token = credentials(facebook_id)
    if not (re.fullmatch(r"v[0-9]+\.[0-9]+", version) and page_token and app_token):
        return f"""
            <section id="facebook"><h2>Kết nối Facebook</h2>
            <p>Chưa cấu hình kết nối. Cần <code>AFFILIATE_FB_PAGE_TOKEN_{escape(facebook_id)}</code>,
            <code>AFFILIATE_FB_APP_TOKEN</code> (hoặc <code>AFFILIATE_FB_APP_TOKEN_{escape(facebook_id)}</code>)
            và <code>AFFILIATE_FB_GRAPH_VERSION</code> trên máy chạy app.</p></section>
        """
    row = db.execute("SELECT * FROM facebook_checks WHERE page_id = ? AND facebook_id = ?",
                     (page["id"], facebook_id)).fetchone()
    report = "<p>Chưa kiểm tra kết nối.</p>"
    if row is not None:
        report = f'<p>{escape(row["message"])} <time datetime="{row["checked_at"]}">{row["checked_at"]}</time></p>'
        if row["passed"]:
            scopes = set(json.loads(row["permissions"]))
            items = []
            for task, required in PERMISSIONS.items():
                missing = set(required) - scopes
                status = "Có quyền trong token" if not missing else f"Thiếu {', '.join(sorted(missing))}"
                items.append(f"<li>{task} · {status}</li>")
            report += '<p>Quyền khai báo trong token</p><ul>' + "".join(items) + '</ul>'
    return f"""
        <section id="facebook"><h2>Kết nối Facebook</h2>{report}
        <form method="post" action="/pages/facebook-check">
            <button name="page_id" value="{page['id']}">Kiểm tra kết nối</button>
        </form></section>
    """
