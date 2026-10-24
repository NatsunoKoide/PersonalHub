"""行情：代码规范化、三个数据源的解析、快照落库、总开关与断网降级。

一个真请求都不发：net._opener 按 URL 路由打桩，GBK 解码和 JSON 解析走的
都是真实代码路径。夹具是 2026-10-23（周五）收盘时的真实响应形态，
三个市场的行情时间戳位置故意不一样（A股 29、港股 29、美股 27）——
解析器必须靠格式锚定而不是写死字段位。
"""

import json
import threading
import time

import pytest

from src import market, market_service, net, sync
from src.api import Api
from src.repo import market as market_repo

# ---------------- 真实形态的夹具 ----------------

# 腾讯：GBK 文本。时间戳后面固定跟 涨跌额、涨跌幅
TENCENT_TEXT = (
    # A股：14 位时间戳，位置 29
    'v_sh600519="1~贵州茅台~600519~1335.00~1318.49~1311.84~57686~31159~26527~1333.00~6~1331.00~2~'
    '1330.00~2~1329.50~3~1329.02~1~1335.00~116~1335.01~2~1335.14~2~1335.19~1~1335.20~1~~'
    '20261023161458~16.51~1.25~1343.88~1310.00~1335.00/57686/7677216283";'
    # 港股：斜杠日期，位置 29
    'v_hk00700="100~腾讯控股~00700~386.000~382.400~381.800~33161473.0~0~0~386.000~0~0~0~0~0~0~0~0~0~'
    '386.000~0~0~0~0~0~0~0~0~0~33161473.0~2026/10/23 16:08:14~3.600~0.94~388.800~378.000";'
    # 美股：横线日期，位置 27（比前两个少两位，字段位不统一是常态）
    'v_usAAPL="200~苹果~AAPL.OQ~346.30~348.22~349.12~25431792~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~~'
    '2026-10-23 14:18:59~-1.92~-0.55~351.73~345.75";'
    # 查无此码时腾讯的返回
    'v_pv_none_match="1";'
    # 坏行：价格是 0
    'v_bad_zero="1~坏数据~000000~0~0~0~0~~20261023150000~0~0~";'
    # 坏行：没有时间戳
    'v_bad_notime="1~没时间~000001~10.00~10.00~10.00~100~0~0~";'
)

ULIST_PAYLOAD = {
    "rc": 0,
    "data": {"total": 8, "diff": [
        {"f2": 3690.48, "f3": 0.89, "f4": 32.45, "f12": "000001", "f14": "上证指数", "f86": 31.13},
        {"f2": 11673.83, "f3": 2.79, "f4": 316.51, "f12": "399001", "f14": "深证成指", "f86": 34.89},
        {"f2": 2684.1, "f3": 4.16, "f4": 107.2, "f12": "399006", "f14": "创业板指", "f86": 33.06},
        {"f2": 1345.51, "f3": 3.04, "f4": 39.64, "f12": "000688", "f14": "科创50", "f86": 14.02},
        {"f2": 23093.37, "f3": 0.69, "f4": 158.69, "f12": "HSI", "f14": "恒生指数", "f86": 0.0},
        {"f2": 52296.77, "f3": -1.08, "f4": -571.21, "f12": "DJIA", "f14": "道琼斯", "f86": 0.0},
        {"f2": 26000.64, "f3": -0.03, "f4": -8.22, "f12": "NDX", "f14": "纳斯达克", "f86": 0.0},
        {"f2": 7633.16, "f3": -0.39, "f4": -30.27, "f12": "SPX", "f14": "标普500", "f86": 0.0},
    ]},
}

# 腾讯的八大指数（真实响应形态）：字段布局与自选一致，时间戳位置三市场不同
TENCENT_INDICES_TEXT = (
    'v_sh000001="1~上证指数~000001~3690.48~3658.03~3623.57~552842912~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~~'
    '20261023161500~32.45~0.89~3691.40~3574.27";'
    'v_sz399001="51~深证成指~399001~11673.83~11357.32~11187.55~690752095~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~~'
    '20261023161454~316.51~2.79~11707.15~11043.31";'
    'v_sz399006="51~创业板指~399006~2684.10~2576.90~2534.16~222875998~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~~'
    '20261023161409~107.20~4.16~2695.08~2494.22";'
    'v_sh000688="1~科创50~000688~1345.51~1305.87~1287.87~10444456~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~~'
    '20261023161412~39.64~3.04~1353.32~1257.29";'
    'v_hkHSI="100~恒生指数~HSI~23093.370~22934.680~23027.980~24978359~0~0~23093.370~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~'
    '2026/10/23 18:31:07~158.690~0.69~23231.630~22803.770";'
    'v_usDJI="200~道琼斯~.DJI~52280.61~52867.98~52696.70~239013236~0~0~52273.02~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~~'
    '2026-10-23 15:28:19~-587.37~-1.11~52696.70~52055.10";'
    'v_usIXIC="200~纳斯达克~.IXIC~25963.72~26008.86~25893.95~4262776590~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~~'
    '2026-10-23 15:28:19~-45.14~-0.17~26111.62~25866.15";'
    'v_usINX="200~标普500~.INX~7627.94~7663.43~7637.18~1808995105~0~0~7626.82~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~~'
    '2026-10-23 15:28:19~-35.49~-0.46~7660.15~7612.07";'
)

CLIST_UP = {"rc": 0, "data": {"total": 496, "diff": [
    {"f2": 1417.66, "f3": 15.02, "f12": "BK1295", "f14": "其他数字媒体"},
    {"f2": 9257.45, "f3": 7.98, "f12": "BK1408", "f14": "机器人"},
]}}

CLIST_DOWN = {"rc": 0, "data": {"total": 496, "diff": [
    {"f3": -2.75, "f12": "BK1611", "f14": "国有大型银行Ⅲ"},
]}}

ZT_POOL = {"rc": 0, "data": {"tc": 82, "qdate": 20261023, "pool": []}}
# 跌停池实测时好时坏，拿不到就体面地显示「—」
DT_POOL = {"rc": 206, "data": None}

# 币圈：Binance 24h 报价（批量），OKX 回落（全量），CoinGecko 板块，
# Alternative.me 恐慌指数（timestamp 是秒），Yahoo VIX 图表
BINANCE_TICKER = [
    {"symbol": "BTCUSDT", "lastPrice": "81363.50000000", "priceChange": "-16.38000000",
     "priceChangePercent": "-0.02", "closeTime": 1792838399999},
    {"symbol": "ETHUSDT", "lastPrice": "2399.07000000", "priceChange": "16.44000000",
     "priceChangePercent": "0.69", "closeTime": 1792838399999},
    {"symbol": "SOLUSDT", "lastPrice": "104.01000000", "priceChange": "0.55000000",
     "priceChangePercent": "0.53", "closeTime": 1792838399999},
]
BINANCE_KLINES = [
    [1792540800000, "83028.14", "84898.00", "82635.32", "84093.42", "16544.48",
     1792627199999, "1388741748.82", 3096152, "8138.40", "682753995.10", "0"],
    [1792627200000, "84093.42", "84377.21", "80939.54", "81938.40", "16544.48",
     1792713599999, "1388741748.82", 3096152, "8138.40", "682753995.10", "0"],
]
OKX_TICKERS = {"code": "0", "data": [
    {"instType": "SPOT", "instId": "PEOPLE-EUR", "last": "0.007179", "open24h": "0.007075",
     "ts": "1792782373662"},
    {"instType": "SPOT", "instId": "BTC-USDT", "last": "81363.50", "open24h": "81379.88",
     "ts": "1792782373662"},
    {"instType": "SPOT", "instId": "ETH-USDT", "last": "2399.07", "open24h": "2382.63",
     "ts": "1792782373662"},
]}
COINGECKO_CATEGORIES = [
    {"id": "smart-contract-platform", "name": "Smart Contract Platform",
     "market_cap": 2366913268505.5, "market_cap_change_24h": 1.25},
    {"id": "ai-agents", "name": "AI Agents", "market_cap": 2100000000.0,
     "market_cap_change_24h": 4.5},
    {"id": "meme", "name": "Meme", "market_cap": 61000000000.0,
     "market_cap_change_24h": -2.1},
    # 市值不够的尘埃板块：±100% 也不该上榜
    {"id": "dust", "name": "Dust Sector", "market_cap": 12000000.0,
     "market_cap_change_24h": 100.03},
    # 涨幅为 null 的跳过
    {"id": "nulls", "name": "Nulls", "market_cap": 3000000000.0,
     "market_cap_change_24h": None},
]
ALTME_FNG = {"name": "Fear and Greed Index", "data": [
    {"value": "50", "value_classification": "Neutral", "timestamp": "1792713600"},
    {"value": "68", "value_classification": "Greed", "timestamp": "1792627200"},
]}
YAHOO_VIX = {"chart": {"result": [{"meta": {"symbol": "^VIX", "regularMarketPrice": 19.78}}]}}
YAHOO_SPARK = {"spark": {"result": [
    {"symbol": "XLC", "response": [{"meta": {"regularMarketPrice": 105.87,
                                            "regularMarketChangePercent": -1.45,
                                            "regularMarketTime": 1792783997}}]},
    {"symbol": "XLK", "response": [{"meta": {"regularMarketPrice": 268.4,
                                            "regularMarketChangePercent": 2.31,
                                            "regularMarketTime": 1792783997}}]},
    {"symbol": "XLE", "response": [{"meta": {"regularMarketPrice": 92.1,
                                            "regularMarketChangePercent": 0.42,
                                            "regularMarketTime": 1792783997}}]},
    # 坏行：没有 response
    {"symbol": "XLF", "response": []},
]}}


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _stub_network(monkeypatch, *, broken=False, tencent_text=None, gate=None):
    """按 URL 路由的假 opener，顺带数请求次数。broken=True 模拟全断网。

    tencent_text 替换腾讯返回体（默认 TENCENT_TEXT，里面没有指数行，
    正好用来测「腾讯没给全就走东财回落」）。
    gate: threading.Event——给了就在腾讯报价返回前等它，用来在测试里
    把一次刷新按在「联网中」状态，验证其他页签不被卡住。
    """
    state = {"calls": 0, "referers": []}

    def opener(request, timeout=None):
        state["calls"] += 1
        state["referers"].append(request.headers.get("Referer"))
        if broken:
            raise OSError("network is unreachable")
        url = request.full_url
        if "gtimg" in url:
            if gate is not None:
                gate.wait(5)
            body = (tencent_text if tencent_text is not None else TENCENT_TEXT).encode("gbk")
        elif "ulist" in url:
            body = json.dumps(ULIST_PAYLOAD).encode("utf-8")
        elif "clist" in url:
            body = json.dumps(CLIST_UP if "po=1" in url else CLIST_DOWN).encode("utf-8")
        elif "getTopicZTPool" in url:
            body = json.dumps(ZT_POOL).encode("utf-8")
        elif "getTopicDTPool" in url:
            body = json.dumps(DT_POOL).encode("utf-8")
        elif "binance.com" in url and "klines" in url:
            body = json.dumps(BINANCE_KLINES).encode("utf-8")
        elif "binance.com" in url:
            body = json.dumps(BINANCE_TICKER).encode("utf-8")
        elif "okx.com" in url:
            body = json.dumps(OKX_TICKERS).encode("utf-8")
        elif "coingecko.com" in url:
            body = json.dumps(COINGECKO_CATEGORIES).encode("utf-8")
        elif "alternative.me" in url:
            body = json.dumps(ALTME_FNG).encode("utf-8")
        elif "yahoo.com" in url and "spark" in url:
            body = json.dumps(YAHOO_SPARK).encode("utf-8")
        elif "yahoo.com" in url:
            body = json.dumps(YAHOO_VIX).encode("utf-8")
        else:
            body = b"{}"
        return _FakeResponse(body)

    monkeypatch.setattr(net, "_opener", opener)
    # 测试不真的退避等待，重试逻辑本身另有专项测试
    monkeypatch.setattr(net, "BACKOFF", (0.0, 0.0))
    return state


# ---------------- 代码规范化 ----------------


def test_normalize_code_covers_every_market():
    assert market.normalize_code("600519") == {"code": "sh600519", "market": "a", "kind": "stock"}
    assert market.normalize_code("000001") == {"code": "sz000001", "market": "a", "kind": "stock"}
    assert market.normalize_code("00700") == {"code": "hk00700", "market": "hk", "kind": "stock"}
    assert market.normalize_code("700") == {"code": "hk00700", "market": "hk", "kind": "stock"}
    assert market.normalize_code("aapl") == {"code": "usAAPL", "market": "us", "kind": "stock"}
    assert market.normalize_code("sh000001")["kind"] == "index"
    assert market.normalize_code("usDJI")["kind"] == "index"
    assert market.normalize_code("510300") == {"code": "sh510300", "market": "a", "kind": "fund"}
    assert market.normalize_code("588000") == {"code": "sh588000", "market": "a", "kind": "fund"}
    assert market.normalize_code("159915") == {"code": "sz159915", "market": "a", "kind": "fund"}
    assert market.normalize_code("") is None
    assert market.normalize_code("!!!") is None
    assert market.normalize_code("12345678") is None


# ---------------- 腾讯报价解析 ----------------


def test_parse_quotes_handles_all_three_markets():
    quotes = {quote["code"]: quote for quote in market.parse_quotes(TENCENT_TEXT)}

    maotai = quotes["sh600519"]
    assert maotai["name"] == "贵州茅台"
    assert maotai["price"] == 1335.0
    assert maotai["change_amount"] == 16.51
    assert maotai["change_pct"] == 1.25
    assert maotai["day"] == "2026-10-23"

    tencent = quotes["hk00700"]
    assert tencent["name"] == "腾讯控股"
    assert tencent["price"] == 386.0
    assert tencent["day"] == "2026-10-23"

    apple = quotes["usAAPL"]
    assert apple["name"] == "苹果"
    assert apple["price"] == 346.3
    assert apple["change_pct"] == -0.55
    assert apple["day"] == "2026-10-23"


def test_parse_quotes_skips_unusable_lines():
    codes = {quote["code"] for quote in market.parse_quotes(TENCENT_TEXT)}
    assert codes == {"sh600519", "hk00700", "usAAPL"}


def test_fetch_quotes_returns_only_what_was_asked(monkeypatch):
    _stub_network(monkeypatch)
    quotes = market.fetch_quotes(["sh600519", "usAAPL"])
    assert {quote["code"] for quote in quotes} == {"sh600519", "usAAPL"}


def test_fetch_quotes_survives_network_failure(monkeypatch):
    _stub_network(monkeypatch, broken=True)
    assert market.fetch_quotes(["sh600519"]) == []


# ---------------- 东方财富解析 ----------------


def test_fetch_indices_maps_all_eight(monkeypatch):
    """腾讯没给全时回落东财 ulist：八条一条不少，字段映射不变。"""
    _stub_network(monkeypatch)  # 默认夹具里没有指数行
    indices = {quote["code"]: quote for quote in market.fetch_indices()}

    assert len(indices) == 8
    assert indices["sh000001"]["name"] == "上证指数"
    assert indices["sh000001"]["price"] == 3690.48
    assert indices["sh000001"]["change_pct"] == 0.89
    assert indices["usDJI"]["change_pct"] == -1.08
    assert indices["hkHSI"]["market"] == "hk"
    assert all(quote["kind"] == "index" for quote in indices.values())


def test_fetch_indices_prefers_tencent(monkeypatch):
    """腾讯能出指数就不劳东财：字段布局与自选一样，还带真实时间戳。"""
    state = _stub_network(monkeypatch, tencent_text=TENCENT_INDICES_TEXT)
    indices = {quote["code"]: quote for quote in market.fetch_indices()}

    assert len(indices) == 8
    assert indices["sh000001"]["price"] == 3690.48
    assert indices["hkHSI"]["change_pct"] == 0.69
    assert indices["usDJI"]["change_pct"] == -1.11
    assert indices["sh000001"]["day"] == "2026-10-23"  # 腾讯的时间戳，不用蹭自选的归日
    assert indices["hkHSI"]["day"] == "2026-10-23"     # 斜杠格式也认得
    assert state["calls"] == 1  # 一次腾讯请求，没碰东财


def test_fetch_sectors_and_limit_stats(monkeypatch):
    _stub_network(monkeypatch)
    up = market.fetch_sectors("up")
    assert up[0]["name"] == "其他数字媒体"
    assert up[0]["pct"] == 15.02

    down = market.fetch_sectors("down")
    assert down[0]["name"] == "国有大型银行Ⅲ"
    assert down[0]["pct"] == -2.75

    limits = market.fetch_limit_stats()
    assert limits["up"] == 82      # 涨停池好用
    assert limits["down"] is None  # 跌停池抽风，体面地交 None


# ---------------- 同步与快照 ----------------


def _watch_codes(conn):
    return [item["code"] for item in market_repo.list_watch(conn)]


def test_sync_writes_snapshots_and_is_idempotent(conn, monkeypatch):
    _stub_network(monkeypatch)
    market_repo.add_watch(conn, "sh600519", "贵州茅台", "a")

    first = market.sync_market(conn)
    assert first["indices"] and first["quotes"]
    assert len(first["crypto"]) == 3  # 币圈三币常驻

    rows = conn.execute("SELECT COUNT(*) AS n FROM market_snapshots").fetchone()["n"]
    assert rows == 12  # 8 指数 + 1 自选 + 3 币

    second = market.sync_market(conn)
    rows_again = conn.execute("SELECT COUNT(*) AS n FROM market_snapshots").fetchone()["n"]
    assert rows_again == 12  # 同日同 code 只更新不插行
    assert second["written"] == 12

    maotai = market_repo.latest_quote(conn, "sh600519")
    assert maotai["price"] == 1335.0
    assert maotai["name"] == "贵州茅台"

    btc = market_repo.latest_quote(conn, "BTCUSDT")
    assert btc["price"] == 81363.5
    assert btc["market"] == "crypto"
    assert btc["kind"] == "coin"
    assert btc["day"] == "2026-10-24"  # 币圈归日按 UTC


def test_index_day_follows_the_quote_trading_day(conn, monkeypatch):
    """周末打开时，指数要跟着自选报价的真实交易日（周五），不是本地今天。"""
    _stub_network(monkeypatch)
    market_repo.add_watch(conn, "sh600519", "贵州茅台", "a")
    market.sync_market(conn)

    assert market_repo.latest_quote(conn, "sh000001")["day"] == "2026-10-23"

    # 模拟早期版本归日算错留下的垃圾行（比交易日还新）
    conn.execute(
        "INSERT INTO market_snapshots (day, code, name, market, kind, price, updated_at)"
        " VALUES ('2026-10-24', 'sh000001', '上证指数', 'a', 'index', 1.0, 'x')"
    )
    conn.commit()
    market.sync_market(conn)

    assert market_repo.latest_quote(conn, "sh000001")["day"] == "2026-10-23"
    # 币圈 UTC 日期比股票交易日新是真实数据，清理不能碰它
    stale = conn.execute(
        "SELECT COUNT(*) AS n FROM market_snapshots"
        " WHERE day > '2026-10-23' AND market <> 'crypto'"
    ).fetchone()["n"]
    assert stale == 0
    assert market_repo.latest_quote(conn, "BTCUSDT")["day"] == "2026-10-24"


def test_master_switch_off_sends_nothing(conn, monkeypatch):
    state = _stub_network(monkeypatch)
    sync.set_enabled(conn, False)

    result = market.sync_market(conn)
    assert result == {"indices": [], "quotes": [], "crypto": [], "written": 0}
    assert state["calls"] == 0


def test_network_failure_is_silent(conn, monkeypatch):
    _stub_network(monkeypatch, broken=True)
    market_repo.add_watch(conn, "sh600519", "贵州茅台", "a")

    result = market.sync_market(conn)
    assert result["indices"] == [] and result["quotes"] == []
    # 不抛异常，也不留半点脏数据
    assert conn.execute("SELECT COUNT(*) AS n FROM market_snapshots").fetchone()["n"] == 0


# ---------------- 自选清单 ----------------


def test_watch_add_round_trip(conn, monkeypatch):
    _stub_network(monkeypatch)
    api = Api(conn)

    result = api.market_watch_add("600519")
    assert result["code"] == "sh600519"
    assert result["name"] == "贵州茅台"
    assert _watch_codes(conn) == ["sh600519"]
    assert market_repo.latest_quote(conn, "sh600519")["price"] == 1335.0


def test_watch_add_rejects_duplicates_and_garbage(conn, monkeypatch):
    _stub_network(monkeypatch)
    api = Api(conn)
    api.market_watch_add("600519")

    with pytest.raises(ValueError, match="已经在自选里"):
        api.market_watch_add("sh600519")
    with pytest.raises(ValueError, match="认不出"):
        api.market_watch_add("!!!")
    with pytest.raises(ValueError, match="没查到"):
        api.market_watch_add("hk99999")  # 格式对但夹具里没这个码


def test_watch_add_needs_the_master_switch(conn, monkeypatch):
    _stub_network(monkeypatch)
    api = Api(conn)
    sync.set_enabled(conn, False)

    with pytest.raises(ValueError, match="总开关"):
        api.market_watch_add("600519")


def test_watch_remove(conn, monkeypatch):
    _stub_network(monkeypatch)
    api = Api(conn)
    added = api.market_watch_add("00700")

    api.market_watch_remove(added["id"])
    assert _watch_codes(conn) == []
    # 快照是缓存，移出自选不该动历史
    assert market_repo.latest_quote(conn, "hk00700")["price"] == 386.0


# ---------------- 页面数据 ----------------


def _wait_for_sync(timeout: float = 10.0) -> bool:
    """等后台刷新结束。打桩的网络都是瞬间完成，超时给足即可。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not market_service.service.status()["syncing"]:
            return True
        time.sleep(0.02)
    return False


def test_overview_shows_everything_after_a_refresh(conn, monkeypatch):
    """一次后台刷新落库后，行情页要的数据本地全能读到。"""
    _stub_network(monkeypatch)
    market_service.service.reset()
    api = Api(conn)
    api.market_watch_add("600519")

    assert api.market_refresh(force=True)["started"] is True
    assert _wait_for_sync()

    overview = api.market_overview()
    assert overview["net_enabled"] is True
    assert overview["syncing"] is False
    assert len(overview["indices"]) == 8
    assert overview["indices"][0]["name"] == "上证指数"
    assert overview["watch"][0]["price"] == 1335.0
    assert overview["limits"]["up"] == 82
    assert overview["sectors_up"][0]["name"] == "其他数字媒体"
    assert overview["day"] == "2026-10-23"  # 股票行情日，不带币圈的 UTC

    # 币圈三币 + 币圈板块
    assert [coin["code"] for coin in overview["crypto"]] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    assert overview["crypto"][0]["price"] == 81363.5
    assert overview["crypto_sectors_up"][0]["name"] == "AI 智能体"  # 尘埃板块被市值下限过滤后第一
    assert overview["crypto_sectors_down"][0]["name"] == "模因币"

    # 四市场温度：A股/港股是估算，美股/币圈取真指数
    temps = {item["market"]: item for item in overview["temperature"]}
    assert set(temps) == {"a", "hk", "us", "crypto"}
    assert temps["a"]["estimated"] is True
    assert temps["hk"]["estimated"] is True
    assert temps["us"]["estimated"] is False and temps["us"]["source"] == "VIX 19.8"
    assert temps["crypto"]["estimated"] is False
    assert temps["crypto"]["label"] == "中性" and temps["crypto"]["value"] == 50

    json.dumps(overview, ensure_ascii=False)  # 必须能直接过 JS 边界


def test_overview_is_purely_local_and_sends_no_requests(conn, monkeypatch):
    """overview 一个请求都不发：行情页打开永远是毫秒级。"""

    def tripwire(request, timeout=None):
        raise AssertionError(f"market_overview 不该联网：{request.full_url}")

    monkeypatch.setattr(net, "_opener", tripwire)
    market_service.service.reset()
    api = Api(conn)
    market_repo.upsert_snapshots(conn, [
        {"day": "2026-10-23", "code": "sh000001", "name": "上证指数", "market": "a",
         "kind": "index", "price": 3690.48, "change_amount": 32.45, "change_pct": 0.89},
        {"day": "2026-10-24", "code": "BTCUSDT", "name": "比特币", "market": "crypto",
         "kind": "coin", "price": 81363.5, "change_amount": -16.38, "change_pct": -0.02},
    ])
    market_repo.save_aggregates(
        conn,
        {"sectors_up": [{"code": "BK1408", "name": "机器人", "pct": 7.98}],
         "limits": {"up": 82, "down": None}},
        [{"market": "a", "market_label": "A股", "value": 95, "label": "极度贪婪",
          "source": "估算", "estimated": True, "day": "2026-10-23"}],
    )

    overview = api.market_overview()

    assert len(overview["indices"]) == 1 and overview["indices"][0]["price"] == 3690.48
    assert overview["crypto"][0]["price"] == 81363.5
    assert overview["sectors_up"][0]["name"] == "机器人"
    assert overview["limits"]["up"] == 82
    assert overview["temperature"][0]["market"] == "a"
    assert overview["syncing"] is False
    assert overview["day"] == "2026-10-23"  # 顶部日期跟股票，不跟币圈 UTC


def test_overview_falls_back_to_local_cache_when_offline(conn, monkeypatch):
    """断网时行情页照样秒开：报价走快照，汇总与温度走缓存，都不是编的。"""
    _stub_network(monkeypatch)
    market_service.service.reset()
    api = Api(conn)
    api.market_watch_add("600519")
    assert market_service.service.refresh(api.db_path, force=True)["started"] is True
    assert _wait_for_sync()

    sync.set_enabled(conn, False)
    offline = api.market_overview()

    assert offline["net_enabled"] is False
    assert len(offline["indices"]) == 8
    assert offline["watch"][0]["price"] == 1335.0
    # 汇总区来自上一轮刷新的缓存
    assert offline["limits"]["up"] == 82
    assert offline["sectors_up"][0]["name"] == "其他数字媒体"
    assert offline["crypto_sectors_up"][0]["name"] == "AI 智能体"
    temps = {item["market"]: item for item in offline["temperature"]}
    assert set(temps) == {"a", "hk", "us", "crypto"}
    assert offline["crypto"][0]["price"] == 81363.5


# ---------------- 后台刷新服务（ADR 0010） ----------------


def test_market_network_never_blocks_other_tabs(conn, monkeypatch):
    """核心回归：行情刷新进行中，其他页签的取数不能卡住。"""
    gate = threading.Event()
    _stub_network(monkeypatch, tencent_text=TENCENT_INDICES_TEXT, gate=gate)
    market_service.service.reset()
    api = Api(conn)

    box: dict = {}
    box["kick_done"] = threading.Event()

    def kicker():
        box["kick"] = api.market_refresh(force=True)
        box["kick_done"].set()

    threading.Thread(target=kicker, daemon=True).start()
    assert box["kick_done"].wait(5), "market_refresh 自己卡住了：联网跑在了调用线程里"
    assert box["kick"]["started"] is True and box["kick"]["syncing"] is True

    # 刷新被按在「联网中」：overview 必须秒回（它只读本地）
    box["ov_done"] = threading.Event()

    def reader():
        box["overview"] = api.market_overview()
        box["ov_done"].set()

    threading.Thread(target=reader, daemon=True).start()
    assert box["ov_done"].wait(5), "market_overview 卡住了：它不该联网"
    assert box["overview"]["syncing"] is True

    # 其他页签的接口在行情刷新期间正常返回——这就是用户报的「一起加载中」
    box["cal_done"] = threading.Event()

    def other_tab():
        box["calendar"] = api.calendar_month(2026, 10)
        box["cal_done"].set()

    threading.Thread(target=other_tab, daemon=True).start()
    assert box["cal_done"].wait(5), "行情刷新占着全局锁，其他页签被卡住了"

    gate.set()
    assert _wait_for_sync()
    assert len(api.market_overview()["indices"]) == 8  # 落库后本地能读到


def test_watch_add_query_does_not_block_other_tabs(conn, monkeypatch):
    """加自选的联网查价同样不持全局锁。"""
    entered = threading.Event()
    gate = threading.Event()
    real_fetch = market.fetch_quotes

    def gated_fetch(codes):
        entered.set()
        gate.wait(5)
        return real_fetch(codes)

    _stub_network(monkeypatch)
    monkeypatch.setattr(market, "fetch_quotes", gated_fetch)
    api = Api(conn)

    box: dict = {}
    box["add_done"] = threading.Event()

    def adder():
        try:
            box["added"] = api.market_watch_add("600519")
        except Exception as exc:  # pragma: no cover - 失败时把异常带出来断言
            box["error"] = exc
        box["add_done"].set()

    threading.Thread(target=adder, daemon=True).start()
    assert entered.wait(5), "加自选没有走到联网查价那步"

    box["cal_done"] = threading.Event()

    def other_tab():
        box["calendar"] = api.calendar_month(2026, 10)
        box["cal_done"].set()

    threading.Thread(target=other_tab, daemon=True).start()
    assert box["cal_done"].wait(5), "加自选的查价卡住了其他页签"

    gate.set()
    assert box["add_done"].wait(5)
    assert "error" not in box
    assert box["added"]["code"] == "sh600519"
    assert _watch_codes(conn) == ["sh600519"]


def test_refresh_dedupes_and_throttles(conn, monkeypatch):
    """并发只刷一次；刚刷完自动刷新被节流；手动刷新绕过节流。"""
    _stub_network(monkeypatch)
    market_service.service.reset()
    api = Api(conn)
    path = api.db_path

    first = market_service.service.refresh(path, force=True)
    assert first["started"] is True
    busy = market_service.service.refresh(path, force=True)
    assert busy["started"] is False and busy["reason"] == "busy" and busy["syncing"] is True
    assert _wait_for_sync()

    throttled = market_service.service.refresh(path)
    assert throttled["started"] is False and throttled["reason"] == "throttled"

    forced = market_service.service.refresh(path, force=True)
    assert forced["started"] is True
    assert _wait_for_sync()


def test_failed_refresh_keeps_previous_aggregates(conn, monkeypatch):
    """一轮没拿到数据，不许把上一轮的板块榜和温度抹成空白。"""
    _stub_network(monkeypatch)
    market_service.service.reset()
    api = Api(conn)
    assert market_service.service.refresh(api.db_path, force=True)["started"] is True
    assert _wait_for_sync()
    before = api.market_overview()
    assert before["sectors_up"] and before["temperature"]

    _stub_network(monkeypatch, broken=True)
    assert market_service.service.refresh(api.db_path, force=True)["started"] is True
    assert _wait_for_sync()

    after = api.market_overview()
    assert after["sectors_up"] == before["sectors_up"]
    assert after["limits"] == before["limits"]
    assert after["temperature"] == before["temperature"]


def test_master_switch_off_sends_no_market_requests(conn, monkeypatch):
    """总开关关着：后台刷新空转，一个请求都不发，界面全是本地数据。"""
    state = _stub_network(monkeypatch)
    sync.set_enabled(conn, False)
    market_service.service.reset()
    api = Api(conn)

    assert market_service.service.refresh(api.db_path, force=True)["started"] is True
    assert _wait_for_sync()
    assert state["calls"] == 0

    overview = api.market_overview()
    assert overview["net_enabled"] is False
    assert overview["sectors_up"] == [] and overview["temperature"] == []


def test_window_change_and_history(conn):
    market_repo.upsert_snapshots(conn, [
        {"day": "2026-10-21", "code": "sh000001", "name": "上证指数", "market": "a",
         "kind": "index", "price": 3600.0, "change_amount": 0, "change_pct": 0},
        {"day": "2026-10-22", "code": "sh000001", "name": "上证指数", "market": "a",
         "kind": "index", "price": 3700.0, "change_amount": 0, "change_pct": 0},
        {"day": "2026-10-23", "code": "sh000001", "name": "上证指数", "market": "a",
         "kind": "index", "price": 3690.0, "change_amount": 0, "change_pct": 0},
    ])

    rows = market_repo.history(conn, "sh000001", 30)
    assert [row["day"] for row in rows] == ["2026-10-21", "2026-10-22", "2026-10-23"]

    window = market_repo.window_change(conn, "sh000001", 30)
    assert window["from_day"] == "2026-10-21"
    assert window["to_day"] == "2026-10-23"
    assert window["pct"] == pytest.approx((3690 - 3600) / 3600 * 100)

    # 只有一个点算不出区间涨跌
    assert market_repo.window_change(conn, "sh000001", 1) is None


# ---------------- 币圈 ----------------


def test_normalize_code_recognizes_crypto():
    assert market.normalize_code("btc") == {"code": "BTCUSDT", "market": "crypto", "kind": "coin"}
    assert market.normalize_code("BTCUSDT")["code"] == "BTCUSDT"
    assert market.normalize_code("BTC-USDT")["code"] == "BTCUSDT"
    assert market.normalize_code("sol")["market"] == "crypto"
    # 不在知名名单里、又不带计价货币的，仍按美股走
    assert market.normalize_code("xyz")["market"] == "us"
    assert market.normalize_code("aapl")["market"] == "us"


def test_parse_crypto_quotes_binance():
    quotes = {quote["code"]: quote for quote in market.parse_crypto_quotes_binance(BINANCE_TICKER)}
    assert quotes["BTCUSDT"]["price"] == 81363.5
    assert quotes["BTCUSDT"]["change_pct"] == -0.02
    assert quotes["BTCUSDT"]["name"] == "比特币"
    assert quotes["BTCUSDT"]["day"] == "2026-10-24"  # UTC
    # 单个 dict 也要认；错误响应（dict 没字段）解析成空
    assert market.parse_crypto_quotes_binance({"code": -1121, "msg": "bad"}) == []


def test_fetch_crypto_quotes_falls_back_to_okx(monkeypatch):
    state = _stub_network(monkeypatch)
    quotes = {quote["code"]: quote for quote in market.fetch_crypto_quotes(["BTCUSDT", "ETHUSDT"])}
    assert quotes["BTCUSDT"]["price"] == 81363.5  # Binance 主路径

    # Binance 整体挂掉时回落 OKX：OKX 的 instId 过滤不生效，靠客户端筛
    def broken_binance(request, timeout=None):
        if "binance.com" in request.full_url:
            raise OSError("binance unreachable")
        return _FakeResponse(json.dumps(OKX_TICKERS).encode("utf-8"))

    monkeypatch.setattr(net, "_opener", broken_binance)
    quotes = {quote["code"]: quote for quote in market.fetch_crypto_quotes(["BTCUSDT", "ETHUSDT"])}
    assert quotes["BTCUSDT"]["price"] == 81363.5
    assert quotes["ETHUSDT"]["price"] == 2399.07
    assert quotes["BTCUSDT"]["change_pct"] == pytest.approx((81363.5 - 81379.88) / 81379.88 * 100, abs=0.01)


def test_parse_crypto_klines():
    points = market.parse_crypto_klines(BINANCE_KLINES)
    assert points[0] == {"day": "2026-10-21", "price": 84093.42}
    assert points[-1]["day"] == "2026-10-22"


def test_fetch_crypto_klines(monkeypatch):
    _stub_network(monkeypatch)
    points = market.fetch_crypto_klines("BTCUSDT", 30)
    assert len(points) == 2


def test_parse_crypto_sectors_filters_dust_and_nulls():
    rows = market.parse_crypto_sectors(COINGECKO_CATEGORIES)
    names = [row["name"] for row in rows]
    assert "AI 智能体" in names  # 映射表命中的译中
    assert "智能合约平台" in names
    assert "Dust Sector" not in names  # 市值不够
    assert "Nulls" not in names  # 涨幅为 null


def test_fetch_crypto_sectors_orders_by_direction(monkeypatch):
    _stub_network(monkeypatch)
    up = market.fetch_crypto_sectors("up", 5)
    down = market.fetch_crypto_sectors("down", 5)
    assert up[0]["name"] == "AI 智能体"
    assert down[0]["name"] == "模因币"
    assert all(up[i]["pct"] >= up[i + 1]["pct"] for i in range(len(up) - 1))


def test_fetch_us_sectors_orders_by_direction(monkeypatch):
    """美股行业用 SPDR 行业 ETF 代理：Yahoo spark 一个请求拿全部 11 只。"""
    _stub_network(monkeypatch)
    up = {row["code"]: row for row in market.fetch_us_sectors("up", 5)}
    down = {row["code"]: row for row in market.fetch_us_sectors("down", 5)}
    assert up["XLK"]["name"] == "信息技术" and up["XLK"]["pct"] == 2.31
    assert next(iter(up)) == "XLK"   # 涨幅第一
    assert next(iter(down)) == "XLC"  # 跌幅第一
    # 没有 response 的坏行跳过，不影响其他
    assert "XLF" not in up and "XLF" not in down


def test_fear_greed_parses_seconds_timestamp():
    fng = market.parse_fear_greed(ALTME_FNG)
    assert fng["value"] == 50
    assert fng["label"] == "中性"  # 英文标签译中
    assert fng["day"] == "2026-10-23"


def test_market_temperature_covers_four_markets(monkeypatch):
    _stub_network(monkeypatch)
    indices = [
        {"code": "sh000001", "market": "a", "change_pct": 1.0},
        {"code": "sz399001", "market": "a", "change_pct": 3.0},
        {"code": "hkHSI", "market": "hk", "change_pct": -1.0},
    ]
    temps = {item["market"]: item for item in market.market_temperature(indices, {"up": 82, "down": 18})}
    assert set(temps) == {"a", "hk", "us", "crypto"}
    # A股：涨跌停占比 82/100=82 与指数均温 (1+3)/2=2% → 83.3，各半 ≈ 82.7
    assert temps["a"]["value"] == 83 and temps["a"]["estimated"] is True
    # 港股：-1% → 50 - 16.7 ≈ 33
    assert temps["hk"]["value"] == 33 and temps["hk"]["estimated"] is True
    # 美股：VIX 19.78 落在 15-20 段 → 80 与 60 之间
    assert temps["us"]["value"] == 61 and temps["us"]["source"] == "VIX 19.8"
    # 币圈：Alternative.me 原值
    assert temps["crypto"]["value"] == 50 and temps["crypto"]["label"] == "中性"


def test_vix_to_temperature_bands():
    assert market._vix_to_temperature(10) == 95
    assert market._vix_to_temperature(20) == 60
    assert market._vix_to_temperature(30) == 30
    assert market._vix_to_temperature(50) == 10  # 超出锚点封顶


# ---------------- 网络层健壮性 ----------------


def test_eastmoney_calls_carry_referer(monkeypatch):
    """东财 push2 校验 Referer，不带就返回空——这是「有时拿不到」的病根之一。"""
    state = _stub_network(monkeypatch)
    market.fetch_sectors("up")
    assert state["referers"][-1] == net.EASTMONEY_REFERER

    market.fetch_indices()
    assert state["referers"][-1] == net.EASTMONEY_REFERER


def test_get_json_retries_transient_failures(monkeypatch):
    """连接被掐断是偶发的：重试必须能救回来，且只重试不改结果。"""
    calls = {"n": 0}

    def flaky(request, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError("Remote end closed connection without response")
        return _FakeResponse(b'{"ok": true}')

    monkeypatch.setattr(net, "_opener", flaky)
    monkeypatch.setattr(net, "BACKOFF", (0.0, 0.0))
    assert net.get_json("https://example.com/x") == {"ok": True}
    assert calls["n"] == 3


def test_get_json_gives_up_after_retries(monkeypatch):
    calls = {"n": 0}

    def always_down(request, timeout=None):
        calls["n"] += 1
        raise OSError("still down")

    monkeypatch.setattr(net, "_opener", always_down)
    monkeypatch.setattr(net, "BACKOFF", (0.0, 0.0))
    assert net.get_json("https://example.com/x") is None
    assert calls["n"] == 3  # 1 + 2 次重试，不无限重试


def test_get_json_does_not_retry_valid_content(monkeypatch):
    """对方正常返回（哪怕是错误 JSON）不重试，避免无谓放大请求量。"""
    calls = {"n": 0}

    def bad_json(request, timeout=None):
        calls["n"] += 1
        return _FakeResponse(b"<html>not json</html>")

    monkeypatch.setattr(net, "_opener", bad_json)
    monkeypatch.setattr(net, "BACKOFF", (0.0, 0.0))
    assert net.get_json("https://example.com/x") is None
    assert calls["n"] == 1


# ---------------- 迁移 ----------------


def test_migration_003_creates_market_tables(empty_conn):
    from src import db

    db.migrate(empty_conn)

    tables = {
        row["name"]
        for row in empty_conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert "market_watch" in tables
    assert "market_snapshots" in tables
    assert "market_aggregates" in tables  # 004：汇总缓存

    version = empty_conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
    assert version["v"] >= 3
