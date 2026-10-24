-- 行情：自选清单与每交易日快照

-- 自选清单。code 是规范代码：sh600519 / sz000001 / hk00700 / usAAPL / usDJI。
-- 输入时做规范化（见 src/market.py 的 normalize_code），数据库里只存规范形式。
CREATE TABLE IF NOT EXISTS market_watch (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT    NOT NULL UNIQUE,
    name        TEXT    NOT NULL,
    market      TEXT    NOT NULL,                   -- a / hk / us
    kind        TEXT    NOT NULL DEFAULT 'stock',   -- stock / fund / index
    created_day TEXT    NOT NULL
);

-- 每交易日快照：一个 (day, code) 一行，同一天重复刷新只更新不插行。
-- day 取行情自带时间戳的日期（周末自然落到上一个交易日），不是本地今天。
CREATE TABLE IF NOT EXISTS market_snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    day           TEXT    NOT NULL,
    code          TEXT    NOT NULL,
    name          TEXT    NOT NULL,
    market        TEXT    NOT NULL,
    kind          TEXT    NOT NULL DEFAULT 'stock',
    price         REAL,
    change_amount REAL,
    change_pct    REAL,
    updated_at    TEXT    NOT NULL,
    UNIQUE (day, code)
);

CREATE INDEX IF NOT EXISTS idx_market_snapshots_lookup
    ON market_snapshots (code, day);
