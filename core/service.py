"""DB 데이터를 읽어 일정 계산, 자원 부하, 진척/EV 지표를 만드는 서비스 계층."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

import pandas as pd

from . import db
from .scheduler import (
    DepInput, Schedule, TaskInput, WorkCalendar, compute_schedule, parse_holidays,
)


def to_date(v) -> date | None:
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def get_project(conn: sqlite3.Connection, project_id: int) -> dict:
    row = conn.execute("SELECT * FROM projects WHERE id=?", [project_id]).fetchone()
    return dict(row) if row else {}


def calendar_for(project: dict) -> WorkCalendar:
    return WorkCalendar(
        to_date(project["start_date"]) or date.today(),
        bool(project.get("skip_weekends", 1)),
        parse_holidays(project.get("holidays")),
    )


def load_inputs(conn: sqlite3.Connection, project_id: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    tasks = db.table_df(conn, "tasks", "project_id=?", [project_id])
    deps = db.table_df(conn, "dependencies", "project_id=?", [project_id])
    return tasks, deps


def build_schedule(conn: sqlite3.Connection, project_id: int) -> tuple[Schedule, pd.DataFrame, list[DepInput]]:
    project = get_project(conn, project_id)
    tasks, deps = load_inputs(conn, project_id)
    tin = [
        TaskInput(
            id=int(r.id), wbs=str(r.wbs), name=str(r.name), duration=r.duration,
            constraint_start=to_date(r.constraint_start),
            actual_start=to_date(r.actual_start), actual_finish=to_date(r.actual_finish),
            percent_complete=float(r.percent_complete or 0),
        )
        for r in tasks.itertuples()
    ]
    din = [
        DepInput(int(r.pred_id), int(r.succ_id), str(r.dep_type or "FS"), float(r.lag or 0))
        for r in deps.itertuples()
    ]
    sched = compute_schedule(tin, din, calendar_for(project), to_date(project.get("status_date")))
    return sched, tasks, din


def schedule_frame(sched: Schedule, tasks: pd.DataFrame) -> pd.DataFrame:
    """일정 결과 + 원본 작업 정보를 WBS 순으로 합친 표."""
    extra = tasks.set_index("id")
    rows = []
    for tid in sched.order:
        r = sched.tasks[tid]
        e = extra.loc[tid]
        rows.append({
            "id": tid,
            "WBS": r.wbs,
            "작업명": ("　" * (r.level - 1)) + r.name,
            "name": r.name,
            "level": r.level,
            "요약": r.is_summary,
            "마일스톤": r.is_milestone,
            "기간(일)": r.duration,
            "시작": r.start,
            "완료": r.finish,
            "늦은시작": r.late_start,
            "늦은완료": r.late_finish,
            "ES": r.es, "EF": r.ef, "LS": r.ls, "LF": r.lf,
            "총여유": r.total_float,
            "자유여유": r.free_float if not r.is_summary else None,
            "주공정": r.critical,
            "진척률(%)": round(r.percent_complete, 1),
            "계획진척률(%)": round(r.planned_percent, 1),
            "분야": e["discipline"],
            "equipment_id": e["equipment_id"],
            "기준시작": to_date(e["baseline_start"]),
            "기준완료": to_date(e["baseline_finish"]),
            "실제시작": to_date(e["actual_start"]),
            "실제완료": to_date(e["actual_finish"]),
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df["자유여유"] = df["자유여유"].astype("Int64")
        df["완료편차(일)"] = [
            (sched.calendar.to_index(f) - sched.calendar.to_index(b)) if (b and f) else None
            for f, b in zip(df["완료"], df["기준완료"])
        ]
        df["완료편차(일)"] = df["완료편차(일)"].astype("Int64")
    return df


def task_labels(tasks: pd.DataFrame, leaf_only_ids: set[int] | None = None) -> dict[int, str]:
    out = {}
    for r in tasks.itertuples():
        if leaf_only_ids is not None and int(r.id) not in leaf_only_ids:
            continue
        out[int(r.id)] = f"{r.wbs} {r.name}"
    return dict(sorted(out.items(), key=lambda kv: kv[1]))


def summary_ids(tasks: pd.DataFrame) -> set[int]:
    wbs = {str(w) for w in tasks["wbs"]}
    out = set()
    for r in tasks.itertuples():
        pref = str(r.wbs) + "."
        if any(w.startswith(pref) for w in wbs):
            out.add(int(r.id))
    return out


# ---------------------------------------------------------------- 자원

def assignment_frame(conn: sqlite3.Connection, project_id: int, sched: Schedule) -> pd.DataFrame:
    a = db.query_df(conn, """
        SELECT a.id, a.task_id, a.resource_id, a.units, r.name AS resource, r.rtype, r.skill,
               r.cost_per_day, r.max_units
        FROM assignments a JOIN resources r ON r.id = a.resource_id
        WHERE a.project_id = ? ORDER BY a.id""", [project_id])
    if a.empty:
        return a
    a = a[a["task_id"].isin(sched.tasks.keys())].copy()
    a["작업"] = [f"{sched.tasks[t].wbs} {sched.tasks[t].name}" for t in a["task_id"]]
    a["시작"] = [sched.tasks[t].start for t in a["task_id"]]
    a["완료"] = [sched.tasks[t].finish for t in a["task_id"]]
    a["기간(일)"] = [sched.tasks[t].duration for t in a["task_id"]]
    a["작업량(인·일)"] = a["기간(일)"] * a["units"]
    a["비용"] = a["작업량(인·일)"] * a["cost_per_day"]
    return a


def resource_loading(assign: pd.DataFrame, sched: Schedule) -> pd.DataFrame:
    """작업일별·자원별 투입량(units 합계)."""
    rows = []
    for r in assign.itertuples():
        t = sched.tasks[r.task_id]
        for i in range(t.es, t.ef):
            rows.append({"날짜": sched.calendar.to_date(i), "자원": r.resource,
                         "투입": float(r.units), "최대": float(r.max_units or 1)})
    if not rows:
        return pd.DataFrame(columns=["날짜", "자원", "투입", "최대"])
    df = pd.DataFrame(rows)
    return df.groupby(["날짜", "자원"], as_index=False).agg(투입=("투입", "sum"), 최대=("최대", "first"))


def task_costs(assign: pd.DataFrame) -> dict[int, float]:
    if assign.empty:
        return {}
    return assign.groupby("task_id")["비용"].sum().to_dict()


# ---------------------------------------------------------------- 진척 / 획득가치

def earned_value(sched: Schedule, assign: pd.DataFrame) -> dict:
    costs = task_costs(assign)
    bac = pv = ev = 0.0
    for tid in sched.leaf_ids():
        t = sched.tasks[tid]
        c = costs.get(tid, 0.0) or float(max(t.duration, 1))  # 비용 미입력 시 기간을 가중치로 사용
        bac += c
        pv += c * t.planned_percent / 100
        ev += c * t.percent_complete / 100
    spi = (ev / pv) if pv > 0 else None
    return {"BAC": bac, "PV": pv, "EV": ev, "SV": ev - pv, "SPI": spi,
            "계획진척률": (pv / bac * 100) if bac else 0, "실적진척률": (ev / bac * 100) if bac else 0,
            "비용입력": bool(costs)}


def save_baseline(conn: sqlite3.Connection, sched: Schedule) -> None:
    for tid, t in sched.tasks.items():
        conn.execute("UPDATE tasks SET baseline_start=?, baseline_finish=? WHERE id=?",
                     [t.start.isoformat(), t.finish.isoformat(), tid])
    conn.commit()


# ---------------------------------------------------------------- 예방정비 / 작업지시

def pm_due_frame(conn: sqlite3.Connection, today: date | None = None) -> pd.DataFrame:
    today = today or date.today()
    df = db.query_df(conn, """
        SELECT p.*, e.code AS eq_code, e.name AS eq_name, e.criticality, r.name AS resource
        FROM pm_plans p JOIN equipment e ON e.id = p.equipment_id
        LEFT JOIN resources r ON r.id = p.resource_id ORDER BY p.id""")
    if df.empty:
        return df
    nxt, left = [], []
    for r in df.itertuples():
        last = to_date(r.last_done)
        n = (last + timedelta(days=int(r.interval_days or 0))) if last else today
        nxt.append(n)
        left.append((n - today).days)
    df["다음예정일"] = nxt
    df["남은일수"] = left
    df["상태"] = ["기한초과" if x < 0 else ("임박" if x <= 7 else "정상") for x in left]
    return df


def next_wo_no(conn: sqlite3.Connection, d: date | None = None) -> str:
    d = d or date.today()
    prefix = f"WO-{d:%y%m}-"
    row = conn.execute("SELECT wo_no FROM work_orders WHERE wo_no LIKE ? ORDER BY wo_no DESC LIMIT 1",
                       [prefix + "%"]).fetchone()
    n = int(row[0].split("-")[-1]) + 1 if row else 1
    return f"{prefix}{n:03d}"


def generate_pm_work_orders(conn: sqlite3.Connection, horizon_days: int = 14, today: date | None = None) -> list[str]:
    """기한이 horizon 이내로 다가온 예방정비 계획에 대해 작업지시를 생성 (중복 방지)."""
    today = today or date.today()
    due = pm_due_frame(conn, today)
    created = []
    if due.empty:
        return created
    for r in due.itertuples():
        if not r.active or r.남은일수 > horizon_days:
            continue
        open_wo = conn.execute(
            "SELECT 1 FROM work_orders WHERE pm_plan_id=? AND status NOT IN ('완료','취소')", [r.id]
        ).fetchone()
        if open_wo:
            continue
        wo_no = next_wo_no(conn, today)
        priority = "높음" if r.남은일수 < 0 or r.criticality == "A" else "보통"
        db.insert(conn, "work_orders", {
            "wo_no": wo_no, "title": f"[{r.eq_code}] {r.name}", "equipment_id": r.equipment_id,
            "wo_type": r.pm_type, "priority": priority, "status": "요청",
            "requested_date": today.isoformat(), "due_date": r.다음예정일.isoformat(),
            "resource_id": None if pd.isna(r.resource_id) else int(r.resource_id),
            "est_hours": r.est_hours, "pm_plan_id": r.id,
            "description": r.checklist or "",
        })
        created.append(wo_no)
    return created


def complete_work_order(conn: sqlite3.Connection, wo_id: int, done: date, actual_hours: float, result: str) -> None:
    db.update(conn, "work_orders", wo_id, {
        "status": "완료", "completed_date": done.isoformat(),
        "actual_hours": actual_hours, "result": result,
    })
    row = conn.execute("SELECT pm_plan_id FROM work_orders WHERE id=?", [wo_id]).fetchone()
    if row and row[0]:
        db.update(conn, "pm_plans", row[0], {"last_done": done.isoformat()})
