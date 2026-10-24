"""行情取数：腾讯报价 + 东方财富汇总 + 币圈与恐慌指数。全部免密钥，失败一律静默。

数据源分工（都实测过，见 README 与 docs/adr/0009）：
- 腾讯 qt.gtimg.cn：自选个股与指数报价。A股/港股/美股一个接口统一字段布局，
  返回 GBK 文本。我们的规范代码（sh600519 / hk00700 / usAAPL）就是腾讯的代码。
- 东方财富 push2 ulist.np：八大指数一个 JSON 调用拿全。
- 东方财富 clist：行业板块涨幅/跌幅榜（po=1 涨、po=0 跌）。
- 东方财富 ZTPool / DTPool：涨停 / 跌停家数。DTPool 时好时坏，
  拿不到就返回 None，界面显示「—」，不编数据。
- 币圈 Binance api/v3：批量 24h 报价 + 日 K；拉不到回落 OKX v5 全量过滤。
- 币圈板块 CoinGecko categories：各板块 24h 涨幅。
- 币圈恐慌指数 alternative.me/fng；美股恐慌指数 Yahoo ^VIX。
  A股/港股没有免费的官方恐慌指数，用已有数据估算，界面会标注「估算」。

「联网总开关」关掉时本模块一个请求都不发。
"""

from __future__ import annotations

import datetime
import json
import re
import sqlite3

from . import net
from .dates import today_iso
from .repo import market as market_repo
from .repo import meta
from .sync import enabled as net_enabled

TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="
EASTMONEY_ULIST_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
EASTMONEY_CLIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
EASTMONEY_ZT_URL = "https://push2ex.eastmoney.com/getTopicZTPool"
EASTMONEY_DT_URL = "https://push2ex.eastmoney.com/getTopicDTPool"
BINANCE_TICKER_URL = "https://api.binance.com/api/v3/ticker/24hr"
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
OKX_TICKERS_URL = "https://www.okx.com/api/v5/market/tickers"
COINGECKO_CATEGORIES_URL = "https://api.coingecko.com/api/v3/coins/categories"
ALTME_FNG_URL = "https://api.alternative.me/fng/"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/"
YAHOO_SPARK_URL = "https://query1.finance.yahoo.com/v7/finance/spark"

# 东方财富接口固定要带的一个公开 ut 串
_EM_UT = "7eea3edcaed734bea9cbfc24409ed989"

# 币圈固定展示的三个币（像指数一样常驻，不进自选也能看）
CRYPTO_COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

# 币圈计价货币。带这些结尾的一律按币圈认；不带的裸码要命中 KNOWN_CRYPTO
CRYPTO_QUOTES = ("USDT", "USDC", "FDUSD", "BUSD")

# 知名裸币：用户只输 btc / sol 也能认。与美股代码撞车的（SOL 也是股票代码）
# 按币圈优先——真要交易那只股票，本就不该用裸代码。
KNOWN_CRYPTO = {
    "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "DOT", "MATIC",
    "LINK", "LTC", "TRX", "ATOM", "UNI", "APT", "ARB", "OP", "SUI", "TON",
    "NEAR", "FIL", "ETC", "XLM", "HBAR", "ICP", "VET", "ALGO", "AAVE", "MKR",
    "GRT", "SAND", "MANA", "AXS", "CRV", "SNX", "COMP", "INJ", "SEI", "TIA",
    "PEPE", "WIF", "BONK", "SHIB", "FLOKI", "JUP", "PYTH", "RENDER", "FETCH",
}

# 币圈常用显示名（认不出的保留代码本身）
CRYPTO_NAMES = {
    "BTCUSDT": "比特币", "ETHUSDT": "以太坊", "SOLUSDT": "Solana",
    "BNBUSDT": "BNB", "XRPUSDT": "瑞波币", "DOGEUSDT": "狗狗币",
    "ADAUSDT": "艾达币", "AVAXUSDT": "雪崩", "LINKUSDT": "Chainlink",
    "TONUSDT": "Toncoin", "SUIUSDT": "Sui", "PEPEUSDT": "Pepe",
}

# 币圈板块市值下限（美元）。低于这个数的分类全是尘埃板块，
# 24h 涨跌动辄 ±100%，上了榜也没有参考意义。
CRYPTO_SECTOR_MIN_CAP = 1_000_000_000

# CoinGecko 板块名的常用中文（认不出的保留英文原名）
CRYPTO_SECTOR_NAMES = {
    "Smart Contract Platform": "智能合约平台",
    "AI Agents": "AI 智能体",
    "Artificial Intelligence (AI)": "人工智能",
    "Meme": "模因币", "Memecoin": "模因币",
    "DeFi": "DeFi 去中心化金融",
    "Decentralized Finance (DeFi)": "DeFi 去中心化金融",
    "Layer 1 (L1)": "L1 公链", "Layer 2 (L2)": "L2 扩容",
    "Gaming": "链游", "Solana Ecosystem": "Solana 生态",
    "Ethereum Ecosystem": "以太坊生态", "BNB Chain Ecosystem": "BNB 生态",
    "Real World Assets (RWA)": "RWA 实体资产", "Stablecoins": "稳定币",
    "Exchange-Based Tokens": "平台币", "Metaverse": "元宇宙",
    "Privacy Coins": "隐私币", "Liquid Staking Tokens": "流动性质押",
    "Restaking": "再质押", "DePIN": "DePIN 去中心化物理网络",
    "Data Availability (DA)": "数据可用性", "Zero Knowledge (ZK)": "零知识证明",
    "Bitcoin Ecosystem": "比特币生态", "Prediction Markets": "预测市场",
    "Perpetual DEX": "永续合约 DEX", "Tokenized Stocks": "股票代币化",
}

# Alternative.me 恐慌指数的英文标签 → 中文
FEAR_GREED_LABELS = {
    "Extreme Fear": "极度恐慌", "Fear": "恐慌", "Neutral": "中性",
    "Greed": "贪婪", "Extreme Greed": "极度贪婪",
}

# 指数条：东财 secid → 我们的规范代码与市场
INDEX_SECIDS = [
    ("1.000001", "sh000001", "a"),
    ("0.399001", "sz399001", "a"),
    ("0.399006", "sz399006", "a"),
    ("1.000688", "sh000688", "a"),
    ("100.HSI", "hkHSI", "hk"),
    ("100.DJIA", "usDJI", "us"),
    ("100.NDX", "usIXIC", "us"),
    ("100.SPX", "usINX", "us"),
]

# 已知指数（用户自选这些代码时按指数归类，其余按个股）
KNOWN_INDICES = {
    "sh000001", "sh000300", "sh000688", "sh000905",
    "sz399001", "sz399005", "sz399006",
    "hkHSI", "usDJI", "usIXIC", "usINX",
}

# 腾讯返回 v_xxx="..."; 一行一个
_TENCENT_LINE = re.compile(r'v_([A-Za-z0-9._]+)="([^"]*)"')

# 名称和现价的位置在各市场是一致的（1 和 3），但行情时间戳的位置不统一：
# A股在第 28 位、港股 29、美股 27 或 29。所以时间戳用格式匹配找，
# 涨跌额和涨跌幅固定在它后面两位。
_F_NAME, _F_PRICE = 1, 3
_TIME_PATTERNS = (
    re.compile(r"^\d{14}$"),                                     # A股：20261023161500
    re.compile(r"^\d{4}/\d{1,2}/\d{1,2} \d{1,2}:\d{2}:\d{2}$"),  # 港股：2026/10/23 16:08:14
    re.compile(r"^\d{4}-\d{2}-\d{2} \d{1,2}:\d{2}:\d{2}$"),      # 美股：2026-10-23 14:18:59
)


def _locate_quote_tail(fields: list[str]) -> tuple[str, float, float] | None:
    """找到行情时间戳，返回 (时间, 涨跌额, 涨跌幅百分比)。

    时间戳后面必须紧跟两个像样的小数（涨跌幅绝对值不超过 100），
    这样即使前面有长得像时间的数字也不会认错。
    """
    for index, field in enumerate(fields):
        if index + 2 >= len(fields):
            break
        text = field.strip()
        if not any(pattern.match(text) for pattern in _TIME_PATTERNS):
            continue
        change = _to_float(fields[index + 1])
        pct = _to_float(fields[index + 2])
        if change is not None and pct is not None and abs(pct) <= 100:
            return text, change, pct
    return None


# ---------------- 代码规范化 ----------------


def normalize_code(raw: str) -> dict | None:
    """把用户输入的代码规范成 {code, market, kind}。认不出来返回 None。

    规则：
    - 带前缀（sh/sz/hk/us）的原样保留
    - 6 位数字：5/6/9 开头是沪（6/9 主板·科创板个股，5 基金·ETF），
      0/1/2/3 开头是深（000001 解析为深市的平安银行，
      要上证指数请输 sh000001——这个歧义是市场本身的，UI 上有提示）
    - 5 位且 0 开头（00700）或更短的纯数字：港股，补前导零到 5 位
    - 币圈：带 USDT 等计价货币结尾（btcusdt），或裸码命中知名币（btc/sol）→
      规范成 BTCUSDT 这种 Binance 代码。与美股裸代码撞车的按币圈优先
    - 其余字母：美股，转大写
    """
    text = str(raw or "").strip()
    if not text:
        return None

    crypto = _normalize_crypto(text)
    if crypto:
        return crypto

    lowered = text.lower()
    for prefix, market in (("sh", "a"), ("sz", "a"), ("hk", "hk"), ("us", "us")):
        if lowered.startswith(prefix) and len(text) > len(prefix):
            body = text[len(prefix):]
            code = prefix + (body.upper() if market == "us" else body)
            return {"code": code, "market": market, "kind": _kind_of(code, market)}

    if re.fullmatch(r"\d{6}", text):
        market = "a"
        # 沪市：6/9 主板·科创板，5 基金·ETF；深市：0/1/2/3 主板·创业板·基金
        code = ("sh" if text[0] in "569" else "sz") + text
        return {"code": code, "market": market, "kind": _kind_of(code, market)}

    if re.fullmatch(r"\d{1,5}", text):
        body = text.zfill(5)
        code = "hk" + body
        return {"code": code, "market": "hk", "kind": _kind_of(code, "hk")}

    if re.fullmatch(r"[A-Za-z.]{1,12}", text):
        code = "us" + text.upper()
        return {"code": code, "market": "us", "kind": _kind_of(code, "us")}

    return None


def _normalize_crypto(text: str) -> dict | None:
    """识别币圈代码：btc / BTC / btcusdt / BTC-USDT → BTCUSDT。

    判定顺序：先看带不带计价货币（带了就一定按币圈认，交给 Binance 校验）；
    不带的裸码必须命中 KNOWN_CRYPTO，免得把 AAPL 这类美股代码误判成币。
    """
    upper = text.upper().replace("-", "").replace("_", "")
    if not upper or not re.fullmatch(r"[A-Z0-9]+", upper):
        return None
    for quote in CRYPTO_QUOTES:
        if upper.endswith(quote) and len(upper) > len(quote):
            base = upper[: -len(quote)]
            if re.fullmatch(r"[A-Z]{2,10}", base):
                return {"code": base + quote, "market": "crypto", "kind": "coin"}
            return None
    if upper in KNOWN_CRYPTO:
        return {"code": upper + "USDT", "market": "crypto", "kind": "coin"}
    return None


def _kind_of(code: str, market: str) -> str:
    if code in KNOWN_INDICES:
        return "index"
    if market == "a" and re.fullmatch(r"(sh5\d{5}|sz1[2568]\d{4})", code):
        # 沪市基金 5xxxxx（50 传统封基 / 51 ETF·LOF / 52·55·58 等），
        # 深市基金 12·15·16·18xxxx。都是 6 位，注意别把位数写少。
        return "fund"
    return "stock"


# ---------------- 腾讯：报价 ----------------


def _quote_day(raw_time: str) -> str:
    """从腾讯的行情时间归日。三种格式：20261023161500 / 2026/10/23 16:08 / 2026-10-23 14:18。"""
    text = str(raw_time or "").strip().replace("/", "").replace("-", "")
    digits = text[:8]
    if len(digits) == 8 and digits.isdigit():
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return today_iso()


def _to_float(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _utc_day(stamp, ms: bool = True) -> str:
    """Unix 时间戳 → UTC 日期。币圈 7×24 交易，归日按 UTC 算最干净。

    ms=True 是毫秒（Binance/OKX），False 是秒（alternative.me）。
    拿不准就退回今天，绝不编。
    """
    try:
        seconds = int(stamp)
    except (TypeError, ValueError):
        return today_iso()
    if ms:
        seconds //= 1000
    try:
        moment = datetime.datetime.fromtimestamp(seconds, tz=datetime.timezone.utc)
    except (OSError, OverflowError, ValueError):
        return today_iso()
    return moment.strftime("%Y-%m-%d")


def parse_quotes(text: str) -> list[dict]:
    """解析腾讯行情文本。字段不全或价格缺失的行直接跳过。"""
    quotes: list[dict] = []
    for match in _TENCENT_LINE.finditer(text or ""):
        code, payload = match.group(1), match.group(2)
        fields = payload.split("~")
        if len(fields) <= _F_PRICE:
            continue
        price = _to_float(fields[_F_PRICE])
        tail = _locate_quote_tail(fields)
        if price is None or price <= 0 or tail is None:
            continue
        quote_time, change, pct = tail
        quotes.append({
            "code": code,
            "name": fields[_F_NAME] or code,
            "day": _quote_day(quote_time),
            "price": price,
            "change_amount": change,
            "change_pct": pct,
        })
    return quotes


def fetch_quotes(codes: list[str]) -> list[dict]:
    """批量拉报价。失败或空结果返回 []。"""
    if not codes:
        return []
    text = net.get_text(TENCENT_QUOTE_URL + ",".join(codes), encoding="gbk")
    if not text:
        return []
    quotes = parse_quotes(text)
    wanted = set(codes)
    return [quote for quote in quotes if quote["code"] in wanted]


# ---------------- 币圈：Binance 报价，OKX 回落 ----------------


def _crypto_name(code: str) -> str:
    return CRYPTO_NAMES.get(code, code)


def parse_crypto_quotes_binance(payload) -> list[dict]:
    """Binance /ticker/24hr：批量（symbols=[...]）返回 list，单个返回 dict。

    失败时它返回 {"code": -1121, "msg": ...}，解析出来就是空列表，
    由调用方回落 OKX。
    """
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        return []
    quotes: list[dict] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        code = str(row.get("symbol") or "")
        price = _to_float(row.get("lastPrice"))
        if not code or price is None or price <= 0:
            continue
        quotes.append({
            "code": code,
            "name": _crypto_name(code),
            "day": _utc_day(row.get("closeTime")),
            "price": price,
            "change_amount": _to_float(row.get("priceChange")),
            "change_pct": _to_float(row.get("priceChangePercent")),
        })
    return quotes


def parse_crypto_quotes_okx(payload, wanted: list[str]) -> list[dict]:
    """OKX /v5/market/tickers 回落解析。instId 过滤参数不生效，只能客户端筛。

    wanted 是 OKX 形式（BTC-USDT）。24h 涨跌用 (最新价-开盘价)/开盘价 算。
    """
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    wanted_set = {code.upper() for code in wanted}
    quotes: list[dict] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        inst_id = str(row.get("instId") or "")
        if inst_id not in wanted_set:
            continue
        price = _to_float(row.get("last"))
        open_24h = _to_float(row.get("open24h"))
        if price is None or price <= 0:
            continue
        code = inst_id.replace("-", "")
        quotes.append({
            "code": code,
            "name": _crypto_name(code),
            "day": _utc_day(row.get("ts")),
            "price": price,
            "change_amount": (price - open_24h) if open_24h else None,
            "change_pct": ((price - open_24h) / open_24h * 100) if open_24h else None,
        })
    return quotes


def fetch_crypto_quotes(codes: list[str]) -> list[dict]:
    """币圈报价。Binance 一个批量调用拿全；缺的或整体失败回落 OKX。"""
    wanted = [str(code).upper() for code in codes if str(code).strip()]
    if not wanted:
        return []
    payload = net.get_json(BINANCE_TICKER_URL, {"symbols": json.dumps(wanted)})
    quotes = parse_crypto_quotes_binance(payload)
    found = {quote["code"] for quote in quotes}
    missing = [code for code in wanted if code not in found]
    if missing:
        okx_wanted = [code.replace("USDT", "-USDT") for code in missing]
        quotes += parse_crypto_quotes_okx(
            net.get_json(OKX_TICKERS_URL, {"instType": "SPOT"}), okx_wanted
        )
    return [quote for quote in quotes if quote["code"] in set(wanted)]


def parse_crypto_klines(payload) -> list[dict]:
    """Binance 日 K：[开盘时间ms, 开, 高, 低, 收, ...]，取收盘价与 UTC 日期。"""
    if not isinstance(payload, list):
        return []
    points: list[dict] = []
    for row in payload:
        if not isinstance(row, list) or len(row) < 5:
            continue
        price = _to_float(row[4])
        if price is None:
            continue
        points.append({"day": _utc_day(row[0]), "price": price})
    return points


def fetch_crypto_klines(code: str, days: int = 30) -> list[dict]:
    """币圈日 K 历史，失败返回 []。Binance 拉不到就没有走势图，不编。"""
    payload = net.get_json(
        BINANCE_KLINES_URL, {"symbol": str(code).upper(), "interval": "1d", "limit": int(days)}
    )
    return parse_crypto_klines(payload)


# ---------------- 币圈板块：CoinGecko 分类 ----------------


def parse_crypto_sectors(payload) -> list[dict]:
    """CoinGecko categories：每个分类带 24h 市值涨跌幅。

    市值低于 CRYPTO_SECTOR_MIN_CAP 或涨跌幅为 null 的直接跳过——
    尘埃板块的 ±100% 没有参考意义。
    """
    if not isinstance(payload, list):
        return []
    rows: list[dict] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        pct = _to_float(item.get("market_cap_change_24h"))
        cap = _to_float(item.get("market_cap"))
        if pct is None or cap is None or cap < CRYPTO_SECTOR_MIN_CAP:
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        rows.append({
            "code": str(item.get("id") or ""),
            "name": CRYPTO_SECTOR_NAMES.get(name, name),
            "pct": pct,
        })
    return rows


def fetch_crypto_sectors(direction: str = "up", limit: int = 5) -> list[dict]:
    """币圈板块 24h 涨/跌前几。direction: 'up' | 'down'。失败返回 []。"""
    payload = net.get_json(COINGECKO_CATEGORIES_URL)
    rows = parse_crypto_sectors(payload)
    rows.sort(key=lambda row: row["pct"], reverse=(direction == "up"))
    return rows[: int(limit)]


# ---------------- 美股板块：Yahoo 行业 ETF ----------------

# 11 只 SPDR 行业 ETF，覆盖 GICS 全部一级行业。它们的当日涨跌就是行业涨跌的
# 标准代理。Yahoo spark 一个请求拿全部，比逐 symbol 拉便宜得多。
US_SECTOR_ETFS = [
    ("XLC", "通信服务"), ("XLY", "可选消费"), ("XLP", "必需消费"),
    ("XLE", "能源"), ("XLF", "金融"), ("XLV", "医疗保健"),
    ("XLI", "工业"), ("XLK", "信息技术"), ("XLB", "原材料"),
    ("XLRE", "房地产"), ("XLU", "公用事业"),
]


def parse_us_sectors(payload) -> list[dict]:
    """Yahoo spark：spark.result[].response[].meta 里带最新价与当日涨跌幅。"""
    try:
        result = payload["spark"]["result"]
    except (KeyError, TypeError):
        return []
    rows: list[dict] = []
    for item in result:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "")
        responses = item.get("response")
        if not isinstance(responses, list) or not responses:
            continue
        meta = responses[0].get("meta") if isinstance(responses[0], dict) else None
        if not isinstance(meta, dict):
            continue
        pct = _to_float(meta.get("regularMarketChangePercent"))
        if pct is None:
            continue
        name = next((label for code, label in US_SECTOR_ETFS if code == symbol), symbol)
        rows.append({"code": symbol, "name": name, "pct": pct})
    return rows


def fetch_us_sectors(direction: str = "up", limit: int = 5) -> list[dict]:
    """美股行业 24h 涨/跌前几（SPDR 行业 ETF 当日涨跌）。失败返回 []。"""
    payload = net.get_json(YAHOO_SPARK_URL, {
        "symbols": ",".join(code for code, _label in US_SECTOR_ETFS),
        "range": "1d",
        "interval": "1d",
    })
    rows = parse_us_sectors(payload)
    rows.sort(key=lambda row: row["pct"], reverse=(direction == "up"))
    return rows[: int(limit)]


# ---------------- 恐慌指数 / 市场温度 ----------------


def parse_fear_greed(payload) -> dict | None:
    """alternative.me 币圈恐慌指数。data[0] 是最新，timestamp 是秒不是毫秒。"""
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        return None
    latest = data[0] if isinstance(data[0], dict) else None
    if latest is None:
        return None
    value = _to_float(latest.get("value"))
    if value is None:
        return None
    return {
        "value": value,
        "label": FEAR_GREED_LABELS.get(str(latest.get("value_classification") or ""),
                                       str(latest.get("value_classification") or "")),
        "day": _utc_day(latest.get("timestamp"), ms=False),
    }


def fetch_crypto_fear_greed() -> dict | None:
    """币圈恐慌指数（Alternative.me），失败返回 None。"""
    return parse_fear_greed(net.get_json(ALTME_FNG_URL, {"limit": 1}))


def parse_yahoo_price(payload) -> float | None:
    """Yahoo v8 chart：meta.regularMarketPrice 就是最新价。"""
    try:
        result = payload["chart"]["result"][0]["meta"]["regularMarketPrice"]
        return float(result)
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def fetch_us_vix() -> dict | None:
    """美股恐慌指数 VIX（Yahoo，^VIX）。失败返回 None。"""
    payload = net.get_json(YAHOO_CHART_URL + "%5EVIX", {"interval": "1d", "range": "5d"})
    price = parse_yahoo_price(payload)
    if price is None or price <= 0:
        return None
    return {"value": price, "day": today_iso()}


# VIX → 0-100 温度的分段锚点。VIX 越低越贪婪，做反向线性映射。
# 锚点：(VIX, 温度)。10→95、15→80、20→60、25→45、30→30、40→10。
_VIX_ANCHORS = ((10.0, 95.0), (15.0, 80.0), (20.0, 60.0), (25.0, 45.0), (30.0, 30.0), (40.0, 10.0))

# 0-100 温度的语义分档
_TEMP_BANDS = ((25, "极度恐慌"), (45, "恐慌"), (55, "中性"), (75, "贪婪"), (101, "极度贪婪"))


def _temp_label(value: float) -> str:
    for ceiling, label in _TEMP_BANDS:
        if value < ceiling:
            return label
    return "极度贪婪"


def _vix_to_temperature(vix: float) -> float:
    """VIX 按锚点分段线性映射到 0-100 温度（锚点见表 _VIX_ANCHORS）。"""
    if vix <= _VIX_ANCHORS[0][0]:
        return _VIX_ANCHORS[0][1]
    for (low_vix, low_temp), (high_vix, high_temp) in zip(_VIX_ANCHORS, _VIX_ANCHORS[1:]):
        if vix <= high_vix:
            ratio = (vix - low_vix) / (high_vix - low_vix)
            return low_temp + ratio * (high_temp - low_temp)
    return _VIX_ANCHORS[-1][1]


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _move_to_temperature(pct: float) -> float:
    """指数涨跌幅 → 温度。±3% 映射到 0/100，中间线性。"""
    return _clamp(50 + pct / 3.0 * 50.0)


def _breadth_temperature(limits: dict) -> float | None:
    """涨跌停家数比 → 温度。涨停占比越高越热。两边都缺就返回 None。"""
    up, down = limits.get("up"), limits.get("down")
    if up is None or down is None or (up + down) <= 0:
        return None
    return up / (up + down) * 100.0


def market_temperature(indices: list[dict], limits: dict) -> list[dict]:
    """四市场温度（0-100，越高越贪婪），按 A股/港股/美股/币圈 排序返回。

    币圈/美股取真指数；A股/港股没有免费的官方恐慌指数，用已有数据估算，
    每条带 estimated 标记，界面照实显示「估算」。

    估算口径：
    - A股 = 涨跌停占比 与 四大 A 股指数涨跌均温 各半；
      跌停数拿不到时（DTPool 时好时坏）只用指数均温
    - 港股只有恒生一条，温度就是它的涨跌幅映射，样本薄，来源里写清
    """
    result: list[dict] = []

    def _index_move(markets: tuple[str, ...]) -> float | None:
        moves = [q["change_pct"] for q in indices
                 if q.get("market") in markets and q.get("change_pct") is not None]
        if not moves:
            return None
        return sum(moves) / len(moves)

    a_move = _index_move(("a",))
    if a_move is not None:
        move_temp = _move_to_temperature(a_move)
        breadth = _breadth_temperature(limits)
        if breadth is not None:
            value = 0.5 * move_temp + 0.5 * breadth
            detail = "估算：涨跌停占比 + 四大指数均温"
        else:
            value = move_temp
            detail = "估算：四大指数均温（跌停数未取到）"
        result.append(_temp_entry("a", "A股", value, detail, True, today_iso()))

    hk_move = _index_move(("hk",))
    if hk_move is not None:
        value = _move_to_temperature(hk_move)
        result.append(_temp_entry("hk", "港股", value, "估算：恒生指数涨跌映射（仅一条样本）", True, today_iso()))

    # 美股：VIX 反向映射（真恐慌指数）
    vix = fetch_us_vix()
    if vix:
        temperature = _vix_to_temperature(vix["value"])
        result.append(_temp_entry("us", "美股", temperature, f"VIX {vix['value']:.1f}", False, vix["day"]))

    # 币圈：Alternative.me 恐慌指数本身就是 0-100
    fng = fetch_crypto_fear_greed()
    if fng:
        result.append(_temp_entry(
            "crypto", "币圈", fng["value"], "Alternative.me 恐慌指数", False, fng["day"]
        ))

    return result


def _temp_entry(market: str, label: str, value: float, source: str,
                estimated: bool, day: str) -> dict:
    return {
        "market": market,
        "market_label": label,
        "value": round(_clamp(value)),
        "label": _temp_label(value),
        "source": source,
        "estimated": estimated,
        "day": day,
    }


# ---------------- 指数：腾讯主源，东财回落 ----------------

# 八大指数的规范代码（腾讯的 q= 直接用这些）
INDEX_CODES = [code for _secid, code, _market in INDEX_SECIDS]


def _index_meta() -> dict:
    return {code: (market, "index") for _secid, code, market in INDEX_SECIDS}


def _fetch_indices_eastmoney() -> list[dict]:
    """东财 ulist 回落：一个调用拿全八条，但不给可靠时间戳。

    day 留空，由 sync_market 用自选报价的真实交易日补。
    """
    payload = net.get_json(EASTMONEY_ULIST_URL, {
        "ut": _EM_UT,
        "fltt": 2,
        "fields": "f2,f3,f4,f12,f14",
        "secids": ",".join(secid for secid, _, _ in INDEX_SECIDS),
        "pn": 1,
        "pz": len(INDEX_SECIDS),
    }, referer=net.EASTMONEY_REFERER)
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, dict):
        return []

    by_secid = {}
    for row in data.get("diff") or []:
        if isinstance(row, dict):
            by_secid[str(row.get("f12"))] = row

    quotes: list[dict] = []
    for secid, code, market in INDEX_SECIDS:
        row = by_secid.get(secid.split(".", 1)[1])
        if row is None:
            continue
        price = _to_float(row.get("f2"))
        if price is None:
            continue
        quotes.append({
            "code": code,
            "name": row.get("f14") or code,
            "day": None,
            "price": price,
            "change_amount": _to_float(row.get("f4")),
            "change_pct": _to_float(row.get("f3")),
            "market": market,
            "kind": "index",
        })
    return quotes


def fetch_indices(quotes: list[dict] | None = None) -> list[dict]:
    """八大指数。优先用腾讯（和自选同一个接口，字段布局一样，还带时间戳）；
    腾讯整体没返回才回落东财 ulist。

    quotes 是调用方已经拉到的腾讯报价（sync 时指数和自选合并成一次请求），
    传了就直接从里面挑指数，不再发请求；不传就自己拉一次。
    """
    if quotes is None:
        quotes = fetch_quotes(INDEX_CODES)
    index_meta = _index_meta()
    indices = [quote for quote in quotes if quote["code"] in index_meta]
    if len(indices) == len(INDEX_CODES):
        for quote in indices:
            quote["market"], quote["kind"] = index_meta[quote["code"]]
        return indices
    return _fetch_indices_eastmoney()


# ---------------- 东方财富：板块榜 ----------------


def fetch_sectors(direction: str = "up", limit: int = 5) -> list[dict]:
    """行业板块涨/跌幅前几。direction: 'up' | 'down'。失败返回 []。"""
    payload = net.get_json(EASTMONEY_CLIST_URL, {
        "ut": _EM_UT,
        "pn": 1,
        "pz": int(limit),
        "po": 1 if direction == "up" else 0,
        "np": 1,
        "fltt": 2,
        "invt": 2,
        "fid": "f3",
        "fs": "m:90 t:2",
        "fields": "f12,f14,f3",
    }, referer=net.EASTMONEY_REFERER)
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, dict):
        return []

    sectors = []
    for row in data.get("diff") or []:
        if not isinstance(row, dict):
            continue
        pct = _to_float(row.get("f3"))
        if pct is None:
            continue
        sectors.append({"code": row.get("f12"), "name": row.get("f14") or "", "pct": pct})
    return sectors


# ---------------- 东方财富：涨跌停 ----------------


def _fetch_pool_count(url: str) -> int | None:
    payload = net.get_json(url, {
        "ut": _EM_UT,
        "dpt": "wz.ztzt" if "ZT" in url else "wz.dtzt",
        "Pageindex": 0,
        "pagesize": 1,
        "sort": "fbt:asc",
        "date": today_iso().replace("-", ""),
    }, referer=net.EASTMONEY_REFERER)
    if not isinstance(payload, dict) or payload.get("rc") != 0:
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    total = data.get("tc")
    return int(total) if isinstance(total, (int, float)) else None


def fetch_limit_stats() -> dict:
    """{up: 涨停家数, down: 跌停家数}，拿不到的一项是 None。"""
    return {
        "up": _fetch_pool_count(EASTMONEY_ZT_URL),
        "down": _fetch_pool_count(EASTMONEY_DT_URL),
    }


def fetch_aggregates() -> dict:
    """页面汇总区要的活数据：A股/币圈/美股板块榜 + 涨跌停。不入库。"""
    return {
        "sectors_up": fetch_sectors("up"),
        "sectors_down": fetch_sectors("down"),
        "us_sectors_up": fetch_us_sectors("up"),
        "us_sectors_down": fetch_us_sectors("down"),
        "crypto_sectors_up": fetch_crypto_sectors("up"),
        "crypto_sectors_down": fetch_crypto_sectors("down"),
        "limits": fetch_limit_stats(),
    }


def fetch_bundle(conn: sqlite3.Connection) -> dict:
    """一次完整刷新：报价（写快照）+ 汇总 + 四市场温度。

    给后台刷新服务用（见 src/market_service.py）：这一串全是联网取数，
    绝不能在 Api 的全局锁里跑，否则其他页签会一起卡在加载中。
    返回 dict 里 aggregates / temperature 由调用方落库。
    """
    live = sync_market(conn)
    aggregates = fetch_aggregates()
    temperature = market_temperature(
        live.get("indices") or [], aggregates.get("limits") or {"up": None, "down": None}
    )
    return {**live, "aggregates": aggregates, "temperature": temperature}


# ---------------- 同步 ----------------


def sync_market(conn: sqlite3.Connection) -> dict:
    """拉指数 + 币圈三币 + 全部自选，写快照。返回各项结果计数。

    行情一天一个样，没有「半天刷一次」的缓存期，每次调用都真拉。
    总开关关掉时直接返回，一个请求都不发。

    归日规则：股票自选报价带真实行情时间（周末自然落到上一交易日），
    股票指数跟自选看齐；币圈 7×24 交易，归日取 UTC 日期，各自为政。
    写之前清掉比最晚归日还新的残留行（早期版本归日算错留的垃圾）。
    """
    if not net_enabled(conn):
        return {"indices": [], "quotes": [], "crypto": [], "written": 0}

    watch = market_repo.list_watch(conn)
    watch_meta = {item["code"]: item for item in watch}
    stock_codes = [item["code"] for item in watch if item["market"] != "crypto"]
    crypto_codes = [item["code"] for item in watch if item["market"] == "crypto"]

    # 指数和股票自选合并成一次腾讯请求（同一个接口、同一种字段布局）；
    # 腾讯没给全的指数由东财 ulist 补
    tencent_codes = list(dict.fromkeys(INDEX_CODES + stock_codes))
    tencent_quotes = fetch_quotes(tencent_codes) if tencent_codes else []
    indices = fetch_indices(tencent_quotes)
    quotes = []
    for quote in tencent_quotes:
        if quote["code"] in _index_meta():
            continue
        item = watch_meta.get(quote["code"])
        if item:
            quote["market"] = item["market"]
            quote["kind"] = item["kind"]
        quotes.append(quote)

    # 币圈：固定三币常驻 + 加密自选，一个批量调用拿全
    crypto_codes = list(dict.fromkeys(CRYPTO_COINS + crypto_codes))
    crypto_quotes = fetch_crypto_quotes(crypto_codes)
    for quote in crypto_quotes:
        quote["market"] = "crypto"
        quote["kind"] = "coin"

    # 东财回落来的指数没有时间戳，归日跟自选报价的真实交易日看齐
    undated = [quote for quote in indices if not quote.get("day")]
    if undated:
        fallback_day = max((quote["day"] for quote in quotes), default=today_iso())
        for quote in undated:
            quote["day"] = fallback_day

    all_quotes = indices + quotes + crypto_quotes
    written = market_repo.upsert_snapshots(conn, all_quotes)
    # 清理只针对股票行：币圈 UTC 日期常比股票交易日新（周六就是这样），
    # 那是真实数据，不能当垃圾删
    stock_day = max((q["day"] for q in indices + quotes if q.get("day")), default=None)
    if stock_day:
        market_repo.drop_rows_after(conn, stock_day)
    meta.set_setting(conn, "market.last_sync_at", today_iso())
    return {
        "indices": indices,
        "quotes": quotes,
        "crypto": crypto_quotes,
        "written": written,
    }
