"""联网同步：节假日与汇率。

两个数据源都是免 key 的公开接口，也都可能哪天就关了。所以这一层的规矩是：
拿不到就当没发生，界面继续用本地数据，用户看不出区别。

「联网总开关」关掉时，本模块一个请求都不发。
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

from . import net
from .dates import now_iso
from .repo import holidays as holidays_repo
from .repo import meta

HOLIDAY_URL = "https://publicapi.xiaoai.me/holiday/year"
FX_URL = "https://open.er-api.com/v6/latest/CNY"

KEY_ENABLED = "net.enabled"
KEY_SYNCED_YEARS = "holidays.synced_years"
KEY_LAST_SYNC = "net.last_sync_at"

# 接口口径：0 工作日 / 1 节假日 / 2 双休日 / 3 调休上班
# 2 只是普通周末，我们的日历按星期自己就能算出来，不入表
_ONLINE_HOLIDAY = 1
_ONLINE_WORKDAY = 3

# 人民币基准的汇率一天动不了多少，半天刷一次足够
FX_MAX_AGE = timedelta(hours=12)

CURRENCIES = {
    "CNY": "人民币",
    "USD": "美元",
    "EUR": "欧元",
    "JPY": "日元",
    "HKD": "港币",
    "GBP": "英镑",
    "KRW": "韩元",
    "TWD": "新台币",
    "AUD": "澳元",
    "CAD": "加元",
    "SGD": "新加坡元",
    "THB": "泰铢",
    "MYR": "马来西亚林吉特",
    "CHF": "瑞士法郎",
    "NZD": "新西兰元",
    "RUB": "俄罗斯卢布",
    "VND": "越南盾",
    "PHP": "菲律宾比索",
    "INR": "印度卢比",
}

SOURCE_LABELS = {
    "holidays": "节假日",
    "fx": "汇率",
}


def enabled(conn: sqlite3.Connection) -> bool:
    return bool(meta.get_setting(conn, KEY_ENABLED, True))


def set_enabled(conn: sqlite3.Connection, value: bool) -> bool:
    meta.set_setting(conn, KEY_ENABLED, bool(value))
    return bool(value)


# ---------------- 节假日 ----------------


def fetch_year(year: int) -> list[dict] | None:
    """拉一年的节假日与调休。失败返回 None。"""
    payload = net.get_json(HOLIDAY_URL, {"date": year})
    if not isinstance(payload, dict) or payload.get("code") != 0:
        return None

    data = payload.get("data")
    if not isinstance(data, list):
        return None

    result: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        day = item.get("date")
        kind = item.get("daytype")
        if not _is_date(day) or kind not in (_ONLINE_HOLIDAY, _ONLINE_WORKDAY):
            continue
        result.append(
            {
                "day": day,
                "type": (
                    holidays_repo.HOLIDAY
                    if kind == _ONLINE_HOLIDAY
                    else holidays_repo.WORKDAY
                ),
                "name": (item.get("holiday") or "").strip(),
            }
        )
    return result


def sync_holidays(conn: sqlite3.Connection, year: int | None = None, overwrite: bool = False) -> dict:
    """同步一年的节假日。

    默认只填补本地没有的日期——你自己手改过的日期，线上数据不许动它。
    overwrite=True 才是「以线上为准」。
    """
    target = int(year or date.today().year)
    if not enabled(conn):
        return _holiday_result(False, target, reason="联网已关闭")

    online = fetch_year(target)
    if not online:
        return _holiday_result(False, target, reason="没拿到线上数据")

    local = holidays_repo.day_map(conn, f"{target}-01-01", f"{target}-12-31")
    added = 0
    updated = 0
    conflicts: list[dict] = []

    for item in online:
        current = local.get(item["day"])
        if current is None:
            holidays_repo.set_day(conn, item["day"], item["type"], item["name"])
            added += 1
            continue
        if current["type"] == item["type"]:
            continue
        if overwrite:
            holidays_repo.set_day(conn, item["day"], item["type"], item["name"])
            updated += 1
        else:
            conflicts.append(item)

    synced = meta.get_setting(conn, KEY_SYNCED_YEARS, [])
    if not isinstance(synced, list):
        synced = []
    if target not in synced:
        synced = sorted({*synced, target})
        meta.set_setting(conn, KEY_SYNCED_YEARS, synced)
    meta.set_setting(conn, KEY_LAST_SYNC, now_iso())

    return _holiday_result(
        True, target, added=added, updated=updated, conflicts=conflicts, total=len(online)
    )


def _holiday_result(ok: bool, year: int, **extra) -> dict:
    result = {
        "ok": ok,
        "source": "holidays",
        "source_label": SOURCE_LABELS["holidays"],
        "year": year,
        "added": 0,
        "updated": 0,
        "conflicts": [],
        "total": 0,
        "reason": "",
    }
    result.update(extra)
    return result


# ---------------- 汇率 ----------------


def refresh_rates(conn: sqlite3.Connection, force: bool = False) -> dict:
    """刷新外币汇率。存的是「1 单位外币 = 多少人民币」。"""
    if not enabled(conn):
        return _fx_result(False, reason="联网已关闭")
    if not force and _rates_fresh(conn):
        return _fx_result(True, updated=0, reason="汇率还新鲜")

    payload = net.get_json(FX_URL)
    if not isinstance(payload, dict) or payload.get("result") != "success":
        return _fx_result(False, reason="没拿到线上汇率")

    rates = payload.get("rates")
    if not isinstance(rates, dict):
        return _fx_result(False, reason="汇率数据格式不对")

    updated = 0
    for code, value in rates.items():
        if code == "CNY" or code not in CURRENCIES:
            continue
        if not isinstance(value, (int, float)) or value <= 0:
            continue
        # 接口以人民币为基准：1 人民币 = value 外币，我们要的是反过来的
        conn.execute(
            "INSERT INTO fx_rates (code, rate, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT (code) DO UPDATE SET rate = excluded.rate,"
            " updated_at = excluded.updated_at",
            (code, 1.0 / float(value), now_iso()),
        )
        updated += 1
    conn.commit()

    if updated == 0:
        return _fx_result(False, reason="没收到可用的币种")

    meta.set_setting(conn, KEY_LAST_SYNC, now_iso())
    return _fx_result(True, updated=updated)


def _fx_result(ok: bool, **extra) -> dict:
    result = {
        "ok": ok,
        "source": "fx",
        "source_label": SOURCE_LABELS["fx"],
        "updated": 0,
        "reason": "",
    }
    result.update(extra)
    return result


def _rates_fresh(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT MAX(updated_at) AS stamp FROM fx_rates").fetchone()
    if row is None or not row["stamp"]:
        return False
    try:
        stamp = datetime.fromisoformat(row["stamp"])
    except ValueError:
        return False
    return (datetime.now() - stamp) < FX_MAX_AGE


# ---------------- 汇率读写 ----------------


def rate_of(conn: sqlite3.Connection, code: str) -> float | None:
    if code == "CNY":
        return 1.0
    row = conn.execute("SELECT rate FROM fx_rates WHERE code = ?", (code,)).fetchone()
    if row is None:
        return None
    return float(row["rate"])


def known_currencies(conn: sqlite3.Connection) -> list[dict]:
    """有汇率可用的币种才算「已知」，没汇率的摆在界面上只会误导。"""
    rows = conn.execute("SELECT code, rate, updated_at FROM fx_rates").fetchall()
    rates = {row["code"]: float(row["rate"]) for row in rows}
    updated = {row["code"]: row["updated_at"] for row in rows}

    items = [{"code": "CNY", "name": "人民币", "rate": 1.0, "updated_at": ""}]
    for code, name in CURRENCIES.items():
        if code == "CNY" or code not in rates:
            continue
        items.append(
            {
                "code": code,
                "name": name,
                "rate": rates[code],
                "updated_at": updated.get(code, ""),
            }
        )
    return items


def convert(conn: sqlite3.Connection, amount: float, code: str) -> float | None:
    """把外币金额折成人民币。没汇率时返回 None，让调用方决定怎么办。"""
    if code == "CNY":
        return float(amount)
    rate = rate_of(conn, code)
    if rate is None:
        return None
    return float(amount) * rate


# ---------------- 汇总 ----------------


def sync_all(conn: sqlite3.Connection, force: bool = False) -> list[dict]:
    """启动时在后台跑的那些同步。返回值只是给日志看的。"""
    if not enabled(conn):
        return []

    results: list[dict] = []
    this_year = date.today().year
    synced = meta.get_setting(conn, KEY_SYNCED_YEARS, [])
    if not isinstance(synced, list):
        synced = []

    if force or this_year not in synced:
        results.append(sync_holidays(conn, this_year))

    # 国务院一般在 11 月发下一年的安排，到点了就顺手把明年也拉了
    next_year = this_year + 1
    if date.today().month >= 11 and (force or next_year not in synced):
        results.append(sync_holidays(conn, next_year))

    results.append(refresh_rates(conn, force=force))
    return results


def status(conn: sqlite3.Connection) -> dict:
    row = conn.execute("SELECT MAX(updated_at) AS stamp FROM fx_rates").fetchone()
    return {
        "enabled": enabled(conn),
        "last_sync_at": meta.get_setting(conn, KEY_LAST_SYNC),
        "synced_years": meta.get_setting(conn, KEY_SYNCED_YEARS, []),
        "fx_updated_at": (row["stamp"] if row and row["stamp"] else ""),
        "fx_count": int(
            conn.execute("SELECT COUNT(*) AS n FROM fx_rates").fetchone()["n"]
        ),
        "holiday_url": HOLIDAY_URL,
        "fx_url": FX_URL,
    }


def _is_date(text) -> bool:
    if not isinstance(text, str):
        return False
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True
