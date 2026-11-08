import json
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app  # noqa: E402
from planner import report  # noqa: E402
from planner.scheduler import (CycleError, DepIn, TaskIn, WorkCalendar, compute,  # noqa: E402
                               parse_predecessors)


def T(i, level=1, dur=1, **kw):
    return TaskIn(id=i, row=i, level=level, name=f"T{i}", duration=dur, **kw)


MON = date(2026, 10, 5)


def test_calendar_skips_weekend_and_holiday():
    cal = WorkCalendar(MON, True, [date(2026, 10, 9)])
    assert cal.to_date(4) == date(2026, 10, 12)  # 금요일 휴일 + 주말
    assert cal.to_index(date(2026, 10, 10)) == 4  # 토요일 -> 다음 작업일
    assert cal.to_date(-1) == date(2026, 10, 2)


def test_parse_predecessors():
    assert parse_predecessors("3, 5SS+2, 7ff-1일") == [(3, "FS", 0), (5, "SS", 2), (7, "FF", -1)]
    with pytest.raises(ValueError):
        parse_predecessors("abc")


def test_cpm_fs_ss_ff_and_critical():
    tasks = [T(1, dur=3), T(2, dur=2), T(3, dur=4), T(4, dur=1)]
    deps = [DepIn(1, 2), DepIn(1, 3, "SS", 1), DepIn(2, 4), DepIn(3, 4, "FF", 0)]
    s = compute(tasks, deps, MON)
    t = s.tasks
    assert (t[2].es, t[2].ef) == (3, 5)
    assert (t[3].es, t[3].ef) == (1, 5)
    assert t[4].es == 5
    assert t[1].critical and t[4].critical
    assert s.finish_index == 6


def test_summary_rollup_and_wbs():
    tasks = [T(1, 1, 0), T(2, 2, 2), T(3, 2, 3), T(4, 1, 1)]
    s = compute(tasks, [DepIn(2, 3), DepIn(1, 4)], MON)
    assert s.tasks[1].is_summary and s.tasks[3].wbs == "1.2" and s.tasks[4].wbs == "2"
    assert (s.tasks[1].es, s.tasks[1].ef) == (0, 5)
    assert s.tasks[4].es == 5  # 요약 작업 관계 -> 하위 작업으로 펼침


def test_cycle_detected():
    with pytest.raises(CycleError):
        compute([T(1), T(2)], [DepIn(1, 2), DepIn(2, 1)], MON)


def test_status_date_forecast_and_delay():
    base = compute([T(1, dur=5), T(2, dur=5)], [DepIn(1, 2)], MON)
    bl = {i: (t.start, t.finish, t.duration) for i, t in base.tasks.items()}
    tasks = [T(1, dur=5, actual_start=MON, pct=40), T(2, dur=5)]
    for t in tasks:
        t.baseline_start, t.baseline_finish, t.baseline_duration = bl[t.id]
    s = compute(tasks, [DepIn(1, 2)], MON, status_date=date(2026, 10, 9))
    # 5일 중 40% → 잔여 3일을 10/12 부터
    assert s.tasks[1].finish == date(2026, 10, 14)
    assert s.tasks[2].finish_var == 3 and s.tasks[2].status == "지연"
    assert s.kpi["finish_var"] == 3 and s.kpi["spi"] < 1


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = create_app({"DATABASE": str(tmp_path / "t.db"), "TESTING": True})
    return app.test_client()


def test_pages_and_exports(client):
    r = client.post("/projects/sample")
    pid = int(r.location.split("/")[2])
    for u in ["/", "gantt", "gantt?mode=tracking", "network", "wbs", "resources", "usage", "usage?unit=day",
              "delay", "info", "export.xlsx", "export.pptx", "export.json"]:
        url = u if u == "/" else f"/p/{pid}/{u}"
        assert client.get(url).status_code == 200, url
    assert client.get(f"/p/{pid}/export.xlsx").data[:2] == b"PK"
    assert client.get(f"/p/{pid}/export.pptx").data[:2] == b"PK"


def test_api_save_cycle_rejected_and_resource_autocreate(client):
    pid = int(client.post("/projects/sample").location.split("/")[2])
    d = client.get(f"/api/p/{pid}").get_json()
    items = [{k: t.get(k) for k in ("id", "level", "name", "duration", "predecessors", "resources", "pct")} for t in d["tasks"]]
    bad = json.loads(json.dumps(items))
    bad[1]["predecessors"] = "3"
    assert client.post(f"/api/p/{pid}/tasks", json={"tasks": bad}).status_code == 400
    items.append({"id": None, "level": 1, "name": "신규", "duration": 2, "predecessors": "20", "resources": "새인력[50%]"})
    r = client.post(f"/api/p/{pid}/tasks", json={"tasks": items})
    assert r.status_code == 200
    j = r.get_json()
    assert j["tasks"][-1]["resources"] == "새인력[50%]"
    assert any(x["name"] == "새인력" for x in j["resources"])


def test_report_rule_based_docx(client):
    pid = int(client.post("/projects/sample").location.split("/")[2])
    r = client.post(f"/p/{pid}/report", data={"notes": "제작사 납기 지연"})
    rid = int(r.location.rstrip("/").split("/")[-1])
    assert client.get(f"/p/{pid}/report/{rid}").status_code == 200
    doc = client.get(f"/p/{pid}/report/{rid}.docx")
    assert doc.status_code == 200 and doc.data[:2] == b"PK"


def test_report_uses_openai_when_key_present(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    seen = {}

    class FakeCompletions:
        def create(self, **kw):
            seen.update(kw)
            content = json.dumps({"title": "AI 보고서", "headline": "핵심", "summary": ["a"], "status": ["b"],
                                  "causes": [], "countermeasures": [], "conclusion": "끝"}, ensure_ascii=False)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    class FakeOpenAI:
        def __init__(self, **kw):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    import openai
    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    pid = int(client.post("/projects/sample").location.split("/")[2])
    r = client.post(f"/p/{pid}/report", data={"notes": ""})
    page = client.get(r.location).get_data(as_text=True)
    assert "AI 보고서" in page and "gpt-4o-mini" in page
    assert seen["model"] == "gpt-4o-mini" and seen["response_format"] == {"type": "json_object"}
