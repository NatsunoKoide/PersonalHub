"""随版本自带的初始数据。

节假日是本地表，数据来自国务院办公厅《关于2026年部分节假日安排的通知》
（国办发明电〔2025〕7号）。换年份时在设置页补，或把这里换成新一年的安排。
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

DEFAULT_CATEGORIES = ["餐饮", "交通", "购物", "居住", "娱乐", "医疗", "学习", "人情", "其他"]

# (名称, 起始, 结束) 含首尾
HOLIDAYS_2026 = [
    ("元旦", "2026-01-01", "2026-01-03"),
    ("春节", "2026-02-15", "2026-02-23"),
    ("清明节", "2026-04-04", "2026-04-06"),
    ("劳动节", "2026-05-01", "2026-05-05"),
    ("端午节", "2026-06-19", "2026-06-21"),
    ("中秋节", "2026-09-25", "2026-09-27"),
    ("国庆节", "2026-10-01", "2026-10-07"),
]

# 放假前后的调休上班日，单独存，无法从假期本身推出来
MAKEUP_WORKDAYS_2026 = [
    "2026-01-04",
    "2026-02-14",
    "2026-02-28",
    "2026-05-09",
    "2026-09-20",
    "2026-10-10",
]


def seed_categories(conn: sqlite3.Connection) -> None:
    for order, name in enumerate(DEFAULT_CATEGORIES):
        conn.execute(
            "INSERT OR IGNORE INTO categories (name, sort_order) VALUES (?, ?)",
            (name, order),
        )
    conn.commit()


def seed_holidays(conn: sqlite3.Connection, year: int = 2026) -> None:
    """只在该年份还没有任何记录时才写入，用户改过就不再覆盖。"""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM holidays WHERE day LIKE ?", (f"{year}-%",)
    ).fetchone()
    if int(row["n"]) > 0:
        return

    for name, start, end in HOLIDAYS_2026:
        for offset in range(_day_span(start, end) + 1):
            conn.execute(
                "INSERT OR REPLACE INTO holidays (day, type, name) VALUES (?, 'holiday', ?)",
                ((date.fromisoformat(start) + timedelta(days=offset)).isoformat(), name),
            )
    for day in MAKEUP_WORKDAYS_2026:
        conn.execute(
            "INSERT OR REPLACE INTO holidays (day, type, name) VALUES (?, 'workday', '调休上班')",
            (day,),
        )
    conn.commit()


def _day_span(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def seed_all(conn: sqlite3.Connection) -> None:
    seed_categories(conn)
    seed_holidays(conn)
