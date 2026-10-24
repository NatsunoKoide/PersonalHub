-- PersonalHub 初始结构：四个模块 + 节假日表
-- 日期一律存 YYYY-MM-DD 文本，跨语言边界无需转换。

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- 模块一：任务与习惯
CREATE TABLE IF NOT EXISTS tasks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT    NOT NULL,
    due_date   TEXT    NOT NULL,
    tag        TEXT    NOT NULL DEFAULT '',
    priority   INTEGER NOT NULL DEFAULT 1,     -- 2 高 / 1 中 / 0 低
    done       INTEGER NOT NULL DEFAULT 0,
    done_at    TEXT,
    created_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks (due_date);

CREATE TABLE IF NOT EXISTS habits (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL,
    cadence    TEXT    NOT NULL DEFAULT 'daily',  -- daily | weekly
    archived   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS habit_logs (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    habit_id INTEGER NOT NULL REFERENCES habits (id) ON DELETE CASCADE,
    day      TEXT    NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_habit_logs_unique ON habit_logs (habit_id, day);
CREATE INDEX IF NOT EXISTS idx_habit_logs_day ON habit_logs (day);

-- 模块二：OKR
CREATE TABLE IF NOT EXISTS objectives (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    title            TEXT    NOT NULL,
    cadence          TEXT    NOT NULL,          -- year | quarter | month | week
    year             INTEGER NOT NULL,
    period_start     TEXT,
    period_end       TEXT,
    note             TEXT    NOT NULL DEFAULT '',
    manual_progress  REAL,                      -- 空表示走加权算法
    created_at       TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_objectives_year ON objectives (year);

CREATE TABLE IF NOT EXISTS key_results (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    objective_id  INTEGER NOT NULL REFERENCES objectives (id) ON DELETE CASCADE,
    name          TEXT    NOT NULL,
    start_value   REAL    NOT NULL DEFAULT 0,
    current_value REAL    NOT NULL DEFAULT 0,
    target_value  REAL    NOT NULL DEFAULT 0,
    unit          TEXT    NOT NULL DEFAULT '',
    weight        REAL    NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_key_results_objective ON key_results (objective_id);

-- 模块三：记账
CREATE TABLE IF NOT EXISTS categories (
    name       TEXT PRIMARY KEY,
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ledger_entries (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    day        TEXT    NOT NULL,
    amount     REAL    NOT NULL,
    direction  TEXT    NOT NULL DEFAULT 'expense',   -- expense | income
    category   TEXT    NOT NULL DEFAULT '其他',
    method     TEXT    NOT NULL DEFAULT '',
    note       TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_ledger_day ON ledger_entries (day);

CREATE TABLE IF NOT EXISTS budgets (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    scope        TEXT    NOT NULL,               -- total | category
    category     TEXT    NOT NULL DEFAULT '',
    month        TEXT    NOT NULL,               -- YYYY-MM，scope=total 时 category 为空
    limit_amount REAL   NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_budgets_unique ON budgets (scope, category, month);

-- 模块四：饮食与身体
CREATE TABLE IF NOT EXISTS meals (
    day     TEXT    NOT NULL,
    slot    TEXT    NOT NULL,                    -- breakfast | lunch | dinner | snack
    content TEXT    NOT NULL DEFAULT '',
    kcal    REAL,
    PRIMARY KEY (day, slot)
);

CREATE TABLE IF NOT EXISTS day_notes (
    day        TEXT PRIMARY KEY,
    water_cups INTEGER NOT NULL DEFAULT 0,
    note       TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS weigh_ins (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    day       TEXT    NOT NULL,
    weight    REAL,
    body_fat  REAL,
    note      TEXT    NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_weigh_ins_day ON weigh_ins (day);

CREATE TABLE IF NOT EXISTS quick_phrases (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT    NOT NULL DEFAULT 'food',
    text TEXT    NOT NULL
);

-- 日历：节假日与调休上班日
CREATE TABLE IF NOT EXISTS holidays (
    day  TEXT PRIMARY KEY,
    type TEXT NOT NULL,                          -- holiday | workday
    name TEXT NOT NULL DEFAULT ''
);
