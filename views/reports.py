from datetime import date

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from core import db, reports, service
from views.common import get_conn, load_schedule, require_project, won

st.title("📑 보고서")
st.caption("화면에서 확인하고 엑셀(.xlsx) 또는 인쇄용 HTML로 내려받을 수 있습니다. HTML 파일을 브라우저로 열고 인쇄(Ctrl+P) → 'PDF로 저장'하면 PDF 보고서가 됩니다.")
conn = get_conn()
p = require_project()
pid = p["id"]
sched, tasks, deps = load_schedule(pid)
sdf = service.schedule_frame(sched, tasks)
assign = service.assignment_frame(conn, pid, sched)
ev = service.earned_value(sched, assign)
leaf = sdf[~sdf["요약"]]

dcols = ["WBS", "작업명", "기간(일)", "시작", "완료", "총여유", "주공정", "진척률(%)", "분야"]
eq_map = {int(r.id): f"{r.code} {r.name}" for r in db.table_df(conn, "equipment").itertuples()}

schedule_tbl = sdf[dcols].copy()
critical_tbl = leaf[leaf["주공정"]][["WBS", "name", "기간(일)", "시작", "완료", "진척률(%)"]].rename(columns={"name": "작업명"})
late_tbl = leaf[leaf["진척률(%)"] < leaf["계획진척률(%)"] - 0.1][["WBS", "name", "계획진척률(%)", "진척률(%)", "총여유", "완료"]] \
    .rename(columns={"name": "작업명"})
asg_tbl = (assign[["resource", "rtype", "작업", "시작", "완료", "units", "작업량(인·일)", "비용"]]
           .rename(columns={"resource": "자원", "rtype": "유형", "units": "투입량"}) if not assign.empty else assign)
wo_tbl = db.query_df(conn, """
    SELECT w.wo_no AS 번호, w.title AS 제목, e.code AS 설비, w.wo_type AS 유형, w.priority AS 우선순위,
           w.status AS 상태, w.requested_date AS 요청일, w.due_date AS 기한, w.completed_date AS 완료일,
           r.name AS 담당, w.est_hours AS 예상공수, w.actual_hours AS 실적공수, w.result AS 조치결과
    FROM work_orders w LEFT JOIN equipment e ON e.id=w.equipment_id LEFT JOIN resources r ON r.id=w.resource_id
    ORDER BY w.requested_date DESC""")
pm_tbl = service.pm_due_frame(conn)
if not pm_tbl.empty:
    pm_tbl = pm_tbl.sort_values("남은일수")[["eq_code", "name", "pm_type", "interval_days", "last_done", "다음예정일", "남은일수", "상태"]]
    pm_tbl.columns = ["설비", "정비항목", "유형", "주기(일)", "최근실시", "다음예정일", "남은일수", "상태"]

REPORTS = {
    "① 프로젝트 종합 보고서": None,
    "② 작업 일정표": schedule_tbl,
    "③ 주공정 작업 목록": critical_tbl,
    "④ 지연 작업 목록": late_tbl,
    "⑤ 자원 배정표": asg_tbl,
    "⑥ 작업지시 현황": wo_tbl,
    "⑦ 예방정비 도래 현황": pm_tbl,
}
kind = st.radio("보고서 종류", list(REPORTS), horizontal=True)

kpi = {
    "기간": f"{sched.project_start:%Y-%m-%d} ~ {sched.project_finish:%Y-%m-%d}",
    "총 공기": f"{sched.finish_index} 작업일",
    "작업 수": f"{len(leaf)}개 (주공정 {int(leaf['주공정'].sum())}개)",
    "계획/실적 진척": f"{ev['계획진척률']:.1f}% / {ev['실적진척률']:.1f}%",
    "SPI": f"{ev['SPI']:.2f}" if ev["SPI"] else "-",
    "예산(BAC)": won(ev["BAC"]),
}
meta = {"프로젝트": p["name"], "현장": p.get("site") or "-", "책임자": p.get("manager") or "-",
        "진척 기준일": p.get("status_date") or "-", "작성일": f"{date.today():%Y-%m-%d}"}

if REPORTS[kind] is None:
    cols = st.columns(len(kpi))
    for c, (k, v) in zip(cols, kpi.items()):
        c.metric(k, v)
    sections = [
        ("1. 핵심 지표", reports.kpi_html(kpi)),
        ("2. 주공정 작업", reports.df_to_html(critical_tbl)),
        ("3. 계획 대비 지연 작업", reports.df_to_html(late_tbl) if not late_tbl.empty else "<p>지연 작업 없음</p>"),
        ("4. 전체 작업 일정", reports.df_to_html(schedule_tbl, "주공정")),
        ("5. 자원 배정", reports.df_to_html(asg_tbl) if not asg_tbl.empty else "<p>배정 없음</p>"),
    ]
    st.markdown("**주공정 작업**")
    st.dataframe(critical_tbl, hide_index=True, use_container_width=True)
    st.markdown("**지연 작업**")
    st.dataframe(late_tbl, hide_index=True, use_container_width=True)
    title = f"{p['name']} 종합 보고서"
    sheets = {"종합지표": pd.DataFrame(list(kpi.items()), columns=["지표", "값"]),
              "작업일정": schedule_tbl, "주공정": critical_tbl, "지연작업": late_tbl, "자원배정": asg_tbl}
else:
    tbl = REPORTS[kind]
    st.dataframe(tbl, hide_index=True, use_container_width=True)
    title = f"{p['name']} - {kind[2:]}" if kind[0] in "②③④⑤" else kind[2:]
    sections = [(kind[2:], reports.df_to_html(tbl, "주공정" if "주공정" in tbl.columns else None))]
    sheets = {kind[2:]: tbl}

html = reports.html_report(title, meta, sections)
c1, c2, c3 = st.columns(3)
c1.download_button("⬇️ 인쇄용 HTML", html.encode("utf-8"), file_name=f"{title}.html", mime="text/html")
c2.download_button("⬇️ 엑셀(.xlsx)", reports.to_excel(sheets), file_name=f"{title}.xlsx",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
first = next(iter(sheets.values()))
c3.download_button("⬇️ CSV", first.to_csv(index=False).encode("utf-8-sig"), file_name=f"{title}.csv", mime="text/csv")
with st.expander("👀 HTML 보고서 미리보기"):
    components.html(html, height=600, scrolling=True)
