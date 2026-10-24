"""行情后台刷新服务：把慢吞吞的联网取数收拢到一条后台线程里。

为什么要有它：行情一次刷新要打八九个数据源（腾讯、东财、币圈、CoinGecko、
VIX、恐慌指数），失败还有重试，慢则十几秒。这些活过去在 Api 的全局锁里跑，
导致打开行情页期间其他页签全部卡在加载中（见 docs/adr/0010）。

规矩：
- 刷新只发生在这里的后台线程里，用**自己的连接**，不碰 Api 的全局锁；
- 对外只暴露 status()（毫秒级，只读内存标志），UI 靠轮询它拿进度；
- 并发只允许一次：刷新中又来请求，直接返回「已在刷」；
- 自动刷新有 60 秒节流（反复切进行情页不该反复打接口），手动刷新 force 绕过；
- 失败一律静默：界面继续用本地快照和上一轮汇总，用户看不出区别。
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta

from . import db, market, paths
from .repo import market as market_repo
from .sync import enabled as net_enabled

# 两次自动刷新之间的最小间隔。手动刷新（force=True）不受这个限制。
MIN_AUTO_INTERVAL = timedelta(seconds=60)

# 等后台刷新结束的最长时间（测试与 UI 轮询都用它兜底）
JOIN_TIMEOUT = 180.0


class _MarketSyncService:
    """进程级单例。app 全程只有一个，测试里也共用（状态可重置）。"""

    def __init__(self) -> None:
        # 可重入：status() 会在持锁状态下被 refresh() 内部调用
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._syncing = False
        self._last_finished: datetime | None = None
        self._last_written = 0

    # ---------------- 对外 ----------------

    def status(self) -> dict:
        """当前刷新状态。只读内存，不碰数据库，不持任何业务锁。"""
        with self._lock:
            return {
                "syncing": self._syncing,
                "last_finished_at": (
                    self._last_finished.isoformat(timespec="seconds") if self._last_finished else None
                ),
                "written": self._last_written,
            }

    def refresh(self, db_path=None, force: bool = False) -> dict:
        """起一次后台刷新，立即返回，绝不等待网络。

        返回 {"started": bool, "reason": str, "syncing": bool, ...}：
        - started=True：这次真起了线程；
        - started=False + reason="busy"：已有刷新在跑（UI 继续轮询即可）；
        - started=False + reason="throttled"：距上次自动刷新太近，
          本地数据还新鲜，不用刷（手动刷新 force=True 可绕过）；
        联网总开关关着时线程会空转一圈（UI 从 overview 的 net_enabled
        已经知道，不会来踢），不算失败。
        syncing 为 True 时 UI 才需要轮询——它同时覆盖「刚起的」和「已在跑的」。
        """
        target = str(db_path) if db_path else str(paths.database_path())
        with self._lock:
            if self._syncing:
                return {"started": False, "reason": "busy", **self.status()}
            if not force and self._last_finished is not None:
                if datetime.now() - self._last_finished < MIN_AUTO_INTERVAL:
                    return {"started": False, "reason": "throttled", **self.status()}
            self._syncing = True
            thread = threading.Thread(
                target=self._run, args=(target,), daemon=True, name="market-sync"
            )
            self._thread = thread
        try:
            thread.start()
        except Exception:
            # 起不来就把标志还回去，别让 UI 永远等一个不存在的线程
            with self._lock:
                self._syncing = False
            return {"started": False, "reason": "busy", **self.status()}
        return {"started": True, "reason": "", **self.status()}

    def wait_idle(self, timeout: float = JOIN_TIMEOUT) -> bool:
        """等当前刷新结束（测试用）。没在刷就立刻返回 True。"""
        with self._lock:
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
        return not self.status()["syncing"]

    def reset(self) -> None:
        """清空状态（测试用）：不杀线程，只把节流和计数归零。"""
        with self._lock:
            self._syncing = False
            self._last_finished = None
            self._last_written = 0
            self._thread = None

    # ---------------- 后台线程 ----------------

    def _run(self, target: str) -> None:
        written = 0
        try:
            conn = db.connect(target)
            try:
                if net_enabled(conn):
                    bundle = market.fetch_bundle(conn)
                    market_repo.save_aggregates(
                        conn, bundle.get("aggregates") or {}, bundle.get("temperature") or []
                    )
                    written = int(bundle.get("written") or 0)
            finally:
                conn.close()
        except Exception:
            # 失败静默：本地快照和上一轮汇总还在，界面照常显示
            pass
        finally:
            with self._lock:
                self._syncing = False
                self._last_finished = datetime.now()
                self._last_written = written


service = _MarketSyncService()
