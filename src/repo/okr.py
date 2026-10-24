"""OKR：目标的进度由关键结果加权算出，手动覆盖优先。"""

from __future__ import annotations

import sqlite3

from ..dates import clamp_progress, now_iso
from .rows import row_to_dict, rows_to_dicts

CADENCE_LABELS = {"year": "年度", "quarter": "季度", "month": "月度", "week": "每周"}
CADENCE_ORDER = ("year", "quarter", "month", "week")


def kr_progress(kr: dict) -> float:
    """反向目标（如体重下降）天然成立：目标值小于起始值时分子分母同为负。"""
    span = kr["target_value"] - kr["start_value"]
    if span == 0:
        return 1.0 if kr["current_value"] >= kr["target_value"] else 0.0
    return clamp_progress((kr["current_value"] - kr["start_value"]) / span)


def _progress_from(key_results: list[dict], manual: float | None) -> float:
    if manual is not None:
        return clamp_progress(manual / 100.0)
    if not key_results:
        return 0.0
    total_weight = sum(k["weight"] for k in key_results)
    if total_weight <= 0:
        total_weight = float(len(key_results))
        return clamp_progress(sum(kr_progress(k) for k in key_results) / total_weight)
    weighted = sum(kr_progress(k) * k["weight"] for k in key_results)
    return clamp_progress(weighted / total_weight)


def add(
    conn: sqlite3.Connection,
    title: str,
    cadence: str,
    year: int,
    period_start: str | None,
    period_end: str | None,
    note: str = "",
) -> int:
    cur = conn.execute(
        "INSERT INTO objectives (title, cadence, year, period_start, period_end, note,"
        " manual_progress, created_at) VALUES (?, ?, ?, ?, ?, ?, NULL, ?)",
        (title, cadence, int(year), period_start, period_end, note, now_iso()),
    )
    conn.commit()
    return int(cur.lastrowid)


def update(
    conn: sqlite3.Connection,
    objective_id: int,
    title: str,
    cadence: str,
    year: int,
    period_start: str | None,
    period_end: str | None,
    note: str,
    manual_progress: float | None,
) -> None:
    conn.execute(
        "UPDATE objectives SET title = ?, cadence = ?, year = ?, period_start = ?,"
        " period_end = ?, note = ?, manual_progress = ? WHERE id = ?",
        (title, cadence, int(year), period_start, period_end, note, manual_progress, objective_id),
    )
    conn.commit()


def remove(conn: sqlite3.Connection, objective_id: int) -> None:
    conn.execute("DELETE FROM objectives WHERE id = ?", (objective_id,))
    conn.commit()


def _key_results(conn: sqlite3.Connection, objective_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM key_results WHERE objective_id = ? ORDER BY id ASC",
        (objective_id,),
    ).fetchall()
    return rows_to_dicts(rows)


def get(conn: sqlite3.Connection, objective_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM objectives WHERE id = ?", (objective_id,)).fetchone()
    if row is None:
        return None
    return _enrich(conn, dict(row))


def _enrich(conn: sqlite3.Connection, objective: dict) -> dict:
    krs = _key_results(conn, objective["id"])
    for kr in krs:
        kr["progress"] = kr_progress(kr)
    objective["key_results"] = krs
    objective["progress"] = _progress_from(krs, objective["manual_progress"])
    objective["progress_percent"] = round(objective["progress"] * 100)
    objective["cadence_label"] = CADENCE_LABELS.get(objective["cadence"], objective["cadence"])
    return objective


def list_all(
    conn: sqlite3.Connection,
    year: int | None = None,
    cadence: str | None = None,
) -> list[dict]:
    sql = "SELECT * FROM objectives WHERE 1 = 1"
    params: list = []
    if year is not None:
        sql += " AND year = ?"
        params.append(int(year))
    if cadence:
        sql += " AND cadence = ?"
        params.append(cadence)
    sql += " ORDER BY year DESC, cadence, id DESC"
    rows = conn.execute(sql, params).fetchall()
    return [_enrich(conn, dict(row)) for row in rows]


def add_kr(
    conn: sqlite3.Connection,
    objective_id: int,
    name: str,
    start_value: float,
    current_value: float,
    target_value: float,
    unit: str = "",
    weight: float = 1.0,
) -> int:
    cur = conn.execute(
        "INSERT INTO key_results (objective_id, name, start_value, current_value,"
        " target_value, unit, weight) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (objective_id, name, start_value, current_value, target_value, unit, weight),
    )
    conn.commit()
    return int(cur.lastrowid)


def update_kr(
    conn: sqlite3.Connection,
    kr_id: int,
    name: str,
    start_value: float,
    current_value: float,
    target_value: float,
    unit: str,
    weight: float,
) -> None:
    conn.execute(
        "UPDATE key_results SET name = ?, start_value = ?, current_value = ?,"
        " target_value = ?, unit = ?, weight = ? WHERE id = ?",
        (name, start_value, current_value, target_value, unit, weight, kr_id),
    )
    conn.commit()


def set_kr_value(conn: sqlite3.Connection, kr_id: int, current_value: float) -> None:
    conn.execute(
        "UPDATE key_results SET current_value = ? WHERE id = ?", (current_value, kr_id)
    )
    conn.commit()


def objective_id_of(conn: sqlite3.Connection, kr_id: int) -> int | None:
    row = conn.execute(
        "SELECT objective_id FROM key_results WHERE id = ?", (kr_id,)
    ).fetchone()
    return int(row["objective_id"]) if row else None


def remove_kr(conn: sqlite3.Connection, kr_id: int) -> None:
    conn.execute("DELETE FROM key_results WHERE id = ?", (kr_id,))
    conn.commit()


def cadence_overview(conn: sqlite3.Connection, year: int) -> list[dict]:
    """年度总览里五类周期各自的完成度。"""
    objectives = list_all(conn, year=year)
    result = []
    for cadence in CADENCE_ORDER:
        subset = [o for o in objectives if o["cadence"] == cadence]
        avg = sum(o["progress"] for o in subset) / len(subset) if subset else 0.0
        result.append(
            {
                "cadence": cadence,
                "label": CADENCE_LABELS[cadence],
                "count": len(subset),
                "progress": avg,
                "progress_percent": round(avg * 100),
            }
        )
    return result


def upcoming(conn: sqlite3.Connection, today: str, within_days: int = 30) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM objectives WHERE period_end IS NOT NULL"
        " AND period_end >= ? AND period_end <= date(?, '+' || ? || ' day')"
        " ORDER BY period_end ASC",
        (today, today, int(within_days)),
    ).fetchall()
    items = [_enrich(conn, dict(row)) for row in rows]
    return [item for item in items if item["progress"] < 1]
