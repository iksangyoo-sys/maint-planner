from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import db, service
from views.common import flash, get_conn, load_schedule, require_project, show_flash, to_date_col, won

st.title("📈 진척관리")
st.caption("① 기준선(Baseline) 저장 → ② 진척 기준일 설정 → ③ 작업별 진척률·실제 시작/완료일 입력 → ④ 계획 대비 실적 확인")
show_flash()
conn = get_conn()
p = require_project()
pid = p["id"]
sched, tasks, deps = load_schedule(pid)
if not sched.tasks:
    st.info("작업을 먼저 입력하세요.")
    st.stop()

c1, c2, c3 = st.columns([2, 2, 3])
with c1:
    sd = st.date_input("진척 기준일(Status date)", value=service.to_date(p.get("status_date")) or date.today())
    if st.button("기준일 적용"):
        db.update(conn, "projects", pid, {"status_date": sd.isoformat()})
        flash("진척 기준일을 변경했습니다.")
        st.rerun()
with c2:
    has_bl = tasks["baseline_start"].notna().any()
    st.write("기준선 상태:", "✅ 저장됨" if has_bl else "❌ 없음")
    if st.button("📌 현재 일정을 기준선으로 저장", help="현재 계산된 일정을 '원래 계획'으로 고정합니다. 이후 변경과 비교됩니다."):
        service.save_baseline(conn, sched)
        flash("기준선을 저장했습니다.")
        st.rerun()

assign = service.assignment_frame(conn, pid, sched)
ev = service.earned_value(sched, assign)
with c3:
    k = st.columns(3)
    k[0].metric("계획 진척률", f"{ev['계획진척률']:.1f}%")
    k[1].metric("실적 진척률", f"{ev['실적진척률']:.1f}%", f"{ev['실적진척률'] - ev['계획진척률']:+.1f}%p")
    k[2].metric("SPI", f"{ev['SPI']:.2f}" if ev["SPI"] else "-")

st.markdown("#### ✏️ 진척 입력")
leaf_ids = sched.leaf_ids()
v = tasks.set_index("id").loc[leaf_ids].reset_index()
v["계획진척(%)"] = [round(sched.tasks[i].planned_percent, 1) for i in v["id"]]
v["계획시작"] = [sched.tasks[i].start for i in v["id"]]
v["계획완료"] = [sched.tasks[i].finish for i in v["id"]]
v = to_date_col(v, ["actual_start", "actual_finish"])
ed = st.data_editor(
    v[["id", "wbs", "name", "계획시작", "계획완료", "계획진척(%)", "percent_complete", "actual_start", "actual_finish"]],
    hide_index=True, use_container_width=True, key=f"prog_editor_{pid}",
    disabled=["wbs", "name", "계획시작", "계획완료", "계획진척(%)"],
    column_config={
        "id": None, "wbs": "WBS", "name": st.column_config.TextColumn("작업명", width="large"),
        "계획시작": st.column_config.DateColumn(format="YYYY-MM-DD"),
        "계획완료": st.column_config.DateColumn(format="YYYY-MM-DD"),
        "percent_complete": st.column_config.NumberColumn("실적 진척(%)", min_value=0, max_value=100, step=5),
        "actual_start": st.column_config.DateColumn("실제 시작", format="YYYY-MM-DD"),
        "actual_finish": st.column_config.DateColumn("실제 완료", format="YYYY-MM-DD"),
    },
)
if st.button("💾 진척 저장", type="primary"):
    for r in ed.itertuples():
        pc = 0.0 if pd.isna(r.percent_complete) else float(r.percent_complete)
        a_s, a_f = service.to_date(r.actual_start), service.to_date(r.actual_finish)
        if pc >= 100 and not a_f:
            a_f = sched.tasks[int(r.id)].finish
        if pc > 0 and not a_s:
            a_s = sched.tasks[int(r.id)].start
        if a_f and pc < 100:
            pc = 100.0
        db.update(conn, "tasks", int(r.id), {"percent_complete": pc, "actual_start": a_s, "actual_finish": a_f})
    flash("진척을 저장했습니다. 실제 시작/완료일이 일정 계산에 반영됩니다.")
    st.rerun()
st.caption("진척률을 입력하면 실제 시작일이, 100%면 실제 완료일이 비어 있을 때 계획일로 자동 기록됩니다. "
           "실제 날짜가 있는 작업은 그 날짜로 고정되어 후속 작업 일정이 다시 계산됩니다.")

st.divider()
sdf = service.schedule_frame(sched, tasks)
leaf = sdf[~sdf["요약"]].copy()
left, right = st.columns(2)
with left:
    st.markdown("#### 계획 대비 실적 (작업별)")
    fig = go.Figure()
    lbl = [f"{w} {n}" for w, n in zip(leaf["WBS"], leaf["name"])]
    fig.add_bar(y=lbl, x=leaf["계획진척률(%)"], name="계획", orientation="h", marker_color="#cbd5e1")
    fig.add_bar(y=lbl, x=leaf["진척률(%)"], name="실적", orientation="h", marker_color="#3b82f6")
    fig.update_layout(barmode="group", height=30 * len(leaf) + 120, margin=dict(l=10, r=10, t=10, b=10),
                      yaxis=dict(autorange="reversed"), xaxis=dict(range=[0, 100], title="%"),
                      plot_bgcolor="white", legend=dict(orientation="h"))
    st.plotly_chart(fig, use_container_width=True)
with right:
    st.markdown("#### 기준선 대비 완료일 편차")
    if leaf["기준완료"].isna().all():
        st.info("기준선을 먼저 저장하세요.")
    else:
        dv = leaf[["WBS", "name", "기준완료", "완료", "완료편차(일)"]].rename(columns={"name": "작업명", "완료": "현재 완료예정"})
        def _dev_style(r):
            v = 0 if pd.isna(r["완료편차(일)"]) else r["완료편차(일)"]
            css = "color:#dc2626;font-weight:600" if v > 0 else ("color:#16a34a" if v < 0 else "")
            return [css] * len(r)

        st.dataframe(dv.style.apply(_dev_style, axis=1),
                     hide_index=True, use_container_width=True,
                     column_config={"기준완료": st.column_config.DateColumn(format="YYYY-MM-DD"),
                                    "현재 완료예정": st.column_config.DateColumn(format="YYYY-MM-DD")})
        bl_finish = max((service.to_date(x) for x in tasks["baseline_finish"] if service.to_date(x)), default=None)
        if bl_finish:
            d = sched.calendar.to_index(sched.project_finish) - sched.calendar.to_index(bl_finish)
            (st.error if d > 0 else st.success)(
                f"프로젝트 완료: 기준선 {bl_finish:%Y-%m-%d} → 현재 {sched.project_finish:%Y-%m-%d} ({d:+d} 작업일)")

    st.markdown("#### 획득가치(EV) 요약")
    st.markdown(
        f"| 지표 | 값 | 설명 |\n|---|---|---|\n"
        f"| BAC | {won(ev['BAC'])} | 총 예산 (자원 단가 × 공수) |\n"
        f"| PV | {won(ev['PV'])} | 기준일까지 계획된 작업의 가치 |\n"
        f"| EV | {won(ev['EV'])} | 실제 완료한 작업의 가치 |\n"
        f"| SV = EV − PV | {won(ev['SV'])} | 음수면 일정 지연 |\n"
        f"| SPI = EV / PV | {ev['SPI']:.2f} | 1 미만이면 지연 |" if ev["SPI"] else "기준일 이전에 계획된 작업이 없습니다."
    )
    if not ev["비용입력"]:
        st.caption("자원 배정·단가가 없어 작업 기간을 가중치로 계산했습니다.")
