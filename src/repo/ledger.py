"""记账：流水、分类、预算。"""

from __future__ import annotations

import sqlite3

from .rows import row_to_dict, rows_to_dicts

EXPENSE = "expense"
INCOME = "income"
FALLBACK_CATEGORY = "其他"
BASE_CURRENCY = "CNY"

# 所有统计读 amount_cny：记下的那一刻就折算成人民币存住，
# 之后汇率怎么动都不改写历史，本币流水两个字段相等。


def add(
    conn: sqlite3.Connection,
    day: str,
    amount: float,
    direction: str = EXPENSE,
    category: str = FALLBACK_CATEGORY,
    method: str = "",
    note: str = "",
    currency: str = BASE_CURRENCY,
    amount_cny: float | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO ledger_entries (day, amount, direction, category, method, note,"
        " currency, amount_cny) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            day,
            float(amount),
            direction,
            category or FALLBACK_CATEGORY,
            method,
            note,
            currency or BASE_CURRENCY,
            float(amount if amount_cny is None else amount_cny),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def update(
    conn: sqlite3.Connection,
    entry_id: int,
    day: str,
    amount: float,
    direction: str,
    category: str,
    method: str,
    note: str,
    currency: str = BASE_CURRENCY,
    amount_cny: float | None = None,
) -> None:
    conn.execute(
        "UPDATE ledger_entries SET day = ?, amount = ?, direction = ?, category = ?,"
        " method = ?, note = ?, currency = ?, amount_cny = ? WHERE id = ?",
        (
            day,
            float(amount),
            direction,
            category,
            method,
            note,
            currency or BASE_CURRENCY,
            float(amount if amount_cny is None else amount_cny),
            entry_id,
        ),
    )
    conn.commit()


def remove(conn: sqlite3.Connection, entry_id: int) -> None:
    conn.execute("DELETE FROM ledger_entries WHERE id = ?", (entry_id,))
    conn.commit()


def get(conn: sqlite3.Connection, entry_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM ledger_entries WHERE id = ?", (entry_id,)).fetchone()
    return row_to_dict(row)


def list_month(conn: sqlite3.Connection, month: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM ledger_entries WHERE day LIKE ? ORDER BY day DESC, id DESC",
        (f"{month}-%",),
    ).fetchall()
    return rows_to_dicts(rows)


def list_range(conn: sqlite3.Connection, start: str, end: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM ledger_entries WHERE day BETWEEN ? AND ? ORDER BY day ASC, id ASC",
        (start, end),
    ).fetchall()
    return rows_to_dicts(rows)


def month_summary(conn: sqlite3.Connection, month: str) -> dict:
    total_row = conn.execute(
        "SELECT"
        " COALESCE(SUM(CASE WHEN direction = 'expense' THEN amount_cny ELSE 0 END), 0) AS expense,"
        " COALESCE(SUM(CASE WHEN direction = 'income' THEN amount_cny ELSE 0 END), 0) AS income,"
        " COUNT(*) AS count"
        " FROM ledger_entries WHERE day LIKE ?",
        (f"{month}-%",),
    ).fetchone()

    cat_rows = conn.execute(
        "SELECT category, SUM(amount_cny) AS amount FROM ledger_entries"
        " WHERE day LIKE ? AND direction = 'expense' GROUP BY category"
        " ORDER BY amount DESC",
        (f"{month}-%",),
    ).fetchall()

    return {
        "month": month,
        "expense": float(total_row["expense"]),
        "income": float(total_row["income"]),
        "count": int(total_row["count"]),
        "by_category": [
            {"category": row["category"], "amount": float(row["amount"])} for row in cat_rows
        ],
    }


def previous_month_summary(conn: sqlite3.Connection, month: str) -> dict:
    year, mon = (int(part) for part in month.split("-"))
    if mon == 1:
        prev = f"{year - 1}-12"
    else:
        prev = f"{year}-{mon - 1:02d}"
    return month_summary(conn, prev)


def year_months(conn: sqlite3.Connection, year: int) -> list[dict]:
    result = []
    for month in range(1, 13):
        key = f"{year}-{month:02d}"
        row = conn.execute(
            "SELECT"
            " COALESCE(SUM(CASE WHEN direction = 'expense' THEN amount_cny ELSE 0 END), 0) AS expense,"
            " COALESCE(SUM(CASE WHEN direction = 'income' THEN amount_cny ELSE 0 END), 0) AS income"
            " FROM ledger_entries WHERE day LIKE ?",
            (f"{key}-%",),
        ).fetchone()
        result.append(
            {
                "month": key,
                "label": f"{month}月",
                "expense": float(row["expense"]),
                "income": float(row["income"]),
            }
        )
    return result


def year_summary(conn: sqlite3.Connection, year: int) -> dict:
    row = conn.execute(
        "SELECT"
        " COALESCE(SUM(CASE WHEN direction = 'expense' THEN amount_cny ELSE 0 END), 0) AS expense,"
        " COALESCE(SUM(CASE WHEN direction = 'income' THEN amount_cny ELSE 0 END), 0) AS income,"
        " COUNT(*) AS count"
        " FROM ledger_entries WHERE day LIKE ?",
        (f"{year}-%",),
    ).fetchone()
    return {
        "expense": float(row["expense"]),
        "income": float(row["income"]),
        "count": int(row["count"]),
    }


def day_total(conn: sqlite3.Connection, day: str) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(amount_cny), 0) AS total FROM ledger_entries"
        " WHERE day = ? AND direction = 'expense'",
        (day,),
    ).fetchone()
    return float(row["total"])


def daily_expense(conn: sqlite3.Connection, start: str, end: str) -> dict[str, float]:
    rows = conn.execute(
        "SELECT day, SUM(amount_cny) AS amount FROM ledger_entries"
        " WHERE day BETWEEN ? AND ? AND direction = 'expense' GROUP BY day",
        (start, end),
    ).fetchall()
    return {row["day"]: float(row["amount"]) for row in rows}


# --- 分类 ---


def categories(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM categories ORDER BY sort_order ASC, name ASC"
    ).fetchall()
    return [row["name"] for row in rows]


def add_category(conn: sqlite3.Connection, name: str) -> None:
    row = conn.execute("SELECT MAX(sort_order) AS m FROM categories").fetchone()
    conn.execute(
        "INSERT OR IGNORE INTO categories (name, sort_order) VALUES (?, ?)",
        (name, int(row["m"] or 0) + 1),
    )
    conn.commit()


def rename_category(conn: sqlite3.Connection, old: str, new: str) -> None:
    conn.execute("UPDATE categories SET name = ? WHERE name = ?", (new, old))
    conn.execute("UPDATE ledger_entries SET category = ? WHERE category = ?", (new, old))
    conn.commit()


def remove_category(conn: sqlite3.Connection, name: str) -> None:
    """删分类不删流水：历史流水落到「其他」，否则历史统计会凭空少一块。"""
    if name == FALLBACK_CATEGORY:
        return
    conn.execute("DELETE FROM categories WHERE name = ?", (name,))
    conn.execute(
        "UPDATE ledger_entries SET category = ? WHERE category = ?",
        (FALLBACK_CATEGORY, name),
    )
    conn.execute("DELETE FROM budgets WHERE scope = 'category' AND category = ?", (name,))
    conn.commit()


# --- 预算 ---


def budgets(conn: sqlite3.Connection, month: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM budgets WHERE month = ? ORDER BY scope DESC, category ASC",
        (month,),
    ).fetchall()
    return rows_to_dicts(rows)


def set_budget(
    conn: sqlite3.Connection, scope: str, category: str, month: str, limit_amount: float
) -> None:
    conn.execute(
        "INSERT INTO budgets (scope, category, month, limit_amount) VALUES (?, ?, ?, ?)"
        " ON CONFLICT (scope, category, month)"
        " DO UPDATE SET limit_amount = excluded.limit_amount",
        (scope, category, month, float(limit_amount)),
    )
    conn.commit()


def remove_budget(conn: sqlite3.Connection, budget_id: int) -> None:
    conn.execute("DELETE FROM budgets WHERE id = ?", (budget_id,))
    conn.commit()


def budget_status(conn: sqlite3.Connection, month: str) -> dict:
    rows = budgets(conn, month)
    summary = month_summary(conn, month)
    total = None
    per_category: list[dict] = []
    by_category = {item["category"]: item["amount"] for item in summary["by_category"]}

    for budget in rows:
        if budget["scope"] == "total":
            total = {
                "id": budget["id"],
                "limit": budget["limit_amount"],
                "used": summary["expense"],
                "left": budget["limit_amount"] - summary["expense"],
                "over": summary["expense"] > budget["limit_amount"],
                "rate": (
                    summary["expense"] / budget["limit_amount"]
                    if budget["limit_amount"]
                    else 0.0
                ),
            }
        else:
            used = by_category.get(budget["category"], 0.0)
            per_category.append(
                {
                    "id": budget["id"],
                    "category": budget["category"],
                    "limit": budget["limit_amount"],
                    "used": used,
                    "left": budget["limit_amount"] - used,
                    "over": used > budget["limit_amount"],
                    "rate": (
                        used / budget["limit_amount"] if budget["limit_amount"] else 0.0
                    ),
                }
            )

    return {"total": total, "by_category": per_category}
