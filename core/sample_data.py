"""실습용 예제 데이터: 공장 정기보수(Shutdown) 프로젝트와 설비·자원·예방정비·작업지시."""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from . import db


def _next_monday(d: date) -> date:
    return d + timedelta(days=(7 - d.weekday()) % 7 or 7)


def load_sample(conn: sqlite3.Connection, today: date | None = None) -> int:
    today = today or date.today()
    start = _next_monday(today)
    iso = lambda d: d.isoformat()  # noqa: E731

    # ---- 설비대장
    eq_rows = [
        ("TR-01", "주변압기 22.9kV/6.6kV 10MVA", "전기", "변전실", "A", "효성", "2015-03-01"),
        ("VCB-01", "진공차단기 인입반", "전기", "변전실", "A", "LS일렉트릭", "2015-03-01"),
        ("MCC-01", "전동기제어반 #1", "전기", "전기실 1층", "B", "LS일렉트릭", "2016-06-15"),
        ("M-101", "원료이송 전동기 75kW", "전기", "원료동", "B", "현대일렉트릭", "2017-09-10"),
        ("C-201", "스크루 공기압축기 200HP", "기계", "유틸리티동", "A", "아틀라스콥코", "2018-01-20"),
        ("P-301", "냉각수 순환펌프", "기계", "냉각탑", "A", "효성굿스프링스", "2016-11-05"),
        ("CV-401", "벨트 컨베이어 #1", "기계", "원료동", "B", "자체제작", "2014-08-30"),
        ("FAN-501", "집진기 송풍기", "기계", "집진동", "C", "삼성팬", "2019-04-12"),
    ]
    eq = {}
    for code, name, disc, loc, crit, maker, inst in eq_rows:
        eq[code] = db.insert(conn, "equipment", {
            "code": code, "name": name, "discipline": disc, "location": loc,
            "criticality": crit, "maker": maker, "install_date": inst, "status": "가동",
        })

    # ---- 자원 (인력·장비)
    res_rows = [
        ("김전기", "인력", "전기(고압)", 1, 350000),
        ("이계전", "인력", "전기(계전)", 1, 330000),
        ("박기계", "인력", "기계(회전기)", 1, 320000),
        ("최정비", "인력", "기계(배관)", 1, 300000),
        ("정안전", "인력", "안전관리", 1, 280000),
        ("협력사 정비반", "인력", "기계 일반", 3, 250000),
        ("크레인 25톤", "장비", "중장비", 1, 900000),
        ("진동분석기", "장비", "측정장비", 1, 50000),
        ("절연저항계", "장비", "측정장비", 2, 20000),
        ("오일필터링기", "장비", "정비장비", 1, 150000),
    ]
    rs = {}
    for name, rtype, skill, mx, cost in res_rows:
        rs[name] = db.insert(conn, "resources", {
            "name": name, "rtype": rtype, "skill": skill, "max_units": mx, "cost_per_day": cost,
        })

    # ---- 프로젝트: 정기보수
    pid = db.insert(conn, "projects", {
        "name": f"{start.year}년 공장 정기보수(Shutdown)",
        "site": "○○공장", "manager": "정비팀장",
        "description": "전기·기계 설비 정기보수 공사 (실습용 예제)",
        "start_date": iso(start), "status_date": iso(start + timedelta(days=15)),
        "skip_weekends": 1, "holidays": "",
    })

    T = {}

    def task(wbs, name, dur, disc="공통", eqc=None, pct=0):
        T[wbs] = db.insert(conn, "tasks", {
            "project_id": pid, "wbs": wbs, "name": name, "duration": dur,
            "discipline": disc, "equipment_id": eq.get(eqc), "percent_complete": pct,
        })

    task("1", "착수 준비", 0)
    task("1.1", "정비계획 수립 및 검토", 3, "공통", None, 100)
    task("1.2", "자재·예비품 확보", 5, "공통", None, 100)
    task("1.3", "안전작업허가(PTW) 및 LOTO", 1, "공통", None, 100)
    task("1.4", "착수 승인 (마일스톤)", 0, "공통", None, 100)
    task("2", "전기설비 정비", 0, "전기")
    task("2.1", "수배전반 정전 및 절연저항 측정", 2, "전기", "VCB-01", 100)
    task("2.2", "변압기 절연유 분석·필터링", 3, "전기", "TR-01", 60)
    task("2.3", "진공차단기(VCB) 점검·조정", 2, "전기", "VCB-01", 50)
    task("2.4", "보호계전기 특성시험", 2, "전기", "VCB-01", 0)
    task("2.5", "MCC 및 전동기 절연·베어링 점검", 3, "전기", "M-101", 30)
    task("3", "기계설비 정비", 0, "기계")
    task("3.1", "공기압축기 분해점검", 4, "기계", "C-201", 50)
    task("3.2", "냉각수펌프 메커니컬 씰 교체", 2, "기계", "P-301", 100)
    task("3.3", "축정렬(얼라인먼트) 및 진동측정", 2, "기계", "P-301", 0)
    task("3.4", "배관·밸브 누설점검", 3, "기계", None, 20)
    task("3.5", "컨베이어 벨트·감속기 점검", 3, "기계", "CV-401", 0)
    task("4", "시운전 및 준공", 0)
    task("4.1", "단독 시운전", 2, "공통")
    task("4.2", "연동 시운전", 2, "공통")
    task("4.3", "정비 결과보고서 작성", 2, "공통")
    task("4.4", "정기보수 완료 (마일스톤)", 0)

    deps = [
        ("1.1", "1.2", "FS", 0), ("1.1", "1.3", "FS", 2), ("1.2", "1.4", "FS", 0), ("1.3", "1.4", "FS", 0),
        ("1.4", "2.1", "FS", 0), ("2.1", "2.2", "FS", 0), ("2.1", "2.3", "FS", 0),
        ("2.3", "2.4", "FS", 0), ("2.1", "2.5", "SS", 1),
        ("1.4", "3.1", "FS", 0), ("1.4", "3.2", "FS", 0), ("3.2", "3.3", "FS", 0),
        ("1.4", "3.4", "FS", 0), ("3.4", "3.5", "SS", 1),
        ("2.2", "4.1", "FS", 0), ("2.4", "4.1", "FS", 0), ("2.5", "4.1", "FS", 0),
        ("3.1", "4.1", "FS", 0), ("3.3", "4.1", "FS", 0), ("3.5", "4.1", "FS", 0),
        ("4.1", "4.2", "FS", 0), ("4.2", "4.3", "FS", 0), ("4.2", "4.4", "FS", 0),
        ("4.3", "4.4", "FF", 0),
    ]
    for p, s, t, lag in deps:
        db.insert(conn, "dependencies", {"project_id": pid, "pred_id": T[p], "succ_id": T[s],
                                         "dep_type": t, "lag": lag})

    assigns = [
        ("1.1", "정안전", 0.5), ("1.1", "김전기", 0.5), ("1.1", "박기계", 0.5),
        ("1.3", "정안전", 1),
        ("2.1", "김전기", 1), ("2.1", "절연저항계", 1),
        ("2.2", "이계전", 1), ("2.2", "오일필터링기", 1),
        ("2.3", "김전기", 1), ("2.4", "이계전", 1),
        ("2.5", "김전기", 0.5), ("2.5", "절연저항계", 1),
        ("3.1", "박기계", 1), ("3.1", "협력사 정비반", 2), ("3.1", "크레인 25톤", 0.5),
        ("3.2", "최정비", 1), ("3.3", "박기계", 1), ("3.3", "진동분석기", 1),
        ("3.4", "최정비", 1), ("3.5", "협력사 정비반", 2),
        ("4.1", "김전기", 1), ("4.1", "박기계", 1), ("4.2", "김전기", 1), ("4.2", "박기계", 1),
        ("4.2", "정안전", 1), ("4.3", "정안전", 1),
    ]
    for w, r, u in assigns:
        db.insert(conn, "assignments", {"project_id": pid, "task_id": T[w], "resource_id": rs[r], "units": u})

    # 기준선(Baseline) 저장: 진척 실습을 위해 일부 기간을 원래 계획보다 짧게 잡아 편차가 보이게 함
    from .service import build_schedule, save_baseline
    sched, _, _ = build_schedule(conn, pid)
    save_baseline(conn, sched)
    conn.execute("UPDATE tasks SET duration=5 WHERE id=?", [T["3.1"]])  # 압축기 점검 기간 증가(지연 발생)
    for tid in sched.leaf_ids():  # 진행된 작업은 실제 시작/완료일 기록
        t = sched.tasks[tid]
        if t.percent_complete >= 100:
            conn.execute("UPDATE tasks SET actual_start=?, actual_finish=? WHERE id=?",
                         [iso(t.start), iso(t.finish), tid])
        elif t.percent_complete > 0:
            conn.execute("UPDATE tasks SET actual_start=? WHERE id=?", [iso(t.start), tid])
    conn.commit()

    # ---- 예방정비 계획
    pm_rows = [
        ("TR-01", "변압기 절연유 분석", "예방정비(PM)", 180, 170, 4, "이계전", "유중가스 분석, 절연파괴전압, 수분 측정"),
        ("TR-01", "변압기 외관·온도 점검", "점검", 7, 5, 1, "김전기", "유온/권선온도, 누유, 이상음 확인"),
        ("VCB-01", "차단기 동작특성 시험", "예방정비(PM)", 365, 300, 6, "김전기", "개폐시간, 접촉저항, 절연저항"),
        ("M-101", "전동기 절연저항 측정", "예방정비(PM)", 90, 95, 2, "김전기", "메거 측정, 베어링 온도/소음"),
        ("C-201", "압축기 오일·필터 교환", "예방정비(PM)", 60, 50, 3, "박기계", "오일 교환, 에어필터·오일필터 교체"),
        ("P-301", "펌프 진동측정", "예측정비(PdM)", 30, 31, 1, "박기계", "베어링 진동 속도(mm/s) 측정, 추세 기록"),
        ("CV-401", "컨베이어 벨트 장력·정렬 점검", "점검", 14, 3, 1, "최정비", "장력, 사행, 롤러 회전 상태"),
        ("FAN-501", "송풍기 베어링 그리스 주입", "예방정비(PM)", 30, 10, 1, "최정비", "그리스 주입 및 온도 확인"),
    ]
    pm = {}
    for code, name, typ, interval, ago, hrs, who, chk in pm_rows:
        pm[(code, name)] = db.insert(conn, "pm_plans", {
            "equipment_id": eq[code], "name": name, "pm_type": typ, "interval_days": interval,
            "last_done": iso(today - timedelta(days=ago)), "est_hours": hrs,
            "resource_id": rs[who], "checklist": chk, "active": 1,
        })

    # ---- 작업지시 (이력 + 진행중)
    yymm = f"{today:%y%m}"
    wo_rows = [
        ("모터 베어링 이상음 조치", "M-101", "사후정비(BM)", "긴급", "진행중", -2, 1, None, "김전기", 4, 2, "",
         "운전 중 이상음 발생, 베어링 교체 필요"),
        ("압축기 토출온도 상승 점검", "C-201", "사후정비(BM)", "높음", "승인", -1, 3, None, "박기계", 3, 0, "", ""),
        ("변압기 외관·온도 점검", "TR-01", "점검", "보통", "완료", -10, -9, -9, "김전기", 1, 1,
         "이상 없음 (유온 52℃)", ""),
        ("컨베이어 롤러 교체", "CV-401", "개량정비(CM)", "보통", "요청", 0, 10, None, "최정비", 6, 0, "",
         "마모 롤러 12개 내마모성 롤러로 교체"),
        ("펌프 씰 누수 조치", "P-301", "사후정비(BM)", "높음", "완료", -20, -18, -19, "최정비", 5, 6,
         "메커니컬 씰 교체 완료", "씰 누수 발생"),
        ("집진기 송풍기 벨트 교체", "FAN-501", "사후정비(BM)", "보통", "완료", -40, -35, -36, "협력사 정비반", 3, 3.5,
         "V벨트 4본 교체", ""),
    ]
    for i, (title, code, typ, pri, st, req, due, done, who, est, act, result, desc) in enumerate(wo_rows, 1):
        db.insert(conn, "work_orders", {
            "wo_no": f"WO-{yymm}-{i:03d}", "title": title, "equipment_id": eq[code], "wo_type": typ,
            "priority": pri, "status": st,
            "requested_date": iso(today + timedelta(days=req)), "due_date": iso(today + timedelta(days=due)),
            "completed_date": iso(today + timedelta(days=done)) if done is not None else None,
            "resource_id": rs[who], "est_hours": est, "actual_hours": act, "result": result,
            "description": desc,
        })
    return pid
