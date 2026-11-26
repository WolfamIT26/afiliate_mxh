from email import policy
from email.parser import BytesParser
from html import escape
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs

import reel_media
from reel_render import ReelRenderError, render_reel


def query_value(environ, key):
    return parse_qs(environ.get("QUERY_STRING", "")).get(key, [""])[-1]


def upload(environ, start_response, database, response):
    content_type = environ.get("CONTENT_TYPE", "")
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
        if not 0 < length <= reel_media.MAX_UPLOAD_BYTES + 16384:
            return response(start_response, "413 Content Too Large", "Tệp vượt giới hạn tải lên.")
        if not content_type.lower().startswith("multipart/form-data;") or any(
            char in content_type for char in "\r\n"
        ):
            raise ValueError("Chọn một tệp MP4.")
        body = environ["wsgi.input"].read(length)
        message = BytesParser(policy=policy.default).parsebytes(
            b"Content-Type: " + content_type.encode("ascii") + b"\r\n\r\n" + body
        )
        parts = list(message.iter_parts())
        if len(body) != length or message.defects or len(parts) != 1:
            raise ValueError("Mỗi lần tải lên cần đúng một tệp MP4.")
        part = parts[0]
        if part.get_param("name", header="content-disposition") != "clip":
            raise ValueError("Chọn một tệp MP4.")
        data = part.get_payload(decode=True)
        if not data:
            raise ValueError("Tệp tải lên trống.")
        with database() as db:
            reel_media.attach(db, query_value(environ, "scene_id"), data)
    except ValueError as error:
        return response(
            start_response, "400 Bad Request",
            f'<p>{escape(str(error))}</p><a href="/">Về dashboard</a>',
        )
    return response(start_response, "303 See Other", "", [("Location", "/")])


def remove(environ, start_response, database, response):
    with database() as db:
        row = db.execute("""
            DELETE FROM scene_assets
            WHERE scene_id = ? AND scene_id IN (
                SELECT reel_scenes.id FROM reel_scenes
                JOIN posts ON posts.id = reel_scenes.post_id WHERE posts.status = 'draft'
            )
            RETURNING filename
        """, (query_value(environ, "scene_id"),)).fetchone()
    if row is None:
        return response(start_response, "400 Bad Request", "Chỉ gỡ được clip trong bản nháp.")
    reel_media.media_path(row["filename"]).unlink(missing_ok=True)
    return response(start_response, "303 See Other", "", [("Location", "/")])


def export(environ, start_response, database, response):
    with database() as db:
        rows = db.execute("""
            SELECT reel_scenes.post_id, scene_assets.filename
            FROM reel_scenes LEFT JOIN scene_assets ON scene_assets.scene_id = reel_scenes.id
            WHERE reel_scenes.post_id = ? ORDER BY reel_scenes.position
        """, (query_value(environ, "post_id"),)).fetchall()
    if not rows or any(not row["filename"] for row in rows):
        return response(
            start_response, "400 Bad Request",
            '<p>Cần một clip cho mỗi cảnh trước khi dựng Reel.</p><a href="/">Về dashboard</a>',
        )

    try:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "reel.mp4"
            render_reel([reel_media.media_path(row["filename"]) for row in rows], output)
            content = output.read_bytes()
    except (OSError, ReelRenderError):
        return response(
            start_response, "503 Service Unavailable",
            '<p>Chưa thể dựng Reel. Kiểm tra tệp nguồn và FFmpeg.</p><a href="/">Về dashboard</a>',
        )
    start_response("200 OK", [
        ("Content-Type", "video/mp4"),
        ("Content-Disposition", f'attachment; filename="reel-{rows[0]["post_id"]}.mp4"'),
        ("Content-Length", str(len(content))),
        ("X-Content-Type-Options", "nosniff"),
        ("Cache-Control", "no-store"),
    ])
    return [content]
