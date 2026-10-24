from datetime import date

from src.repo import habits, tasks


def test_task_lifecycle(conn):
    task_id = tasks.add(conn, "交房租", "2026-10-23", tag="生活", priority=2)

    assert tasks.get(conn, task_id)["done"] == 0
    tasks.set_done(conn, task_id, True)

    task = tasks.get(conn, task_id)
    assert task["done"] == 1
    assert task["done_at"] is not None

    tasks.set_done(conn, task_id, False)
    assert tasks.get(conn, task_id)["done_at"] is None


def test_task_order_puts_undone_high_priority_first(conn):
    tasks.add(conn, "低优先级", "2026-10-23", priority=0)
    high = tasks.add(conn, "高优先级", "2026-10-23", priority=2)
    tasks.add(conn, "已完成", "2026-10-23", priority=2)
    tasks.set_done(conn, high, False)

    titles = [task["title"] for task in tasks.list_day(conn, "2026-10-23")]
    assert titles[0] == "高优先级"


def test_counts_by_day_and_year_stats(conn):
    done = tasks.add(conn, "做了", "2026-01-05")
    tasks.set_done(conn, done, True)
    tasks.add(conn, "没做", "2026-01-06")

    counts = tasks.counts_by_day(conn, "2026-01-01", "2026-01-31")
    assert counts["2026-01-05"] == {"total": 1, "done": 1}
    assert counts["2026-01-06"] == {"total": 1, "done": 0}

    stats = tasks.year_stats(conn, "2026-01-01", "2026-12-31")
    assert stats == {"total": 2, "done": 1, "rate": 0.5}


def test_overdue_lists_only_unfinished_past_tasks(conn):
    tasks.add(conn, "过去的没做", "2026-10-20")
    past_done = tasks.add(conn, "过去的做了", "2026-10-21")
    tasks.set_done(conn, past_done, True)
    tasks.add(conn, "未来的", "2026-10-25")

    titles = [task["title"] for task in tasks.overdue(conn, "2026-10-23")]
    assert titles == ["过去的没做"]


def test_habit_toggle_is_idempotent_per_day(conn):
    habit_id = habits.add(conn, "喝水 2L")

    assert habits.toggle(conn, habit_id, "2026-10-23") is True
    assert habits.toggle(conn, habit_id, "2026-10-23") is False


def test_streak_skips_today_when_not_yet_done(conn):
    habit_id = habits.add(conn, "早起")
    habits.toggle(conn, habit_id, "2026-10-22")
    habits.toggle(conn, habit_id, "2026-10-21")

    # 今天还没打勾不算断链
    assert habits.streak(conn, habit_id, date(2026, 10, 23)) == 2


def test_streak_breaks_on_gap(conn):
    habit_id = habits.add(conn, "早起")
    habits.toggle(conn, habit_id, "2026-10-23")
    habits.toggle(conn, habit_id, "2026-10-21")

    assert habits.streak(conn, habit_id, date(2026, 10, 23)) == 1


def test_weekly_habit_counts_weeks_not_days(conn):
    habit_id = habits.add(conn, "周复盘", cadence="weekly")
    habits.toggle(conn, habit_id, "2026-10-19")  # 周一
    habits.toggle(conn, habit_id, "2026-10-26")

    # 2026 年 10 月的周一是 5、12、19、26 四天
    stats = habits.habit_stats(conn, habit_id, "2026-10-01", "2026-10-31")
    assert stats["expected"] == 4
    assert stats["done"] == 2


def test_habit_year_stats_merges_across_habits(conn):
    water = habits.add(conn, "喝水")
    reading = habits.add(conn, "读书")
    for day in range(1, 4):
        habits.toggle(conn, water, f"2026-01-0{day}")
    habits.toggle(conn, reading, "2026-01-01")

    stats = habits.year_stats(conn, "2026-01-01", "2026-01-31")
    assert stats["expected"] == 31 * 2
    assert stats["done"] == 4
    assert abs(stats["rate"] - 4 / 62) < 1e-9


def test_deleting_habit_removes_its_logs(conn):
    habit_id = habits.add(conn, "喝水")
    habits.toggle(conn, habit_id, "2026-10-23")

    habits.remove(conn, habit_id)
    assert conn.execute("SELECT COUNT(*) AS n FROM habit_logs").fetchone()["n"] == 0
