from html import escape

STATUS_LABELS = {
    "pending": "Chờ nhận việc",
    "running": "Đang thực hiện",
    "done": "Đã bàn giao",
}
TRANSITIONS = {"running": "pending", "done": "running"}


def initialize(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS work_tasks (
            id INTEGER PRIMARY KEY,
            page_id INTEGER REFERENCES pages(id),
            title TEXT NOT NULL,
            assignee TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'running', 'done')),
            output TEXT NOT NULL DEFAULT ''
        )
    """)


def create(db, fields):
    title = fields.get("title", "").strip()
    assignee = fields.get("assignee", "").strip()
    page_id = fields.get("page_id") or None
    if not 1 <= len(title) <= 160 or not 1 <= len(assignee) <= 100:
        raise ValueError("Nhập tên việc từ 1–160 ký tự và người hoặc nhóm phụ trách từ 1–100 ký tự.")
    if page_id is not None and db.execute("SELECT id FROM pages WHERE id = ?", (page_id,)).fetchone() is None:
        raise ValueError("Fanpage không tồn tại.")
    db.execute("INSERT INTO work_tasks (page_id, title, assignee) VALUES (?, ?, ?)",
               (page_id, title, assignee))


def advance(db, fields):
    target = fields.get("status")
    previous = TRANSITIONS.get(target)
    output = fields.get("output", "").strip()
    if previous is None:
        raise ValueError("Trạng thái đích không hợp lệ.")
    if len(output) > 2000:
        raise ValueError("Kết quả bàn giao tối đa 2.000 ký tự.")
    if target == "running" and output:
        raise ValueError("Ghi kết quả khi bàn giao.")
    result = db.execute("""
        UPDATE work_tasks SET status = ?, output = ?
        WHERE id = ? AND status = ?
    """, (target, output, fields.get("id"), previous))
    if result.rowcount != 1:
        raise ValueError("Phiếu không tồn tại hoặc trạng thái đã thay đổi.")


def task_card(row):
    task_id = row["id"]
    status = row["status"]
    title = escape(row["title"])
    owner = escape(row["assignee"])
    page = escape(row["page"] or "Toàn dự án")
    notes = ""
    actions = ""
    if status == "pending":
        actions = transition_form(task_id, "running", "Bắt đầu")
    elif status == "running":
        actions = transition_form(task_id, "done", "Bàn giao")
    elif row["output"]:
        notes = f'<p style="white-space: pre-wrap">{escape(row["output"])}</p>'
    return f"""
        <article><strong>{title}</strong>
        <p>{page} · {owner} · {STATUS_LABELS[status]}</p>{notes}{actions}</article>
    """


def transition_form(task_id, target, label):
    output = ""
    if target == "done":
        output = '<label>Kết quả bàn giao <textarea name="output" maxlength="2000" rows="2"></textarea></label>'
    return f"""
        <form method="post" action="/tasks/advance">
            <input type="hidden" name="id" value="{task_id}">
            {output}
            <button name="status" value="{target}">{label}</button>
        </form>
    """


def section(db):
    pages = "".join(
        f'<option value="{row["id"]}">{escape(row["name"])}</option>'
        for row in db.execute("SELECT id, name FROM pages ORDER BY id")
    )
    cards = "".join(task_card(row) for row in db.execute("""
        SELECT work_tasks.*, pages.name AS page
        FROM work_tasks LEFT JOIN pages ON pages.id = work_tasks.page_id
        ORDER BY work_tasks.status = 'done', work_tasks.id DESC
    """))
    return f"""
        <section>
            <h2>Phiếu công việc</h2>
            <p>Trạng thái do người dùng cập nhật trên dashboard.</p>
            <form method="post" action="/tasks">
                <label>Tên việc <input name="title" required maxlength="160"></label>
                <label>Người hoặc nhóm phụ trách <input name="assignee" required maxlength="100"></label>
                <label>Fanpage <select name="page_id"><option value="">Toàn dự án</option>{pages}</select></label>
                <button>Tạo phiếu</button>
            </form>
            {cards or "<p>Chưa có phiếu công việc.</p>"}
        </section>
    """
