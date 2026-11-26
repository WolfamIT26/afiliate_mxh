from html import escape

import activity

MAX_SCENES = 12


def initialize(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS reel_scenes (
            id INTEGER PRIMARY KEY,
            post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
            position INTEGER NOT NULL CHECK (position > 0),
            prompt TEXT NOT NULL,
            seconds INTEGER NOT NULL CHECK (seconds BETWEEN 1 AND 30),
            UNIQUE (post_id, position)
        )
    """)


def scene_values(fields):
    prompt = fields.get("prompt", "").strip()
    try:
        seconds = int(fields.get("seconds", ""))
    except ValueError:
        raise ValueError("Thời lượng cảnh phải là số nguyên.") from None
    if not 1 <= len(prompt) <= 2000 or not 1 <= seconds <= 30:
        raise ValueError("Nhập mô tả 1–2000 ký tự và thời lượng 1–30 giây.")
    return prompt, seconds


def add_scene(db, fields):
    prompt, seconds = scene_values(fields)
    post_id = fields.get("post_id")
    result = db.execute("""
        INSERT INTO reel_scenes(post_id, position, prompt, seconds)
        SELECT posts.id, COALESCE(MAX(reel_scenes.position), 0) + 1, ?, ?
        FROM posts LEFT JOIN reel_scenes ON reel_scenes.post_id = posts.id
        WHERE posts.id = ? AND posts.status = 'draft'
        GROUP BY posts.id
        HAVING COUNT(reel_scenes.id) < ?
    """, (prompt, seconds, post_id, MAX_SCENES))
    if result.rowcount != 1:
        raise ValueError("Chỉ thêm cảnh vào bản nháp và tối đa 12 cảnh mỗi bài.")
    activity.record(db, post_id, "scene_added")


def edit_scene(db, fields):
    prompt, seconds = scene_values(fields)
    result = db.execute("""
        UPDATE reel_scenes SET prompt = ?, seconds = ?
        WHERE id = ? AND post_id IN (SELECT id FROM posts WHERE status = 'draft')
    """, (prompt, seconds, fields.get("id")))
    if result.rowcount != 1:
        raise ValueError("Chỉ sửa được cảnh thuộc bản nháp.")


def delete_scene(db, fields):
    result = db.execute("""
        DELETE FROM reel_scenes
        WHERE id = ? AND post_id IN (SELECT id FROM posts WHERE status = 'draft')
    """, (fields.get("id"),))
    if result.rowcount != 1:
        raise ValueError("Chỉ xóa được cảnh thuộc bản nháp.")


def move_scene(db, fields):
    direction = fields.get("direction")
    if direction not in ("up", "down"):
        raise ValueError("Chọn đưa cảnh lên hoặc xuống.")

    comparison, order = ("<", "DESC") if direction == "up" else (">", "ASC")
    pair = db.execute(f"""
        SELECT current.id, current.position, neighbor.id AS neighbor_id,
               neighbor.position AS neighbor_position
        FROM reel_scenes AS current
        JOIN posts ON posts.id = current.post_id
        JOIN reel_scenes AS neighbor
            ON neighbor.post_id = current.post_id
            AND neighbor.position {comparison} current.position
        WHERE current.id = ? AND posts.status = 'draft'
        ORDER BY neighbor.position {order}
        LIMIT 1
    """, (fields.get("id"),)).fetchone()
    if pair is None:
        raise ValueError("Cảnh phải thuộc bản nháp và có cảnh liền kề theo hướng đã chọn.")

    # Park the scene in an unused slot before swapping the two unique positions.
    result = db.execute(f"""
        UPDATE reel_scenes
        SET position = (
            SELECT COALESCE(MAX(other.position), 0) + 1 FROM reel_scenes AS other
            WHERE other.post_id = reel_scenes.post_id
        )
        WHERE id = ? AND position = ?
            AND post_id IN (SELECT id FROM posts WHERE status = 'draft')
            AND ? = (
                SELECT neighbor.id FROM reel_scenes AS neighbor
                WHERE neighbor.post_id = reel_scenes.post_id
                    AND neighbor.position {comparison} reel_scenes.position
                ORDER BY neighbor.position {order}
                LIMIT 1
            )
            AND EXISTS (
                SELECT 1 FROM reel_scenes AS neighbor
                WHERE neighbor.id = ? AND neighbor.position = ?
            )
    """, (pair["id"], pair["position"], pair["neighbor_id"],
           pair["neighbor_id"], pair["neighbor_position"]))
    if result.rowcount != 1:
        raise ValueError("Thứ tự cảnh đã thay đổi. Mở lại bản nháp rồi thử lại.")
    db.execute("UPDATE reel_scenes SET position = ? WHERE id = ?",
               (pair["position"], pair["neighbor_id"]))
    db.execute("UPDATE reel_scenes SET position = ? WHERE id = ?",
               (pair["neighbor_position"], pair["id"]))


def scene_item(row, editable, can_move_up, can_move_down):
    prompt = escape(row["prompt"])
    seconds = row["seconds"]
    scene_id = row["id"]
    controls = ""
    if editable:
        controls = f"""
            <details><summary>Sửa hoặc xóa cảnh</summary>
                <form method="post" action="/reels/scenes/edit">
                    <input type="hidden" name="id" value="{scene_id}">
                    <label>Prompt hoặc mô tả cảnh
                        <textarea name="prompt" maxlength="2000" required>{prompt}</textarea>
                    </label>
                    <label>Thời lượng (giây)
                        <input name="seconds" type="number" min="1" max="30" value="{seconds}" required>
                    </label>
                    <button>Lưu thay đổi</button>
                    <button formaction="/reels/scenes/delete" formnovalidate
                        onclick="return confirm('Xóa cảnh này khỏi bản nháp?')">Xóa cảnh</button>
                </form>
            </details>
        """
        moves = []
        if can_move_up:
            moves.append('<button name="direction" value="up">Đưa lên</button>')
        if can_move_down:
            moves.append('<button name="direction" value="down">Đưa xuống</button>')
        if moves:
            controls += f"""
                <form method="post" action="/reels/scenes/move">
                    <input type="hidden" name="id" value="{scene_id}">
                    {"".join(moves)}
                </form>
            """
    return f"<li>{prompt} <small>({seconds} giây)</small>{controls}</li>"


def render_plan(db, post_id, status):
    rows = db.execute("""
        SELECT id, prompt, seconds FROM reel_scenes WHERE post_id = ? ORDER BY position
    """, (post_id,)).fetchall()
    content = ""
    if rows:
        total = sum(row["seconds"] for row in rows)
        scenes = "".join(
            scene_item(row, status == "draft", index > 0, index < len(rows) - 1)
            for index, row in enumerate(rows)
        )
        content = f"<h4>Kế hoạch Reel 9:16 · {total} giây</h4><ol>{scenes}</ol>"
    if status == "draft":
        content += f"""
            <details><summary>Thêm cảnh Reel 9:16</summary>
                <form method="post" action="/reels/scenes">
                    <input type="hidden" name="post_id" value="{post_id}">
                    <label>Prompt hoặc mô tả cảnh
                        <textarea name="prompt" minlength="1" maxlength="2000" required></textarea>
                    </label>
                    <label>Thời lượng (giây)
                        <input name="seconds" type="number" min="1" max="30" required>
                    </label>
                    <button>Lưu cảnh</button>
                </form>
            </details>
        """
    return content
