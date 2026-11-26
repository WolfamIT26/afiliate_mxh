from html import escape

FIELDS = (
    ("audience", "Đối tượng người xem", 500),
    ("voice", "Giọng văn", 500),
    ("cadence", "Ghi chú lịch đăng", 500),
)


def initialize(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS page_profiles (
            page_id INTEGER PRIMARY KEY REFERENCES pages(id) ON DELETE CASCADE,
            audience TEXT NOT NULL DEFAULT '',
            voice TEXT NOT NULL DEFAULT '',
            cadence TEXT NOT NULL DEFAULT ''
        )
    """)


def save(db, fields):
    page_id = fields.get("page_id")
    if db.execute("SELECT 1 FROM pages WHERE id = ?", (page_id,)).fetchone() is None:
        raise ValueError("Không tìm thấy Fanpage.")
    values = []
    for name, label, limit in FIELDS:
        value = fields.get(name, "").strip()
        if len(value) > limit:
            raise ValueError(f"{label} chỉ được tối đa {limit} ký tự.")
        values.append(value)
    db.execute("""
        INSERT INTO page_profiles(page_id, audience, voice, cadence)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(page_id) DO UPDATE SET
            audience = excluded.audience,
            voice = excluded.voice,
            cadence = excluded.cadence
    """, (page_id, *values))


def page_item(page):
    fields = "".join(
        f'<label>{label}<br><textarea name="{name}" rows="2" maxlength="{limit}">'
        f'\n{escape(page[name] or "")}</textarea></label>'
        for name, label, limit in FIELDS
    )
    name = escape(page["name"])
    return f"""
        <li><details>
            <summary>{name}</summary>
            <form method="post" action="/pages/profile" aria-label="Hồ sơ {name}">
                <input type="hidden" name="page_id" value="{page['id']}">
                {fields}
                <button>Lưu hồ sơ</button>
            </form>
        </details></li>
    """


def page_items(db):
    pages = db.execute("""
        SELECT pages.id, pages.name, page_profiles.audience,
               page_profiles.voice, page_profiles.cadence
        FROM pages LEFT JOIN page_profiles ON page_profiles.page_id = pages.id
        ORDER BY pages.id
    """)
    return "".join(page_item(page) for page in pages)
