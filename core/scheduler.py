"""일정 계산 엔진: 작업일 달력, WBS 요약, CPM(주공정법) 전진/후진 계산.

시간 단위는 '작업일 인덱스'입니다. 프로젝트 시작일의 첫 작업일이 0이고,
작업 i 는 [ES, EF) 구간을 차지합니다 (EF = ES + 기간). 기간 0 은 마일스톤입니다.

선후행 관계 유형 (lag 는 작업일 단위, 음수면 리드):
  FS 종료-시작 : 후행 ES >= 선행 EF + lag
  SS 시작-시작 : 후행 ES >= 선행 ES + lag
  FF 종료-종료 : 후행 EF >= 선행 EF + lag
  SF 시작-종료 : 후행 EF >= 선행 ES + lag
"""
from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable

DEP_TYPES = {
    "FS": "종료-시작(FS)",
    "SS": "시작-시작(SS)",
    "FF": "종료-종료(FF)",
    "SF": "시작-종료(SF)",
}


class CycleError(ValueError):
    """선후행 관계에 순환이 있을 때 발생."""

    def __init__(self, task_ids: list[int]):
        super().__init__(f"선후행 관계에 순환이 있습니다: {task_ids}")
        self.task_ids = task_ids


# ---------------------------------------------------------------- 달력

class WorkCalendar:
    def __init__(self, start: date, skip_weekends: bool = True, holidays: Iterable[date] = ()):
        self.skip_weekends = skip_weekends
        self.holidays = set(holidays)
        d = start
        while not self.is_workday(d):
            d += timedelta(days=1)
        self.start = d
        self._days: list[date] = [d]

    def is_workday(self, d: date) -> bool:
        if self.skip_weekends and d.weekday() >= 5:
            return False
        return d not in self.holidays

    def _extend(self, n: int) -> None:
        d = self._days[-1]
        while len(self._days) <= n:
            d += timedelta(days=1)
            if self.is_workday(d):
                self._days.append(d)

    def to_date(self, idx: int) -> date:
        """작업일 인덱스 -> 날짜. 음수면 시작일 이전으로 역산."""
        if idx >= 0:
            self._extend(idx)
            return self._days[idx]
        d, k = self.start, 0
        while k > idx:
            d -= timedelta(days=1)
            if self.is_workday(d):
                k -= 1
        return d

    def to_index(self, d: date) -> int:
        """날짜 -> 그 날짜 이후 첫 작업일의 인덱스(= d 이전 작업일 수)."""
        if d <= self.start:
            n, x = 0, d
            while x < self.start:
                if self.is_workday(x):
                    n -= 1
                x += timedelta(days=1)
            return n
        lo = 0
        while self.to_date(lo) < d:
            lo = max(1, lo * 2)
        # 이진 탐색: to_date(i) >= d 인 최소 i
        hi = lo
        lo = lo // 2
        while lo < hi:
            mid = (lo + hi) // 2
            if self.to_date(mid) < d:
                lo = mid + 1
            else:
                hi = mid
        return lo

    def workdays_through(self, d: date) -> int:
        """시작일~d(포함) 사이 작업일 수."""
        return self.to_index(d + timedelta(days=1))


def parse_holidays(text: str | None) -> list[date]:
    out = []
    for tok in (text or "").replace("\n", ",").split(","):
        tok = tok.strip()
        if tok:
            try:
                out.append(date.fromisoformat(tok))
            except ValueError:
                pass
    return out


# ---------------------------------------------------------------- 결과 구조

@dataclass
class TaskInput:
    id: int
    wbs: str
    name: str
    duration: float = 1
    constraint_start: date | None = None
    actual_start: date | None = None
    actual_finish: date | None = None
    percent_complete: float = 0.0


@dataclass
class DepInput:
    pred_id: int
    succ_id: int
    dep_type: str = "FS"
    lag: float = 0


@dataclass
class TaskResult:
    id: int
    wbs: str
    name: str
    level: int
    is_summary: bool
    duration: int
    es: int = 0
    ef: int = 0
    ls: int = 0
    lf: int = 0
    total_float: int = 0
    free_float: int = 0
    critical: bool = False
    start: date | None = None
    finish: date | None = None
    late_start: date | None = None
    late_finish: date | None = None
    percent_complete: float = 0.0
    planned_percent: float = 0.0
    children: list[int] = field(default_factory=list)

    @property
    def is_milestone(self) -> bool:
        return not self.is_summary and self.duration == 0


@dataclass
class Schedule:
    tasks: dict[int, TaskResult]
    order: list[int]  # WBS 정렬 순서
    project_start: date
    project_finish: date
    finish_index: int
    calendar: WorkCalendar

    def leaf_ids(self) -> list[int]:
        return [i for i in self.order if not self.tasks[i].is_summary]

    def critical_ids(self) -> list[int]:
        return [i for i in self.leaf_ids() if self.tasks[i].critical]


# ---------------------------------------------------------------- WBS

def wbs_key(wbs: str) -> tuple:
    parts = []
    for p in str(wbs).strip().split("."):
        parts.append((0, int(p), "") if p.isdigit() else (1, 0, p))
    return tuple(parts)


def wbs_parent(wbs: str, all_wbs: set[str]) -> str | None:
    parts = str(wbs).strip().split(".")
    while len(parts) > 1:
        parts = parts[:-1]
        cand = ".".join(parts)
        if cand in all_wbs:
            return cand
    return None


# ---------------------------------------------------------------- CPM

def _dur(x: float | None) -> int:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return 0
    return max(0, int(math.ceil(float(x))))


def topo_order(nodes: list[int], deps: list[DepInput]) -> list[int]:
    indeg = {n: 0 for n in nodes}
    succ = defaultdict(list)
    for d in deps:
        succ[d.pred_id].append(d.succ_id)
        indeg[d.succ_id] += 1
    q = deque(n for n in nodes if indeg[n] == 0)
    out = []
    while q:
        n = q.popleft()
        out.append(n)
        for s in succ[n]:
            indeg[s] -= 1
            if indeg[s] == 0:
                q.append(s)
    if len(out) != len(nodes):
        raise CycleError(sorted(n for n in nodes if indeg[n] > 0))
    return out


def compute_schedule(
    tasks: list[TaskInput],
    deps: list[DepInput],
    calendar: WorkCalendar,
    status_date: date | None = None,
) -> Schedule:
    all_wbs = {t.wbs for t in tasks}
    by_wbs = {t.wbs: t for t in tasks}
    res: dict[int, TaskResult] = {}
    for t in tasks:
        res[t.id] = TaskResult(
            id=t.id, wbs=t.wbs, name=t.name,
            level=len(str(t.wbs).split(".")),
            is_summary=False, duration=_dur(t.duration),
            percent_complete=float(t.percent_complete or 0),
        )
    for t in tasks:
        p = wbs_parent(t.wbs, all_wbs)
        if p is not None:
            parent = res[by_wbs[p].id]
            parent.is_summary = True
            parent.children.append(t.id)

    leaves = [t for t in tasks if not res[t.id].is_summary]
    leaf_ids = {t.id for t in leaves}
    # 요약 작업에 걸린 관계는 계산에서 제외 (요약 작업은 하위 작업에서 일정이 결정됨)
    deps = [d for d in deps if d.pred_id in leaf_ids and d.succ_id in leaf_ids and d.pred_id != d.succ_id]

    # 실적 반영: 실제 시작/완료일이 있으면 해당 값으로 고정
    fixed_es: dict[int, int] = {}
    for t in leaves:
        r = res[t.id]
        if t.actual_start:
            if r.duration == 0:  # 마일스톤: 해당일 종료 시점
                fixed_es[t.id] = calendar.workdays_through(t.actual_start)
            else:
                fixed_es[t.id] = calendar.to_index(t.actual_start)
            if t.actual_finish and r.duration > 0:  # 마일스톤(기간 0)은 그대로 유지
                r.duration = max(1, calendar.workdays_through(t.actual_finish) - fixed_es[t.id])

    order = topo_order([t.id for t in leaves], deps)
    preds = defaultdict(list)
    succs = defaultdict(list)
    for d in deps:
        preds[d.succ_id].append(d)
        succs[d.pred_id].append(d)

    tin = {t.id: t for t in leaves}
    # 전진 계산 (Forward pass)
    for tid in order:
        r = res[tid]
        if tid in fixed_es:
            es = fixed_es[tid]
        else:
            es = 0
            cs = tin[tid].constraint_start
            if cs:
                es = max(es, calendar.to_index(cs))
            for d in preds[tid]:
                p = res[d.pred_id]
                lag = int(round(d.lag or 0))
                if d.dep_type == "SS":
                    es = max(es, p.es + lag)
                elif d.dep_type == "FF":
                    es = max(es, p.ef + lag - r.duration)
                elif d.dep_type == "SF":
                    es = max(es, p.es + lag - r.duration)
                else:
                    es = max(es, p.ef + lag)
        r.es, r.ef = es, es + r.duration

    finish = max((res[i].ef for i in leaf_ids), default=0)

    # 후진 계산 (Backward pass)
    for tid in reversed(order):
        r = res[tid]
        lf = finish
        for d in succs[tid]:
            s = res[d.succ_id]
            lag = int(round(d.lag or 0))
            if d.dep_type == "SS":
                lf = min(lf, s.ls - lag + r.duration)
            elif d.dep_type == "FF":
                lf = min(lf, s.lf - lag)
            elif d.dep_type == "SF":
                lf = min(lf, s.lf - lag + r.duration)
            else:
                lf = min(lf, s.ls - lag)
        r.lf, r.ls = lf, lf - r.duration
        r.total_float = r.ls - r.es
        r.critical = r.total_float <= 0

    # 자유여유 (Free float)
    for tid in order:
        r = res[tid]
        ff = finish - r.ef
        for d in succs[tid]:
            s = res[d.succ_id]
            lag = int(round(d.lag or 0))
            if d.dep_type == "SS":
                ff = min(ff, s.es - lag - r.es)
            elif d.dep_type == "FF":
                ff = min(ff, s.ef - lag - r.ef)
            elif d.dep_type == "SF":
                ff = min(ff, s.ef - lag - r.es)
            else:
                ff = min(ff, s.es - lag - r.ef)
        r.free_float = max(0, ff)

    # 요약 작업 롤업 (깊은 레벨부터)
    for t in sorted(tasks, key=lambda x: -len(str(x.wbs).split("."))):
        r = res[t.id]
        if not r.is_summary:
            continue
        kids = [res[c] for c in r.children]
        r.es = min(k.es for k in kids)
        r.ef = max(k.ef for k in kids)
        r.ls = min(k.ls for k in kids)
        r.lf = max(k.lf for k in kids)
        r.duration = r.ef - r.es
        r.total_float = min(k.total_float for k in kids)
        r.critical = any(k.critical for k in kids)
        weight = sum(max(k.duration, 1) for k in kids)
        r.percent_complete = sum(k.percent_complete * max(k.duration, 1) for k in kids) / weight

    # 날짜 변환 및 계획 진척률
    elapsed = calendar.workdays_through(status_date) if status_date else None
    for r in res.values():
        if r.duration == 0:
            # 마일스톤은 직전 작업일의 '종료 시점'에 표시 (예: 선행작업 완료일)
            r.start = r.finish = calendar.to_date(max(r.es - 1, 0))
            r.late_start = r.late_finish = calendar.to_date(max(r.ls - 1, 0))
        else:
            r.start = calendar.to_date(r.es)
            r.finish = calendar.to_date(r.ef - 1)
            r.late_start = calendar.to_date(r.ls)
            r.late_finish = calendar.to_date(r.lf - 1)
        if elapsed is not None:
            if r.duration == 0:
                r.planned_percent = 100.0 if elapsed > r.es else 0.0
            else:
                r.planned_percent = min(100.0, max(0.0, (elapsed - r.es) / r.duration * 100))

    wbs_sorted = sorted(res, key=lambda i: wbs_key(res[i].wbs))
    return Schedule(
        tasks=res,
        order=wbs_sorted,
        project_start=calendar.start,
        project_finish=calendar.to_date(finish - 1) if finish > 0 else calendar.start,
        finish_index=finish,
        calendar=calendar,
    )


def topo_levels(schedule: Schedule, deps: list[DepInput]) -> dict[int, int]:
    """네트워크 다이어그램용: 각 작업의 단계(열) 번호."""
    leaf = set(schedule.leaf_ids())
    deps = [d for d in deps if d.pred_id in leaf and d.succ_id in leaf]
    order = topo_order(sorted(leaf, key=lambda i: wbs_key(schedule.tasks[i].wbs)), deps)
    level = {i: 0 for i in leaf}
    succ = defaultdict(list)
    for d in deps:
        succ[d.pred_id].append(d.succ_id)
    for i in order:
        for s in succ[i]:
            level[s] = max(level[s], level[i] + 1)
    return level
