"""Streamlit AppTest로 모든 화면이 오류 없이 그려지는지 확인."""
import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
PAGES = sorted(p.name for p in (ROOT / "views").glob("*.py") if p.name not in ("__init__.py", "common.py"))


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("MAINT_DB", str(tmp_path / "t.db"))
    monkeypatch.chdir(ROOT)


def test_main_app_runs():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    assert not at.exception, at.exception


@pytest.mark.parametrize("page", PAGES)
def test_page_renders(page):
    at = AppTest.from_file(str(ROOT / "views" / page), default_timeout=60)
    at.session_state["project_id"] = 1
    at.run()
    assert not at.exception, [e.message for e in at.exception]


SAVE_BUTTONS = {
    "tasks.py": "💾 저장",
    "dependencies.py": "💾 저장",
    "resources.py": "💾 자원 저장",
    "equipment.py": "💾 저장",
    "pm_plans.py": "💾 저장",
    "progress.py": "💾 진척 저장",
    "work_orders.py": "💾 변경 저장",
}


def _counts():
    from core import db
    conn = db.connect()
    db.init_db(conn)
    out = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in db.TABLE_ORDER}
    conn.close()
    return out


@pytest.mark.parametrize("page,label", SAVE_BUTTONS.items())
def test_save_roundtrip_keeps_data(page, label):
    at = AppTest.from_file(str(ROOT / "views" / page), default_timeout=60)
    at.session_state["project_id"] = 1
    at.run()
    before = _counts()
    assert before["tasks"] > 0  # 예제 데이터가 실제로 로드된 DB인지 확인
    btn = next(b for b in at.button if b.label == label)
    btn.click().run()
    assert not at.exception, [e.message for e in at.exception]
    assert _counts() == before


def test_generate_pm_work_orders_button():
    at = AppTest.from_file(str(ROOT / "views" / "pm_plans.py"), default_timeout=60)
    at.run()
    n0 = _counts()["work_orders"]
    next(b for b in at.button if b.label == "작업지시 발행").click().run()
    assert not at.exception
    assert _counts()["work_orders"] >= n0
