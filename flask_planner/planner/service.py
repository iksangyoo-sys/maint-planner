"""프로젝트 데이터 읽기/쓰기와 일정 계산 연결."""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date, timedelta

from . import db
from .scheduler import (DepIn, Schedule, ScheduleError, TaskIn, compute, format_predecessor,
                        parse_holidays, parse_predecessors, to_date)


def _d(v):
    return v.isoformat() if isinstance(v, date) else v


# ------------------------------------------------------------------ 조회

def get_project(pid: int):
    return db.query("SELECT * FROM project WHERE id=?", (pid,), one=True)


def list_projects():
    return db.query("""SELECT p.*, (SELECT COUNT(*) FROM task t WHERE t.project_id=p.id) AS n_tasks
                       FROM project p ORDER BY p.id DESC""")


def load_rows(pid: int):
    tasks = db.query("SELECT * FROM task WHERE project_id=? ORDER BY row", (pid,))
    deps = db.query("SELECT * FROM dependency WHERE project_id=?", (pid,))
    resources = db.query("SELECT * FROM resource WHERE project_id=? ORDER BY id", (pid,))
    assigns = db.query("""SELECT a.* FROM assignment a JOIN task t ON t.id=a.task_id
                          WHERE t.project_id=?""", (pid,))
    return tasks, deps, resources, assigns


def _task_in(r) -> TaskIn:
    return TaskIn(id=r["id"], row=r["row"], level=r["level"], name=r["name"], duration=r["duration"],
                  constraint_start=to_date(r["constraint_start"]), actual_start=to_date(r["actual_start"]),
                  actual_finish=to_date(r["actual_finish"]), pct=r["pct"] or 0,
                  baseline_start=to_date(r["baseline_start"]), baseline_finish=to_date(r["baseline_finish"]),
                  baseline_duration=r["baseline_duration"])


def schedule_for(pid: int) -> Schedule:
    p = get_project(pid)
    tasks, deps, _, _ = load_rows(pid)
    return compute([_task_in(r) for r in tasks],
                   [DepIn(d["pred_id"], d["succ_id"], d["type"], d["lag"]) for d in deps],
                   to_date(p["start_date"]), status_date=to_date(p["status_date"]),
                   skip_weekends=bool(p["skip_weekends"]), holidays=parse_holidays(p["holidays"]))


def project_bundle(pid: int) -> dict:
    """화면·내보내기에서 공통으로 쓰는 계산 결과 묶음."""
    p = get_project(pid)
    tasks, deps, resources, assigns = load_rows(pid)
    sched = schedule_for(pid)
    raw = {r["id"]: r for r in tasks}
    res_by_id = {r["id"]: r for r in resources}
    task_res = defaultdict(list)
    for a in assigns:
        if a["resource_id"] in res_by_id:
            task_res[a["task_id"]].append((res_by_id[a["resource_id"]], a["units"]))
    preds_txt = defaultdict(list)
    for d in deps:
        if d["pred_id"] in sched.tasks and d["succ_id"] in sched.tasks:
            preds_txt[d["succ_id"]].append(format_predecessor(sched.tasks[d["pred_id"]].row, d["type"], d["lag"]))

    cost = {}
    for tid, t in sched.tasks.items():
        if not t.is_summary:
            cost[tid] = sum((r["rate"] or 0) * t.forecast_duration * u / 100 for r, u in task_res[tid])

    def rollup_cost(tid):
        t = sched.tasks[tid]
        if t.is_summary:
            cost[tid] = sum(rollup_cost(c) for c in t.children)
        return cost[tid]

    for tid in sched.order:
        if sched.tasks[tid].parent_id is None:
            rollup_cost(tid)

    rows = []
    for tid in sched.order:
        t, r = sched.tasks[tid], raw[tid]
        rows.append({
            "id": tid, "row": t.row, "level": t.level, "wbs": t.wbs, "name": t.name,
            "summary": t.is_summary, "milestone": t.is_milestone, "parent": t.parent_id,
            "duration": t.duration if t.is_summary else r["duration"],
            "forecast_duration": t.forecast_duration,
            "es": t.es, "ef": t.ef, "ls": t.ls, "lf": t.lf,
            "start": _d(t.start), "finish": _d(t.finish),
            "late_start": _d(t.late_start), "late_finish": _d(t.late_finish),
            "total_float": t.total_float, "free_float": t.free_float, "critical": t.critical,
            "pct": t.pct, "planned_pct": t.planned_pct, "status": t.status,
            "constraint_start": r["constraint_start"], "actual_start": r["actual_start"],
            "actual_finish": r["actual_finish"], "notes": r["notes"] or "",
            "baseline_start": _d(t.baseline_start), "baseline_finish": _d(t.baseline_finish),
            "baseline_duration": t.baseline_duration,
            "start_var": t.start_var, "finish_var": t.finish_var,
            "predecessors": ", ".join(preds_txt[tid]),
            "resources": ", ".join(res["name"] + ("" if u == 100 else f"[{u:g}%]") for res, u in task_res[tid]),
            "resource_list": [{"name": res["name"], "units": u} for res, u in task_res[tid]],
            "cost": round(cost.get(tid, 0)),
        })
    links = [{"pred": d.pred_id, "succ": d.succ_id, "type": d.type, "lag": d.lag} for d in sched.leaf_deps]
    return {
        "project": dict(p), "schedule": sched, "tasks": rows, "links": links,
        "resources": [dict(r) for r in resources], "task_res": task_res,
        "kpi": dict(sched.kpi, total_cost=round(sum(cost[t] for t in sched.order if sched.tasks[t].parent_id is None))),
        "project_start": _d(sched.project_start), "project_finish": _d(sched.project_finish),
        "status_date": p["status_date"], "baseline_finish": _d(sched.baseline_finish),
        "holidays": [d.isoformat() for d in parse_holidays(p["holidays"])],
        "skip_weekends": bool(p["skip_weekends"]),
    }


def bundle_json(b: dict) -> dict:
    return {k: v for k, v in b.items() if k not in ("schedule", "task_res")}


# ------------------------------------------------------------------ 저장

RES_RE = re.compile(r"^\s*(.+?)\s*(?:\[\s*(\d+(?:\.\d+)?)\s*%?\s*\])?\s*$")


def parse_resources(text: str) -> list[tuple[str, float]]:
    out = []
    for tok in (text or "").split(","):
        if tok.strip():
            m = RES_RE.match(tok)
            out.append((m.group(1), float(m.group(2) or 100)))
    return out


def save_tasks(pid: int, items: list[dict]) -> None:
    """간트 화면의 작업표 전체를 저장한다. 오류 시 아무것도 바꾸지 않는다."""
    con = db.get_db()
    try:
        con.execute("BEGIN")
        existing = {r["id"] for r in con.execute("SELECT id FROM task WHERE project_id=?", (pid,))}
        ids = []
        for n, it in enumerate(items, start=1):
            vals = (
                n, max(1, int(it.get("level") or 1)), str(it.get("name") or "").strip() or "새 작업",
                max(0.0, float(it.get("duration") if it.get("duration") not in (None, "") else 1)),
                to_date(it.get("constraint_start")) and _d(to_date(it.get("constraint_start"))),
                to_date(it.get("actual_start")) and _d(to_date(it.get("actual_start"))),
                to_date(it.get("actual_finish")) and _d(to_date(it.get("actual_finish"))),
                max(0.0, min(100.0, float(it.get("pct") or 0))), str(it.get("notes") or ""),
            )
            tid = it.get("id")
            if tid in existing:
                con.execute("""UPDATE task SET row=?, level=?, name=?, duration=?, constraint_start=?,
                               actual_start=?, actual_finish=?, pct=?, notes=? WHERE id=?""", vals + (tid,))
            else:
                tid = con.execute("""INSERT INTO task (row, level, name, duration, constraint_start, actual_start,
                                     actual_finish, pct, notes, project_id) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                                  vals + (pid,)).lastrowid
            ids.append(tid)
        for gone in existing - set(ids):
            con.execute("DELETE FROM task WHERE id=?", (gone,))

        # 선행작업
        con.execute("DELETE FROM dependency WHERE project_id=?", (pid,))
        row_to_id = {n: tid for n, tid in enumerate(ids, start=1)}
        for n, (it, tid) in enumerate(zip(items, ids), start=1):
            for row, typ, lag in parse_predecessors(str(it.get("predecessors") or "")):
                if row not in row_to_id:
                    raise ScheduleError(f"{n}행: 선행작업 ID {row} 이(가) 없습니다.")
                if row == n:
                    raise ScheduleError(f"{n}행: 자기 자신을 선행작업으로 지정할 수 없습니다.")
                con.execute("INSERT INTO dependency (project_id, pred_id, succ_id, type, lag) VALUES (?,?,?,?,?)",
                            (pid, row_to_id[row], tid, typ, lag))

        # 자원 배정 (없는 자원 이름은 자원 시트에 자동 추가)
        res = {r["name"]: r["id"] for r in con.execute("SELECT id, name FROM resource WHERE project_id=?", (pid,))}
        for it, tid in zip(items, ids):
            if "resources" not in it:
                continue
            con.execute("DELETE FROM assignment WHERE task_id=?", (tid,))
            for name, units in parse_resources(str(it.get("resources") or "")):
                if name not in res:
                    res[name] = con.execute("INSERT INTO resource (project_id, name) VALUES (?,?)", (pid, name)).lastrowid
                con.execute("INSERT INTO assignment (task_id, resource_id, units) VALUES (?,?,?)",
                            (tid, res[name], units))
        schedule_for(pid)  # 순환 등 검증
        con.commit()
    except Exception:
        con.rollback()
        raise


def set_baseline(pid: int, clear: bool = False) -> None:
    con = db.get_db()
    if clear:
        con.execute("""UPDATE task SET baseline_start=NULL, baseline_finish=NULL, baseline_duration=NULL
                       WHERE project_id=?""", (pid,))
        con.execute("UPDATE project SET baseline_saved_at=NULL WHERE id=?", (pid,))
    else:
        s = schedule_for(pid)
        for t in s.tasks.values():
            if not t.is_summary:
                con.execute("UPDATE task SET baseline_start=?, baseline_finish=?, baseline_duration=? WHERE id=?",
                            (_d(t.start), _d(t.finish), t.forecast_duration, t.id))
        con.execute("UPDATE project SET baseline_saved_at=datetime('now','localtime') WHERE id=?", (pid,))
    con.commit()


def update_project(pid: int, f: dict) -> None:
    db.execute("""UPDATE project SET name=?, manager=?, description=?, start_date=?, status_date=?,
                  skip_weekends=?, holidays=? WHERE id=?""",
               (f.get("name") or "이름 없는 프로젝트", f.get("manager", ""), f.get("description", ""),
                _d(to_date(f.get("start_date")) or date.today()), _d(to_date(f.get("status_date"))),
                1 if f.get("skip_weekends") else 0, f.get("holidays", ""), pid))


def create_project(f: dict) -> int:
    return db.execute("""INSERT INTO project (name, manager, description, start_date, status_date, skip_weekends, holidays)
                         VALUES (?,?,?,?,?,?,?)""",
                      (f.get("name") or "새 프로젝트", f.get("manager", ""), f.get("description", ""),
                       _d(to_date(f.get("start_date")) or date.today()), _d(to_date(f.get("status_date"))),
                       1 if f.get("skip_weekends", True) else 0, f.get("holidays", "")))


def delete_project(pid: int) -> None:
    db.execute("DELETE FROM project WHERE id=?", (pid,))


# ------------------------------------------------------------------ 자원

def save_resource(pid: int, f: dict, rid: int | None = None) -> None:
    vals = (f.get("name", "").strip() or "자원", f.get("type") or "인력", f.get("grp", ""),
            float(f.get("max_units") or 100), float(f.get("rate") or 0), f.get("email", ""))
    if rid:
        db.execute("UPDATE resource SET name=?, type=?, grp=?, max_units=?, rate=?, email=? WHERE id=? AND project_id=?",
                   vals + (rid, pid))
    else:
        db.execute("INSERT INTO resource (name, type, grp, max_units, rate, email, project_id) VALUES (?,?,?,?,?,?,?)",
                   vals + (pid,))


def delete_resource(pid: int, rid: int) -> None:
    db.execute("DELETE FROM resource WHERE id=? AND project_id=?", (rid, pid))


def resource_usage(b: dict, unit: str = "week") -> dict:
    """자원별 기간 부하(%)와 과부하 표시."""
    s: Schedule = b["schedule"]
    cal = s.calendar
    daily: dict[int, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    work = defaultdict(float)
    for tid, lst in b["task_res"].items():
        t = s.tasks.get(tid)
        if not t or t.is_summary:
            continue
        for r, u in lst:
            for i in range(t.es, t.ef):
                daily[r["id"]][i] += u
            work[r["id"]] += u / 100 * t.forecast_duration
    n = max(s.finish_index, 1)
    buckets = []  # (label, [idx...])
    if unit == "day":
        for i in range(n):
            buckets.append((cal.to_date(i).strftime("%m/%d"), [i]))
    else:
        cur, label = [], None
        for i in range(n):
            d = cal.to_date(i)
            mon = d - timedelta(days=d.weekday())
            lab = mon.strftime("%m/%d") + "주"
            if lab != label and cur:
                buckets.append((label, cur))
                cur = []
            label = lab
            cur.append(i)
        if cur:
            buckets.append((label, cur))
    rows = []
    for r in b["resources"]:
        dd = daily.get(r["id"], {})
        peak_list = []
        for _, idxs in buckets:
            peak_list.append(max((dd.get(i, 0) for i in idxs), default=0))
        over_days = [cal.to_date(i).isoformat() for i, v in sorted(dd.items()) if v > (r["max_units"] or 100) + 1e-9]
        rows.append({"resource": r, "peaks": peak_list, "work_days": round(work[r["id"]], 1),
                     "cost": round(work[r["id"]] * (r["rate"] or 0)),
                     "max_peak": max(dd.values(), default=0), "over_days": over_days})
    return {"labels": [l for l, _ in buckets], "rows": rows}


# ------------------------------------------------------------------ 백업 / 복원

def export_json(pid: int) -> dict:
    p = get_project(pid)
    tasks, deps, resources, assigns = load_rows(pid)
    return {"format": "flask-planner/1", "project": {k: p[k] for k in p.keys() if k not in ("id",)},
            "tasks": [dict(t) for t in tasks], "dependencies": [dict(d) for d in deps],
            "resources": [dict(r) for r in resources], "assignments": [dict(a) for a in assigns]}


def import_json(data: dict) -> int:
    con = db.get_db()
    p = data["project"]
    pid = create_project(p)
    db.execute("UPDATE project SET baseline_saved_at=? WHERE id=?", (p.get("baseline_saved_at"), pid))
    tmap, rmap = {}, {}
    for t in data.get("tasks", []):
        tmap[t["id"]] = con.execute(
            """INSERT INTO task (project_id,row,level,name,duration,constraint_start,actual_start,actual_finish,
               pct,notes,baseline_start,baseline_finish,baseline_duration) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (pid, t["row"], t["level"], t["name"], t["duration"], t.get("constraint_start"), t.get("actual_start"),
             t.get("actual_finish"), t.get("pct", 0), t.get("notes", ""), t.get("baseline_start"),
             t.get("baseline_finish"), t.get("baseline_duration"))).lastrowid
    for d in data.get("dependencies", []):
        if d["pred_id"] in tmap and d["succ_id"] in tmap:
            con.execute("INSERT INTO dependency (project_id,pred_id,succ_id,type,lag) VALUES (?,?,?,?,?)",
                        (pid, tmap[d["pred_id"]], tmap[d["succ_id"]], d.get("type", "FS"), d.get("lag", 0)))
    for r in data.get("resources", []):
        rmap[r["id"]] = con.execute(
            "INSERT INTO resource (project_id,name,type,grp,max_units,rate,email) VALUES (?,?,?,?,?,?,?)",
            (pid, r["name"], r.get("type", "인력"), r.get("grp", ""), r.get("max_units", 100), r.get("rate", 0),
             r.get("email", ""))).lastrowid
    for a in data.get("assignments", []):
        if a["task_id"] in tmap and a["resource_id"] in rmap:
            con.execute("INSERT INTO assignment (task_id,resource_id,units) VALUES (?,?,?)",
                        (tmap[a["task_id"]], rmap[a["resource_id"]], a.get("units", 100)))
    con.commit()
    schedule_for(pid)
    return pid


# ------------------------------------------------------------------ 보고서 저장

def save_report(pid: int, source: str, notes: str, content: dict) -> int:
    return db.execute("INSERT INTO report (project_id, source, notes, content) VALUES (?,?,?,?)",
                      (pid, source, notes, json.dumps(content, ensure_ascii=False)))


def list_reports(pid: int):
    return db.query("SELECT id, created_at, source, notes FROM report WHERE project_id=? ORDER BY id DESC", (pid,))


def get_report(pid: int, rid: int):
    r = db.query("SELECT * FROM report WHERE id=? AND project_id=?", (rid, pid), one=True)
    return None if r is None else {**dict(r), "content": json.loads(r["content"])}
