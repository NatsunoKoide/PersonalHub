from src.repo import ledger


def test_month_summary_splits_direction_and_category(conn):
    ledger.add(conn, "2026-10-01", 30, "expense", "餐饮")
    ledger.add(conn, "2026-10-02", 20, "expense", "餐饮")
    ledger.add(conn, "2026-10-03", 15, "expense", "交通")
    ledger.add(conn, "2026-10-05", 8000, "income", "其他", note="工资")

    summary = ledger.month_summary(conn, "2026-10")
    assert summary["expense"] == 65
    assert summary["income"] == 8000
    assert summary["count"] == 4
    assert summary["by_category"][0] == {"category": "餐饮", "amount": 50}
    assert summary["by_category"][1] == {"category": "交通", "amount": 15}


def test_previous_month_summary_covers_year_boundary(conn):
    ledger.add(conn, "2025-12-31", 100, "expense", "餐饮")
    summary = ledger.previous_month_summary(conn, "2026-01")
    assert summary["expense"] == 100


def test_year_months_always_returns_twelve(conn):
    ledger.add(conn, "2026-03-10", 88, "expense", "购物")
    months = ledger.year_months(conn, 2026)
    assert len(months) == 12
    assert months[2]["expense"] == 88
    assert months[2]["label"] == "3月"
    assert months[0]["expense"] == 0


def test_deleting_category_moves_history_to_fallback(conn):
    ledger.add(conn, "2026-10-01", 30, "expense", "餐饮")
    ledger.remove_category(conn, "餐饮")

    assert "餐饮" not in ledger.categories(conn)
    entry = ledger.get(conn, 1)
    assert entry["category"] == "其他"
    # 删分类绝不删流水，否则历史统计会凭空少一块
    assert ledger.month_summary(conn, "2026-10")["expense"] == 30


def test_fallback_category_cannot_be_deleted(conn):
    ledger.remove_category(conn, "其他")
    assert "其他" in ledger.categories(conn)


def test_renaming_category_keeps_history(conn):
    ledger.add(conn, "2026-10-01", 30, "expense", "餐饮")
    ledger.rename_category(conn, "餐饮", "伙食")

    assert ledger.get(conn, 1)["category"] == "伙食"
    assert ledger.month_summary(conn, "2026-10")["expense"] == 30


def test_budget_status_reports_total_and_categories(conn):
    ledger.add(conn, "2026-10-01", 900, "expense", "餐饮")
    ledger.add(conn, "2026-10-02", 300, "expense", "交通")
    ledger.set_budget(conn, "total", "", "2026-10", 1000)
    ledger.set_budget(conn, "category", "餐饮", "2026-10", 500)

    status = ledger.budget_status(conn, "2026-10")
    assert status["total"]["used"] == 1200
    assert status["total"]["over"] is True
    assert status["by_category"][0]["over"] is True
    assert status["by_category"][0]["left"] == -400


def test_daily_expense_for_heatmap(conn):
    ledger.add(conn, "2026-10-01", 30, "expense", "餐饮")
    ledger.add(conn, "2026-10-01", 20, "expense", "交通")

    totals = ledger.daily_expense(conn, "2026-10-01", "2026-10-31")
    assert totals == {"2026-10-01": 50}
