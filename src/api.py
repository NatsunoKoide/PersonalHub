"""暴露给前端的方法集合。

只有这一层是 JSON 边界，日期一律 YYYY-MM-DD 字符串，返回值必须是可序列化的普通类型。
"""

from __future__ import annotations

import functools
import json
import os
import sqlite3
import subprocess
import threading
from datetime import date, timedelta
from pathlib import Path

from . import db, foods, market, market_service, paths, sync
from .dates import (
    iso,
    month_range,
    month_key,
    now_iso,
    parse,
    today,
    today_iso,
    week_start,
    year_range,
)
from .repo import body, diet, habits, holidays, ledger, meta, okr, tasks
from .repo import market as market_repo
from .version import APP_NAME, APP_VERSION, SCHEMA_VERSION


class Api:
    """挂在 pywebview 的 js_api 上，前端用 pywebview.api.xxx() 调用。"""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        # 后台刷新服务要用自己的连接，路径从这里取（PRAGMA 不碰业务数据）
        row = conn.execute("PRAGMA database_list").fetchone()
        self.db_path = row[2] if row and row[2] else str(paths.database_path())

    # ---------------- 启动与系统 ----------------

    def bootstrap(self) -> dict:
        info = meta.data_info(self.conn)
        return {
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            "schema_version": SCHEMA_VERSION,
            "today": today_iso(),
            **info,
        }

    def data_info(self) -> dict:
        return meta.data_info(self.conn)

    def open_data_home(self) -> dict:
        target = paths.data_home()
        try:
            os.startfile(str(target))  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            subprocess.Popen(["explorer", str(target)])
        return {"opened": str(target)}

    def backup_now(self) -> dict:
        target = db.create_backup(self.conn)
        return {"path": str(target), "size_human": paths.human_size(target.stat().st_size)}

    def move_data_home(self, target: str) -> dict:
        """搬家顺序很关键：先复制数据 → 再换连接 → 最后才删旧库。

        顺序反了会让连接指向一个已删除的文件，之后的写入全部落空。
        """
        destination = Path(target).expanduser()
        destination.mkdir(parents=True, exist_ok=True)
        new_db = destination / paths.DB_NAME
        old_db = paths.database_path()

        staging = db.connect(new_db)
        self.conn.backup(staging)
        db.migrate(staging)
        staging.close()

        old_conn = self.conn
        paths.set_data_home(destination)

        self.conn = db.connect(paths.database_path())
        db.migrate(self.conn)
        old_conn.close()

        # Windows 上文件要等连接彻底关掉才删得掉
        try:
            if old_db.exists() and old_db != new_db:
                old_db.unlink()
        except OSError:
            pass

        return meta.data_info(self.conn)

    def export_json(self) -> dict:
        target = self._export_dir() / f"personalhub-{today_iso()}.json"
        payload = meta.export_payload(self.conn)
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {"path": str(target), "size_human": paths.human_size(target.stat().st_size)}

    def export_csv(self) -> dict:
        target = self._export_dir() / f"ledger-{today_iso()}.csv"
        target.write_text(meta.export_ledger_csv(self.conn), encoding="utf-8-sig")
        return {"path": str(target), "size_human": paths.human_size(target.stat().st_size)}

    def _export_dir(self) -> Path:
        target = paths.data_home() / "exports"
        target.mkdir(parents=True, exist_ok=True)
        return target

    # ---------------- 首页 ----------------

    def home(self) -> dict:
        day = today_iso()
        current = today()

        habit_items = self._habit_rows(day, *_month_bounds(current))
        habit_total = len(habit_items)
        habit_done_today = sum(1 for item in habit_items if item["done"])

        return {
            "today": day,
            "today_label": f"{current.year} 年 {current.month} 月 {current.day} 日",
            "nudges": self._nudges(day),
            "tasks": tasks.list_day(self.conn, day),
            "overdue": tasks.overdue(self.conn, day),
            "habits": habit_items,
            "habit_today": {"done": habit_done_today, "total": habit_total},
            "today_expense": ledger.day_total(self.conn, day),
            "diet": diet.get_day(self.conn, day),
            "body": body.week_status(self.conn, day),
            "body_targets": body.targets(self.conn),
            "upcoming_objectives": okr.upcoming(self.conn, day, 30),
        }

    def _habit_rows(self, day: str, start: str, end: str) -> list[dict]:
        """习惯清单统一入口：done 是当天有没有打勾，done_count 是本区间打了几次。"""
        rows = []
        for habit in habits.list_all(self.conn):
            stats = habits.habit_stats(self.conn, habit["id"], start, end)
            item = dict(habit)
            item.update(stats)
            item["done_count"] = stats["done"]
            item["done"] = habits.logged_on(self.conn, habit["id"], day)
            item["streak"] = habits.streak(self.conn, habit["id"], today())
            rows.append(item)
        return rows

    def _nudges(self, day: str) -> list[dict]:
        items: list[dict] = []

        undone = [
            task for task in tasks.list_day(self.conn, day) if not task["done"]
        ]
        if undone:
            items.append(
                {"kind": "tasks", "tab": "tasks", "text": f"今天还有 {len(undone)} 项待办没核销"}
            )

        overdue = tasks.overdue(self.conn, day)
        if overdue:
            items.append(
                {"kind": "tasks", "tab": "tasks", "text": f"{len(overdue)} 项任务已逾期"}
            )

        if ledger.day_total(self.conn, day) == 0:
            items.append({"kind": "ledger", "tab": "ledger", "text": "今天还没记账"})

        for over in self._overspent(day):
            items.append(over)

        week = body.week_status(self.conn, day)
        if not week["logged_this_week"]:
            items.append({"kind": "body", "tab": "body", "text": "本周还没称重"})

        for objective in okr.upcoming(self.conn, day, 30):
            items.append(
                {
                    "kind": "okr",
                    "tab": "okr",
                    "text": f"「{objective['title']}」{objective['period_end']} 到期，当前 {objective['progress_percent']}%",
                }
            )

        return items

    def _overspent(self, day: str) -> list[dict]:
        status = ledger.budget_status(self.conn, month_key(parse(day)))
        items = []
        if status["total"] and status["total"]["over"]:
            items.append({
                "kind": "ledger",
                "tab": "ledger",
                "text": f"本月支出已超总预算 {status['total']['used'] - status['total']['limit']:.0f} 元",
            })
        for budget in status["by_category"]:
            if budget["over"]:
                items.append({
                    "kind": "ledger",
                    "tab": "ledger",
                    "text": f"「{budget['category']}」本月已超预算 {budget['used'] - budget['limit']:.0f} 元",
                })
        return items

    # ---------------- 任务 ----------------

    def list_tasks(self, day: str) -> list[dict]:
        return tasks.list_day(self.conn, day)

    def list_tasks_range(self, start: str, end: str) -> list[dict]:
        return tasks.list_range(self.conn, start, end)

    def add_task(self, title: str, due_date: str, tag: str = "", priority: int = 1) -> dict:
        task_id = tasks.add(self.conn, title, due_date, tag, int(priority))
        return tasks.get(self.conn, task_id)

    def update_task(
        self, task_id: int, title: str, due_date: str, tag: str, priority: int
    ) -> dict:
        tasks.update(self.conn, task_id, title, due_date, tag, int(priority))
        return tasks.get(self.conn, task_id)

    def set_task_done(self, task_id: int, done: bool) -> dict:
        tasks.set_done(self.conn, task_id, bool(done))
        return {"id": task_id, "done": bool(done)}

    def postpone_task(self, task_id: int, due_date: str) -> dict:
        task = tasks.get(self.conn, task_id)
        tasks.update(
            self.conn, task_id, task["title"], due_date, task["tag"], task["priority"]
        )
        return tasks.get(self.conn, task_id)

    def delete_task(self, task_id: int) -> dict:
        tasks.remove(self.conn, task_id)
        return {"id": task_id}

    def task_tags(self) -> list[str]:
        return tasks.tags(self.conn)

    # ---------------- 习惯 ----------------

    def list_habits(self, day: str | None = None) -> list[dict]:
        day = day or today_iso()
        return self._habit_rows(day, *_month_bounds(parse(day)))

    def add_habit(self, name: str, cadence: str = "daily") -> dict:
        habit_id = habits.add(self.conn, name, cadence)
        return self._habit_view(habit_id)

    def update_habit(self, habit_id: int, name: str, cadence: str) -> dict:
        habits.update(self.conn, habit_id, name, cadence)
        return self._habit_view(habit_id)

    def delete_habit(self, habit_id: int) -> dict:
        habits.remove(self.conn, habit_id)
        return {"id": habit_id}

    def toggle_habit(self, habit_id: int, day: str) -> dict:
        state = habits.toggle(self.conn, habit_id, day)
        return {"habit_id": habit_id, "day": day, "done": state}

    def _habit_view(self, habit_id: int) -> dict:
        start, end = _month_bounds()
        stats = habits.habit_stats(self.conn, habit_id, start, end)
        item = habits.get(self.conn, habit_id)
        item.update(stats)
        item["streak"] = habits.streak(self.conn, habit_id, today())
        return item

    # ---------------- OKR ----------------

    def list_objectives(self, year: int | None = None, cadence: str | None = None) -> list[dict]:
        return okr.list_all(self.conn, year, cadence)

    def get_objective(self, objective_id: int) -> dict | None:
        return okr.get(self.conn, objective_id)

    def add_objective(
        self,
        title: str,
        cadence: str,
        year: int,
        period_start: str | None = None,
        period_end: str | None = None,
        note: str = "",
    ) -> dict:
        objective_id = okr.add(self.conn, title, cadence, int(year), period_start, period_end, note)
        return okr.get(self.conn, objective_id)

    def update_objective(
        self,
        objective_id: int,
        title: str,
        cadence: str,
        year: int,
        period_start: str | None,
        period_end: str | None,
        note: str,
        manual_progress,
    ) -> dict:
        okr.update(
            self.conn,
            objective_id,
            title,
            cadence,
            int(year),
            period_start or None,
            period_end or None,
            note,
            None if manual_progress in ("", None) else float(manual_progress),
        )
        return okr.get(self.conn, objective_id)

    def delete_objective(self, objective_id: int) -> dict:
        okr.remove(self.conn, objective_id)
        return {"id": objective_id}

    def add_kr(
        self,
        objective_id: int,
        name: str,
        start_value: float,
        current_value: float,
        target_value: float,
        unit: str = "",
        weight: float = 1,
    ) -> dict:
        okr.add_kr(
            self.conn,
            objective_id,
            name,
            float(start_value),
            float(current_value),
            float(target_value),
            unit,
            float(weight),
        )
        return okr.get(self.conn, objective_id)

    def update_kr(
        self,
        kr_id: int,
        name: str,
        start_value: float,
        current_value: float,
        target_value: float,
        unit: str,
        weight: float,
    ) -> dict:
        okr.update_kr(
            self.conn,
            kr_id,
            name,
            float(start_value),
            float(current_value),
            float(target_value),
            unit,
            float(weight),
        )
        return okr.get(self.conn, okr.objective_id_of(self.conn, int(kr_id)))

    def set_kr_value(self, kr_id: int, current_value: float) -> dict:
        okr.set_kr_value(self.conn, kr_id, float(current_value))
        return okr.get(self.conn, okr.objective_id_of(self.conn, int(kr_id)))

    def delete_kr(self, kr_id: int) -> dict:
        objective_id = okr.objective_id_of(self.conn, int(kr_id))
        okr.remove_kr(self.conn, kr_id)
        return okr.get(self.conn, objective_id)

    def okr_overview(self, year: int) -> dict:
        return {
            "year": int(year),
            "cadences": okr.cadence_overview(self.conn, int(year)),
            "objectives": okr.list_all(self.conn, year=int(year)),
        }

    # ---------------- 记账 ----------------

    def ledger_month(self, month: str) -> dict:
        return {
            "month": month,
            "summary": ledger.month_summary(self.conn, month),
            "previous": ledger.previous_month_summary(self.conn, month),
            "entries": ledger.list_month(self.conn, month),
            "categories": ledger.categories(self.conn),
            "currencies": sync.known_currencies(self.conn),
            "budget": ledger.budget_status(self.conn, month),
        }

    def ledger_year(self, year: int) -> dict:
        return {
            "year": int(year),
            "months": ledger.year_months(self.conn, int(year)),
            "summary": ledger.year_summary(self.conn, int(year)),
        }

    def add_entry(
        self,
        day: str,
        amount: float,
        direction: str = "expense",
        category: str = "其他",
        method: str = "",
        note: str = "",
        currency: str = "CNY",
    ) -> dict:
        entry_id = ledger.add(
            self.conn,
            day,
            float(amount),
            direction,
            category,
            method,
            note,
            currency,
            _converted(self.conn, amount, currency),
        )
        return ledger.get(self.conn, entry_id)

    def update_entry(
        self,
        entry_id: int,
        day: str,
        amount: float,
        direction: str,
        category: str,
        method: str,
        note: str,
        currency: str = "CNY",
    ) -> dict:
        ledger.update(
            self.conn,
            entry_id,
            day,
            float(amount),
            direction,
            category,
            method,
            note,
            currency,
            _converted(self.conn, amount, currency),
        )
        return ledger.get(self.conn, entry_id)

    def delete_entry(self, entry_id: int) -> dict:
        ledger.remove(self.conn, entry_id)
        return {"id": entry_id}

    def ledger_categories(self) -> list[str]:
        return ledger.categories(self.conn)

    def add_category(self, name: str) -> list[str]:
        ledger.add_category(self.conn, name)
        return ledger.categories(self.conn)

    def rename_category(self, old: str, new: str) -> list[str]:
        ledger.rename_category(self.conn, old, new)
        return ledger.categories(self.conn)

    def delete_category(self, name: str) -> list[str]:
        ledger.remove_category(self.conn, name)
        return ledger.categories(self.conn)

    def set_budget(self, scope: str, category: str, month: str, limit_amount: float) -> dict:
        ledger.set_budget(self.conn, scope, category, month, float(limit_amount))
        return ledger.budget_status(self.conn, month)

    def delete_budget(self, budget_id: int, month: str) -> dict:
        ledger.remove_budget(self.conn, budget_id)
        return ledger.budget_status(self.conn, month)

    # ---------------- 饮食 ----------------

    def diet_day(self, day: str) -> dict:
        result = diet.get_day(self.conn, day)
        result["phrases"] = diet.phrases(self.conn)
        result["targets"] = body.targets(self.conn)
        return result

    def save_meal(self, day: str, slot: str, content: str) -> dict:
        diet.save_slot(self.conn, day, slot, content)
        return diet.get_day(self.conn, day)

    def set_water(self, day: str, cups: int) -> dict:
        diet.set_water(self.conn, day, int(cups))
        return diet.get_day(self.conn, day)

    def set_day_note(self, day: str, note: str) -> dict:
        diet.set_note(self.conn, day, note)
        return diet.get_day(self.conn, day)

    def diet_phrases(self) -> list[dict]:
        return diet.phrases(self.conn)

    def add_phrase(self, text: str) -> list[dict]:
        diet.add_phrase(self.conn, text)
        return diet.phrases(self.conn)

    def delete_phrase(self, phrase_id: int) -> list[dict]:
        diet.remove_phrase(self.conn, phrase_id)
        return diet.phrases(self.conn)

    # --- 常见菜名表：内置，离线可用 ---

    def food_search(self, keyword: str) -> list[dict]:
        return foods.search(keyword)

    def food_groups(self) -> list[str]:
        return list(foods.GROUPS)

    def food_total(self) -> int:
        return foods.count()

    def add_food_to_meal(self, day: str, slot: str, name: str) -> dict:
        """把菜名点进这一餐，只记名字，不算热量。"""
        food = foods.find(name)
        if food is None:
            return diet.get_day(self.conn, day)

        current = diet.get_day(self.conn, day)
        target = next((item for item in current["slots"] if item["slot"] == slot), None)
        if target is None:
            return current

        existing = (target["content"] or "").strip()
        diet.save_slot(
            self.conn,
            day,
            slot,
            f"{existing}，{food.name}" if existing else food.name,
        )
        return diet.get_day(self.conn, day)

    # ---------------- 身体 ----------------

    def body_series(self, limit: int = 120) -> list[dict]:
        return body.list_series(self.conn, int(limit))

    def body_status(self) -> dict:
        return {
            "series": body.list_series(self.conn),
            "week": body.week_status(self.conn, today_iso()),
            "targets": body.targets(self.conn),
        }

    def save_weigh_in(self, day: str, weight, body_fat, note: str = "") -> dict:
        body.upsert(
            self.conn,
            day,
            None if weight in ("", None) else float(weight),
            None if body_fat in ("", None) else float(body_fat),
            note,
        )
        return body.week_status(self.conn, today_iso())

    def delete_weigh_in(self, day: str) -> dict:
        body.remove(self.conn, day)
        return body.week_status(self.conn, today_iso())

    def save_body_targets(self, target_weight, target_body_fat) -> dict:
        body.set_targets(
            self.conn,
            None if target_weight in ("", None) else float(target_weight),
            None if target_body_fat in ("", None) else float(target_body_fat),
        )
        return body.targets(self.conn)

    # ---------------- 行情 ----------------

    def market_overview(self) -> dict:
        """行情页一次拿全：指数、币圈三币、自选（含 30 日区间涨跌）、
        板块榜（A股 + 币圈）、涨跌停、四市场温度。

        **只读本地，一个请求都不发**：报价取快照表，汇总与温度取
        market_aggregates 缓存。行情页打开时靠它秒开；新鲜数据由后台
        刷新服务（market_service）异步补齐，UI 轮询到 syncing=false
        再刷新一次界面。取数与全局锁的分离见 docs/adr/0010。

        不同市场的行情日不完全对齐，所以不假设大家同一天，各自取最新。
        """
        aggregates = market_repo.load_aggregates(self.conn)

        def quote_for(code: str) -> dict | None:
            return market_repo.latest_quote(self.conn, code)

        indices = [
            quote
            for quote in (quote_for(code) for _secid, code, _m in market.INDEX_SECIDS)
            if quote
        ]

        # 币圈三币常驻卡片：报价不到就回落库里最近一条，再没有就占位
        crypto = []
        for code in market.CRYPTO_COINS:
            quote = quote_for(code)
            if quote:
                crypto.append({
                    "code": code,
                    "name": market.CRYPTO_NAMES.get(code, code),
                    "price": quote["price"],
                    "change_pct": quote["change_pct"],
                    "change_amount": quote["change_amount"],
                    "day": quote["day"],
                })

        watch = []
        for item in market_repo.list_watch(self.conn):
            quote = quote_for(item["code"])
            window = market_repo.window_change(self.conn, item["code"], 30)
            watch.append({
                "id": item["id"],
                "code": item["code"],
                "name": item["name"],
                "market": item["market"],
                "kind": item["kind"],
                "price": quote["price"] if quote else None,
                "change_pct": quote["change_pct"] if quote else None,
                "change_amount": quote["change_amount"] if quote else None,
                "window_pct": window["pct"] if window else None,
                "window_from": window["from_day"] if window else None,
                "window_to": window["to_day"] if window else None,
            })

        return {
            "day": market_repo.latest_stock_day(self.conn) or market_repo.latest_snapshot_day(self.conn),
            "net_enabled": sync.enabled(self.conn),
            "syncing": market_service.service.status()["syncing"],
            "last_updated": market_service.service.status()["last_finished_at"],
            "indices": indices,
            "crypto": crypto,
            "watch": watch,
            "sectors_up": aggregates.get("sectors_up") or [],
            "sectors_down": aggregates.get("sectors_down") or [],
            "us_sectors_up": aggregates.get("us_sectors_up") or [],
            "us_sectors_down": aggregates.get("us_sectors_down") or [],
            "crypto_sectors_up": aggregates.get("crypto_sectors_up") or [],
            "crypto_sectors_down": aggregates.get("crypto_sectors_down") or [],
            "limits": aggregates.get("limits") or {"up": None, "down": None},
            "temperature": aggregates.get("temperature") or [],
            "benchmarks": self._market_benchmarks(),
        }

    def _market_benchmarks(self) -> list[dict]:
        """30 日走势用三条基准线：A股看上证，美股看纳指，币圈看 BTC。"""
        result = []
        for code in ("sh000001", "usIXIC", "BTCUSDT"):
            series = market_repo.history(self.conn, code, 30)
            if len(series) >= 2:
                result.append({"code": code, "series": series})
        return result

    def market_watch_add(self, raw_code: str) -> dict:
        """加自选。认不出代码、查不到行情都直接报错，让界面告诉用户哪儿错了。

        自己管锁（不在 _synchronize 的全局锁里）：本地检查与落库持锁，
        中间的联网查价**不持锁**——其他页签的请求这时能正常走。
        见 docs/adr/0010。
        """
        with Api._lock:
            if not sync.enabled(self.conn):
                raise ValueError("联网总开关关着，先到设置里打开才能添加自选")
            item = market.normalize_code(raw_code)
            if item is None:
                raise ValueError("认不出这个代码：A股 6 位数字，港股如 00700，美股如 AAPL，币圈如 BTC")
            existing = market_repo.find_watch_by_code(self.conn, item["code"])
            if existing:
                raise ValueError(f"{existing['name']} 已经在自选里了")

        # 联网查价：全局锁已放开，行情页之外的操作不会被这次请求卡住
        if item["market"] == "crypto":
            quotes = market.fetch_crypto_quotes([item["code"]])
        else:
            quotes = market.fetch_quotes([item["code"]])
        if not quotes:
            raise ValueError("没查到这只代码的行情，检查一下是否输入正确")

        quote = quotes[0]
        with Api._lock:
            # 查价这些时间里可能有人抢先加了同一只，落库前再查一次
            existing = market_repo.find_watch_by_code(self.conn, item["code"])
            if existing:
                raise ValueError(f"{existing['name']} 已经在自选里了")
            watch_id = market_repo.add_watch(
                self.conn, item["code"], quote["name"], item["market"], item["kind"]
            )
            market_repo.upsert_snapshots(
                self.conn,
                [{**quote, "market": item["market"], "kind": item["kind"]}],
            )
        return {"id": watch_id, "code": item["code"], "name": quote["name"]}

    def market_watch_remove(self, watch_id: int) -> dict:
        market_repo.remove_watch(self.conn, int(watch_id))
        return {"id": int(watch_id)}

    def market_refresh(self, force: bool = False) -> dict:
        """踢一次后台刷新，立即返回，不等待网络。

        UI 的用法：打开行情页或点刷新时调用，返回里 syncing=true 就
        开始轮询 market_overview，syncing=false 时那一轮数据已落库。
        force=True 供刷新按钮用，绕过 60 秒自动节流。
        """
        return market_service.service.refresh(self.db_path, force=bool(force))

    # ---------------- 日历与节假日 ----------------

    def calendar_month(self, year: int, month: int) -> dict:
        year, month = int(year), int(month)
        first, last = month_range(year, month)
        grid_first = week_start(first)
        grid_last = week_start(last) + timedelta(days=6)

        start_iso, end_iso = iso(grid_first), iso(grid_last)
        task_counts = tasks.counts_by_day(self.conn, start_iso, end_iso)
        habit_logs = habits.logs_by_day(self.conn, start_iso, end_iso)
        habit_total = len(habits.list_all(self.conn))
        expenses = ledger.daily_expense(self.conn, start_iso, end_iso)
        weigh_days = body.days_in_range(self.conn, start_iso, end_iso)
        meals = diet.recorded_by_day(self.conn, start_iso, end_iso)
        holiday_map = holidays.day_map(self.conn, start_iso, end_iso)

        days: list[dict] = []
        cursor = grid_first
        while cursor <= grid_last:
            key = iso(cursor)
            counts = task_counts.get(key, {"total": 0, "done": 0})
            holiday = holiday_map.get(key)
            is_weekend = cursor.weekday() >= 5
            kind = "normal"
            if holiday:
                kind = holiday["type"]
            elif is_weekend:
                kind = "weekend"
            days.append(
                {
                    "day": key,
                    "day_number": cursor.day,
                    "month": cursor.month,
                    "in_month": cursor.month == month,
                    "is_today": key == today_iso(),
                    "kind": kind,
                    "holiday_name": holiday["name"] if holiday else "",
                    "tasks": counts,
                    "habits_done": len(habit_logs.get(key, [])),
                    "habits_total": habit_total,
                    "expense": expenses.get(key, 0.0),
                    "meals": meals.get(key, 0),
                    "weighed": key in weigh_days,
                    "busy": _busy_level(
                        counts["total"],
                        len(habit_logs.get(key, [])),
                        1 if expenses.get(key, 0.0) else 0,
                        meals.get(key, 0),
                        key in weigh_days,
                    ),
                }
            )
            cursor += timedelta(days=1)

        weeks = [days[index : index + 7] for index in range(0, len(days), 7)]
        return {"year": year, "month": month, "weeks": weeks}

    def calendar_day(self, day: str) -> dict:
        current = parse(day)
        day_tasks = tasks.list_day(self.conn, day)
        day_habits = habits.with_done_on(self.conn, day)
        day_entries = ledger.list_range(self.conn, day, day)
        diet_day = diet.get_day(self.conn, day)
        weighed = day in body.days_in_range(self.conn, day, day)
        return {
            "day": day,
            "tasks": day_tasks,
            "habits": day_habits,
            "entries": day_entries,
            "diet": diet_day,
            "weighed": weighed,
            "holiday": holidays.day_map(self.conn, day, day).get(day),
            "prev": iso(current - timedelta(days=1)),
            "next": iso(current + timedelta(days=1)),
            "busy": _busy_level(
                len(day_tasks),
                sum(1 for item in day_habits if item["done"]),
                len(day_entries),
                diet_day["recorded"],
                weighed,
            ),
        }

    def holidays_year(self, year: int) -> list[dict]:
        return holidays.list_year(self.conn, int(year))

    def set_holiday(self, day: str, kind: str, name: str = "") -> list[dict]:
        holidays.set_day(self.conn, day, kind, name)
        return holidays.list_year(self.conn, int(day[:4]))

    def delete_holiday(self, day: str) -> list[dict]:
        holidays.remove_day(self.conn, day)
        return holidays.list_year(self.conn, int(day[:4]))

    def import_holidays(self, text: str) -> dict:
        written = holidays.import_text(self.conn, text)
        return {"written": written, "latest": holidays.list_year(self.conn, today().year)}

    # ---------------- 联网 ----------------

    def net_status(self) -> dict:
        return sync.status(self.conn)

    def set_net_enabled(self, value: bool) -> dict:
        """总开关。关掉之后一个请求都不会发。"""
        sync.set_enabled(self.conn, bool(value))
        return sync.status(self.conn)

    def sync_now(self) -> list[dict]:
        """手动把节假日和汇率都刷一遍，返回每项的结果清单。"""
        return sync.sync_all(self.conn, force=True)

    def sync_holidays_now(self, year: int, overwrite: bool = False) -> dict:
        """同步一年的节假日。overwrite 为真才是「以线上为准」。"""
        return sync.sync_holidays(self.conn, int(year), bool(overwrite))

    def refresh_rates_now(self) -> dict:
        return sync.refresh_rates(self.conn, force=True)

    # ---------------- 年度总览 ----------------

    def year_overview(self, year: int) -> dict:
        year = int(year)
        start, end = year_range(year)
        start_iso, end_iso = iso(start), iso(end)

        today_date = today()
        last = min(end, today_date) if year == today_date.year else end

        return {
            "year": year,
            "okr": okr.cadence_overview(self.conn, year),
            "tasks": tasks.year_stats(self.conn, start_iso, iso(last)),
            "habits": habits.year_stats(self.conn, start_iso, iso(last)),
            "ledger": ledger.year_summary(self.conn, year),
            "months": ledger.year_months(self.conn, year),
            "heatmap": self._heatmap(year),
        }

    def _heatmap(self, year: int) -> dict:
        start, end = year_range(year)
        start_iso, end_iso = iso(start), iso(end)

        task_counts = tasks.counts_by_day(self.conn, start_iso, end_iso)
        habit_logs = habits.logs_by_day(self.conn, start_iso, end_iso)
        expenses = ledger.daily_expense(self.conn, start_iso, end_iso)
        weigh = body.days_in_range(self.conn, start_iso, end_iso)
        meals = diet.recorded_by_day(self.conn, start_iso, end_iso)

        return {
            "tasks": _pack(
                {day: float(counts["done"]) for day, counts in task_counts.items()}
            ),
            "habits": _pack({day: float(len(ids)) for day, ids in habit_logs.items()}),
            "expense": _pack(expenses),
            "weigh": _pack({day: 1.0 for day in weigh}),
            "meals": _pack({day: float(count) for day, count in meals.items()}),
        }


def _synchronize():
    """pywebview 的回调来自别的线程，把所有对外方法串行化。

    连接本身允许跨线程，但没有锁的话两个请求交错着写会出事。
    用可重入锁，这样方法内部互相调用也不会把自己锁死。

    例外见 SELF_LOCKING：少数方法的联网段不能持锁，否则一次查价
    就把其他页签全卡住（ADR 0010）。这些方法自己分段持 Api._lock。
    新增对外方法时如果要发网络请求，先想清楚该不该进这个集合。
    """
    lock = threading.RLock()
    Api._lock = lock

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with lock:
                return func(*args, **kwargs)

        return wrapper

    for name, method in list(vars(Api).items()):
        if not name.startswith("_") and callable(method) and name not in SELF_LOCKING:
            setattr(Api, name, decorator(method))


# 自己管锁的方法：联网段不持全局锁。加名字前先读 ADR 0010。
SELF_LOCKING = {"market_watch_add"}


_synchronize()


def _busy_level(task_total: int, habits_done: int, ledger_activity: int, meals: int, weighed: bool) -> int:
    """当天的繁忙程度，0-4 级。日历格子底色和单日全貌都用它。

    任务按 2 分计：排了就是负担，跟完没完成无关；习惯打勾、记一笔账、
    记一餐、称一次重各 1 分。整天什么都不记就是 0 级。
    分档按「一天最多十几分」设：空 → 1-2 → 3-5 → 6-8 → 9 以上。
    """
    score = (
        task_total * 2
        + habits_done
        + ledger_activity
        + meals
        + (1 if weighed else 0)
    )
    if score <= 0:
        return 0
    if score <= 2:
        return 1
    if score <= 5:
        return 2
    if score <= 8:
        return 3
    return 4


def _pack(mapping: dict[str, float]) -> list[dict]:
    return [{"day": day, "value": value} for day, value in sorted(mapping.items())]


def _converted(conn: sqlite3.Connection, amount, currency: str) -> float:
    """折成人民币。没有汇率时退回原值——保住这笔账比算出精确数字重要。"""
    value = sync.convert(conn, float(amount), currency)
    return float(value) if value is not None else float(amount)


def _month_bounds(day: date | None = None) -> tuple[str, str]:
    current = day or today()
    first, last = month_range(current.year, current.month)
    return iso(first), iso(last)


