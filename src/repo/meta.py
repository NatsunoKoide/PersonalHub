"""设置、导出与数据概况。"""

from __future__ import annotations

import csv
import io
import json
import sqlite3

from .. import paths
from ..dates import now_iso
from ..version import APP_NAME, APP_VERSION, SCHEMA_VERSION
from . import okr
from .rows import rows_to_dicts

def get_setting(conn: sqlite3.Connection, key: str, default=None):
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return json.loads(row["value"])
    except (ValueError, TypeError):
        return row["value"]


def get_settings(conn: sqlite3.Connection, keys, default=None) -> dict:
    return {key: get_setting(conn, key, default) for key in keys}


def set_setting(conn: sqlite3.Connection, key: str, value) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?)"
        " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value, ensure_ascii=False)),
    )
    conn.commit()


def data_info(conn: sqlite3.Connection) -> dict:
    from ..db import database_size_of, table_counts

    size = database_size_of(conn)
    return {
        "data_home": str(paths.data_home()),
        "database_path": str(paths.database_path()),
        "backups_dir": str(paths.backups_dir()),
        "db_size_bytes": size,
        "db_size_human": paths.human_size(size),
        "backups_size_human": paths.human_size(_dir_size(paths.backups_dir())),
        "backup_count": _count_files(paths.backups_dir(), "*.db"),
        "counts": table_counts(conn),
        "app_version": APP_VERSION,
        "schema_version": SCHEMA_VERSION,
    }


def _dir_size(path) -> int:
    total = 0
    for child in path.glob("*"):
        if child.is_file():
            try:
                total += child.stat().st_size
            except OSError:
                pass
    return total


def _count_files(path, pattern: str) -> int:
    return len(list(path.glob(pattern))) if path.exists() else 0


def export_payload(conn: sqlite3.Connection) -> dict:
    """导出的完整快照，可以拿任何 sqlite 工具直接读。"""
    objectives = []
    for objective in okr.list_all(conn):
        objectives.append(objective)

    return {
        "app": APP_NAME,
        "app_version": APP_VERSION,
        "schema_version": SCHEMA_VERSION,
        "exported_at": now_iso(),
        "tasks": rows_to_dicts(conn.execute("SELECT * FROM tasks").fetchall()),
        "habits": rows_to_dicts(conn.execute("SELECT * FROM habits").fetchall()),
        "habit_logs": rows_to_dicts(conn.execute("SELECT * FROM habit_logs").fetchall()),
        "objectives": objectives,
        "key_results": rows_to_dicts(conn.execute("SELECT * FROM key_results").fetchall()),
        "categories": rows_to_dicts(conn.execute("SELECT * FROM categories").fetchall()),
        "ledger_entries": rows_to_dicts(
            conn.execute("SELECT * FROM ledger_entries").fetchall()
        ),
        "budgets": rows_to_dicts(conn.execute("SELECT * FROM budgets").fetchall()),
        "meals": rows_to_dicts(conn.execute("SELECT * FROM meals").fetchall()),
        "day_notes": rows_to_dicts(conn.execute("SELECT * FROM day_notes").fetchall()),
        "weigh_ins": rows_to_dicts(conn.execute("SELECT * FROM weigh_ins").fetchall()),
        "quick_phrases": rows_to_dicts(
            conn.execute("SELECT * FROM quick_phrases").fetchall()
        ),
        "holidays": rows_to_dicts(conn.execute("SELECT * FROM holidays").fetchall()),
        "fx_rates": rows_to_dicts(conn.execute("SELECT * FROM fx_rates").fetchall()),
        "settings": rows_to_dicts(conn.execute("SELECT * FROM settings").fetchall()),
    }


def export_ledger_csv(conn: sqlite3.Connection) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["日期", "方向", "原币金额", "币种", "折合人民币", "分类", "支付方式", "备注"])
    rows = conn.execute(
        "SELECT * FROM ledger_entries ORDER BY day ASC, id ASC"
    ).fetchall()
    for row in rows:
        writer.writerow(
            [
                row["day"],
                "支出" if row["direction"] == "expense" else "收入",
                f"{row['amount']:.2f}",
                row["currency"],
                f"{row['amount_cny']:.2f}",
                row["category"],
                row["method"],
                row["note"],
            ]
        )
    return buffer.getvalue()
