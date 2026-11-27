from html import escape
import json

FIELDS = (
    ("audience", "Đối tượng người xem", 500),
    ("voice", "Giọng văn", 500),
    ("cadence", "Lịch và tần suất đăng", 500),
    ("topics", "Chủ đề và series", 1000),
    ("formats", "Định dạng nội dung", 500),
    ("sources", "Nguồn tư liệu và dữ liệu", 1000),
    ("cta", "Mẫu CTA", 500),
    ("ai_prompt", "Hướng dẫn cho AI", 4000),
    ("review_rules", "Quy tắc kiểm duyệt", 4000),
    ("support_rules", "Quy tắc chăm sóc khách hàng", 4000),
    ("logo_url", "Đường dẫn logo", 1000),
    ("brand_colors", "Màu thương hiệu", 250),
)
PROFILE_KEYS = tuple(key for key, _, _ in FIELDS)
TEMPLATE_KEYS = PROFILE_KEYS[:-2]
PAGE_STATES = {"active": "Đang hoạt động", "paused": "Tạm dừng", "archived": "Đã lưu trữ"}
STARTER_PAGES = {
    "Trạm AI": ("Công nghệ & dịch vụ AI", {
        "topics": "Hướng dẫn công cụ AI và thông tin gói đã xác minh.",
        "formats": "Poster 4:5 do người dùng tải lên. Có thể dùng poster đã duyệt làm tư liệu Reel.",
        "review_rules": "Chỉ đăng bài bán khi có nguồn, điều kiện, giá và thời hạn gói đã xác minh.",
    }),
    "Tủ Đồ Hay": ("Thời trang", {
        "topics": "Hai cách phối đồ theo dịp, màu hoặc phom.",
        "formats": "Reel dọc phối đồ. Đối chiếu ảnh mẫu với ảnh shop.",
        "review_rules": "Chốt sản phẩm, biến thể và ảnh shop trước. Đối chiếu màu, phom, chi tiết và từng link.",
    }),
    "Có Gì Hay": ("Đồ tiện ích", {
        "topics": "Demo món giúp giải quyết một vấn đề cụ thể.",
        "formats": "Reel 9:16, 15–25 giây, theo mạch vấn đề → cách dùng → lưu ý mua.",
        "review_rules": "Kiểm tra link từng món, gắn nhãn minh họa và giãn tối thiểu 7 ngày giữa hai bài cùng món.",
    }),
}


def initialize(db):
    db.execute("CREATE TABLE IF NOT EXISTS pages (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE)")
    page_columns = {row["name"] for row in db.execute("PRAGMA table_info(pages)")}
    first_setup = "state" not in page_columns
    for key, definition in {
        "state": "TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'paused', 'archived'))",
        "category": "TEXT NOT NULL DEFAULT ''",
        "facebook_id": "TEXT",
    }.items():
        if key not in page_columns:
            db.execute(f"ALTER TABLE pages ADD COLUMN {key} {definition}")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS pages_facebook_id ON pages(facebook_id)")
    db.execute("""
        CREATE TABLE IF NOT EXISTS page_profiles (
            page_id INTEGER PRIMARY KEY REFERENCES pages(id) ON DELETE CASCADE
        )
    """)
    profile_columns = {row["name"] for row in db.execute("PRAGMA table_info(page_profiles)")}
    for key in PROFILE_KEYS:
        if key not in profile_columns:
            db.execute(f"ALTER TABLE page_profiles ADD COLUMN {key} TEXT NOT NULL DEFAULT ''")
    db.execute("""
        CREATE TABLE IF NOT EXISTS page_templates (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL COLLATE NOCASE UNIQUE,
            category TEXT NOT NULL,
            content TEXT NOT NULL
        )
    """)
    if first_setup:
        for name, (category, content) in STARTER_PAGES.items():
            db.execute("INSERT OR IGNORE INTO pages(name) VALUES (?)", (name,))
            page = db.execute("SELECT id FROM pages WHERE name = ?", (name,)).fetchone()
            db.execute("UPDATE pages SET category = ? WHERE id = ?", (category, page["id"]))
            write_profile(db, page["id"], content)


def get(db, page_id):
    return db.execute("""
        SELECT pages.*, page_profiles.*
        FROM pages LEFT JOIN page_profiles ON page_profiles.page_id = pages.id
        WHERE pages.id = ?
    """, (page_id,)).fetchone()


def require_page(db, page_id):
    page = get(db, page_id)
    if page is None:
        raise ValueError("Không tìm thấy Fanpage.")
    return page


def write_profile(db, page_id, values):
    if not values:
        return
    keys = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    updates = ", ".join(f"{key} = excluded.{key}" for key in values)
    db.execute(f"""
        INSERT INTO page_profiles(page_id, {keys}) VALUES (?, {placeholders})
        ON CONFLICT(page_id) DO UPDATE SET {updates}
    """, (page_id, *values.values()))


def save(db, fields):
    page = require_page(db, fields.get("page_id"))
    values = {}
    for key, label, limit in FIELDS:
        if key in fields:
            value = fields[key].strip()
            if len(value) > limit:
                raise ValueError(f"{label} cần tối đa {limit} ký tự.")
            values[key] = value
    write_profile(db, page["id"], values)


def template_choices(db):
    return db.execute("SELECT id, name FROM page_templates ORDER BY name, id").fetchall()


def find_template(db, template_id):
    template = db.execute("SELECT * FROM page_templates WHERE id = ?", (template_id,)).fetchone()
    if template is None:
        raise ValueError("Không tìm thấy mẫu Fanpage.")
    return template


def save_template(db, fields):
    page = require_page(db, fields.get("page_id"))
    name = fields.get("template_name", "").strip()
    if not 1 <= len(name) <= 120:
        raise ValueError("Tên mẫu cần từ 1 đến 120 ký tự.")
    values = {key: page[key] or "" for key in TEMPLATE_KEYS}
    db.execute("INSERT INTO page_templates(name, category, content) VALUES (?, ?, ?)",
               (name, page["category"], json.dumps(values, ensure_ascii=False)))


def apply_template(db, page_id, template):
    content = json.loads(template["content"])
    db.execute("UPDATE pages SET category = ? WHERE id = ?", (template["category"], page_id))
    write_profile(db, page_id, {key: content.get(key, "") for key in TEMPLATE_KEYS})


def profile_fields(page):
    return "".join(
        f'<label>{label}<textarea id="profile-{key}" name="{key}" maxlength="{limit}" rows="2">'
        f'{escape(page[key] or "")}</textarea></label>'
        for key, label, limit in FIELDS
    )
