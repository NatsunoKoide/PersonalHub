"""启动入口：建库、迁移、每日自动备份，然后开窗口。"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import threading
from pathlib import Path

from . import db, market_service, paths, single_instance, sync
from .seed import seed_all
from .version import APP_NAME, APP_VERSION, SCHEMA_VERSION

UI_FILE = Path(__file__).parent / "ui" / "index.html"


def build_context(db_path: str | Path | None = None) -> sqlite3.Connection:
    paths.ensure_dirs()
    conn = db.open_db(db_path)
    seed_all(conn)
    # 每天首次启动留一份快照，迁移出问题时有退路
    if not db.backup_exists_today():
        db.create_backup(conn)
    return conn


def _sync_in_background(db_path: str) -> None:
    """联网的活儿放后台：节假日/汇率用一条独立连接，行情收拢给后台刷新服务。

    主连接忙着给界面取数据时，这条连接写它的节假日，谁也不碍着谁。
    行情的刷新由 market_service 用第三条连接跑，不占 Api 的全局锁——
    不然打开行情页的十几秒里，其他页签全得排队（ADR 0010）。
    """
    try:
        conn = db.connect(db_path)
    except (OSError, sqlite3.Error):
        conn = None
    if conn is not None:
        try:
            sync.sync_all(conn)
        except (OSError, sqlite3.Error):
            pass
        finally:
            conn.close()
    market_service.service.refresh(db_path, force=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=APP_NAME)
    parser.add_argument("--db", help="指定数据库文件，默认用数据家里的那个")
    parser.add_argument("--version", action="store_true", help="打印版本号后退出")
    parser.add_argument("--info", action="store_true", help="打印数据家位置后退出")
    args = parser.parse_args(argv)

    if args.version:
        print(f"{APP_NAME} {APP_VERSION} (schema {SCHEMA_VERSION})")
        return 0

    if args.info:
        print(f"数据家: {paths.data_home()}")
        print(f"数据库: {paths.database_path()}")
        print(f"备份目录: {paths.backups_dir()}")
        return 0

    # 单实例互斥：两个进程并发写同一个 SQLite 会互相撞锁，
    # 界面表现为页签永远停在加载中，宁可直说也不让用户猜（ADR 0013）
    lock_handle = single_instance.acquire_lock()
    if lock_handle is None:
        single_instance.warn_duplicate()
        return 1

    db_path = str(Path(args.db).resolve()) if args.db else str(paths.database_path())
    conn = build_context(db_path)

    import webview

    from .api import Api

    api = Api(conn)
    threading.Thread(target=_sync_in_background, args=(db_path,), daemon=True).start()
    window = webview.create_window(
        f"{APP_NAME} {APP_VERSION}",
        url=UI_FILE.as_uri(),
        js_api=api,
        width=1320,
        height=880,
        min_size=(1120, 720),
        background_color="#f5f6f8",
    )
    webview.start(debug=False)
    # 退出前把 WAL 落回主库，这样用户看到的体积就是真实占用
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
