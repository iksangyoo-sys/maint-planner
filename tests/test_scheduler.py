from datetime import date

import pytest

from core.scheduler import CycleError, DepInput, TaskInput, WorkCalendar, compute_schedule

MON = date(2026, 11, 16)  # 월요일


def cal(skip=True, holidays=()):
    return WorkCalendar(MON, skip, holidays)


def T(i, wbs, d, **kw):
    return TaskInput(id=i, wbs=wbs, name=f"t{i}", duration=d, **kw)


def test_calendar_skips_weekend_and_holiday():
    c = cal(holidays=[date(2026, 11, 18)])
    assert [c.to_date(i) for i in range(4)] == [date(2026, 11, 16), date(2026, 11, 17), date(2026, 11, 19), date(2026, 11, 20)]
    assert c.to_date(4) == date(2026, 11, 23)
    assert c.to_index(date(2026, 11, 21)) == 4  # 토요일 -> 다음 월요일
    assert c.to_index(date(2026, 11, 23)) == 4


def test_calendar_start_on_weekend_moves_forward():
    c = WorkCalendar(date(2026, 11, 14))  # 토요일
    assert c.start == MON


def test_textbook_cpm():
    # A(3) -> B(2) -> D(4); A -> C(5) -> D  => 주공정 A-C-D, 공기 12
    tasks = [T(1, "1", 3), T(2, "2", 2), T(3, "3", 5), T(4, "4", 4)]
    deps = [DepInput(1, 2), DepInput(1, 3), DepInput(2, 4), DepInput(3, 4)]
    s = compute_schedule(tasks, deps, cal(skip=False))
    assert s.finish_index == 12
    assert s.critical_ids() == [1, 3, 4]
    assert s.tasks[2].total_float == 3
    assert s.tasks[2].free_float == 3
    assert (s.tasks[4].es, s.tasks[4].ef) == (8, 12)


def test_dependency_types_and_lag():
    tasks = [T(1, "1", 4), T(2, "2", 2), T(3, "3", 3), T(4, "4", 2)]
    deps = [DepInput(1, 2, "SS", 1), DepInput(1, 3, "FF", 0), DepInput(1, 4, "FS", -1)]
    s = compute_schedule(tasks, deps, cal(skip=False))
    assert s.tasks[2].es == 1       # SS+1
    assert s.tasks[3].ef == 4       # FF
    assert s.tasks[4].es == 3       # FS-1 (lead)


def test_summary_rollup_and_milestone_dates():
    tasks = [T(1, "1", 0), T(2, "1.1", 2), T(3, "1.2", 3), T(4, "2", 0)]
    deps = [DepInput(2, 3), DepInput(3, 4)]
    s = compute_schedule(tasks, deps, cal())
    assert s.tasks[1].is_summary and s.tasks[1].duration == 5
    assert s.tasks[4].is_milestone
    assert s.tasks[4].finish == s.tasks[3].finish  # 마일스톤은 선행 완료일에 표시
    assert s.project_finish == date(2026, 11, 20)


def test_cycle_detected():
    tasks = [T(1, "1", 1), T(2, "2", 1)]
    with pytest.raises(CycleError):
        compute_schedule(tasks, [DepInput(1, 2), DepInput(2, 1)], cal())


def test_actual_start_fixes_task_and_planned_percent():
    tasks = [T(1, "1", 2, actual_start=date(2026, 11, 18)), T(2, "2", 2)]
    s = compute_schedule(tasks, [DepInput(1, 2)], cal(), status_date=date(2026, 11, 18))
    assert s.tasks[1].start == date(2026, 11, 18)
    assert s.tasks[2].start == date(2026, 11, 20)
    assert s.tasks[1].planned_percent == 50.0
    assert s.tasks[2].planned_percent == 0.0


def test_constraint_start():
    s = compute_schedule([T(1, "1", 1, constraint_start=date(2026, 11, 25))], [], cal())
    assert s.tasks[1].start == date(2026, 11, 25)
