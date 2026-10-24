"""饮食：一天四餐次 + 饮水。只记「吃了什么」，不算热量。

kcal 列与 foods.py 的热量数据都保留着（删表要重写、以后想捡回来成本高），
只是不再暴露给界面。想恢复热量记录时改这里就行，不动表结构。
"""

from __future__ import annotations

import sqlite3

from .rows import rows_to_dicts

SLOTS = ("breakfast", "lunch", "dinner", "snack")
SLOT_LABELS = {
    "breakfast": "早餐",
    "lunch": "午餐",
    "dinner": "晚餐",
    "snack": "加餐",
}


def get_day(conn: sqlite3.Connection, day: str) -> dict:
    rows = conn.execute(
        "SELECT slot, content FROM meals WHERE day = ?", (day,)
    ).fetchall()
    stored = {row["slot"]: row for row in rows}

    slots = []
    recorded = 0
    for slot in SLOTS:
        row = stored.get(slot)
        content = row["content"] if row else ""
        if content.strip():
            recorded += 1
        slots.append({"slot": slot, "label": SLOT_LABELS[slot], "content": content})

    note_row = conn.execute(
        "SELECT water_cups, note FROM day_notes WHERE day = ?", (day,)
    ).fetchone()
    water = int(note_row["water_cups"]) if note_row else 0
    note = note_row["note"] if note_row else ""

    return {
        "day": day,
        "slots": slots,
        "recorded": recorded,
        "water_cups": water,
        "note": note,
    }


def save_slot(conn: sqlite3.Connection, day: str, slot: str, content: str) -> None:
    if slot not in SLOTS:
        raise ValueError(f"unknown meal slot: {slot}")
    conn.execute(
        "INSERT INTO meals (day, slot, content, kcal) VALUES (?, ?, ?, NULL)"
        " ON CONFLICT (day, slot) DO UPDATE SET content = excluded.content",
        (day, slot, content),
    )
    conn.commit()


def set_water(conn: sqlite3.Connection, day: str, cups: int) -> None:
    conn.execute(
        "INSERT INTO day_notes (day, water_cups, note) VALUES (?, ?, '')"
        " ON CONFLICT (day) DO UPDATE SET water_cups = excluded.water_cups",
        (day, int(cups)),
    )
    conn.commit()


def set_note(conn: sqlite3.Connection, day: str, note: str) -> None:
    conn.execute(
        "INSERT INTO day_notes (day, water_cups, note) VALUES (?, 0, ?)"
        " ON CONFLICT (day) DO UPDATE SET note = excluded.note",
        (day, note),
    )
    conn.commit()


def recorded_by_day(conn: sqlite3.Connection, start: str, end: str) -> dict[str, int]:
    """区间内每天记了几餐，供日历格子与年度热力图用。"""
    rows = conn.execute(
        "SELECT day, COUNT(*) AS recorded FROM meals"
        " WHERE day BETWEEN ? AND ? AND TRIM(COALESCE(content, '')) <> ''"
        " GROUP BY day",
        (start, end),
    ).fetchall()
    return {row["day"]: int(row["recorded"]) for row in rows}


# --- 快捷短语 ---


def phrases(conn: sqlite3.Connection, kind: str = "food") -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM quick_phrases WHERE kind = ? ORDER BY id DESC", (kind,)
    ).fetchall()
    return rows_to_dicts(rows)


def add_phrase(conn: sqlite3.Connection, text: str, kind: str = "food") -> int:
    cur = conn.execute(
        "INSERT INTO quick_phrases (kind, text) VALUES (?, ?)", (kind, text)
    )
    conn.commit()
    return int(cur.lastrowid)


def remove_phrase(conn: sqlite3.Connection, phrase_id: int) -> None:
    conn.execute("DELETE FROM quick_phrases WHERE id = ?", (phrase_id,))
    conn.commit()
