"""예제 프로젝트: 이차전지 양극재 소성 라인 증설 (실습용 가상 데이터)."""
from __future__ import annotations

from . import db, service

RESOURCES = [
    # name, type, group, max %, 단가(원/일)
    ("PM", "인력", "사업관리", 100, 550000),
    ("공정엔지니어", "인력", "생산기술", 100, 450000),
    ("설계엔지니어", "인력", "설계", 100, 450000),
    ("기계엔지니어", "인력", "설비", 100, 420000),
    ("전기엔지니어", "인력", "설비", 100, 420000),
    ("구매담당", "인력", "구매", 100, 350000),
    ("품질담당", "인력", "품질", 100, 380000),
    ("교육담당", "인력", "HRD", 100, 350000),
    ("시공업체", "장비·외주", "외주", 200, 2200000),
]

# level, 작업명, 기간(작업일), 선행작업(행 번호), 자원
TASKS = [
    (1, "착수 및 기본설계", 0, "", ""),
    (2, "프로젝트 착수 회의", 1, "", "PM, 공정엔지니어"),
    (2, "공정 요구사항 정의", 5, "2", "공정엔지니어, PM[30%]"),
    (2, "기본설계(레이아웃·P&ID)", 10, "3", "설계엔지니어, 공정엔지니어[50%]"),
    (2, "기본설계 승인", 0, "4", "PM"),
    (1, "설비 조달", 0, "", ""),
    (2, "소성로(RHK) 발주·제작", 25, "5", "구매담당"),
    (2, "분쇄·분급기 발주·제작", 18, "5", "구매담당[50%]"),
    (2, "전기·제어 판넬 제작", 15, "5", "전기엔지니어"),
    (1, "시공", 0, "", ""),
    (2, "기초 토목 공사", 12, "5", "시공업체"),
    (2, "소성로 설치", 10, "7, 11", "시공업체, 기계엔지니어"),
    (2, "분쇄·분급기 설치", 6, "8, 11", "시공업체[50%], 기계엔지니어[50%]"),
    (2, "전기·배관 공사", 10, "12SS+3, 9", "전기엔지니어, 시공업체[50%]"),
    (1, "시운전 및 양산 이관", 0, "", ""),
    (2, "단독 시운전", 5, "13, 14", "기계엔지니어, 전기엔지니어"),
    (2, "종합 시운전(무부하·부하)", 7, "16", "공정엔지니어, 품질담당"),
    (2, "작업자 교육(SOP·안전)", 4, "16SS", "교육담당"),
    (2, "고객 인증 샘플 평가", 6, "17", "품질담당"),
    (2, "양산 이관 승인", 0, "19, 18", "PM"),
]

# 진척 기준일(2026-11-06) 현재 실적
ACTUALS = {
    2: {"actual_start": "2026-10-05", "actual_finish": "2026-10-05"},
    3: {"actual_start": "2026-10-06", "actual_finish": "2026-10-15"},
    4: {"actual_start": "2026-10-16", "pct": 70},
    11: {"actual_start": "2026-10-29", "pct": 20},
}


def create_sample() -> int:
    pid = service.create_project({
        "name": "양극재 소성 2라인 증설 프로젝트", "manager": "PM",
        "description": "이차전지 양극재 소성로(RHK) 1기와 분쇄·분급 설비를 증설하고 시운전 후 양산 이관하는 가상의 실습 프로젝트",
        "start_date": "2026-10-05", "skip_weekends": True, "holidays": "2026-10-09, 2026-12-25",
    })
    for name, typ, grp, mx, rate in RESOURCES:
        service.save_resource(pid, {"name": name, "type": typ, "grp": grp, "max_units": mx, "rate": rate})
    items = [{"level": lv, "name": nm, "duration": du, "predecessors": pr, "resources": rs}
             for lv, nm, du, pr, rs in TASKS]
    service.save_tasks(pid, items)
    service.set_baseline(pid)
    # 실적 입력
    con = db.get_db()
    for row, vals in ACTUALS.items():
        sets = ", ".join(f"{k}=?" for k in vals)
        con.execute(f"UPDATE task SET {sets} WHERE project_id=? AND row=?", (*vals.values(), pid, row))
    con.execute("UPDATE project SET status_date='2026-11-06' WHERE id=?", (pid,))
    con.commit()
    return pid
