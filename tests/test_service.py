from datetime import date

from core import db, sample_data, service


def make():
    conn = db.connect(":memory:")
    db.init_db(conn)
    pid = sample_data.load_sample(conn, today=date(2026, 11, 6))
    return conn, pid


def test_sample_schedule_builds():
    conn, pid = make()
    s, tasks, deps = service.build_schedule(conn, pid)
    assert len(tasks) == 22 and len(deps) == 24
    assert s.project_start == date(2026, 11, 9)
    assert s.critical_ids()
    df = service.schedule_frame(s, tasks)
    assert df["완료편차(일)"].max() >= 1  # 압축기 점검 기간 증가로 편차 발생


def test_resources_and_ev():
    conn, pid = make()
    s, _, _ = service.build_schedule(conn, pid)
    a = service.assignment_frame(conn, pid, s)
    load = service.resource_loading(a, s)
    assert not load.empty
    ev = service.earned_value(s, a)
    assert ev["BAC"] > 0 and 0 < ev["SPI"] < 1


def test_pm_generation_and_completion():
    conn, _ = make()
    today = date(2026, 11, 6)
    created = service.generate_pm_work_orders(conn, 14, today)
    assert created
    assert service.generate_pm_work_orders(conn, 14, today) == []  # 중복 발행 방지
    wo = conn.execute("SELECT id, pm_plan_id FROM work_orders WHERE pm_plan_id IS NOT NULL LIMIT 1").fetchone()
    service.complete_work_order(conn, wo[0], today, 2, "ok")
    last = conn.execute("SELECT last_done FROM pm_plans WHERE id=?", [wo[1]]).fetchone()[0]
    assert last == today.isoformat()


def test_backup_roundtrip():
    conn, _ = make()
    dump = db.export_json(conn)
    conn2 = db.connect(":memory:")
    db.init_db(conn2)
    db.import_json(conn2, dump)
    for t in db.TABLE_ORDER:
        a = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        b = conn2.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        assert a == b, t


def test_sync_table_add_update_delete():
    import pandas as pd
    conn, _ = make()
    res = db.table_df(conn, "resources")
    ed = res.copy()
    ed.loc[0, "name"] = "김전기(수정)"
    ed = ed.drop(index=1)  # 삭제
    ed = pd.concat([ed, pd.DataFrame([{"id": None, "name": "신규 기술자", "rtype": "인력", "max_units": 1}])])
    n = db.sync_table(conn, "resources", ed, res["id"])
    assert n == (1, len(res) - 1, 1)
    names = db.table_df(conn, "resources")["name"].tolist()
    assert "김전기(수정)" in names and "신규 기술자" in names and res.loc[1, "name"] not in names
