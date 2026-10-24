"""API 层是 Python 与 JS 的边界，这里守住它的契约。"""

import json
import os
from pathlib import Path

import pytest

from src.api import Api
from src.repo import habits, ledger, okr, tasks
from src.version import APP_VERSION, SCHEMA_VERSION


def is_json_safe(value):
    """边界上只能过 JSON 能表达的东西。"""
    try:
        json.loads(json.dumps(value, ensure_ascii=False))
        return True
    except (TypeError, ValueError):
        return False


def test_api_can_be_called_from_another_thread(conn):
    """pywebview 的回调来自别的线程，这条守的就是那个契约。"""
    import threading

    api = Api(conn)
    seen = []

    def worker():
        seen.append(api.bootstrap()["app_version"])

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()

    assert seen == [APP_VERSION]


def test_bootstrap_reports_where_data_lives(api):
    info = api.bootstrap()
    assert info["app_version"] == APP_VERSION
    assert info["schema_version"] == SCHEMA_VERSION
    assert info["data_home"]
    assert info["db_size_human"]


def test_home_is_json_safe_and_has_all_parts(api):
    assert is_json_safe(api.home())
    home = api.home()
    for key in ("today", "tasks", "habits", "nudges", "diet", "body", "upcoming_objectives"):
        assert key in home


def test_nudges_appear_and_disappear(api):
    """不要写死日期，否则跨天就假失败。"""
    today = api.bootstrap()["today"]

    api.add_task("要做的事", today)
    home = api.home()
    assert "今天还有 1 项待办没核销" in [nudge["text"] for nudge in home["nudges"]]

    api.set_task_done(1, True)
    api.save_weigh_in(today, 78, 22)
    api.add_entry(today, 20, "expense", "餐饮")
    home = api.home()
    assert [nudge["text"] for nudge in home["nudges"]] == []


def test_home_habits_carry_today_state(api):
    today = api.bootstrap()["today"]
    habit_id = api.add_habit("喝水")["id"]
    api.toggle_habit(habit_id, today)

    home = api.home()
    assert home["habit_today"] == {"done": 1, "total": 1}
    assert home["habits"][0]["done"] is True


def test_calendar_month_shape(api):
    api.add_task("十月的事", "2026-10-08")
    month = api.calendar_month(2026, 10)

    assert month["year"] == 2026
    assert len(month["weeks"][0]) == 7
    all_days = [day for week in month["weeks"] for day in week]
    assert sum(1 for day in all_days if day["in_month"]) >= 31

    national_day = next(day for day in all_days if day["day"] == "2026-10-01")
    assert national_day["kind"] == "holiday"
    assert national_day["holiday_name"] == "国庆节"

    makeup = next(day for day in all_days if day["day"] == "2026-10-10")
    assert makeup["kind"] == "workday"


def test_calendar_day_detail(api):
    api.add_task("那天的事", "2026-10-08")
    api.add_entry("2026-10-08", 66, "expense", "购物")

    detail = api.calendar_day("2026-10-08")
    assert detail["tasks"][0]["title"] == "那天的事"
    assert detail["entries"][0]["amount"] == 66
    assert detail["prev"] == "2026-10-07"
    assert detail["next"] == "2026-10-09"
    assert detail["weighed"] is False


def test_busy_level_rises_with_the_days_load(api):
    # 什么都没记的日子是 0 级
    assert api.calendar_day("2026-10-07")["busy"] == 0

    # 一项任务（2 分）+ 一笔账（1 分）= 3 → 2 级
    api.add_task("那天的事", "2026-10-08")
    api.add_entry("2026-10-08", 66, "expense", "购物")
    assert api.calendar_day("2026-10-08")["busy"] == 2

    # 再加习惯打勾、一餐、一次称量：3 + 1 + 1 + 1 = 6 → 3 级
    habit = api.add_habit("喝水")
    api.toggle_habit(habit["id"], "2026-10-08")
    api.save_meal("2026-10-08", "lunch", "牛肉面")
    api.save_weigh_in("2026-10-08", 70, 20)
    assert api.calendar_day("2026-10-08")["busy"] == 3

    # 整月视图里同一天带同一个值，空白日保持 0
    month = api.calendar_month(2026, 10)
    by_day = {day["day"]: day for week in month["weeks"] for day in week}
    assert by_day["2026-10-08"]["busy"] == 3
    assert by_day["2026-10-07"]["busy"] == 0


def test_okr_round_trip(api):
    objective = api.add_objective("减脂", "quarter", 2026, "2026-10-01", "2026-12-31")
    api.add_kr(objective["id"], "体重", 80, 80, 70, "kg", 2)
    api.add_kr(objective["id"], "跑步", 0, 50, 100, "km", 1)

    result = api.list_objectives(2026)[0]
    assert result["progress_percent"] == 17  # (0*2 + 0.5*1) / 3

    kr_id = result["key_results"][1]["id"]
    api.set_kr_value(kr_id, 100)
    assert api.list_objectives(2026)[0]["progress_percent"] == 33


def test_manual_override_through_api(api):
    objective = api.add_objective("想清楚方向", "year", 2026, "2026-01-01", "2026-12-31")
    api.add_kr(objective["id"], "读书", 0, 0, 12, "本", 1)

    api.update_objective(
        objective["id"], "想清楚方向", "year", 2026, "2026-01-01", "2026-12-31", "", 60
    )
    assert api.get_objective(objective["id"])["progress_percent"] == 60

    api.update_objective(
        objective["id"], "想清楚方向", "year", 2026, "2026-01-01", "2026-12-31", "", ""
    )
    assert api.get_objective(objective["id"])["progress_percent"] == 0


def test_kr_current_value_accepts_empty(api):
    objective = api.add_objective("目标", "year", 2026, "2026-01-01", "2026-12-31")
    api.add_kr(objective["id"], "存钱", 0, 0, 10000, "元", 1)
    updated = api.set_kr_value(1, 0)
    assert updated["key_results"][0]["current_value"] == 0


def test_ledger_month_view(api):
    api.add_entry("2026-10-03", 30, "expense", "餐饮")
    api.add_entry("2026-10-04", 20, "expense", "交通")
    api.add_entry("2026-09-04", 99, "expense", "餐饮")

    view = api.ledger_month("2026-10")
    assert view["summary"]["expense"] == 50
    assert view["previous"]["expense"] == 99
    assert view["categories"][0] == "餐饮"
    assert view["budget"]["total"] is None


def test_budget_round_trip(api):
    api.add_entry("2026-10-03", 300, "expense", "餐饮")
    api.set_budget("total", "", "2026-10", 200)

    view = api.ledger_month("2026-10")
    assert view["budget"]["total"]["over"] is True
    assert view["budget"]["total"]["id"]

    api.delete_budget(view["budget"]["total"]["id"], "2026-10")
    assert api.ledger_month("2026-10")["budget"]["total"] is None


def test_diet_and_water(api):
    api.save_meal("2026-10-23", "lunch", "鸡胸肉沙拉")
    api.set_water("2026-10-23", 5)

    day = api.diet_day("2026-10-23")
    assert day["recorded"] == 1
    assert day["water_cups"] == 5
    assert day["phrases"] == []
    assert "kcal_total" not in day


def test_body_view(api):
    api.save_weigh_in("2026-10-12", 79, 22.5)
    api.save_weigh_in("2026-10-19", 78, 22.0)
    api.save_body_targets(70, 15)

    status = api.body_status()
    assert status["week"]["logged_this_week"] is True
    assert status["targets"]["target_weight"] == 70
    assert [item["weight"] for item in status["series"]] == [79.0, 78.0]
    assert status["series"][1]["weight_delta"] == -1.0


def test_year_overview_returns_numbers_not_nested_dicts(api):
    api.add_task("做了", "2026-03-01")
    api.set_task_done(1, True)
    api.add_entry("2026-03-01", 88, "expense", "购物")

    overview = api.year_overview(2026)
    assert overview["tasks"]["rate"] == 1.0
    assert overview["ledger"]["expense"] == 88
    assert len(overview["months"]) == 12

    for entry in overview["heatmap"]["tasks"]:
        assert isinstance(entry["value"], float)


def test_holiday_import_through_api(api):
    result = api.import_holidays("2027-01-01~2027-01-03 放假 元旦\n2027-01-04 上班\n")
    assert result["written"] == 4

    month = api.calendar_month(2027, 1)
    days = [day for week in month["weeks"] for day in week]
    assert next(day for day in days if day["day"] == "2027-01-02")["kind"] == "holiday"
    assert next(day for day in days if day["day"] == "2027-01-04")["kind"] == "workday"


def test_moving_data_home_keeps_writing_to_the_new_place(api, tmp_path, monkeypatch):
    """搬家顺序反了会让连接指向已删除的文件，之后的写入全部落空。

    隔离是本测试的生命线：它刻意 delenv PERSONALHUB_HOME 去走「指针 / 默认位置」
    的解析分支，但 default_data_home() 读的是 APPDATA 而非 LOCALAPPDATA——
    所以必须把 APPDATA 也重定向到临时目录，否则默认位置会落到用户真实的
    %APPDATA%\\PersonalHub，move_data_home 的 old_db.unlink() 就把真库删了
    （历史事故：每跑一次全量测试就删一次用户数据）。
    """
    real_appdata = os.environ.get("APPDATA")
    real_db = (
        Path(real_appdata) / "PersonalHub" / "data.db" if real_appdata else None
    )
    real_mtime = real_db.stat().st_mtime if (real_db and real_db.exists()) else None

    local = tmp_path / "local"
    appdata = tmp_path / "appdata"
    (appdata / "PersonalHub").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.delenv("PERSONALHUB_HOME")

    api.add_task("搬家前", "2026-10-23")
    target = tmp_path / "new-home"

    api.move_data_home(str(target))
    api.add_task("搬家后", "2026-10-24")

    assert (target / "data.db").exists()
    assert api.bootstrap()["data_home"] == str(target)
    assert [task["title"] for task in api.list_tasks("2026-10-23")] == ["搬家前"]
    assert [task["title"] for task in api.list_tasks("2026-10-24")] == ["搬家后"]

    # 回归守护：绝不允许碰到用户真实数据家
    after = real_db.stat().st_mtime if (real_db and real_db.exists()) else None
    assert after == real_mtime, f"测试误改了真实数据家 {real_db}"


def test_habit_rows_keep_today_and_month_count_separate(api):
    """done 是当天有没有打勾，done_count 是这个月打了几次，两者不能互相覆盖。"""
    habit_id = api.add_habit("喝水")["id"]
    api.toggle_habit(habit_id, "2026-10-10")
    api.toggle_habit(habit_id, "2026-10-11")
    api.toggle_habit(habit_id, "2026-10-23")

    habit = api.list_habits("2026-10-23")[0]
    assert habit["done"] is True
    assert habit["done_count"] == 3
    assert habit["expected"] == 31


def test_habit_not_done_today_still_counts_the_month(api):
    habit_id = api.add_habit("喝水")["id"]
    api.toggle_habit(habit_id, "2026-10-11")

    habit = api.list_habits("2026-10-23")[0]
    assert habit["done"] is False
    assert habit["done_count"] == 1


def test_budget_status_exposes_ids_so_it_can_be_cleared(api):
    api.set_budget("total", "", "2026-10", 100)
    api.set_budget("category", "餐饮", "2026-10", 50)

    status = api.ledger_month("2026-10")["budget"]
    assert isinstance(status["total"]["id"], int)
    assert isinstance(status["by_category"][0]["id"], int)


def test_overspent_budget_shows_up_in_nudges(api):
    today = api.bootstrap()["today"]
    month = today[:7]

    api.set_budget("total", "", month, 100)
    api.add_entry(today, 300, "expense", "餐饮")
    api.save_weigh_in(today, 78, 22)

    texts = [nudge["text"] for nudge in api.home()["nudges"]]
    assert any("超总预算" in text for text in texts)


def test_empty_cadences_are_not_treated_as_zero_percent(api):
    overview = api.okr_overview(2026)
    assert all(cadence["count"] == 0 for cadence in overview["cadences"])

    api.add_objective("读 12 本书", "year", 2026, "2026-01-01", "2026-12-31")
    overview = api.okr_overview(2026)
    year = next(item for item in overview["cadences"] if item["cadence"] == "year")
    assert year["count"] == 1
    assert next(item for item in overview["cadences"] if item["cadence"] == "week")["count"] == 0


def test_export_round_trip(api, tmp_path):
    api.add_task("记账", "2026-10-23")
    api.add_entry("2026-10-23", 42, "expense", "餐饮", note="午饭")

    payload = json.loads(Path(api.export_json()["path"]).read_text(encoding="utf-8"))
    assert payload["tasks"][0]["title"] == "记账"
    assert payload["holidays"]

    csv_text = Path(api.export_csv()["path"]).read_text(encoding="utf-8-sig")
    assert "2026-10-23,支出,42.00,CNY,42.00,餐饮,,午饭" in csv_text
