import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import db, seed  # noqa: E402
from src.api import Api  # noqa: E402


@pytest.fixture(autouse=True)
def isolate_data_home(tmp_path, monkeypatch):
    """测试一律用临时数据家，绝不碰用户 AppData 里那个真的。"""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("PERSONALHUB_HOME", str(home))


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "test.db")
    db.migrate(connection)
    seed.seed_all(connection)
    yield connection
    connection.close()


@pytest.fixture
def api(conn):
    return Api(conn)


@pytest.fixture
def empty_conn(tmp_path):
    """只建结构不灌种子数据，用于验证迁移本身。"""
    connection = db.connect(tmp_path / "empty.db")
    yield connection
    connection.close()
