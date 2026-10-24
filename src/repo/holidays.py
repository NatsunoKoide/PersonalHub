"""节假日与调休上班日。本地表，不联网。"""

from __future__ import annotations

import re
import sqlite3
from datetime import date, timedelta

from .rows import rows_to_dicts

HOLIDAY = "holiday"
WORKDAY = "workday"
TYPE_LABELS = {HOLIDAY: "放假", WORKDAY: "调休上班"}

_HOLIDAY_WORDS = {"holiday", "放假", "休", "假"}
_WORKDAY_WORDS = {"workday", "上班", "调休", "补班", "班"}

# 日期本身带连字符，所以区间分隔符只认 ~ 和 至，绝不把 - 当分隔符
_RANGE_SPLIT = re.compile(r"~|～|至")
_SEPARATORS = re.compile(r"[\s,，\t]+")


def list_year(conn: sqlite3.Connection, year: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM holidays WHERE day LIKE ? ORDER BY day ASC", (f"{year}-%",)
    ).fetchall()
    items = rows_to_dicts(rows)
    for item in items:
        item["type_label"] = TYPE_LABELS.get(item["type"], item["type"])
    return items


def set_day(conn: sqlite3.Connection, day: str, kind: str, name: str = "") -> None:
    if kind not in (HOLIDAY, WORKDAY):
        raise ValueError(f"unknown holiday type: {kind}")
    conn.execute(
        "INSERT INTO holidays (day, type, name) VALUES (?, ?, ?)"
        " ON CONFLICT (day) DO UPDATE SET type = excluded.type, name = excluded.name",
        (day, kind, name),
    )
    conn.commit()


def remove_day(conn: sqlite3.Connection, day: str) -> None:
    conn.execute("DELETE FROM holidays WHERE day = ?", (day,))
    conn.commit()


def day_map(conn: sqlite3.Connection, start: str, end: str) -> dict[str, dict]:
    rows = conn.execute(
        "SELECT * FROM holidays WHERE day BETWEEN ? AND ?", (start, end)
    ).fetchall()
    return {row["day"]: {"type": row["type"], "name": row["name"]} for row in rows}


def import_text(conn: sqlite3.Connection, text: str) -> int:
    """批量导入。每行：日期[~结束日期] 类型 名称，类型支持 放假/上班。"""
    written = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part for part in _SEPARATORS.split(line) if part]
        if not parts:
            continue

        # 日期本身带横线，只有显式写了结束日期才当作区间
        start_text, end_text = _split_range(parts[0], parts[1] if len(parts) > 1 else None)
        if start_text is None:
            continue

        kind = _parse_kind(parts)
        name = _parse_name(parts, kind)

        try:
            start = date.fromisoformat(start_text)
            end = date.fromisoformat(end_text) if end_text else start
        except ValueError:
            continue

        cursor = start
        while cursor <= end:
            set_day(conn, cursor.isoformat(), kind, name)
            written += 1
            cursor += timedelta(days=1)
    return written


def _split_range(first: str, second: str | None):
    """识别 2026-01-01~2026-01-03 这类区间，单个日期时结束为空。"""
    if _RANGE_SPLIT.search(first):
        start, end = _RANGE_SPLIT.split(first, maxsplit=1)
        return start.strip(), end.strip()
    if second and re.match(r"^\d{4}-\d{2}-\d{2}$", second):
        return first.strip(), second.strip()
    return first.strip(), None


def _parse_kind(parts: list[str]) -> str:
    for part in parts[1:]:
        if part in _HOLIDAY_WORDS:
            return HOLIDAY
        if part in _WORKDAY_WORDS:
            return WORKDAY
    return HOLIDAY


def _parse_name(parts: list[str], kind: str) -> str:
    stop_words = _HOLIDAY_WORDS | _WORKDAY_WORDS
    rest = [
        part
        for part in parts[1:]
        if part not in stop_words and not re.match(r"^\d{4}-\d{2}-\d{2}$", part)
    ]
    return "".join(rest) if rest else TYPE_LABELS[kind]


def is_holiday(conn: sqlite3.Connection, day: str) -> bool:
    row = conn.execute(
        "SELECT type FROM holidays WHERE day = ?", (day,)
    ).fetchone()
    return row is not None and row["type"] == HOLIDAY
