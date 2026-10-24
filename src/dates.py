"""日期工具。跨到 JS 边界时一律是 YYYY-MM-DD 字符串。"""

from __future__ import annotations

from datetime import date, datetime, timedelta

ISO = "%Y-%m-%d"

def iso(day: date) -> str:
    return day.strftime(ISO)


def parse(text: str) -> date:
    return datetime.strptime(text, ISO).date()


def today() -> date:
    return date.today()


def today_iso() -> str:
    return iso(date.today())


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def month_range(year: int, month: int) -> tuple[date, date]:
    first = date(year, month, 1)
    if month == 12:
        last = date(year, 12, 31)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    return first, last


def month_key(day: date) -> str:
    return day.strftime("%Y-%m")


def week_start(day: date) -> date:
    """周一为一周之始。"""
    return day - timedelta(days=day.weekday())


def year_range(year: int) -> tuple[date, date]:
    return date(year, 1, 1), date(year, 12, 31)


def clamp_progress(value: float) -> float:
    return 0.0 if value < 0 else 1.0 if value > 1 else value
