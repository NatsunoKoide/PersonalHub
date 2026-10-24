"""身体：每周一次的称量，以及减脂目标。"""

from __future__ import annotations

import sqlite3

from ..dates import week_start
from .rows import row_to_dict, rows_to_dicts

TARGET_KEYS = ("target_weight", "target_body_fat")


def upsert(
    conn: sqlite3.Connection,
    day: str,
    weight: float | None,
    body_fat: float | None,
    note: str = "",
) -> None:
    conn.execute(
        "INSERT INTO weigh_ins (day, weight, body_fat, note) VALUES (?, ?, ?, ?)"
        " ON CONFLICT (day) DO UPDATE SET weight = excluded.weight,"
        " body_fat = excluded.body_fat, note = excluded.note",
        (day, weight, body_fat, note),
    )
    conn.commit()


def remove(conn: sqlite3.Connection, day: str) -> None:
    conn.execute("DELETE FROM weigh_ins WHERE day = ?", (day,))
    conn.commit()


def list_series(conn: sqlite3.Connection, limit: int = 120) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM weigh_ins ORDER BY day DESC LIMIT ?", (int(limit),)
    ).fetchall()
    items = rows_to_dicts(rows)
    items.reverse()

    previous = None
    for item in items:
        item["weight_delta"] = (
            round(item["weight"] - previous["weight"], 2)
            if previous and item["weight"] is not None and previous["weight"] is not None
            else None
        )
        item["body_fat_delta"] = (
            round(item["body_fat"] - previous["body_fat"], 2)
            if previous
            and item["body_fat"] is not None
            and previous["body_fat"] is not None
            else None
        )
        if item["weight"] is not None:
            previous = item
    return items


def latest(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT * FROM weigh_ins ORDER BY day DESC LIMIT 1"
    ).fetchone()
    return row_to_dict(row)


def week_status(conn: sqlite3.Connection, today: str) -> dict:
    """本周是否已称量，以及相对上次的变化。"""
    from ..dates import parse

    monday = week_start(parse(today)).isoformat()
    row = conn.execute(
        "SELECT * FROM weigh_ins WHERE day BETWEEN ? AND ? ORDER BY day DESC LIMIT 1",
        (monday, today),
    ).fetchone()

    series = list_series(conn, limit=8)
    previous = series[-2] if len(series) >= 2 else None
    current = series[-1] if series else None

    return {
        "logged_this_week": row is not None,
        "last_day": current["day"] if current else None,
        "latest": current,
        "previous": previous,
        "weeks_since": _weeks_since(current["day"], today) if current else None,
    }


def _weeks_since(last_day: str, today: str) -> int:
    from ..dates import parse

    return max(0, (week_start(parse(today)) - week_start(parse(last_day))).days // 7)


def days_in_range(conn: sqlite3.Connection, start: str, end: str) -> set[str]:
    rows = conn.execute(
        "SELECT day FROM weigh_ins WHERE day BETWEEN ? AND ?", (start, end)
    ).fetchall()
    return {row["day"] for row in rows}


def targets(conn: sqlite3.Connection) -> dict:
    from .meta import get_settings

    return get_settings(conn, TARGET_KEYS, default=None)


def set_targets(
    conn: sqlite3.Connection,
    target_weight: float | None,
    target_body_fat: float | None,
) -> None:
    from .meta import set_setting

    set_setting(conn, "target_weight", target_weight)
    set_setting(conn, "target_body_fat", target_body_fat)
