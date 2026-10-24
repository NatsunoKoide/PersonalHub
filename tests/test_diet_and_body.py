from src.repo import body, diet


def test_day_starts_empty_with_four_slots(conn):
    day = diet.get_day(conn, "2026-10-23")

    assert [slot["slot"] for slot in day["slots"]] == [
        "breakfast",
        "lunch",
        "dinner",
        "snack",
    ]
    assert day["water_cups"] == 0
    assert day["recorded"] == 0


def test_saving_slot_is_an_upsert(conn):
    diet.save_slot(conn, "2026-10-23", "breakfast", "燕麦+鸡蛋")
    diet.save_slot(conn, "2026-10-23", "breakfast", "燕麦+鸡蛋+牛奶")

    day = diet.get_day(conn, "2026-10-23")
    breakfast = day["slots"][0]
    assert breakfast["content"] == "燕麦+鸡蛋+牛奶"
    assert day["recorded"] == 1


def test_blank_slot_does_not_count_as_recorded(conn):
    diet.save_slot(conn, "2026-10-23", "lunch", "随便吃了点")
    diet.save_slot(conn, "2026-10-23", "dinner", "   ")

    day = diet.get_day(conn, "2026-10-23")
    assert day["recorded"] == 1
    assert day["slots"][1]["content"] == "随便吃了点"


def test_recorded_by_day_counts_meals_per_day(conn):
    diet.save_slot(conn, "2026-10-22", "breakfast", "燕麦")
    diet.save_slot(conn, "2026-10-22", "lunch", "米饭")
    diet.save_slot(conn, "2026-10-23", "dinner", "沙拉")

    counts = diet.recorded_by_day(conn, "2026-10-01", "2026-10-31")
    assert counts == {"2026-10-22": 2, "2026-10-23": 1}


def test_water_and_note_are_independent(conn):
    diet.set_water(conn, "2026-10-23", 6)
    diet.set_note(conn, "2026-10-23", "今天多喝水")

    day = diet.get_day(conn, "2026-10-23")
    assert day["water_cups"] == 6
    assert day["note"] == "今天多喝水"


def test_unknown_slot_is_rejected(conn):
    try:
        diet.save_slot(conn, "2026-10-23", "brunch", "早午餐")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown slot should be rejected")


def test_quick_phrases(conn):
    diet.add_phrase(conn, "燕麦 40g")
    diet.add_phrase(conn, "鸡胸肉 150g")

    texts = [phrase["text"] for phrase in diet.phrases(conn)]
    assert "燕麦 40g" in texts


def test_weigh_in_upserts_by_day(conn):
    body.upsert(conn, "2026-10-19", 78.5, 22.1, "状态不错")
    body.upsert(conn, "2026-10-19", 78.0, 22.0)

    assert conn.execute("SELECT COUNT(*) AS n FROM weigh_ins").fetchone()["n"] == 1
    assert body.latest(conn)["weight"] == 78.0


def test_series_computes_deltas(conn):
    body.upsert(conn, "2026-10-05", 80.0, 23.0)
    body.upsert(conn, "2026-10-12", 79.0, 22.5)
    body.upsert(conn, "2026-10-19", 78.0, 22.0)

    series = body.list_series(conn)
    assert [item["weight"] for item in series] == [80.0, 79.0, 78.0]
    assert series[0]["weight_delta"] is None
    assert series[1]["weight_delta"] == -1.0
    assert series[2]["body_fat_delta"] == -0.5


def test_week_status_detects_missing_weigh_in(conn):
    from src.repo import body as body_repo

    assert body_repo.week_status(conn, "2026-10-23")["logged_this_week"] is False

    body.upsert(conn, "2026-10-12", 79.0, 22.5)
    status = body_repo.week_status(conn, "2026-10-23")
    assert status["logged_this_week"] is False
    assert status["weeks_since"] == 1

    body.upsert(conn, "2026-10-21", 78.0, 22.0)
    assert body_repo.week_status(conn, "2026-10-23")["logged_this_week"] is True


def test_targets_round_trip(conn):
    body.set_targets(conn, 70.0, 15.0)

    targets = body.targets(conn)
    assert targets["target_weight"] == 70.0
    assert targets["target_body_fat"] == 15.0
    assert "daily_kcal_limit" not in targets
