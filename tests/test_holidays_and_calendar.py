from src.repo import holidays, meta
from src.version import SCHEMA_VERSION


def test_seed_provides_2026_arrangement(conn):
    rows = holidays.list_year(conn, 2026)
    kinds = {}
    for row in rows:
        kinds.setdefault(row["type"], []).append(row["day"])

    assert kinds["holiday"][0] == "2026-01-01"
    assert "2026-02-17" in kinds["holiday"]  # 春节
    assert kinds["workday"] == [
        "2026-01-04",
        "2026-02-14",
        "2026-02-28",
        "2026-05-09",
        "2026-09-20",
        "2026-10-10",
    ]
    # 7 个节日共 33 天假期
    assert len(kinds["holiday"]) == 33


def test_seeding_does_not_overwrite_user_edits(conn):
    holidays.remove_day(conn, "2026-01-01")
    from src import seed

    seed.seed_holidays(conn, 2026)
    assert holidays.is_holiday(conn, "2026-01-01") is False


def test_import_range_and_single_lines(conn):
    written = holidays.import_text(
        conn,
        "2028-01-01~2028-01-03 放假 元旦\n"
        "2028-02-14 上班\n"
        "\n"
        "# 这是注释\n"
        "2028-05-01,2028-05-05,放假,劳动节\n",
    )

    assert written == 3 + 1 + 5
    assert holidays.is_holiday(conn, "2028-01-02") is True

    days = holidays.day_map(conn, "2028-01-01", "2028-12-31")
    assert days["2028-02-14"]["type"] == "workday"
    assert days["2028-05-03"]["name"] == "劳动节"


def test_import_ignores_garbage(conn):
    assert holidays.import_text(conn, "随便写的一句话\n\n") == 0


def test_set_and_remove_day(conn):
    holidays.set_day(conn, "2026-12-25", "holiday", "圣诞节")
    assert holidays.is_holiday(conn, "2026-12-25") is True

    holidays.remove_day(conn, "2026-12-25")
    assert holidays.is_holiday(conn, "2026-12-25") is False


def test_data_info_reports_location_and_size(conn):
    from src.repo import tasks

    tasks.add(conn, "占位", "2026-10-23")
    info = meta.data_info(conn)

    import os

    # 测试里数据家被隔离到临时目录，绝不能跑到用户真正的 AppData 去
    assert info["data_home"] == os.environ["PERSONALHUB_HOME"]
    assert info["db_size_bytes"] > 0
    assert "KB" in info["db_size_human"] or "B" in info["db_size_human"]
    assert info["counts"]["tasks"] == 1
    assert info["schema_version"] == SCHEMA_VERSION


def test_export_payload_is_json_serializable(conn):
    import json

    from src.repo import habits as habits_repo

    habits_repo.add(conn, "喝水")
    payload = meta.export_payload(conn)

    json.dumps(payload, ensure_ascii=False)
    assert payload["app_version"]
    assert payload["holidays"]


def test_ledger_csv_has_header_and_rows(conn):
    from src.repo import ledger

    ledger.add(conn, "2026-10-01", 30, "expense", "餐饮", note="午饭")
    csv_text = meta.export_ledger_csv(conn)

    assert (
        csv_text.splitlines()[0]
        == "日期,方向,原币金额,币种,折合人民币,分类,支付方式,备注"
    )
    assert "2026-10-01,支出,30.00,CNY,30.00,餐饮,,午饭" in csv_text


def test_settings_round_trip(conn):
    meta.set_setting(conn, "target_weight", 70)
    assert meta.get_setting(conn, "target_weight") == 70
    assert meta.get_setting(conn, "missing", "fallback") == "fallback"
