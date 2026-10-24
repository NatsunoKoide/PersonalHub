"""把 sqlite3.Row 转成普通字典，跨到 JS 边界时可直接序列化。"""

from __future__ import annotations

import sqlite3


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(row) for row in rows]


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None
