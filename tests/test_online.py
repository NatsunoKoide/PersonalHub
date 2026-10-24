"""联网相关：接口解析、失败降级、食物热量表、外币折算。

这里一个请求都不发。网络层被打桩，测试既不依赖外网，也不依赖对方的数据。
"""

import pytest

from src import foods, net, sync
from src.repo import ledger


class _FakeResponse:
    """模仿 urlopen 的返回：能进 with、能 read。"""

    def __init__(self, body: bytes):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _stub_opener(monkeypatch, body: bytes):
    monkeypatch.setattr(net, "_opener", lambda request, timeout=None: _FakeResponse(body))


def _stub_break(monkeypatch):
    def boom(request, timeout=None):
        raise OSError("network is unreachable")

    monkeypatch.setattr(net, "_opener", boom)


def _stub_json(monkeypatch, payload):
    monkeypatch.setattr(net, "get_json", lambda *args, **kwargs: payload)


# ---------------- 网络层 ----------------


def test_get_json_parses_a_json_body(monkeypatch):
    _stub_opener(monkeypatch, b'{"result":"success"}')
    assert net.get_json("https://example.invalid") == {"result": "success"}


def test_get_json_swallows_connection_failures(monkeypatch):
    """断网、超时、对方 500 全是 OSError，一律当作没拿到。"""
    _stub_break(monkeypatch)
    assert net.get_json("https://example.invalid") is None


def test_get_json_swallows_non_json_bodies(monkeypatch):
    """对方返回 503 的 HTML 页面时不能把 HTML 当成数据。"""
    _stub_opener(monkeypatch, b"<html><body>503 Service Unavailable</body></html>")
    assert net.get_json("https://example.invalid") is None


def test_get_json_swallows_broken_encoding(monkeypatch):
    _stub_opener(monkeypatch, b"\xff\xfe\x00bad")
    assert net.get_json("https://example.invalid") is None


def test_get_json_appends_query_string(monkeypatch):
    seen = {}

    def capture(request, timeout=None):
        seen["url"] = request.full_url
        return _FakeResponse(b"{}")

    monkeypatch.setattr(net, "_opener", capture)
    net.get_json("https://example.invalid/api", {"date": 2026})
    assert seen["url"].endswith("?date=2026")


# ---------------- 节假日同步 ----------------


def _holiday_payload(year: int) -> dict:
    return {
        "code": 0,
        "data": [
            {"daytype": 1, "holiday": "测试节", "date": f"{year}-03-01"},
            {"daytype": 3, "holiday": "测试节调休", "date": f"{year}-03-02"},
            # 普通周末与工作日由日历自己算，不该进表
            {"daytype": 2, "holiday": "周六", "date": f"{year}-03-07"},
            {"daytype": 0, "holiday": "周一", "date": f"{year}-03-09"},
        ],
    }


def _days_in(conn, year: int) -> dict:
    rows = conn.execute(
        "SELECT day, type FROM holidays WHERE day LIKE ?", (f"{year}-%",)
    ).fetchall()
    return {row["day"]: row["type"] for row in rows}


def test_sync_fills_missing_days_and_ignores_ordinary_days(conn, monkeypatch):
    _stub_json(monkeypatch, _holiday_payload(2027))
    result = sync.sync_holidays(conn, 2027)

    assert result["ok"] is True
    assert result["added"] == 2
    assert _days_in(conn, 2027) == {"2027-03-01": "holiday", "2027-03-02": "workday"}


def test_sync_keeps_days_the_user_changed_by_hand(conn, monkeypatch):
    """你手改过的日期，线上数据不许动它——这是数据安全的默认。"""
    _stub_json(monkeypatch, _holiday_payload(2027))
    sync.sync_holidays(conn, 2027)

    from src.repo import holidays as holidays_repo

    holidays_repo.set_day(conn, "2027-03-01", "workday", "我自己改的")
    result = sync.sync_holidays(conn, 2027)

    assert _days_in(conn, 2027)["2027-03-01"] == "workday"
    assert result["added"] == 0
    assert len(result["conflicts"]) == 1


def test_sync_can_be_forced_to_trust_the_online_data(conn, monkeypatch):
    _stub_json(monkeypatch, _holiday_payload(2027))
    sync.sync_holidays(conn, 2027)

    from src.repo import holidays as holidays_repo

    holidays_repo.set_day(conn, "2027-03-01", "workday", "改错了")
    result = sync.sync_holidays(conn, 2027, overwrite=True)

    assert result["updated"] == 1
    assert _days_in(conn, 2027)["2027-03-01"] == "holiday"


def test_sync_reports_failure_instead_of_raising(conn, monkeypatch):
    _stub_json(monkeypatch, None)
    result = sync.sync_holidays(conn, 2027)
    assert result["ok"] is False
    assert result["reason"]


def test_sync_rejects_a_malformed_payload(conn, monkeypatch):
    _stub_json(monkeypatch, {"code": 0, "data": "这不是数组"})
    assert sync.sync_holidays(conn, 2027)["ok"] is False


def test_sync_skips_entries_without_a_valid_date(conn, monkeypatch):
    _stub_json(
        monkeypatch,
        {"code": 0, "data": [{"daytype": 1, "holiday": "坏数据", "date": "不是日期"}]},
    )
    assert sync.sync_holidays(conn, 2027)["added"] == 0


def test_nothing_is_requested_when_networking_is_off(conn, monkeypatch):
    calls = []

    def spy(*args, **kwargs):
        calls.append(args)
        return None

    monkeypatch.setattr(net, "get_json", spy)
    sync.set_enabled(conn, False)
    sync.sync_all(conn)
    assert calls == []


# ---------------- 汇率 ----------------

_FX_PAYLOAD = {
    "result": "success",
    "base_code": "CNY",
    "rates": {"CNY": 1, "USD": 0.2, "EUR": 0.25, "JPY": 20},
}


def test_rates_are_inverted_because_the_api_is_cny_based(conn, monkeypatch):
    """接口给的是 1 人民币值多少外币，我们要的是反过来。"""
    _stub_json(monkeypatch, _FX_PAYLOAD)
    result = sync.refresh_rates(conn, force=True)

    assert result["ok"] is True
    assert result["updated"] == 3
    assert sync.rate_of(conn, "USD") == 5.0
    assert sync.rate_of(conn, "EUR") == 4.0
    assert round(sync.convert(conn, 1000, "JPY"), 2) == 50.0


def test_base_currency_always_converts_to_itself(conn, monkeypatch):
    _stub_json(monkeypatch, _FX_PAYLOAD)
    sync.refresh_rates(conn, force=True)
    assert sync.convert(conn, 88.8, "CNY") == 88.8


def test_failed_refresh_keeps_the_previous_rates(conn, monkeypatch):
    _stub_json(monkeypatch, _FX_PAYLOAD)
    sync.refresh_rates(conn, force=True)

    _stub_json(monkeypatch, None)
    result = sync.refresh_rates(conn, force=True)

    assert result["ok"] is False
    assert sync.rate_of(conn, "USD") == 5.0


def test_refresh_rejects_a_payload_without_rates(conn, monkeypatch):
    _stub_json(monkeypatch, {"result": "success"})
    assert sync.refresh_rates(conn, force=True)["ok"] is False


def test_only_known_currencies_are_offered(conn, monkeypatch):
    """没有汇率的币种不该出现在下拉框里，选了也算不出数。"""
    _stub_json(monkeypatch, _FX_PAYLOAD)
    sync.refresh_rates(conn, force=True)
    codes = {item["code"] for item in sync.known_currencies(conn)}
    assert codes == {"CNY", "USD", "EUR", "JPY"}


def test_only_fresh_enough_rates_count_as_fresh(conn, monkeypatch):
    _stub_json(monkeypatch, _FX_PAYLOAD)
    sync.refresh_rates(conn, force=True)
    # 刚同步过，再来一次应该直接跳过
    calls = []
    monkeypatch.setattr(net, "get_json", lambda *a, **k: calls.append(1) or _FX_PAYLOAD)
    sync.refresh_rates(conn)
    assert calls == []


# ---------------- 常见菜名表 ----------------
#
# 这张表原本是算热量用的，热量那一层撤了之后它只负责「点一下就把菜名
# 填进某一餐」。kcal_100g 数据仍然留着，测试继续守着它别跑偏。


def test_food_table_is_big_enough_to_be_useful():
    assert foods.count() >= 200


def test_search_finds_common_food():
    hits = foods.search("米饭")
    assert hits[0]["name"] == "米饭"


def test_search_accepts_colloquial_names():
    """口语说的和成分表写的不是同一个词，两个都要能搜到。"""
    assert foods.find("番茄").name == "西红柿"
    assert foods.find("洋芋").name == "土豆"


def test_search_returns_nothing_for_unknown_food():
    assert foods.search("不存在的食物") == []
    assert foods.find("不存在的食物") is None


def test_search_payload_carries_no_calories():
    """界面不显示热量，接口也不该把它送出去。"""
    for item in foods.search("米饭"):
        assert "kcal" not in item
        assert item["portion_label"]


def test_retained_energy_data_stays_sane():
    """热量数据是留着备用的资产，别让它悄悄跑偏。"""
    for food in foods.ALL:
        assert food.group in foods.GROUPS, food.name
        assert 0 <= food.kcal_100g <= 900, food.name
        assert food.portion_g > 0, food.name


# ---------------- API 层 ----------------


def test_expense_in_foreign_currency_is_converted(api, monkeypatch):
    _stub_json(monkeypatch, _FX_PAYLOAD)
    sync.refresh_rates(api.conn, force=True)

    entry = api.add_entry("2026-10-01", 100, "expense", "餐饮", currency="USD")
    assert entry["currency"] == "USD"
    assert entry["amount"] == 100
    assert entry["amount_cny"] == 500


def test_month_totals_use_converted_amounts(api, monkeypatch):
    _stub_json(monkeypatch, _FX_PAYLOAD)
    sync.refresh_rates(api.conn, force=True)

    api.add_entry("2026-10-01", 100, "expense", "餐饮", currency="USD")
    api.add_entry("2026-10-02", 50, "expense", "餐饮")
    summary = api.ledger_month("2026-10")["summary"]

    assert summary["expense"] == 550


def test_updating_an_entry_reconverts_it(api, monkeypatch):
    _stub_json(monkeypatch, _FX_PAYLOAD)
    sync.refresh_rates(api.conn, force=True)

    entry = api.add_entry("2026-10-01", 100, "expense", "餐饮", currency="USD")
    updated = api.update_entry(
        entry["id"], "2026-10-01", 20, "expense", "餐饮", "", "", "EUR"
    )
    assert updated["currency"] == "EUR"
    assert updated["amount_cny"] == 80


def test_absent_rate_falls_back_to_the_original_amount(api):
    """没有汇率时也要把这笔账记下来，总比让它消失好。"""
    entry = api.add_entry("2026-10-01", 100, "expense", "餐饮", currency="USD")
    assert entry["amount_cny"] == 100


def test_food_picker_appends_names_only(api):
    api.add_food_to_meal("2026-10-01", "lunch", "米饭")
    api.add_food_to_meal("2026-10-01", "lunch", "鸡胸肉")

    slot = next(
        item for item in api.diet_day("2026-10-01")["slots"] if item["slot"] == "lunch"
    )
    assert slot["content"] == "米饭，鸡胸肉"
    assert "kcal" not in slot


def test_unknown_food_does_not_touch_the_meal(api):
    before = api.diet_day("2026-10-01")
    after = api.add_food_to_meal("2026-10-01", "lunch", "不存在的食物")
    assert after["slots"] == before["slots"]


def test_net_status_describes_both_sources(api):
    status = api.net_status()
    assert "enabled" in status
    assert status["holiday_url"]
    assert status["fx_url"]
    assert isinstance(status["synced_years"], list)


def test_networking_can_be_switched_off(api):
    api.set_net_enabled(False)
    assert api.net_status()["enabled"] is False
    api.set_net_enabled(True)
    assert api.net_status()["enabled"] is True


def test_ledger_month_offers_currencies(api, monkeypatch):
    _stub_json(monkeypatch, _FX_PAYLOAD)
    sync.refresh_rates(api.conn, force=True)
    currencies = api.ledger_month("2026-10")["currencies"]
    assert {item["code"] for item in currencies} == {"CNY", "USD", "EUR", "JPY"}
    assert currencies[0]["code"] == "CNY"


def test_foreign_entries_survive_a_round_trip(api, monkeypatch):
    _stub_json(monkeypatch, _FX_PAYLOAD)
    sync.refresh_rates(api.conn, force=True)

    api.add_entry("2026-10-01", 100, "expense", "餐饮", currency="USD")
    payload = api.export_json()
    import json
    from pathlib import Path

    text = Path(payload["path"]).read_text(encoding="utf-8")
    entries = json.loads(text)["ledger_entries"]
    assert entries[0]["currency"] == "USD"
    assert entries[0]["amount_cny"] == 500


def test_csv_export_shows_both_amounts(api, monkeypatch):
    _stub_json(monkeypatch, _FX_PAYLOAD)
    sync.refresh_rates(api.conn, force=True)
    api.add_entry("2026-10-01", 100, "expense", "餐饮", currency="USD")

    from pathlib import Path

    text = Path(api.export_csv()["path"]).read_text(encoding="utf-8-sig")
    assert "2026-10-01,支出,100.00,USD,500.00,餐饮,," in text
