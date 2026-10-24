-- 行情汇总数据的本地缓存：板块榜、涨跌停、四市场温度。
--
-- 这些是「一次刷新一批、刷新前一直有效」的汇总值，不像快照那样按日积累，
-- 所以按 kind 各存一行，payload 是 JSON。刷新时只覆盖非空结果——
-- 一次没拿到不该抹掉上一轮的榜。行情页打开时先读这里秒开，
-- 后台刷新成功后由 UI 轮询替换。见 docs/adr/0010。
CREATE TABLE IF NOT EXISTS market_aggregates (
    kind TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
