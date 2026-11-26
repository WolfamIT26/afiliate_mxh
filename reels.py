from html import escape

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


def add_scene(db, fields):
    prompt = fields.get("prompt", "").strip()
    try:
        seconds = int(fields.get("seconds", ""))
    except ValueError:
        raise ValueError("Thời lượng cảnh phải là số nguyên.") from None
    if not 1 <= len(prompt) <= 2000 or not 1 <= seconds <= 30:
        raise ValueError("Nhập mô tả 1–2000 ký tự và thời lượng 1–30 giây.")
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


def render_plan(db, post_id, status):
    rows = db.execute("""
        SELECT prompt, seconds FROM reel_scenes WHERE post_id = ? ORDER BY position
    """, (post_id,)).fetchall()
    content = ""
    if rows:
        total = sum(row["seconds"] for row in rows)
        scenes = "".join(
            f'<li>{escape(row["prompt"])} <small>({row["seconds"]} giây)</small></li>'
            for row in rows
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
