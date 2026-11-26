import json
import os
import sqlite3
from contextlib import contextmanager
from html import escape
from pathlib import Path
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

import activity
import catalog
import profiles
import reels
import reel_media
import media_routes
import tasks
import workflow

DATABASE = os.environ.get("AFFILIATE_DB", "affiliate.sqlite3")
SEED_PAGES = ("Trạm AI", "Tủ Đồ Hay", "Có Gì Hay")
PLAYBOOK_PATH = Path(__file__).resolve().parent / "docs" / "agent-playbook.md"


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
        profiles.initialize(db)
        catalog.initialize(db)
        workflow.initialize(db)
        reels.initialize(db)
        reel_media.initialize(db)
        activity.initialize(db)
        tasks.initialize(db)


def page_section(db):
    items = profiles.page_items(db)
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


def render(db, filters=None):
    return (
        tasks.section(db, filters) + activity.section(db) + page_section(db)
        + catalog.section(db) + workflow.section(db, filters)
    )


ACTIONS = {
    "/tasks": tasks.create,
    "/tasks/advance": tasks.advance,
    "/pages": add_page,
    "/pages/profile": profiles.save,
    "/products": catalog.add_product,
    "/posts": workflow.add_post,
    "/reels/scenes": reels.add_scene,
    "/reels/scenes/edit": reels.edit_scene,
    "/reels/scenes/move": reels.move_scene,
    "/reels/scenes/delete": reels.delete_scene,
    "/posts/approve": workflow.approve,
    "/posts/schedule": workflow.schedule,
}


def response(start_response, status, content, headers=(), content_type="text/html; charset=utf-8"):
    start_response(status, [("Content-Type", content_type), *headers])
    return [content.encode("utf-8")]


def application(environ, start_response):
    path = environ["PATH_INFO"]
    method = environ["REQUEST_METHOD"]
    if method == "GET" and path in ("/", "/knowledge"):
        if path == "/knowledge":
            page_title = "Sổ tay Agent"
            navigation = '<a href="/">Về dashboard</a>'
            playbook = escape(PLAYBOOK_PATH.read_text(encoding="utf-8"))
            content = f'<section><pre class="playbook">{playbook}</pre></section>'
        else:
            page_title = "Affiliate MXH"
            navigation = '<a href="/knowledge">Sổ tay Agent</a>'
            filters = parse_qs(environ.get("QUERY_STRING", ""))
            with database() as db:
                content = render(db, filters)
        return response(start_response, "200 OK", f"""<!doctype html>
<html lang="vi"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{page_title}</title>
<style>
body {{ margin: 2rem auto; padding: 0 1rem; max-width: 64rem; background: #f2f5f2;
        color: #142b22; font: 1rem/1.5 system-ui, sans-serif; }}
section {{ background: white; padding: 1.25rem; border-radius: .75rem; margin-bottom: 1rem; }}
nav {{ margin-bottom: 1rem; }}
.playbook {{ font: inherit; margin: 0; overflow-wrap: anywhere; white-space: pre-wrap; }}
h2 {{ margin-top: 0; }} label {{ display: block; margin-bottom: .75rem; }}
input, select, textarea, button {{ font: inherit; padding: .4rem; max-width: 100%; }}
button {{ color: white; background: #18563f; border: 0; border-radius: .3rem; cursor: pointer; }}
article {{ border-top: 1px solid #d5ddd8; padding: .75rem 0; overflow-wrap: anywhere; }}
</style>
<main><h1>{page_title}</h1><nav>{navigation}</nav>{content}</main></html>""")

    if method == "GET" and path == "/reels/brief":
        post_id = parse_qs(environ.get("QUERY_STRING", "")).get("post_id", [""])[-1]
        with database() as db:
            brief = workflow.reel_brief(db, post_id)
        if brief is None:
            return response(start_response, "404 Not Found", "Không tìm thấy bài viết.")
        return response(
            start_response, "200 OK", json.dumps(brief, ensure_ascii=False, indent=2) + "\n",
            [("Content-Disposition", f'attachment; filename="reel-brief-{brief["post_id"]}.json"'),
             ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff")],
            content_type="application/json; charset=utf-8",
        )

    if method == "POST" and path == "/reels/clip":
        return media_routes.upload(environ, start_response, database, response)
    if method == "POST" and path == "/reels/clip/remove":
        return media_routes.remove(environ, start_response, database, response)
    if method == "POST" and path == "/reels/render":
        return media_routes.export(environ, start_response, database, response)
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
