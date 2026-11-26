import os
import sqlite3
from contextlib import contextmanager
from html import escape
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

import catalog
import workflow

DATABASE = os.environ.get("AFFILIATE_DB", "affiliate.sqlite3")
SEED_PAGES = ("Trạm AI", "Tủ Đồ Hay", "Có Gì Hay")


@contextmanager
def database():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize():
    with database() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS pages (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE
            )
        """)
        db.executemany("INSERT OR IGNORE INTO pages(name) VALUES (?)",
                       [(name,) for name in SEED_PAGES])
        catalog.initialize(db)
        workflow.initialize(db)


def page_section(db):
    items = "".join(f"<li>{escape(row['name'])}</li>"
                    for row in db.execute("SELECT name FROM pages ORDER BY id"))
    return f"""
        <section><h2>Fanpage</h2><ul>{items}</ul>
        <form method="post" action="/pages">
            <label>Tên Fanpage <input name="name" required maxlength="120"></label>
            <button>Thêm Fanpage</button>
        </form></section>
    """


def add_page(db, fields):
    name = fields.get("name", "").strip()
    if not 1 <= len(name) <= 120:
        raise ValueError("Tên Fanpage cần từ 1 đến 120 ký tự.")
    db.execute("INSERT INTO pages(name) VALUES (?)", (name,))


def render(db):
    return page_section(db) + catalog.section(db) + workflow.section(db)


ACTIONS = {
    "/pages": add_page,
    "/products": catalog.add_product,
    "/posts": workflow.add_post,
    "/posts/approve": workflow.approve,
    "/posts/schedule": workflow.schedule,
}


def response(start_response, status, content, headers=()):
    start_response(status, [("Content-Type", "text/html; charset=utf-8"), *headers])
    return [content.encode("utf-8")]


def application(environ, start_response):
    path = environ["PATH_INFO"]
    method = environ["REQUEST_METHOD"]
    if method == "GET" and path == "/":
        with database() as db:
            content = render(db)
        return response(start_response, "200 OK", f"""<!doctype html>
<html lang="vi"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Affiliate MXH</title>
<style>
body {{ margin: 2rem auto; padding: 0 1rem; max-width: 64rem; background: #f2f5f2;
        color: #142b22; font: 1rem/1.5 system-ui, sans-serif; }}
section {{ background: white; padding: 1.25rem; border-radius: .75rem; margin-bottom: 1rem; }}
h2 {{ margin-top: 0; }} label {{ display: block; margin-bottom: .75rem; }}
input, select, textarea, button {{ font: inherit; padding: .4rem; max-width: 100%; }}
button {{ color: white; background: #18563f; border: 0; border-radius: .3rem; cursor: pointer; }}
article {{ border-top: 1px solid #d5ddd8; padding: .75rem 0; overflow-wrap: anywhere; }}
</style>
<main><h1>Affiliate MXH</h1>{content}</main></html>""")

    if method == "POST" and path in ACTIONS:
        try:
            length = int(environ.get("CONTENT_LENGTH") or 0)
            if not 0 <= length <= 65536:
                return response(start_response, "413 Content Too Large", "Dữ liệu quá lớn.")
            form = environ["wsgi.input"].read(length).decode("utf-8")
            fields = {key: values[-1] for key, values in parse_qs(form).items()}
            with database() as db:
                ACTIONS[path](db, fields)
        except (ValueError, sqlite3.IntegrityError) as error:
            message = str(error) if isinstance(error, ValueError) else "Dữ liệu bị trùng hoặc không hợp lệ."
            return response(start_response, "400 Bad Request",
                            f'<p>{escape(message)}</p><a href="/">Về trang chính</a>')
        return response(start_response, "303 See Other", "", [("Location", "/")])
    return response(start_response, "404 Not Found", "Không tìm thấy trang.")


if __name__ == "__main__":
    initialize()
    with make_server("127.0.0.1", int(os.environ.get("PORT", "8080")), application) as server:
        print(f"http://127.0.0.1:{server.server_port}", flush=True)
        server.serve_forever()
