-- 联网能力与外币记账

-- 记账流水：记下原币金额，同时留一份折算成人民币的金额。
-- 所有统计一律读 amount_cny，这样同一笔账不会因汇率变动而改历史。
ALTER TABLE ledger_entries ADD COLUMN currency TEXT NOT NULL DEFAULT 'CNY';
ALTER TABLE ledger_entries ADD COLUMN amount_cny REAL NOT NULL DEFAULT 0;

-- 迁移前已有的流水都是人民币，原币金额就是折算金额
UPDATE ledger_entries SET amount_cny = amount WHERE currency = 'CNY';

-- 汇率缓存：1 单位外币值多少人民币。断网时用上一次的继续干活。
CREATE TABLE IF NOT EXISTS fx_rates (
    code       TEXT PRIMARY KEY,   -- USD / JPY / EUR …
    rate       REAL    NOT NULL,   -- 1 外币 = rate 人民币
    updated_at TEXT    NOT NULL
);
