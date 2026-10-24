"""行情数据落库：自选清单 + 每交易日快照 + 汇总缓存。取数在 src/market.py，这里只写库。"""

from __future__ import annotations

import json
import sqlite3

from ..dates import now_iso, today_iso
from .rows import row_to_dict, rows_to_dicts


# ---------------- 自选清单 ----------------


def add_watch(
    conn: sqlite3.Connection, code: str, name: str, market: str, kind: str = "stock"
) -> int:
    cur = conn.execute(
        "INSERT INTO market_watch (code, name, market, kind, created_day)"
        " VALUES (?, ?, ?, ?, ?)",
        (code, name, market, kind, today_iso()),
    )
    conn.commit()
    return int(cur.lastrowid)


def remove_watch(conn: sqlite3.Connection, watch_id: int) -> None:
    conn.execute("DELETE FROM market_watch WHERE id = ?", (watch_id,))
    conn.commit()


def list_watch(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM market_watch ORDER BY id ASC"
    ).fetchall()
    return rows_to_dicts(rows)


def find_watch_by_code(conn: sqlite3.Connection, code: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM market_watch WHERE code = ?", (code,)
    ).fetchone()
    return row_to_dict(row)


# ---------------- 快照 ----------------


def upsert_snapshots(conn: sqlite3.Connection, quotes: list[dict]) -> int:
    """一天同一 code 只保留一行，重复刷新是更新。返回写进去的行数。"""
    written = 0
    for quote in quotes:
        conn.execute(
            """
            INSERT INTO market_snapshots
                (day, code, name, market, kind, price, change_amount, change_pct, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(day, code) DO UPDATE SET
                name = excluded.name,
                market = excluded.market,
                kind = excluded.kind,
                price = excluded.price,
                change_amount = excluded.change_amount,
                change_pct = excluded.change_pct,
                updated_at = excluded.updated_at
            """,
            (
                quote["day"],
                quote["code"],
                quote["name"],
                quote["market"],
                quote.get("kind", "stock"),
                quote.get("price"),
                quote.get("change_amount"),
                quote.get("change_pct"),
                now_iso(),
            ),
        )
        written += 1
    if written:
        conn.commit()
    return written


def drop_rows_after(conn: sqlite3.Connection, day: str, exclude_market: str = "crypto") -> int:
    """清掉归日晚于 day 的快照行。

    真实行情数据的日期不可能超过它的交易日，晚于的都是早期归日算错
    留下的残留（比如把没时间戳的指数写成了「今天」）。快照是可再生
    缓存，删掉不心疼；自选清单不碰。

    默认排除币圈：币圈 7×24 交易，UTC 日期常比股票交易日新一天
    （周六就是这样），那是真实数据不是垃圾。
    """
    cur = conn.execute(
        "DELETE FROM market_snapshots WHERE day > ? AND market <> ?",
        (day, exclude_market),
    )
    conn.commit()
    return cur.rowcount or 0


def latest_snapshot_day(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT MAX(day) AS day FROM market_snapshots").fetchone()
    return row["day"] if row and row["day"] else None


def latest_stock_day(conn: sqlite3.Connection) -> str | None:
    """股票部分的最近行情日。币圈 UTC 日期常比股票交易日新一天，
    页面顶部的「X 收盘」说的是股票，不能把币圈的日期混进来。"""
    row = conn.execute(
        "SELECT MAX(day) AS day FROM market_snapshots WHERE market <> 'crypto'"
    ).fetchone()
    return row["day"] if row and row["day"] else None


def latest_quote(conn: sqlite3.Connection, code: str) -> dict | None:
    """某个标的最近的一条快照。不同市场的行情日不完全对齐，
    显示时逐个标的取最新，不假设大家同一天。"""
    row = conn.execute(
        "SELECT * FROM market_snapshots WHERE code = ? ORDER BY day DESC LIMIT 1",
        (code,),
    ).fetchone()
    return row_to_dict(row)


def history(conn: sqlite3.Connection, code: str, days: int = 30) -> list[dict]:
    """最近 N 个交易日，按时间正序返回。"""
    rows = conn.execute(
        """
        SELECT day, price, change_pct FROM market_snapshots
        WHERE code = ?
        ORDER BY day DESC
        LIMIT ?
        """,
        (code, int(days)),
    ).fetchall()
    return list(reversed(rows_to_dicts(rows)))


def window_change(conn: sqlite3.Connection, code: str, days: int = 30) -> dict | None:
    """区间涨跌幅：窗口内首尾两个快照算。数据不够两个点返回 None。"""
    rows = history(conn, code, days)
    if len(rows) < 2:
        return None
    first, last = rows[0].get("price"), rows[-1].get("price")
    if not first or last is None:
        return None
    return {
        "from_day": rows[0]["day"],
        "to_day": rows[-1]["day"],
        "pct": (last - first) / first * 100,
    }


# ---------------- 汇总缓存 ----------------

# 汇总数据的种类。一次后台刷新写一批，行情页打开时先读这里秒开。
AGGREGATE_KINDS = (
    "sectors_up",
    "sectors_down",
    "us_sectors_up",
    "us_sectors_down",
    "crypto_sectors_up",
    "crypto_sectors_down",
)


def save_aggregates(conn: sqlite3.Connection, aggregates: dict, temperature: list | None = None) -> None:
    """把一轮刷新的汇总与温度写进缓存。

    空结果不覆盖：某个数据源当场没拿到（板块接口抽风、跌停池挂掉），
    不能让上一轮的好数据被抹成空白。一样都没拿到就什么都不写。
    """
    payloads: dict[str, object] = {}
    for kind in AGGREGATE_KINDS:
        rows = aggregates.get(kind) or []
        if rows:
            payloads[kind] = rows
    limits = aggregates.get("limits") or {}
    if limits.get("up") is not None or limits.get("down") is not None:
        payloads["limits"] = {"up": limits.get("up"), "down": limits.get("down")}
    if temperature:
        payloads["temperature"] = temperature
    if not payloads:
        return
    for kind, payload in payloads.items():
        conn.execute(
            "INSERT INTO market_aggregates (kind, payload, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT (kind) DO UPDATE SET"
            " payload = excluded.payload, updated_at = excluded.updated_at",
            (kind, json.dumps(payload, ensure_ascii=False), now_iso()),
        )
    conn.commit()


def load_aggregates(conn: sqlite3.Connection) -> dict:
    """读汇总缓存。没有的种类不会出现在结果里，调用方按缺省值显示。"""
    result: dict = {}
    for row in conn.execute("SELECT kind, payload FROM market_aggregates").fetchall():
        try:
            result[row["kind"]] = json.loads(row["payload"])
        except (ValueError, TypeError):
            continue
    return result
