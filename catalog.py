from html import escape
from urllib.parse import urlsplit


def initialize(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL UNIQUE
        )
    """)


def add_product(db, fields):
    name = fields.get("name", "").strip()
    url = fields.get("url", "").strip()
    parsed = urlsplit(url)
    if not 1 <= len(name) <= 160:
        raise ValueError("Tên sản phẩm cần từ 1 đến 160 ký tự.")
    if (len(url) > 2048 or parsed.scheme not in {"http", "https"}
            or not parsed.hostname or parsed.username is not None
            or any(character.isspace() or ord(character) < 32 for character in url)):
        raise ValueError("Nhập một link affiliate HTTP hoặc HTTPS hợp lệ.")
    db.execute("INSERT INTO products(name, url) VALUES (?, ?)", (name, url))


def section(db):
    rows = "".join(
        f'<li><a href="{escape(row["url"])}" rel="noreferrer">{escape(row["name"])}</a></li>'
        for row in db.execute("SELECT name, url FROM products ORDER BY id DESC")
    )
    return f"""
        <section><h2>Kho sản phẩm affiliate</h2><ul>{rows}</ul>
        <form method="post" action="/products">
            <label>Tên sản phẩm <input name="name" required maxlength="160"></label>
            <label>Link affiliate <input name="url" type="url" required maxlength="2048"></label>
            <button>Lưu sản phẩm</button>
        </form></section>
    """
