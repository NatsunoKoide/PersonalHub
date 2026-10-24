"""单实例互斥：第二个实例必须拿不到锁，释放后又能拿到。"""

import os

from src import single_instance


def test_second_instance_is_blocked_then_allowed(tmp_path, monkeypatch):
    monkeypatch.setenv("PERSONALHUB_HOME", str(tmp_path))

    first = single_instance.acquire_lock()
    assert first is not None, "第一个实例应该拿得到锁"

    try:
        second = single_instance.acquire_lock()
        assert second is None, "第二个实例必须拿不到锁"
    finally:
        os.close(first)  # 模拟第一个实例退出（或崩溃）

    # 崩溃/退出后锁必须自动可用，不能遗留假锁
    again = single_instance.acquire_lock()
    assert again is not None, "锁释放后应该能重新拿到"
    os.close(again)


def test_lock_file_lives_in_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PERSONALHUB_HOME", str(tmp_path))

    handle = single_instance.acquire_lock()
    assert handle is not None
    try:
        assert (tmp_path / "app.lock").exists()
    finally:
        os.close(handle)
