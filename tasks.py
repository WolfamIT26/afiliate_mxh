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
    result = db.execute("""
        INSERT INTO work_tasks(page_id, title, assignee)
        SELECT ?, ?, ? WHERE ? IS NULL OR EXISTS (
            SELECT 1 FROM pages WHERE id = ? AND state <> 'archived'
        )
    """, (page_id, title, assignee, page_id, page_id))
    if result.rowcount != 1:
        raise ValueError("Chọn Fanpage tồn tại và chưa lưu trữ để tạo phiếu.")


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


def options(choices, selected=""):
    html = []
    for value, label in choices:
        marker = " selected" if value == selected else ""
        html.append(f'<option value="{escape(value)}"{marker}>{escape(label)}</option>')
    return "".join(html)


def section(db, filters=None):
    filters = filters or {}
    all_pages = db.execute("SELECT id, name, state FROM pages ORDER BY id").fetchall()
    page_choices = [(str(row["id"]), row["name"]) for row in all_pages]
    available_pages = [(str(row["id"]), row["name"]) for row in all_pages if row["state"] != "archived"]
    page = filters.get("task_page", [""])[-1]
    if page != "project" and page not in dict(page_choices):
        page = ""
    status = filters.get("task_status", [""])[-1]
    if status not in STATUS_LABELS:
        status = ""

    pages = options([("", "Toàn dự án"), *available_pages])
    filter_pages = options([("", "Tất cả Fanpage"), ("project", "Toàn dự án"), *page_choices], page)
    filter_statuses = options([("", "Tất cả trạng thái"), *STATUS_LABELS.items()], status)
    cards = "".join(task_card(row) for row in db.execute("""
        SELECT work_tasks.*, pages.name AS page
        FROM work_tasks LEFT JOIN pages ON pages.id = work_tasks.page_id
        WHERE (? = '' OR (? = 'project' AND work_tasks.page_id IS NULL) OR work_tasks.page_id = ?)
          AND (? = '' OR work_tasks.status = ?)
        ORDER BY work_tasks.status = 'done', work_tasks.id DESC
    """, (page, page, page, status, status)))
    return f"""
        <section id="work-tasks">
            <h2>Phiếu công việc</h2>
            <p>Trạng thái do người dùng cập nhật trên dashboard.</p>
            <form method="post" action="/tasks">
                <label>Tên việc <input name="title" required maxlength="160"></label>
                <label>Người hoặc nhóm phụ trách <input name="assignee" required maxlength="100"></label>
                <label>Fanpage <select name="page_id">{pages}</select></label>
                <button>Tạo phiếu</button>
            </form>
            <form method="get" action="/#work-tasks">
                <label>Lọc phiếu theo Fanpage <select name="task_page">{filter_pages}</select></label>
                <label>Lọc phiếu theo trạng thái <select name="task_status">{filter_statuses}</select></label>
                <button>Lọc phiếu</button>
                <a href="/#work-tasks">Xóa bộ lọc phiếu</a>
            </form>
            {cards or "<p>Chưa có phiếu công việc phù hợp.</p>"}
        </section>
    """
