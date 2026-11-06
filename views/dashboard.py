from datetime import date

import plotly.express as px
import streamlit as st

from core import charts, db, service
from views.common import get_conn, load_schedule, require_project, won

st.title("🏠 대시보드")
conn = get_conn()
p = require_project()
sched, tasks, deps = load_schedule(p["id"])
sdf = service.schedule_frame(sched, tasks)
assign = service.assignment_frame(conn, p["id"], sched)
ev = service.earned_value(sched, assign)
leaf = sdf[~sdf["요약"]]

st.subheader(f"📁 {p['name']}")
st.caption(f"현장: {p.get('site') or '-'} · 책임자: {p.get('manager') or '-'} · 진척 기준일: {p.get('status_date') or '미지정'}")

c = st.columns(6)
c[0].metric("시작일", sched.project_start.strftime("%y.%m.%d"))
c[1].metric("완료 예정일", sched.project_finish.strftime("%y.%m.%d"))
c[2].metric("총 공기(작업일)", f"{sched.finish_index}일")
c[3].metric("작업 수", f"{len(leaf)}개", f"주공정 {int(leaf['주공정'].sum())}개", delta_color="off")
c[4].metric("실적 진척률", f"{ev['실적진척률']:.1f}%", f"{ev['실적진척률'] - ev['계획진척률']:+.1f}%p (계획 대비)")
c[5].metric("일정성과지수 SPI", f"{ev['SPI']:.2f}" if ev["SPI"] else "-",
            help="SPI = EV / PV. 1보다 작으면 계획보다 늦음")

left, right = st.columns([3, 2])
with left:
    st.markdown("#### 일정 요약 (간트, 1단계 요약)")
    fig = charts.gantt(sched, deps, show_deps=False, collapse_levels=1,
                       status_date=service.to_date(p.get("status_date")))
    st.plotly_chart(fig, use_container_width=True)
with right:
    st.markdown("#### 분야별 진척률")
    g = leaf.assign(가중=leaf["기간(일)"].clip(lower=1))
    g["실적"] = g["진척률(%)"] * g["가중"]
    g["계획"] = g["계획진척률(%)"] * g["가중"]
    agg = g.groupby("분야")[["실적", "계획", "가중"]].sum()
    agg = (agg[["실적", "계획"]].div(agg["가중"], axis=0)).reset_index().melt(
        id_vars="분야", var_name="구분", value_name="진척률(%)")
    fig2 = px.bar(agg, x="분야", y="진척률(%)", color="구분", barmode="group",
                  color_discrete_map={"실적": "#3b82f6", "계획": "#cbd5e1"}, range_y=[0, 100])
    fig2.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10), plot_bgcolor="white")
    st.plotly_chart(fig2, use_container_width=True)

    late = leaf[(leaf["진척률(%)"] < leaf["계획진척률(%)"] - 0.1)]
    st.markdown(f"#### ⚠️ 계획 대비 지연 작업 ({len(late)}건)")
    if late.empty:
        st.success("지연 작업이 없습니다.")
    else:
        st.dataframe(late[["WBS", "name", "진척률(%)", "계획진척률(%)", "총여유"]].rename(columns={"name": "작업명"}),
                     hide_index=True, use_container_width=True)

st.divider()
st.markdown("### 🧾 설비 정비 현황")
wo = db.query_df(conn, "SELECT status, priority, wo_type, due_date FROM work_orders")
due = service.pm_due_frame(conn)
k = st.columns(5)
open_wo = wo[~wo["status"].isin(["완료", "취소"])] if not wo.empty else wo
k[0].metric("미결 작업지시", f"{len(open_wo)}건")
k[1].metric("긴급·높음", f"{int(open_wo['priority'].isin(['긴급', '높음']).sum()) if not open_wo.empty else 0}건")
today = date.today().isoformat()
k[2].metric("기한 초과 작업지시",
            f"{int((open_wo['due_date'] < today).sum()) if not open_wo.empty else 0}건")
k[3].metric("예방정비 기한초과", f"{int((due['상태'] == '기한초과').sum()) if not due.empty else 0}건")
k[4].metric("예방정비 7일내 도래", f"{int((due['상태'] == '임박').sum()) if not due.empty else 0}건")

a, b = st.columns(2)
if not wo.empty:
    with a:
        f = px.pie(wo, names="status", title="작업지시 상태", hole=0.45)
        f.update_layout(height=300, margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(f, use_container_width=True)
    with b:
        f = px.histogram(wo, x="wo_type", color="priority", title="정비 유형별 작업지시",
                         category_orders={"priority": ["긴급", "높음", "보통", "낮음"]},
                         color_discrete_map={"긴급": "#dc2626", "높음": "#f97316", "보통": "#3b82f6", "낮음": "#94a3b8"})
        f.update_layout(height=300, margin=dict(l=10, r=10, t=40, b=10), xaxis_title="", yaxis_title="건수",
                        plot_bgcolor="white")
        st.plotly_chart(f, use_container_width=True)
st.caption(f"예산(BAC) {won(ev['BAC'])} · 계획가치(PV) {won(ev['PV'])} · 획득가치(EV) {won(ev['EV'])}")
