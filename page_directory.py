from html import escape
from urllib.parse import urlencode

import profiles
from workflow import options

PAGE_SIZE = 20
PROFILE_LABELS = {key: label for key, label, _ in profiles.FIELDS}
ONBOARDING_GROUPS = (
    ("Người xem và giọng văn", ("audience", "voice")),
    ("Nhận diện hình ảnh", ("logo_url", "brand_colors")),
    ("Kế hoạch nội dung", ("topics", "formats", "cadence", "cta")),
    ("Nguồn tư liệu", ("sources",)),
    ("Hướng dẫn AI và duyệt bài", ("ai_prompt", "review_rules")),
    ("Chăm sóc khách hàng", ("support_rules",)),
)


def settings_url(page_id):
    return f"/pages/settings?page_id={page_id}"


def page_values(fields):
    name = fields.get("name", "").strip()
    category = fields.get("category", "").strip()
    facebook_id = fields.get("facebook_id", "").strip()
    if not 1 <= len(name) <= 120:
        raise ValueError("Tên Fanpage cần từ 1 đến 120 ký tự.")
    if len(category) > 80:
        raise ValueError("Tên nhóm cần tối đa 80 ký tự.")
    if facebook_id and not (facebook_id.isascii() and facebook_id.isdecimal()
                            and not facebook_id.startswith("0") and len(facebook_id) <= 32):
        raise ValueError("Facebook Page ID phải là dãy số tối đa 32 ký tự và không bắt đầu bằng 0.")
    return name, category, facebook_id or None


def create(db, fields):
    name, category, facebook_id = page_values(fields)
    result = db.execute("INSERT INTO pages(name, category, facebook_id) VALUES (?, ?, ?)",
                        (name, category, facebook_id))
    page_id = result.lastrowid
    if template_id := fields.get("template_id"):
        profiles.apply_template(db, page_id, profiles.find_template(db, template_id))
        if category:
            db.execute("UPDATE pages SET category = ? WHERE id = ?", (category, page_id))
    return settings_url(page_id)


def save(db, fields):
    page = profiles.require_page(db, fields.get("page_id"))
    name, category, facebook_id = page_values(fields)
    state = fields.get("state")
    if state not in profiles.PAGE_STATES:
        raise ValueError("Chọn trạng thái Fanpage hợp lệ.")
    db.execute("UPDATE pages SET name = ?, category = ?, facebook_id = ?, state = ? WHERE id = ?",
               (name, category, facebook_id, state, page["id"]))
    if facebook_id != page["facebook_id"]:
        db.execute("DELETE FROM facebook_checks WHERE page_id = ?", (page["id"],))
    profiles.save(db, fields)
    return settings_url(page["id"])


def apply_template(db, fields):
    page = profiles.require_page(db, fields.get("page_id"))
    profiles.apply_template(db, page["id"], profiles.find_template(db, fields.get("template_id")))
    return settings_url(page["id"])


def save_template(db, fields):
    profiles.save_template(db, fields)
    page = profiles.require_page(db, fields.get("page_id"))
    return settings_url(page["id"])


def bulk_update(db, fields):
    page_ids = tuple(dict.fromkeys(fields.get("page_ids", ())))
    state = fields.get("state", "")
    category = fields.get("category", "").strip()
    if not 1 <= len(page_ids) <= PAGE_SIZE:
        raise ValueError(f"Chọn từ 1 đến {PAGE_SIZE} Fanpage trong danh sách.")
    if state and state not in profiles.PAGE_STATES:
        raise ValueError("Chọn trạng thái Fanpage hợp lệ.")
    if len(category) > 80:
        raise ValueError("Tên nhóm cần tối đa 80 ký tự.")
    if not (state or category):
        raise ValueError("Chọn trạng thái hoặc nhập nhóm để cập nhật.")
    placeholders = ", ".join("?" for _ in page_ids)
    result = db.execute(f"""
        UPDATE pages SET state = COALESCE(?, state), category = COALESCE(?, category)
        WHERE id IN ({placeholders})
    """, (state or None, category or None, *page_ids))
    if result.rowcount != len(page_ids):
        raise ValueError("Danh sách có Fanpage không hợp lệ. Tải lại danh sách rồi thử lại.")
    return "/pages"


def template_options(db, first_label):
    return options([("", first_label), *((row["id"], row["name"]) for row in profiles.template_choices(db))])


def directory(db, filters):
    query = filters.get("q", [""])[-1].strip()[:120]
    category = filters.get("category", [""])[-1]
    state = filters.get("state", [""])[-1]
    if state not in profiles.PAGE_STATES:
        state = ""
    try:
        number = max(int(filters.get("p", ["1"])[-1]), 1)
    except ValueError:
        number = 1
    pages = db.execute("SELECT * FROM pages ORDER BY name COLLATE NOCASE, id").fetchall()
    categories = sorted({page["category"] for page in pages if page["category"]}, key=str.casefold)
    visible = [page for page in pages if (not category or page["category"] == category)
               and (not state or page["state"] == state)
               and (query.casefold() in page["name"].casefold() or query == page["facebook_id"])]
    last = max((len(visible) + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    number = min(number, last)
    start = (number - 1) * PAGE_SIZE
    rows = "".join(directory_row(page) for page in visible[start:start + PAGE_SIZE])
    category_options = options([("", "Tất cả nhóm"), *((value, value) for value in categories)], category)
    states = options([("", "Tất cả trạng thái"), *profiles.PAGE_STATES.items()], state)
    bulk_states = options([("", "Giữ trạng thái"), *profiles.PAGE_STATES.items()])
    pagination = ""
    if last > 1:
        links = []
        for target, label in ((number - 1, "Trang trước"), (number + 1, "Trang sau")):
            if 1 <= target <= last:
                url = urlencode({"q": query, "category": category, "state": state, "p": target})
                links.append(f'<a href="/pages?{escape(url)}">{label}</a>')
        pagination = f'<nav aria-label="Phân trang Fanpage">Trang {number}/{last} · {" · ".join(links)}</nav>'
    results = '<p>Không có Fanpage phù hợp.</p>'
    if rows:
        results = f"""
            <form method="post" action="/pages/bulk">
                <div class="table-wrap"><table>
                    <thead><tr><th scope="col">Chọn</th><th scope="col">Fanpage</th>
                    <th scope="col">Nhóm</th><th scope="col">Trạng thái</th><th scope="col">Page ID</th></tr></thead>
                    <tbody>{rows}</tbody>
                </table></div>
                <div class="form-row">
                    <label>Trạng thái trang đã chọn <select name="state">{bulk_states}</select></label>
                    <label>Đổi nhóm trang đã chọn <input name="category" maxlength="80"></label>
                    <button>Cập nhật trang đã chọn</button>
                </div>
            </form>{pagination}
        """
    return f"""
        <section>
            <form class="form-row" method="get" action="/pages">
                <label>Tìm theo tên hoặc Page ID <input name="q" maxlength="120" value="{escape(query)}"></label>
                <label>Nhóm <select name="category">{category_options}</select></label>
                <label>Trạng thái <select name="state">{states}</select></label>
                <button>Lọc Fanpage</button><a href="/pages">Xóa bộ lọc</a>
            </form>
            <p>{len(visible)} / {len(pages)} Fanpage</p>{results}
        </section>
        <section>
            <h2>Thêm Fanpage</h2>
            <form class="form-row" method="post" action="/pages">
                <label>Tên Fanpage <input name="name" maxlength="120" required></label>
                <label>Nhóm <input name="category" maxlength="80"></label>
                <label>Facebook Page ID <input name="facebook_id" inputmode="numeric" maxlength="32"></label>
                <label>Mẫu cấu hình <select name="template_id">{template_options(db, 'Cấu hình mới')}</select></label>
                <button>Thêm Fanpage</button>
            </form>
        </section>
    """


def directory_row(page):
    page_id = page["id"]
    name = escape(page["name"])
    return f"""
        <tr><td><input type="checkbox" name="page_ids" value="{page_id}" aria-label="Chọn {name}"></td>
        <td><a href="{settings_url(page_id)}">{name}</a></td><td>{escape(page['category']) or '—'}</td>
        <td>{profiles.PAGE_STATES[page['state']]}</td><td>{escape(page['facebook_id'] or '') or '—'}</td></tr>
    """


def onboarding(db, page):
    rows = []
    for title, fields in ONBOARDING_GROUPS:
        missing = [key for key in fields if not (page[key] or "").strip()]
        if missing:
            labels = ", ".join(PROFILE_LABELS[key] for key in missing)
            rows.append((title, f"Còn trống · {labels}", f"#profile-{missing[0]}", "Bổ sung"))
        else:
            rows.append((title, "Đã lưu", f"#profile-{fields[0]}", "Xem hồ sơ"))

    facebook_id = page["facebook_id"]
    rows.append(("Facebook Page ID", "Đã lưu" if facebook_id else "Chưa nhập",
                 "#facebook-page-id", "Mở thông tin Fanpage"))
    check_status = "Lưu Page ID để kiểm tra"
    if facebook_id:
        check = db.execute(
            "SELECT passed FROM facebook_checks WHERE page_id = ? AND facebook_id = ?",
            (page["id"], facebook_id),
        ).fetchone()
        if check is None:
            check_status = "Chưa kiểm tra"
        elif check["passed"]:
            check_status = "Đã xác minh Page ID ở lần kiểm tra gần nhất"
        else:
            check_status = "Lần kiểm tra gần nhất chưa đạt"
    rows.append(("Kết nối Facebook", check_status, "#facebook", "Xem kết nối"))

    body = "".join(
        f'<tr><th scope="row">{escape(title)}</th><td>{escape(status)}</td>'
        f'<td><a href="{target}" aria-label="{escape(f"{link} · {title}")}">{link}</a></td></tr>'
        for title, status, target, link in rows
    )
    return f"""
        <section id="page-onboarding" aria-labelledby="page-onboarding-heading">
            <h2 id="page-onboarding-heading">Thiết lập Fanpage</h2>
            <div class="table-wrap"><table>
                <thead><tr><th scope="col">Hạng mục</th><th scope="col">Tình trạng</th>
                    <th scope="col">Cài đặt</th></tr></thead>
                <tbody>{body}</tbody>
            </table></div>
        </section>
    """


def settings(db, page):
    page_id = page["id"]
    states = options(profiles.PAGE_STATES.items(), page["state"])
    templates = template_options(db, "Chọn mẫu")
    return f"""
        {onboarding(db, page)}
        <section>
            <nav aria-label="Thao tác Fanpage">
                <a href="/?page_id={page_id}#posts">Xem bài viết</a>
                <a href="/calendar?page_id={page_id}">Xem lịch đăng</a>
                <a href="/trends?page_id={page_id}">Xem Radar xu hướng</a>
            </nav>
            <form method="post" action="/pages/settings">
                <input type="hidden" name="page_id" value="{page_id}">
                <div class="form-row">
                    <label>Tên Fanpage <input name="name" required maxlength="120" value="{escape(page['name'])}"></label>
                    <label>Nhóm <input name="category" maxlength="80" value="{escape(page['category'])}"></label>
                    <label>Facebook Page ID <input id="facebook-page-id" name="facebook_id" inputmode="numeric" maxlength="32" value="{escape(page['facebook_id'] or '')}"></label>
                    <label>Trạng thái <select name="state">{states}</select></label>
                </div>
                <p>Tạm dừng giữ lịch đã lưu và chặn lịch mới. Lưu trữ cũng chặn tạo bản nháp và phiếu mới. Có thể kích hoạt lại trong phần trạng thái.</p>
                <div class="profile-fields">{profiles.profile_fields(page)}</div>
                <button>Lưu cấu hình</button>
            </form>
        </section>
        <section>
            <h2>Mẫu cấu hình</h2>
            <form class="form-row" method="post" action="/pages/templates">
                <input type="hidden" name="page_id" value="{page_id}">
                <label>Tên mẫu mới <input name="template_name" required maxlength="120"></label>
                <button>Lưu cấu hình hiện tại làm mẫu</button>
            </form>
            <form class="form-row" method="post" action="/pages/apply-template">
                <input type="hidden" name="page_id" value="{page_id}">
                <label>Mẫu áp dụng <select name="template_id" required>{templates}</select></label>
                <button>Thay quy tắc nội dung bằng mẫu</button>
            </form>
        </section>
    """
