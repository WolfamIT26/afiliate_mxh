import json
import os
import sqlite3
from contextlib import contextmanager
from html import escape
from pathlib import Path
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

import activity
import calendar_view
import catalog
import facebook_connection
import office
import page_directory
import profiles
import reels
import reel_media
import reel_review
import media_routes
import tasks
import trend_radar
import workflow

DATABASE = os.environ.get("AFFILIATE_DB", "affiliate.sqlite3")
PLAYBOOK_PATH = Path(__file__).resolve().parent / "docs" / "agent-playbook.md"
NAVIGATION = (
    '<a href="/">Hôm nay</a><a href="/pages">Fanpage</a><a href="/calendar">Lịch đăng</a>'
    '<a href="/products">Sản phẩm</a><a href="/trends">Radar xu hướng</a>'
    '<a href="/office">Văn phòng 3D</a><a href="/knowledge">Sổ tay Agent</a>'
)


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
        db.execute("BEGIN IMMEDIATE")
        profiles.initialize(db)
        facebook_connection.initialize(db)
        catalog.initialize(db)
        workflow.initialize(db)
        trend_radar.initialize(db)
        reels.initialize(db)
        reel_media.initialize(db)
        reel_review.initialize(db)
        if db.execute("PRAGMA user_version").fetchone()[0] == 0:
            reel_review.migrate_page_identity(db)
            db.execute("PRAGMA user_version = 1")
        activity.initialize(db)
        tasks.initialize(db)


def render(db, filters=None):
    return (
        calendar_view.today(db) + workflow.section(db, filters) + tasks.section(db, filters)
        + catalog.section(db) + activity.section(db)
    )


ACTIONS = {
    "/tasks": tasks.create,
    "/tasks/advance": tasks.advance,
    "/pages": page_directory.create,
    "/pages/settings": page_directory.save,
    "/pages/bulk": page_directory.bulk_update,
    "/pages/profile": profiles.save,
    "/pages/templates": page_directory.save_template,
    "/pages/apply-template": page_directory.apply_template,
    "/pages/facebook-check": facebook_connection.check,
    "/products": catalog.add_product,
    "/products/import": catalog.import_products,
    "/products/source": catalog.update_source,
    "/posts": workflow.add_post,
    "/posts/edit": workflow.edit_post,
    "/trends": trend_radar.create,
    "/trends/draft": trend_radar.make_draft,
    "/reels/scenes": reels.add_scene,
    "/reels/scenes/edit": reels.edit_scene,
    "/reels/scenes/move": reels.move_scene,
    "/reels/scenes/delete": reels.delete_scene,
    "/reels/review/confirm": reel_review.confirm,
    "/posts/approve": workflow.approve,
    "/posts/schedule": workflow.schedule,
    "/posts/unschedule": workflow.cancel_schedule,
}


def response(start_response, status, content, headers=(), content_type="text/html; charset=utf-8"):
    start_response(status, [("Content-Type", content_type), *headers])
    return [content.encode("utf-8")]


def application(environ, start_response):
    path = environ["PATH_INFO"]
    method = environ["REQUEST_METHOD"]
    if method == "GET" and path in office.ASSETS:
        content = (office.ASSET_DIR / path.lstrip("/")).read_text(encoding="utf-8")
        return response(start_response, "200 OK", content, content_type=office.ASSETS[path])
    if method == "GET" and path in ("/office", "/office/tasks"):
        with database() as db:
            if path == "/office":
                return response(start_response, "200 OK", office.render(db))
            return response(
                start_response, "200 OK", json.dumps(office.task_snapshot(db), ensure_ascii=False),
                [("Cache-Control", "no-store")], content_type="application/json; charset=utf-8",
            )
    if method == "GET" and path in (
        "/", "/knowledge", "/reels/review", "/pages", "/pages/settings", "/calendar", "/products", "/trends",
    ):
        filters = parse_qs(environ.get("QUERY_STRING", ""))
        if path == "/knowledge":
            page_title = "Sổ tay Agent"
            playbook = escape(PLAYBOOK_PATH.read_text(encoding="utf-8"))
            content = f'<section><pre class="playbook">{playbook}</pre></section>'
        elif path == "/reels/review":
            page_title = "Kiểm tra Reel"
            with database() as db:
                post, scenes, revision = reel_review.snapshot(
                    db, media_routes.query_value(environ, "post_id")
                )
                if not scenes:
                    return response(start_response, "404 Not Found", "Không tìm thấy kế hoạch Reel.")
                review = reel_review.current(db, post["id"], revision)
            content = reel_review.section(post, scenes, revision, review)
        elif path == "/pages":
            page_title = "Quản lý Fanpage"
            with database() as db:
                content = page_directory.directory(db, filters)
        elif path == "/pages/settings":
            with database() as db:
                page = profiles.get(db, filters.get("page_id", [""])[-1])
                if page is None:
                    return response(start_response, "404 Not Found", "Không tìm thấy Fanpage.")
                page_title = page["name"]
                content = page_directory.settings(db, page) + facebook_connection.section(db, page)
        elif path == "/calendar":
            page_title = "Lịch đăng"
            with database() as db:
                content = calendar_view.calendar(db, filters)
        elif path == "/products":
            page_title = "Kho sản phẩm affiliate"
            with database() as db:
                content = catalog.directory(db, filters)
        elif path == "/trends":
            page_title = "Radar xu hướng"
            with database() as db:
                content = trend_radar.directory(db, filters)
        else:
            page_title = "Affiliate MXH"
            with database() as db:
                content = render(db, filters)
        return response(start_response, "200 OK", f"""<!doctype html>
<html lang="vi"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(page_title)}</title>
<style>
body {{ margin: 2rem auto; padding: 0 1rem; max-width: 64rem; background: #f2f5f2;
        color: #142b22; font: 1rem/1.5 system-ui, sans-serif; }}
section {{ background: white; padding: 1.25rem; border-radius: .75rem; margin-bottom: 1rem; }}
nav {{ margin-bottom: 1rem; display: flex; gap: .75rem; align-items: center; flex-wrap: wrap; }}
.playbook {{ font: inherit; margin: 0; overflow-wrap: anywhere; white-space: pre-wrap; }}
h2 {{ margin-top: 0; }} label {{ display: block; margin-bottom: .75rem; }}
input, select, textarea, button {{ font: inherit; padding: .4rem; max-width: 100%; }}
button {{ color: white; background: #18563f; border: 0; border-radius: .3rem; cursor: pointer; }}
article {{ border-top: 1px solid #d5ddd8; padding: .75rem 0; overflow-wrap: anywhere; }}
article:target {{ outline: 2px solid #18563f; padding-inline: .5rem; }}
.form-row {{ display: flex; gap: .75rem; flex-wrap: wrap; align-items: end; margin-block: .75rem; }}
.form-row label {{ margin: 0; }}
.form-row label :is(input, select) {{ display: block; max-width: 100%; }}
.profile-fields {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 16rem), 1fr)); gap: .75rem; }}
.profile-fields textarea {{ box-sizing: border-box; width: 100%; display: block; }}
.table-wrap {{ overflow-x: auto; }}
table {{ width: 100%; border-collapse: collapse; text-align: left; }}
th, td {{ border-bottom: 1px solid #d5ddd8; padding: .55rem; }}
</style>
<main><h1>{escape(page_title)}</h1><nav aria-label="Điều hướng chính">{NAVIGATION}</nav>{content}</main></html>""")

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
    if method == "POST" and path == "/reels/review/generate":
        return media_routes.generate_preview(environ, start_response, database, response)
    if method == "GET" and path == "/reels/review/video":
        return media_routes.preview_video(environ, start_response, database, response)
    if method == "POST" and path in ACTIONS:
        fields = {}
        try:
            length = int(environ.get("CONTENT_LENGTH") or 0)
            limit = catalog.MAX_IMPORT_FORM_BYTES if path == "/products/import" else 65536
            if not 0 <= length <= limit:
                return response(start_response, "413 Content Too Large", "Dữ liệu quá lớn.")
            form = environ["wsgi.input"].read(length).decode("utf-8")
            parsed = parse_qs(form, keep_blank_values=True)
            fields = {key: values[-1] for key, values in parsed.items()}
            if path == "/pages/bulk":
                fields["page_ids"] = parsed.get("page_ids", [])
            with database() as db:
                location = ACTIONS[path](db, fields) or "/"
        except (ValueError, sqlite3.IntegrityError) as error:
            message = str(error) if isinstance(error, ValueError) else "Dữ liệu bị trùng hoặc không hợp lệ."
            back = '<a href="/">Về trang chính</a>'
            if path.startswith("/products"):
                back = '<a href="/products">Về kho sản phẩm</a>'
            elif path.startswith("/trends"):
                back = '<a href="/trends">Về Radar xu hướng</a>'
            elif path in ("/posts/edit", "/posts/approve"):
                post_id = fields.get("id", "")
                if 1 <= len(post_id) <= 19 and post_id.isascii() and post_id.isdecimal():
                    back = f'<a href="/?post_id={post_id}#post-{post_id}">Mở lại bài viết</a>'
            return response(start_response, "400 Bad Request", f'<p>{escape(message)}</p>{back}')
        return response(start_response, "303 See Other", "", [("Location", location)])
    return response(start_response, "404 Not Found", "Không tìm thấy trang.")


if __name__ == "__main__":
    initialize()
    with make_server("127.0.0.1", int(os.environ.get("PORT", "8080")), application) as server:
        print(f"http://127.0.0.1:{server.server_port}", flush=True)
        server.serve_forever()
