"""일정 계산 엔진 — 작업일 달력, 개요(WBS) 구조, 주공정법(CPM), 기준선 대비 지연 분석.

시간 단위는 '작업일 인덱스'입니다. 프로젝트 시작일 이후 첫 작업일이 0이며,
작업은 [ES, EF) 구간을 차지합니다(EF = ES + 기간). 기간 0 작업은 마일스톤입니다.

선후행 관계(lag 는 작업일, 음수면 리드):
  FS 종료-시작 : 후행 ES >= 선행 EF + lag
  SS 시작-시작 : 후행 ES >= 선행 ES + lag
  FF 종료-종료 : 후행 EF >= 선행 EF + lag
  SF 시작-종료 : 후행 EF >= 선행 ES + lag

진척 기준일(status date)이 있으면
  - 진행 중 작업의 잔여 기간은 기준일 다음 작업일부터 다시 배치하고,
  - 시작하지 않은 작업은 기준일 이전에 시작할 수 없게 하여
'현재 추세대로 가면 언제 끝나는가(예측 일정)'를 계산합니다. 이 예측을 기준선과 비교해 지연을 판정합니다.
"""
from __future__ import annotations

import math
import re
from bisect import bisect_left
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable

DEP_TYPES = {"FS": "종료-시작", "SS": "시작-시작", "FF": "종료-종료", "SF": "시작-종료"}


class ScheduleError(ValueError):
    pass


class CycleError(ScheduleError):
    def __init__(self, rows: list[int]):
        super().__init__("선행 관계에 순환이 있습니다 (작업 ID: " + ", ".join(map(str, rows)) + ")")
        self.rows = rows


# ------------------------------------------------------------------ 달력

class WorkCalendar:
    """주말·휴일을 건너뛰는 작업일 달력. 음수 인덱스(시작일 이전)도 지원."""

    PAD = 400  # 시작일 이전으로 미리 만들어 둘 달력 일수

    def __init__(self, start: date, skip_weekends: bool = True, holidays: Iterable[date] = ()):
        self.skip_weekends = skip_weekends
        self.holidays = set(holidays)
        d = start
        while not self.is_workday(d):
            d += timedelta(days=1)
        self.start = d
        days, x = [], d - timedelta(days=self.PAD)
        while x <= d:
            if self.is_workday(x):
                days.append(x.toordinal())
            x += timedelta(days=1)
        self._days = days
        self._offset = len(days) - 1  # self.start 의 위치

    def is_workday(self, d: date) -> bool:
        if self.skip_weekends and d.weekday() >= 5:
            return False
        return d not in self.holidays

    def _extend_to_ordinal(self, ordv: int) -> None:
        x = date.fromordinal(self._days[-1])
        while self._days[-1] < ordv:
            x += timedelta(days=1)
            if self.is_workday(x):
                self._days.append(x.toordinal())

    def to_date(self, idx: int) -> date:
        pos = idx + self._offset
        if pos < 0:
            raise ScheduleError("프로젝트 시작일보다 너무 이른 날짜입니다.")
        while pos >= len(self._days):
            self._extend_to_ordinal(self._days[-1] + 30)
        return date.fromordinal(self._days[pos])

    def to_index(self, d: date) -> int:
        """날짜 d 당일(작업일이 아니면 그 다음 작업일)의 인덱스."""
        o = d.toordinal()
        self._extend_to_ordinal(o)
        pos = bisect_left(self._days, o)
        return pos - self._offset

    def workdays_between(self, a: date, b: date) -> int:
        """b - a 를 작업일 수로(부호 있음)."""
        return self.to_index(b) - self.to_index(a)


def parse_holidays(text: str | None) -> list[date]:
    out = []
    for tok in re.split(r"[,\s]+", text or ""):
        if tok:
            try:
                out.append(date.fromisoformat(tok))
            except ValueError:
                pass
    return out


def to_date(v) -> date | None:
    if v in (None, ""):
        return None
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


# ------------------------------------------------------------------ 입력·결과

@dataclass
class TaskIn:
    id: int
    row: int            # 1부터 시작하는 표시 순번(ProjectLibre 의 ID)
    level: int          # 개요 수준(1 = 최상위)
    name: str
    duration: float = 1
    constraint_start: date | None = None   # 시작 제한일(이 날짜 이후 시작)
    actual_start: date | None = None
    actual_finish: date | None = None
    pct: float = 0
    baseline_start: date | None = None
    baseline_finish: date | None = None
    baseline_duration: float | None = None


@dataclass
class DepIn:
    pred_id: int
    succ_id: int
    type: str = "FS"
    lag: float = 0


@dataclass
class TaskOut:
    id: int
    row: int
    level: int
    wbs: str
    name: str
    is_summary: bool
    parent_id: int | None
    duration: int            # 계획(입력) 기간
    es: int = 0
    ef: int = 0
    ls: int = 0
    lf: int = 0
    total_float: int = 0
    free_float: int = 0
    critical: bool = False
    pct: float = 0
    start: date | None = None
    finish: date | None = None
    late_start: date | None = None
    late_finish: date | None = None
    baseline_start: date | None = None
    baseline_finish: date | None = None
    baseline_duration: int | None = None
    start_var: int | None = None     # 작업일, + 는 늦어짐
    finish_var: int | None = None
    planned_pct: float | None = None  # 기준선 기준, 진척 기준일 시점의 계획 진척률
    status: str = "예정"
    ms_end: bool = False      # 마일스톤이 선행작업 종료 시점(전 작업일 끝)에 놓이는지
    children: list[int] = field(default_factory=list)

    @property
    def is_milestone(self) -> bool:
        return not self.is_summary and self.duration == 0

    @property
    def forecast_duration(self) -> int:
        return self.ef - self.es


@dataclass
class Schedule:
    tasks: dict[int, TaskOut]
    order: list[int]
    deps: list[DepIn]
    leaf_deps: list[DepIn]
    calendar: WorkCalendar
    project_start: date
    project_finish: date
    finish_index: int
    status_date: date | None
    baseline_finish: date | None
    kpi: dict

    def leaves(self) -> list[TaskOut]:
        return [self.tasks[i] for i in self.order if not self.tasks[i].is_summary]

    def critical_path(self) -> list[TaskOut]:
        return sorted([t for t in self.leaves() if t.critical], key=lambda t: (t.es, t.row))

    def delayed(self) -> list[TaskOut]:
        return [t for t in self.leaves() if t.status in ("지연", "주의")]


# ------------------------------------------------------------------ 선행작업 문자열

PRED_RE = re.compile(r"^\s*(\d+)\s*(FS|SS|FF|SF)?\s*(?:([+-])\s*(\d+(?:\.\d+)?)\s*(?:일|d|D)?)?\s*$", re.I)


def parse_predecessors(text: str) -> list[tuple[int, str, float]]:
    """'3, 5SS+2, 7FF-1일' -> [(3,'FS',0), (5,'SS',2), (7,'FF',-1)]"""
    out = []
    for tok in re.split(r"[,;]", text or ""):
        if not tok.strip():
            continue
        m = PRED_RE.match(tok)
        if not m:
            raise ScheduleError(f"선행작업 형식 오류: '{tok.strip()}' (예: 3, 5SS+2, 7FF-1)")
        row = int(m.group(1))
        typ = (m.group(2) or "FS").upper()
        lag = float(m.group(4) or 0) * (-1 if m.group(3) == "-" else 1)
        out.append((row, typ, lag))
    return out


def format_predecessor(row: int, typ: str, lag: float) -> str:
    s = str(row)
    if typ != "FS" or lag:
        s += typ
    if lag:
        lag_s = f"{lag:g}"
        s += ("+" if lag > 0 else "") + lag_s
    return s


# ------------------------------------------------------------------ 개요 구조

def build_outline(tasks: list[TaskIn]) -> dict[int, dict]:
    """행 순서·수준으로 WBS 번호, 부모, 요약 여부를 만든다."""
    tasks = sorted(tasks, key=lambda t: t.row)
    info: dict[int, dict] = {}
    stack: list[tuple[int, int]] = []  # (level, id)
    counters: list[int] = []
    prev_level = 0
    for t in tasks:
        lvl = max(1, min(int(t.level or 1), prev_level + 1))
        while stack and stack[-1][0] >= lvl:
            stack.pop()
        parent = stack[-1][1] if stack else None
        counters = counters[:lvl]
        while len(counters) < lvl:
            counters.append(0)
        counters[lvl - 1] += 1
        info[t.id] = {"level": lvl, "parent": parent, "wbs": ".".join(map(str, counters)), "children": []}
        if parent is not None:
            info[parent]["children"].append(t.id)
        stack.append((lvl, t.id))
        prev_level = lvl
    return info


# ------------------------------------------------------------------ CPM

def _ival(x) -> int:
    if x is None:
        return 0
    try:
        f = float(x)
    except (TypeError, ValueError):
        return 0
    if math.isnan(f):
        return 0
    return max(0, int(round(f)))


def compute(tasks: list[TaskIn], deps: list[DepIn], project_start: date, *,
            status_date: date | None = None, skip_weekends: bool = True,
            holidays: Iterable[date] = ()) -> Schedule:
    cal = WorkCalendar(project_start, skip_weekends, holidays)
    by_id = {t.id: t for t in tasks}
    outline = build_outline(tasks)
    order = [t.id for t in sorted(tasks, key=lambda t: t.row)]
    row_of = {t.id: t.row for t in tasks}

    out: dict[int, TaskOut] = {}
    for tid in order:
        t, o = by_id[tid], outline[tid]
        out[tid] = TaskOut(
            id=tid, row=t.row, level=o["level"], wbs=o["wbs"], name=t.name,
            is_summary=bool(o["children"]), parent_id=o["parent"],
            duration=_ival(t.duration), pct=max(0.0, min(100.0, float(t.pct or 0))),
            children=list(o["children"]),
            baseline_start=t.baseline_start, baseline_finish=t.baseline_finish,
            baseline_duration=None if t.baseline_duration is None else _ival(t.baseline_duration),
        )

    def leaf_desc(tid: int) -> list[int]:
        if not out[tid].is_summary:
            return [tid]
        res = []
        for c in out[tid].children:
            res.extend(leaf_desc(c))
        return res

    # 요약 작업에 걸린 관계는 하위 리프 작업들 사이의 관계로 펼친다.
    leaf_deps: list[DepIn] = []
    seen = set()
    for d in deps:
        if d.pred_id not in out or d.succ_id not in out:
            continue
        for p in leaf_desc(d.pred_id):
            for s in leaf_desc(d.succ_id):
                if p == s or (p, s) in seen:
                    continue
                # 요약 작업과 그 하위 작업 사이의 관계는 무시
                seen.add((p, s))
                leaf_deps.append(DepIn(p, s, (d.type or "FS").upper(), float(d.lag or 0)))

    leaves = [i for i in order if not out[i].is_summary]
    preds: dict[int, list[DepIn]] = defaultdict(list)
    succs: dict[int, list[DepIn]] = defaultdict(list)
    indeg = {i: 0 for i in leaves}
    for d in leaf_deps:
        preds[d.succ_id].append(d)
        succs[d.pred_id].append(d)
        indeg[d.succ_id] += 1

    q = deque(i for i in leaves if indeg[i] == 0)
    topo = []
    while q:
        i = q.popleft()
        topo.append(i)
        for d in succs[i]:
            indeg[d.succ_id] -= 1
            if indeg[d.succ_id] == 0:
                q.append(d.succ_id)
    if len(topo) != len(leaves):
        bad = sorted(row_of[i] for i in leaves if indeg[i] > 0)
        raise CycleError(bad)

    # 진척 기준일: 그 날까지의 실적이 반영되었다고 보고, 잔여 작업은 다음 작업일부터
    status_idx = cal.to_index(status_date + timedelta(days=1)) if status_date else None

    # ---- 전진 계산
    for i in topo:
        t, o = by_id[i], out[i]
        dur = o.duration
        es = 0
        has_pred_drive = False
        for d in preds[i]:
            p = out[d.pred_id]
            lag = int(round(d.lag))
            if d.type == "SS":
                es = max(es, p.es + lag)
            elif d.type == "FF":
                es = max(es, p.ef + lag - dur)
            elif d.type == "SF":
                es = max(es, p.es + lag - dur)
            else:
                es = max(es, p.ef + lag)
        has_pred_drive = es > 0
        if t.constraint_start and cal.to_index(t.constraint_start) >= es:
            es = cal.to_index(t.constraint_start)
            has_pred_drive = False
        es = max(es, 0) if not t.actual_start else es

        if t.actual_finish:
            o.pct = 100.0
        started = bool(t.actual_start) or o.pct > 0
        if t.actual_start:
            es = cal.to_index(t.actual_start)
        if t.actual_finish:
            ef = cal.to_index(t.actual_finish) + (1 if dur > 0 else 0)
            ef = max(ef, es)
        elif started:
            ef = es + dur
            if status_idx is not None and o.pct < 100:
                remaining = math.ceil(round(dur * (1 - o.pct / 100.0), 6))
                ef = max(ef, status_idx + remaining)
        else:
            if status_idx is not None and es < status_idx:
                es = status_idx
            ef = es + dur
        o.es, o.ef = es, ef
        o.ms_end = dur == 0 and has_pred_drive and not t.actual_start and es > 0

    finish_idx = max([out[i].ef for i in leaves], default=0)

    # ---- 후진 계산
    for i in reversed(topo):
        o = out[i]
        dur = o.ef - o.es
        lf = finish_idx
        for d in succs[i]:
            s = out[d.succ_id]
            lag = int(round(d.lag))
            if d.type == "SS":
                lf = min(lf, s.ls - lag + dur)
            elif d.type == "FF":
                lf = min(lf, s.lf - lag)
            elif d.type == "SF":
                lf = min(lf, s.lf - lag + dur)
            else:
                lf = min(lf, s.ls - lag)
        o.lf, o.ls = lf, lf - dur
        o.total_float = o.ls - o.es
        ff = finish_idx - o.ef if not succs[i] else None
        for d in succs[i]:
            s = out[d.succ_id]
            lag = int(round(d.lag))
            if d.type == "SS":
                slack = s.es - lag - o.es
            elif d.type == "FF":
                slack = s.ef - lag - o.ef
            elif d.type == "SF":
                slack = s.ef - lag - o.es
            else:
                slack = s.es - lag - o.ef
            ff = slack if ff is None else min(ff, slack)
        o.free_float = max(0, ff or 0)
        o.critical = o.total_float <= 0 and o.pct < 100

    # ---- 요약 작업 롤업 (하위부터)
    def rollup(tid: int):
        o = out[tid]
        if not o.is_summary:
            return
        for c in o.children:
            rollup(c)
        kids = [out[c] for c in o.children]
        o.es = min(k.es for k in kids)
        o.ef = max(k.ef for k in kids)
        o.ls = min(k.ls for k in kids)
        o.lf = max(k.lf for k in kids)
        o.total_float = min(k.total_float for k in kids)
        o.critical = any(k.critical for k in kids)
        o.duration = o.ef - o.es
        weights = [max(k.forecast_duration, 1) for k in kids]
        o.pct = round(sum(k.pct * w for k, w in zip(kids, weights)) / sum(weights), 1)
        bs = [k.baseline_start for k in kids if k.baseline_start]
        bf = [k.baseline_finish for k in kids if k.baseline_finish]
        if bs and bf:
            o.baseline_start, o.baseline_finish = min(bs), max(bf)
            o.baseline_duration = cal.to_index(o.baseline_finish) + 1 - cal.to_index(o.baseline_start)

    for tid in order:
        if out[tid].parent_id is None:
            rollup(tid)

    # ---- 날짜 변환·기준선 비교
    def finish_date(es, ef):
        return cal.to_date(ef - 1) if ef > es else cal.to_date(es)

    for tid in order:
        o = out[tid]
        if o.ms_end:
            o.start = o.finish = cal.to_date(o.es - 1)
        else:
            o.start = cal.to_date(o.es)
            o.finish = finish_date(o.es, o.ef)
        o.late_start = cal.to_date(o.ls)
        o.late_finish = finish_date(o.ls, o.lf)
        if o.baseline_start and o.baseline_finish:
            o.start_var = cal.to_index(o.start) - cal.to_index(o.baseline_start)
            o.finish_var = cal.to_index(o.finish) - cal.to_index(o.baseline_finish)
            if status_date:
                bs_i = cal.to_index(o.baseline_start)
                bf_i = cal.to_index(o.baseline_finish) + (1 if (o.baseline_duration or 0) > 0 else 0)
                span = max(bf_i - bs_i, 1)
                o.planned_pct = round(min(100.0, max(0.0, (status_idx - bs_i) / span * 100.0)), 1)

    for tid in order:
        o = out[tid]
        if o.pct >= 100:
            o.status = "완료"
        elif (o.finish_var or 0) > 0:
            o.status = "지연"
        elif o.planned_pct is not None and o.planned_pct - o.pct >= 10:
            o.status = "주의"
        elif o.pct > 0:
            o.status = "진행"
        else:
            o.status = "예정"

    # ---- 프로젝트 KPI
    leaf_objs = [out[i] for i in leaves]
    bl_finish_list = [t.baseline_finish for t in leaf_objs if t.baseline_finish]
    bl_finish = max(bl_finish_list) if bl_finish_list else None
    project_finish = max([t.finish for t in leaf_objs], default=cal.start)
    weights = [max(t.baseline_duration if t.baseline_duration is not None else t.duration, 1) for t in leaf_objs]
    tw = sum(weights) or 1
    ev = sum(t.pct * w for t, w in zip(leaf_objs, weights)) / tw
    pv = None
    if status_date and bl_finish:
        pv = sum((t.planned_pct if t.planned_pct is not None else 0) * w for t, w in zip(leaf_objs, weights)) / tw
    kpi = {
        "task_count": len(leaf_objs),
        "milestones": sum(1 for t in leaf_objs if t.is_milestone),
        "critical_count": sum(1 for t in leaf_objs if t.critical),
        "complete": sum(1 for t in leaf_objs if t.pct >= 100),
        "delayed": sum(1 for t in leaf_objs if t.status == "지연"),
        "warning": sum(1 for t in leaf_objs if t.status == "주의"),
        "actual_pct": round(ev, 1),
        "planned_pct": None if pv is None else round(pv, 1),
        "spi": None if not pv else round(ev / pv, 2),
        "duration": finish_idx,
        "has_baseline": bl_finish is not None,
        "finish_var": None if bl_finish is None else cal.to_index(project_finish) - cal.to_index(bl_finish),
    }

    return Schedule(tasks=out, order=order, deps=list(deps), leaf_deps=leaf_deps, calendar=cal,
                    project_start=cal.start, project_finish=project_finish, finish_index=finish_idx,
                    status_date=status_date, baseline_finish=bl_finish, kpi=kpi)


# ------------------------------------------------------------------ 네트워크 배치

def network_layout(s: Schedule) -> dict:
    """리프 작업을 최장 경로 단계(열)로 배치한 PERT 네트워크 좌표."""
    leaves = [t.id for t in s.leaves()]
    preds = defaultdict(list)
    for d in s.leaf_deps:
        preds[d.succ_id].append(d.pred_id)
    col: dict[int, int] = {}

    def depth(i, guard=0):
        if i in col:
            return col[i]
        col[i] = 0 if not preds[i] else 1 + max(depth(p) for p in preds[i])
        return col[i]

    for i in leaves:
        depth(i)
    columns: dict[int, list[int]] = defaultdict(list)
    for i in sorted(leaves, key=lambda x: (s.tasks[x].es, s.tasks[x].row)):
        columns[col[i]].append(i)
    W, H, GX, GY, M = 190, 92, 60, 26, 20
    pos = {}
    for c, ids in columns.items():
        for r, i in enumerate(ids):
            pos[i] = (M + c * (W + GX), M + r * (H + GY))
    width = M * 2 + (max(columns) + 1 if columns else 1) * (W + GX) - GX
    height = M * 2 + (max((len(v) for v in columns.values()), default=1)) * (H + GY) - GY
    edges = []
    for d in s.leaf_deps:
        if d.pred_id in pos and d.succ_id in pos:
            x1, y1 = pos[d.pred_id]
            x2, y2 = pos[d.succ_id]
            crit = s.tasks[d.pred_id].critical and s.tasks[d.succ_id].critical
            edges.append({"x1": x1 + W, "y1": y1 + H / 2, "x2": x2, "y2": y2 + H / 2,
                          "critical": crit, "type": d.type, "lag": d.lag})
    return {"pos": pos, "w": W, "h": H, "width": width, "height": height, "edges": edges}
