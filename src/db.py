"""sqlite 连接与迁移链。

迁移脚本是纯 .sql 文件，按编号顺序执行，执行过的记在 schema_migrations 里。
任何 sqlite 工具都能直接打开这些脚本，不依赖本项目代码。
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from . import paths
from .dates import now_iso

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

COUNTED_TABLES = (
    "tasks",
    "habits",
    "habit_logs",
    "objectives",
    "key_results",
    "ledger_entries",
    "meals",
    "weigh_ins",
    "holidays",
    "fx_rates",
)


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    target = Path(db_path) if db_path else paths.database_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    # pywebview 会在另一个线程里回调 js_api，所以连接必须允许跨线程；
    # 并发访问由 Api 层的锁负责串行化。timeout 是写锁的排队上限：
    # 后台同步（节假日/汇率/行情）和界面写入共用一个库，短促竞争
    # 等一等就过去了，别动不动就抛 database is locked。
    conn = sqlite3.connect(str(target), check_same_thread=False, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _migration_files() -> list[tuple[int, Path]]:
    found: list[tuple[int, Path]] = []
    for path in MIGRATIONS_DIR.glob("*.sql"):
        try:
            version = int(path.name.split("_", 1)[0])
        except ValueError:
            continue
        found.append((version, path))
    return sorted(found)


def pending_migrations(conn: sqlite3.Connection) -> list[Path]:
    applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    return [path for version, path in _migration_files() if version not in applied]


def migrate(conn: sqlite3.Connection) -> list[str]:
    """按编号顺序补跑没执行过的迁移，返回本次执行的脚本名。"""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version INTEGER PRIMARY KEY,"
        " applied_at TEXT NOT NULL)"
    )
    applied_names: list[str] = []
    for path in pending_migrations(conn):
        version = int(path.name.split("_", 1)[0])
        conn.executescript(path.read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (version, now_iso()),
        )
        conn.commit()
        applied_names.append(path.name)
    return applied_names


def schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
    return int(row["v"]) if row and row["v"] is not None else 0


def open_db(db_path: str | Path | None = None) -> sqlite3.Connection:
    paths.ensure_dirs()
    conn = connect(db_path)
    migrate(conn)
    return conn


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    counts = {}
    for name in COUNTED_TABLES:
        row = conn.execute(f"SELECT COUNT(*) AS n FROM {name}").fetchone()
        counts[name] = int(row["n"])
    return counts


def db_size() -> int:
    """默认数据家下数据库的占用，包含 WAL 与共享内存文件。"""
    return _footprint(paths.database_path())


def database_size_of(conn: sqlite3.Connection) -> int:
    """当前连接指向的数据库占用。测试里连的是临时库，不能去读默认路径。"""
    row = conn.execute("PRAGMA database_list").fetchone()
    if row is None:
        return 0
    return _footprint(Path(row[2]))


def _footprint(main: Path) -> int:
    total = 0
    for target in (main, Path(str(main) + "-wal"), Path(str(main) + "-shm")):
        try:
            total += target.stat().st_size
        except OSError:
            pass
    return total


def backup_name(day: date | None = None) -> str:
    stamp = (day or date.today()).strftime("%Y-%m-%d")
    return f"{paths.DB_NAME.rsplit('.', 1)[0]}-{stamp}.db"


def backup_exists_today() -> bool:
    return (paths.backups_dir() / backup_name()).exists()


def create_backup(conn: sqlite3.Connection) -> Path:
    """用 sqlite 的 backup 接口做一份一致的快照，保留最近 30 份。"""
    paths.ensure_dirs()
    target = paths.backups_dir() / backup_name()
    target.parent.mkdir(parents=True, exist_ok=True)
    dest = sqlite3.connect(str(target))
    try:
        conn.backup(dest)
    finally:
        dest.close()
    _prune_backups(keep=30)
    return target


def _prune_backups(keep: int = 30) -> None:
    files = sorted(paths.backups_dir().glob("*.db"), key=lambda p: p.stat().st_mtime)
    for stale in files[:-keep]:
        try:
            stale.unlink()
        except OSError:
            pass
