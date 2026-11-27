import csv
from html import escape
from io import StringIO
from urllib.parse import urlencode, urlsplit

from workflow import options

PLATFORMS = {
    "": "Chưa phân loại",
    "shopee": "Shopee",
    "lazada": "Lazada",
    "tiktok_shop": "TikTok Shop",
    "other": "Khác",
}
PAGE_SIZE = 25
MAX_IMPORT_ROWS = 100
MAX_IMPORT_FORM_BYTES = 2 * 1024 * 1024
IMPORT_FIELDS = ("ten_san_pham", "link_affiliate", "san", "link_goc")


def initialize(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL UNIQUE
        )
    """)
    columns = {row["name"] for row in db.execute("PRAGMA table_info(products)")}
    if "platform" not in columns:
        db.execute("ALTER TABLE products ADD COLUMN platform TEXT NOT NULL DEFAULT ''")
    if "source_url" not in columns:
        db.execute("ALTER TABLE products ADD COLUMN source_url TEXT NOT NULL DEFAULT ''")


def validate_url(value, label):
    error = f"Nhập {label} theo định dạng HTTP hoặc HTTPS hợp lệ."
    if len(value) > 2048 or any(char.isspace() or ord(char) < 32 or char == "\\" for char in value):
        raise ValueError(error)
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ValueError(error) from None
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or port == 0):
        raise ValueError(error)
    return value


def source_fields(fields):
    platform = fields.get("platform", "")
    if platform not in PLATFORMS:
        raise ValueError("Chọn sàn có trong danh sách.")
    source = fields.get("source_url", "").strip()
    return platform, validate_url(source, "link sản phẩm gốc") if source else ""


def add_product(db, fields):
    name = fields.get("name", "").strip()
    if not 1 <= len(name) <= 160:
        raise ValueError("Tên sản phẩm cần từ 1 đến 160 ký tự.")
    affiliate_url = validate_url(fields.get("url", "").strip(), "link affiliate")
    platform, source = source_fields(fields)
    result = db.execute(
        "INSERT INTO products(name, url, platform, source_url) VALUES (?, ?, ?, ?) ON CONFLICT(url) DO NOTHING",
        (name, affiliate_url, platform, source),
    )
    if result.rowcount != 1:
        raise ValueError("Link affiliate này đã có trong kho.")
    if fields.get("return_to") == "catalog":
        return f"/products#product-{result.lastrowid}"


def import_products(db, fields):
    content = fields.get("rows", "").lstrip("\ufeff").strip()
    if not content:
        raise ValueError("Dán danh sách sản phẩm trước khi nhập.")
    delimiter = "\t" if "\t" in content.splitlines()[0] else ","
    reader = csv.reader(StringIO(content, newline=""), delimiter=delimiter, strict=True)
    platform_aliases = {label.casefold(): code for code, label in PLATFORMS.items()}
    imported = 0
    try:
        for row in reader:
            values = [cell.strip() for cell in row]
            if not any(values):
                continue
            if reader.line_num == 1 and tuple(values) == IMPORT_FIELDS[:len(values)] and len(values) >= 2:
                continue
            if not 2 <= len(values) <= len(IMPORT_FIELDS):
                raise ValueError(f"Dòng {reader.line_num} cần từ 2 đến 4 cột.")
            if imported == MAX_IMPORT_ROWS:
                raise ValueError(f"Mỗi lượt nhập tối đa {MAX_IMPORT_ROWS} sản phẩm.")
            product = dict(zip(("name", "url", "platform", "source_url"), values))
            platform = product.get("platform", "").casefold()
            product["platform"] = platform_aliases.get(platform, platform)
            try:
                add_product(db, product)
            except ValueError as error:
                raise ValueError(f"Dòng {reader.line_num}. {error}") from None
            imported += 1
    except csv.Error:
        raise ValueError(f"Định dạng CSV hoặc TSV chưa đúng ở dòng {reader.line_num}.") from None
    if not imported:
        raise ValueError("Danh sách chưa có sản phẩm.")
    return f"/products?imported={imported}#catalog-import"


def update_source(db, fields):
    platform, source = source_fields(fields)
    submitted_id = fields.get("id")
    result = db.execute("UPDATE products SET platform = ?, source_url = ? WHERE id = ?",
                        (platform, source, submitted_id))
    if result.rowcount != 1:
        raise ValueError("Không tìm thấy sản phẩm.")
    product_id = db.execute("SELECT id FROM products WHERE id = ?", (submitted_id,)).fetchone()["id"]
    newer = db.execute("SELECT COUNT(*) FROM products WHERE id > ?", (product_id,)).fetchone()[0]
    return f"/products?p={newer // PAGE_SIZE + 1}#product-{product_id}"


def source_inputs(platform="", source=""):
    return f"""
        <label>Sàn <select name="platform">{options(PLATFORMS.items(), platform)}</select></label>
        <label>Link sản phẩm gốc <input name="source_url" type="url" maxlength="2048"
            value="{escape(source)}"></label>
    """


def add_form(*, show_source=False):
    return f"""
        <form method="post" action="/products">
            <label>Tên sản phẩm <input name="name" required maxlength="160"></label>
            <label>Link affiliate <input name="url" type="url" required maxlength="2048"></label>
            {source_inputs() if show_source else ""}
            {'<input type="hidden" name="return_to" value="catalog">' if show_source else ""}
            <button>Lưu sản phẩm</button>
        </form>
    """


def section(db):
    rows = "".join(
        f'<li><a href="{escape(row["url"])}" rel="noreferrer">{escape(row["name"])}</a></li>'
        for row in db.execute("SELECT name, url FROM products ORDER BY id DESC LIMIT 5")
    )
    return f"""
        <section><h2>Kho sản phẩm affiliate</h2>
        <p><a href="/products">Mở kho sản phẩm</a></p>
        {f'<ul>{rows}</ul>' if rows else ''}
        {add_form()}</section>
    """


def directory(db, filters):
    query = filters.get("q", [""])[-1].strip()[:160]
    platform = filters.get("platform", ["all"])[-1]
    if platform not in PLATFORMS:
        platform = "all"
    try:
        number = max(int(filters.get("p", ["1"])[-1]), 1)
    except ValueError:
        number = 1
    db.create_function("casefold", 1, str.casefold, deterministic=True)
    where = """
        WHERE (? = 'all' OR platform = ?)
            AND (? = '' OR instr(casefold(name), ?) > 0 OR instr(casefold(url), ?) > 0
                OR instr(casefold(source_url), ?) > 0)
    """
    term = query.casefold()
    values = (platform, platform, term, term, term, term)
    total = db.execute("SELECT COUNT(*) FROM products " + where, values).fetchone()[0]
    last = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    number = min(number, last)
    products = db.execute(
        "SELECT id, name, url, platform, source_url FROM products " + where + " ORDER BY id DESC LIMIT ? OFFSET ?",
        (*values, PAGE_SIZE, (number - 1) * PAGE_SIZE),
    ).fetchall()
    filters_html = options([("all", "Tất cả sàn"), *PLATFORMS.items()], platform)
    links = []
    for page, label in ((number - 1, "Trang trước"), (number + 1, "Trang sau")):
        if 1 <= page <= last:
            params = escape(urlencode({"q": query, "platform": platform, "p": page}))
            links.append(f'<a href="/products?{params}">{label}</a>')
    pagination = f'<nav aria-label="Trang sản phẩm">Trang {number}/{last} {" ".join(links)}</nav>' if last > 1 else ""
    return f"""
        <section><h2>Thêm sản phẩm</h2>{add_form(show_source=True)}</section>
        {import_section(filters)}
        <section><h2>Danh sách sản phẩm</h2>
            <form method="get" action="/products" class="form-row" role="search">
                <label>Tìm theo tên hoặc link <input type="search" name="q" maxlength="160"
                    value="{escape(query)}"></label>
                <label>Lọc theo sàn <select name="platform">{filters_html}</select></label>
                <button>Lọc sản phẩm</button>
                <a href="/products">Xóa bộ lọc</a>
            </form>
            <p>{total} sản phẩm</p>
            {''.join(product_card(row) for row in products) if products else '<p>Không có sản phẩm phù hợp.</p>'}
            {pagination}
        </section>
    """


def import_section(filters):
    try:
        count = int(filters.get("imported", ["0"])[-1])
    except ValueError:
        count = 0
    message = f'<p role="status">Đã nhập {count} sản phẩm.</p>' if 0 < count <= MAX_IMPORT_ROWS else ""
    return f"""
        <section id="catalog-import">
            <details {'open' if message else ''}>
                <summary>Nhập nhiều sản phẩm</summary>
                {message}
                <p>Dán tối đa {MAX_IMPORT_ROWS} dòng từ bảng tính hoặc CSV theo thứ tự
                    tên sản phẩm, link affiliate, sàn, link gốc. Hai cột cuối có thể để trống.
                    Nếu dữ liệu vượt 2 MB, hãy chia thành nhiều lượt.</p>
                <form method="post" action="/products/import">
                    <label>Danh sách sản phẩm
                        <textarea name="rows" rows="5" cols="65" required aria-describedby="import-header"></textarea>
                    </label>
                    <p id="import-header">Nếu có dòng tiêu đề, dùng <code>{",".join(IMPORT_FIELDS)}</code>.</p>
                    <button>Nhập vào kho</button>
                </form>
            </details>
        </section>
    """


def product_card(product):
    product_id = product["id"]
    source = product["source_url"]
    source_link = f'<a href="{escape(source)}" rel="noreferrer">Mở link sản phẩm gốc</a>' if source else ""
    affiliate_url = escape(product["url"])
    return f"""
        <article id="product-{product_id}">
            <h3>{escape(product["name"])}</h3>
            <p>{PLATFORMS[product["platform"]]}</p>
            <p>Link affiliate<br><a href="{affiliate_url}" rel="noreferrer">{affiliate_url}</a></p>
            {source_link}
            <details><summary>Cập nhật sàn và link gốc</summary>
                <form method="post" action="/products/source">
                    <input type="hidden" name="id" value="{product_id}">
                    {source_inputs(product["platform"], source)}
                    <button>Lưu nguồn sản phẩm</button>
                </form>
            </details>
        </article>
    """
