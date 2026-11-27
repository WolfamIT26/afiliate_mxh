import re
from email import policy
from email.parser import BytesParser
from html import escape
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs

import reel_media
import reel_review
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
        with reel_media.checked_upload(data) as asset:
            with database() as db:
                previous = reel_media.attach(db, query_value(environ, "scene_id"), asset)
        reel_media.discard(previous)
    except ValueError as error:
        return response(
            start_response, "400 Bad Request",
            f'<p>{escape(str(error))}</p><a href="/">Về dashboard</a>',
        )
    except OSError:
        return response(start_response, "503 Service Unavailable", "Không thể lưu clip.")
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
    reel_media.discard(row["filename"])
    return response(start_response, "303 See Other", "", [("Location", "/")])


def generate_preview(environ, start_response, database, response):
    try:
        post_id = reel_review.generate(
            database, query_value(environ, "post_id"), query_value(environ, "revision")
        )
    except ValueError as error:
        return response(
            start_response, "400 Bad Request",
            f'<p>{escape(str(error))}</p><a href="/">Về dashboard</a>',
        )
    except (OSError, ReelRenderError):
        return response(
            start_response, "503 Service Unavailable",
            '<p>Chưa thể dựng Reel. Kiểm tra tệp nguồn và FFmpeg.</p><a href="/">Về dashboard</a>',
        )
    return response(
        start_response, "303 See Other", "", [("Location", f"/reels/review?post_id={post_id}")]
    )


def preview_video(environ, start_response, database, response):
    with database() as db:
        post, _, revision = reel_review.snapshot(db, query_value(environ, "post_id"))
        review = None
        if post and revision == query_value(environ, "revision"):
            review = reel_review.current(db, post["id"], revision)
    if review is None:
        return response(start_response, "404 Not Found", "Chưa có bản xem trước cho bản Reel hiện tại.")
    return stream_video(environ, start_response, response, reel_media.media_path(review["filename"]))


def file_chunks(path, offset, remaining):
    with path.open("rb") as source:
        source.seek(offset)
        while remaining:
            chunk = source.read(min(remaining, 65536))
            if not chunk:
                return
            remaining -= len(chunk)
            yield chunk


def stream_video(environ, start_response, response, path, disposition=None):
    try:
        size = path.stat().st_size
    except OSError:
        return response(start_response, "404 Not Found", "Không tìm thấy bản Reel.")
    start, end = 0, size - 1
    status = "200 OK"
    headers = [
        ("Content-Type", "video/mp4"), ("Accept-Ranges", "bytes"),
        ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"),
    ]
    if disposition:
        headers.append(("Content-Disposition", disposition))
    byte_range = re.fullmatch(r"bytes=(\d{0,20})-(\d{0,20})", environ.get("HTTP_RANGE", ""))
    if byte_range and any(byte_range.groups()):
        first, last = byte_range.groups()
        if first:
            start = int(first)
            if last:
                end = min(end, int(last))
        else:
            start = max(0, size - int(last))
        if start > end:
            return response(start_response, "416 Range Not Satisfiable", "",
                            [("Content-Range", f"bytes */{size}")])
        status = "206 Partial Content"
        headers.append(("Content-Range", f"bytes {start}-{end}/{size}"))
    length = end - start + 1
    headers.append(("Content-Length", str(length)))
    start_response(status, headers)
    return file_chunks(path, start, length)


def export(environ, start_response, database, response):
    post_id = query_value(environ, "post_id")
    requested_revision = query_value(environ, "revision")
    with database() as db:
        post, rows, revision = reel_review.snapshot(db, post_id)
        review = reel_review.current(db, post["id"], revision) if rows else None
    if requested_revision and (requested_revision != revision or review is None):
        return response(
            start_response, "400 Bad Request",
            '<p>Bản xem trước đã thay đổi. Mở lại trang kiểm tra Reel.</p><a href="/">Về dashboard</a>',
        )
    if not rows or any(not row["filename"] for row in rows):
        return response(
            start_response, "400 Bad Request",
            '<p>Cần một clip cho mỗi cảnh trước khi dựng Reel.</p><a href="/">Về dashboard</a>',
        )
    disposition = f'attachment; filename="reel-{post["id"]}.mp4"'
    if review:
        return stream_video(
            environ, start_response, response, reel_media.media_path(review["filename"]), disposition
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
        ("Content-Disposition", disposition),
        ("Content-Length", str(len(content))),
        ("X-Content-Type-Options", "nosniff"),
        ("Cache-Control", "no-store"),
    ])
    return [content]
