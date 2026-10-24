from src.repo import okr


def _objective(conn, cadence="year", year=2026, title="目标"):
    return okr.add(conn, title, cadence, year, f"{year}-01-01", f"{year}-12-31")


def test_kr_progress_forward():
    kr = {"start_value": 0, "current_value": 5, "target_value": 10}
    assert okr.kr_progress(kr) == 0.5


def test_kr_progress_reverse_target():
    """反向目标（体重下降）不需要额外标记方向。"""
    kr = {"start_value": 80, "current_value": 75, "target_value": 70}
    assert okr.kr_progress(kr) == 0.5


def test_kr_progress_clamped():
    over = {"start_value": 0, "current_value": 12, "target_value": 10}
    under = {"start_value": 5, "current_value": 0, "target_value": 10}
    assert okr.kr_progress(over) == 1.0
    assert okr.kr_progress(under) == 0.0


def test_kr_progress_zero_span():
    done = {"start_value": 3, "current_value": 3, "target_value": 3}
    not_done = {"start_value": 3, "current_value": 1, "target_value": 3}
    assert okr.kr_progress(done) == 1.0
    assert okr.kr_progress(not_done) == 0.0


def test_progress_is_weighted(conn):
    oid = _objective(conn)
    okr.add_kr(conn, oid, "跑步", 0, 100, 100, "km", 3)
    okr.add_kr(conn, oid, "读书", 0, 0, 10, "本", 1)

    objective = okr.get(conn, oid)
    assert objective["progress"] == 0.75


def test_manual_override_wins(conn):
    oid = _objective(conn)
    okr.add_kr(conn, oid, "跑步", 0, 100, 100, "km", 1)

    okr.update(conn, oid, "目标", "year", 2026, "2026-01-01", "2026-12-31", "", 60)
    assert okr.get(conn, oid)["progress"] == 0.6

    okr.update(conn, oid, "目标", "year", 2026, "2026-01-01", "2026-12-31", "", None)
    assert okr.get(conn, oid)["progress"] == 1.0


def test_objective_without_kr_has_zero_progress(conn):
    oid = _objective(conn)
    assert okr.get(conn, oid)["progress"] == 0.0


def test_deleting_objective_cascades_to_krs(conn):
    oid = _objective(conn)
    okr.add_kr(conn, oid, "跑步", 0, 10, 100)

    conn.execute("PRAGMA foreign_keys = ON")
    okr.remove(conn, oid)

    assert conn.execute("SELECT COUNT(*) AS n FROM key_results").fetchone()["n"] == 0


def test_cadence_overview_groups_by_period(conn):
    _objective(conn, "year", 2026, "年度目标")
    _objective(conn, "quarter", 2026, "季度目标")

    overview = {item["cadence"]: item for item in okr.cadence_overview(conn, 2026)}
    assert overview["year"]["count"] == 1
    assert overview["week"]["count"] == 0
    assert overview["week"]["progress"] == 0.0


def test_upcoming_only_lists_unfinished(conn):
    finished = okr.add(conn, "已完成", "quarter", 2026, "2026-01-01", "2026-10-30")
    okr.add_kr(conn, finished, "跑步", 0, 100, 100, "km", 1)
    okr.add(conn, "还没完成", "quarter", 2026, "2026-01-01", "2026-11-05")
    okr.add(conn, "太远了", "year", 2026, "2026-01-01", "2027-06-01")

    items = okr.upcoming(conn, "2026-10-23", within_days=30)
    assert [item["title"] for item in items] == ["还没完成"]
