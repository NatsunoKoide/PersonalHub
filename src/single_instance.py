"""单实例互斥：同一个数据家同时只允许一个 PersonalHub 进程。

为什么要有它（ADR 0013 的前传）：库是 SQLite，两个实例并发写会互相撞
「database is locked」，前端表现为页签永远停在「加载中」——用户只会觉得
应用坏了。文件锁在进程崩溃时由操作系统自动释放，不会遗留假锁。

锁文件放数据家里（app.lock），跟数据一起搬家；测试用临时数据家，互不影响。
"""

from __future__ import annotations

import os
import sys
from typing import BinaryIO

LOCK_NAME = "app.lock"


def acquire_lock() -> BinaryIO | int | None:
    """尝试独占当前数据家。

    成功返回锁文件句柄（进程退出前别关，关了锁就放了）；拿不到返回 None，
    说明已经有一个实例在跑。
    """
    from . import paths

    paths.ensure_dirs()
    target = paths.data_home() / LOCK_NAME
    try:
        # 另一个实例若还独占打开着（哪怕不同桌面会话），这里会直接吃 PermissionError，
        # 这本身就是「已有实例在跑」的信号，按重复启动处理，别甩堆栈。
        handle = os.open(str(target), os.O_CREAT | os.O_RDWR)
    except OSError:
        return None
    try:
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(handle, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, ValueError):
        os.close(handle)
        return None
    os.write(handle, str(os.getpid()).encode())
    return handle


def warn_duplicate() -> None:
    """第二个实例起不来时给用户一个看得见的解释。"""
    message = "PersonalHub 已经在运行了，同一个数据家一次只开一个窗口。\n请到任务栏找已经打开的那个。"
    try:
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, "PersonalHub", 0x40)
        else:
            print(message, file=sys.stderr)
    except Exception:
        print(message, file=sys.stderr)
