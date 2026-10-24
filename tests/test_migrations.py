from src import db
from src.version import SCHEMA_VERSION


def test_migrate_applies_all_scripts(empty_conn):
    applied = db.migrate(empty_conn)

    assert applied == [
        "001_init.sql",
        "002_online_and_currency.sql",
        "003_market.sql",
        "004_market_aggregates.sql",
    ]
    assert db.schema_version(empty_conn) == SCHEMA_VERSION
    assert db.pending_migrations(empty_conn) == []


def test_migrate_is_idempotent(empty_conn):
    db.migrate(empty_conn)
    assert db.migrate(empty_conn) == []


def test_all_tables_created(empty_conn):
    db.migrate(empty_conn)
    names = {
        row["name"]
        for row in empty_conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    expected = {
        "tasks",
        "habits",
        "habit_logs",
        "objectives",
        "key_results",
        "categories",
        "ledger_entries",
        "budgets",
        "meals",
        "day_notes",
        "weigh_ins",
        "quick_phrases",
        "holidays",
        "settings",
    }
    assert expected <= names


def test_migrations_are_plain_sql_files():
    """迁移脚本必须脱离本项目也能被任何 sqlite 工具执行。"""
    for _version, path in sorted(db._migration_files()):
        assert path.suffix == ".sql"
        script = path.read_text(encoding="utf-8")
        assert "CREATE TABLE IF NOT EXISTS" in script


def test_backup_produces_readable_copy(conn, tmp_path):
    from src.repo import tasks

    tasks.add(conn, "写测试", "2026-10-23")

    target = db.create_backup(conn)
    assert target.exists()
    assert target.stat().st_size > 0

    copy = db.connect(target)
    assert db.schema_version(copy) >= 1
    rows = copy.execute("SELECT title FROM tasks").fetchall()
    assert [row["title"] for row in rows] == ["写测试"]
    copy.close()
