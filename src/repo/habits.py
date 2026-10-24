"""习惯：按天或按周重复，逐次打勾，与任务是两张表。"""

from __future__ import annotations

import sqlite3
from datetime import date

from ..dates import now_iso, parse
from .rows import row_to_dict, rows_to_dicts


def add(conn: sqlite3.Connection, name: str, cadence: str = "daily") -> int:
    cur = conn.execute(
        "INSERT INTO habits (name, cadence, archived, created_at) VALUES (?, ?, 0, ?)",
        (name, cadence, now_iso()),
    )
    conn.commit()
    return int(cur.lastrowid)


def update(conn: sqlite3.Connection, habit_id: int, name: str, cadence: str) -> None:
    conn.execute(
        "UPDATE habits SET name = ?, cadence = ? WHERE id = ?", (name, cadence, habit_id)
    )
    conn.commit()


def remove(conn: sqlite3.Connection, habit_id: int) -> None:
    conn.execute("DELETE FROM habits WHERE id = ?", (habit_id,))
    conn.commit()


def get(conn: sqlite3.Connection, habit_id: int) -> dict:
    row = conn.execute("SELECT * FROM habits WHERE id = ?", (habit_id,)).fetchone()
    return dict(row) if row else {}


def list_all(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM habits WHERE archived = 0 ORDER BY id ASC"
    ).fetchall()
    return rows_to_dicts(rows)


def toggle(conn: sqlite3.Connection, habit_id: int, day: str) -> bool:
    """在打勾与取消之间切换，返回切换后的状态。"""
    row = conn.execute(
        "SELECT id FROM habit_logs WHERE habit_id = ? AND day = ?", (habit_id, day)
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO habit_logs (habit_id, day) VALUES (?, ?)", (habit_id, day)
        )
        conn.commit()
        return True
    conn.execute("DELETE FROM habit_logs WHERE id = ?", (row["id"],))
    conn.commit()
    return False


def logged_on(conn: sqlite3.Connection, habit_id: int, day: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM habit_logs WHERE habit_id = ? AND day = ?", (habit_id, day)
    ).fetchone()
    return row is not None


def with_done_on(conn: sqlite3.Connection, day: str) -> list[dict]:
    """列出所有习惯，并标出这一天有没有打勾。"""
    rows = conn.execute(
        "SELECT h.*, EXISTS("
        " SELECT 1 FROM habit_logs l WHERE l.habit_id = h.id AND l.day = ?) AS done"
        " FROM habits h WHERE h.archived = 0 ORDER BY h.id ASC",
        (day,),
    ).fetchall()
    return [dict(row) for row in rows]


def logs_by_day(conn: sqlite3.Connection, start: str, end: str) -> dict[str, list[int]]:
    rows = conn.execute(
        "SELECT day, habit_id FROM habit_logs WHERE day BETWEEN ? AND ?", (start, end)
    ).fetchall()
    result: dict[str, list[int]] = {}
    for row in rows:
        result.setdefault(row["day"], []).append(int(row["habit_id"]))
    return result


def streak(conn: sqlite3.Connection, habit_id: int, today: date) -> int:
    """从今天往回数连续完成的次数，今天没做不算断（当天还没过完）。"""
    row = conn.execute("SELECT cadence FROM habits WHERE id = ?", (habit_id,)).fetchone()
    if row is None:
        return 0
    step = 7 if row["cadence"] == "weekly" else 1
    count = 0
    cursor = today
    while True:
        exists = conn.execute(
            "SELECT 1 FROM habit_logs WHERE habit_id = ? AND day = ?",
            (habit_id, cursor.isoformat()),
        ).fetchone()
        if exists:
            count += 1
        elif cursor != today:
            break  # 今天还没做是常态，不算断链
        cursor = date.fromordinal(cursor.toordinal() - step)
    return count


def _expected_slots(cadence: str, start: date, end: date) -> int:
    if cadence == "weekly":
        return _mondays(start, end)
    return (end - start).days + 1


def _mondays(start: date, end: date) -> int:
    cursor = date.fromordinal(start.toordinal() - start.weekday())
    count = 0
    while cursor <= end:
        if cursor >= start:
            count += 1
        cursor = date.fromordinal(cursor.toordinal() + 7)
    return count


def habit_stats(conn: sqlite3.Connection, habit_id: int, start: str, end: str) -> dict:
    row = conn.execute("SELECT cadence FROM habits WHERE id = ?", (habit_id,)).fetchone()
    if row is None:
        return {"done": 0, "expected": 0, "rate": 0.0}
    cadence = row["cadence"]
    expected = _expected_slots(cadence, parse(start), parse(end))
    done_row = conn.execute(
        "SELECT COUNT(*) AS n FROM habit_logs WHERE habit_id = ? AND day BETWEEN ? AND ?",
        (habit_id, start, end),
    ).fetchone()
    done = int(done_row["n"] or 0)
    return {
        "done": done,
        "expected": expected,
        "rate": (done / expected) if expected else 0.0,
    }


def year_stats(conn: sqlite3.Connection, start: str, end: str) -> dict:
    """年度坚持率 = 今年已打勾次数 / 今年应打勾次数，跨习惯合并。"""
    habits_rows = conn.execute(
        "SELECT id, cadence FROM habits WHERE archived = 0"
    ).fetchall()
    total_done = 0
    total_expected = 0
    for row in habits_rows:
        expected = _expected_slots(row["cadence"], parse(start), parse(end))
        done_row = conn.execute(
            "SELECT COUNT(*) AS n FROM habit_logs"
            " WHERE habit_id = ? AND day BETWEEN ? AND ?",
            (row["id"], start, end),
        ).fetchone()
        total_expected += expected
        total_done += int(done_row["n"] or 0)
    return {
        "done": total_done,
        "expected": total_expected,
        "rate": (total_done / total_expected) if total_expected else 0.0,
    }

