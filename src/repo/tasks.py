"""任务：一次性、有日期的待办，核销即终态。"""

from __future__ import annotations

import sqlite3

from ..dates import now_iso
from .rows import row_to_dict, rows_to_dicts

PRIORITY_LABELS = {2: "高", 1: "中", 0: "低"}


def add(conn: sqlite3.Connection, title: str, due_date: str, tag: str = "", priority: int = 1) -> int:
    cur = conn.execute(
        "INSERT INTO tasks (title, due_date, tag, priority, done, created_at)"
        " VALUES (?, ?, ?, ?, 0, ?)",
        (title, due_date, tag, int(priority), now_iso()),
    )
    conn.commit()
    return int(cur.lastrowid)


def update(conn: sqlite3.Connection, task_id: int, title: str, due_date: str, tag: str, priority: int) -> None:
    conn.execute(
        "UPDATE tasks SET title = ?, due_date = ?, tag = ?, priority = ? WHERE id = ?",
        (title, due_date, tag, int(priority), task_id),
    )
    conn.commit()


def set_done(conn: sqlite3.Connection, task_id: int, done: bool) -> None:
    conn.execute(
        "UPDATE tasks SET done = ?, done_at = ? WHERE id = ?",
        (1 if done else 0, now_iso() if done else None, task_id),
    )
    conn.commit()


def remove(conn: sqlite3.Connection, task_id: int) -> None:
    conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()


def get(conn: sqlite3.Connection, task_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return row_to_dict(row)


def list_day(conn: sqlite3.Connection, day: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM tasks WHERE due_date = ?"
        " ORDER BY done ASC, priority DESC, id ASC",
        (day,),
    ).fetchall()
    return rows_to_dicts(rows)


def list_range(conn: sqlite3.Connection, start: str, end: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM tasks WHERE due_date BETWEEN ? AND ?"
        " ORDER BY due_date ASC, priority DESC, id ASC",
        (start, end),
    ).fetchall()
    return rows_to_dicts(rows)


def counts_by_day(conn: sqlite3.Connection, start: str, end: str) -> dict[str, dict]:
    rows = conn.execute(
        "SELECT due_date AS day,"
        " COUNT(*) AS total,"
        " SUM(CASE WHEN done = 1 THEN 1 ELSE 0 END) AS done"
        " FROM tasks WHERE due_date BETWEEN ? AND ? GROUP BY due_date",
        (start, end),
    ).fetchall()
    return {row["day"]: {"total": row["total"], "done": row["done"]} for row in rows}


def overdue(conn: sqlite3.Connection, today: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM tasks WHERE done = 0 AND due_date < ?"
        " ORDER BY due_date ASC, priority DESC",
        (today,),
    ).fetchall()
    return rows_to_dicts(rows)


def year_stats(conn: sqlite3.Connection, start: str, end: str) -> dict:
    row = conn.execute(
        "SELECT COUNT(*) AS total,"
        " SUM(CASE WHEN done = 1 THEN 1 ELSE 0 END) AS done"
        " FROM tasks WHERE due_date BETWEEN ? AND ?",
        (start, end),
    ).fetchone()
    total = int(row["total"] or 0)
    done = int(row["done"] or 0)
    return {
        "total": total,
        "done": done,
        "rate": (done / total) if total else 0.0,
    }


def tags(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT tag FROM tasks WHERE tag != '' ORDER BY tag"
    ).fetchall()
    return [row["tag"] for row in rows]
