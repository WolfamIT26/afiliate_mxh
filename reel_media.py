import json
import os
import re
import sqlite3
import subprocess
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
FFPROBE_TIMEOUT = 10
DECODE_TIMEOUT = 30


def initialize(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS scene_assets (
            scene_id INTEGER PRIMARY KEY REFERENCES reel_scenes(id) ON DELETE CASCADE,
            filename TEXT NOT NULL UNIQUE,
            width INTEGER NOT NULL CHECK (width > 0),
            height INTEGER NOT NULL CHECK (height > 0),
            duration_ms INTEGER NOT NULL CHECK (duration_ms > 0)
        )
    """)


def media_path(filename):
    if not re.fullmatch(r"[a-f0-9]{32}\.mp4", filename):
        raise ValueError("Tên tệp video không hợp lệ.")
    return Path(os.environ.get("AFFILIATE_MEDIA_DIR") or "media") / filename


def discard(filename):
    if filename:
        try:
            media_path(filename).unlink(missing_ok=True)
        except OSError:
            pass


def probe(path):
    try:
        result = subprocess.run([
            "ffprobe", "-v", "error", "-max_alloc", "33554432",
            "-protocol_whitelist", "file", "-f", "mov", "-enable_drefs", "0",
            "-select_streams", "v:0",
            "-show_entries",
            "stream=width,height,sample_aspect_ratio,duration:"
            "stream_disposition=attached_pic:stream_side_data=rotation:"
            "format_tags=major_brand",
            "-of", "json", "-i", str(path.absolute()),
        ], check=True, capture_output=True, timeout=FFPROBE_TIMEOUT)
    except FileNotFoundError:
        raise ValueError("Máy chủ cần cài ffprobe để kiểm tra video.") from None
    except subprocess.TimeoutExpired:
        raise ValueError("Kiểm tra video quá thời gian cho phép.") from None
    except subprocess.CalledProcessError:
        raise ValueError("Không đọc được tệp video MP4.") from None

    try:
        metadata = json.loads(result.stdout)
        video = metadata["streams"][0]
        brand = metadata["format"]["tags"]["major_brand"]
        if not (brand.startswith(("iso", "mp4", "avc", "M4V")) or brand == "MSNV"):
            raise ValueError
        if video.get("disposition", {}).get("attached_pic"):
            raise ValueError
        width = int(video["width"])
        height = int(video["height"])
        duration = Decimal(video["duration"])
        if not duration.is_finite() or duration <= 0:
            raise ValueError
        duration_ms = int(duration * 1000)
        if duration_ms < 1 or duration_ms > 2**63 - 1:
            raise ValueError
        rotation = any(item.get("rotation", 0) % 360 for item in video.get("side_data_list", []))
    except (KeyError, IndexError, TypeError, ValueError, InvalidOperation, OverflowError):
        raise ValueError("Tệp phải là MP4 có luồng video và thời lượng hợp lệ.") from None
    if (
        width <= 0
        or height <= 0
        or width * 16 != height * 9
        or rotation
        or video.get("sample_aspect_ratio", "N/A") not in {"1:1", "N/A"}
    ):
        raise ValueError("Video phải có khung hình dọc 9:16, pixel vuông và không cần xoay.")
    return width, height, duration_ms


def check_container(path):
    # FFmpeg can decode the first frames of a cut MP4 without reporting an error.
    size = path.stat().st_size
    offset = 0
    with path.open("rb") as source:
        while offset < size:
            header = source.read(8)
            if len(header) != 8:
                break
            box_size = int.from_bytes(header[:4], "big")
            if box_size == 0:
                return  # The final box extends to EOF.
            header_size = 8
            if box_size == 1:
                extended_size = source.read(8)
                if len(extended_size) != 8:
                    break
                box_size = int.from_bytes(extended_size, "big")
                header_size = 16
            if not header_size <= box_size <= size - offset:
                break
            offset += box_size
            source.seek(offset)
    if offset != size:
        raise ValueError("Clip có dữ liệu video bị lỗi hoặc bị cắt.")


def check_playback(path):
    try:
        subprocess.run([
            "ffmpeg", "-nostdin", "-v", "error", "-xerror",
            "-protocol_whitelist", "file",
            "-f", "mov", "-enable_drefs", "0", "-threads", "2", "-i", str(path.absolute()),
            "-map", "0:V:0", "-an", "-abort_on", "empty_output_stream", "-f", "null", "-",
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=DECODE_TIMEOUT)
    except FileNotFoundError:
        raise ValueError("Máy chủ cần cài FFmpeg để kiểm tra video.") from None
    except subprocess.TimeoutExpired:
        raise ValueError("Kiểm tra phát video quá thời gian cho phép.") from None
    except subprocess.CalledProcessError:
        raise ValueError("Clip có dữ liệu video bị lỗi hoặc bị cắt.") from None


@contextmanager
def checked_upload(data):
    if not 1 <= len(data) <= MAX_UPLOAD_BYTES:
        raise ValueError("Tệp video phải có dung lượng từ 1 byte đến 25 MiB.")
    filename = uuid4().hex + ".mp4"
    path = media_path(filename)
    created = False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as video_file:
            created = True
            video_file.write(data)
        width, height, duration_ms = probe(path)
        if duration_ms > 30000 or width > 2160 or height > 3840:
            raise ValueError("Clip tối đa 30 giây và 2160 × 3840 pixel.")
        check_container(path)
        check_playback(path)
        yield filename, width, height, duration_ms
    except (ValueError, OSError, sqlite3.Error):
        if created:
            discard(filename)
        raise


def attach(db, scene_id, asset):
    if not db.in_transaction:
        db.execute("BEGIN IMMEDIATE")
    scene = db.execute("""
        SELECT scene_assets.filename
        FROM reel_scenes JOIN posts ON posts.id = reel_scenes.post_id
        LEFT JOIN scene_assets ON scene_assets.scene_id = reel_scenes.id
        WHERE reel_scenes.id = ? AND posts.status = 'draft'
    """, (scene_id,)).fetchone()
    if scene is None:
        raise ValueError("Chỉ nhập clip vào cảnh thuộc bản nháp.")
    db.execute("""
        INSERT INTO scene_assets(scene_id, filename, width, height, duration_ms)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(scene_id) DO UPDATE SET
            filename = excluded.filename, width = excluded.width,
            height = excluded.height, duration_ms = excluded.duration_ms
    """, (scene_id, *asset))
    return scene["filename"]
