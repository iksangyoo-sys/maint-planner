import streamlit as st

from core import charts, service
from views.common import load_schedule, require_project

st.title("📊 간트차트")
p = require_project()
sched, tasks, deps = load_schedule(p["id"])
if not sched.tasks:
    st.info("작업을 먼저 입력하세요.")
    st.stop()

c = st.columns(6)
crit = c[0].toggle("주공정 강조", True)
dep = c[1].toggle("선후행 화살표", True)
prog = c[2].toggle("진척률 표시", True)
base = c[3].toggle("기준선 비교", False)
stat = c[4].toggle("기준일 선", True)
max_lv = max(t.level for t in sched.tasks.values())
lv = c[5].selectbox("표시 단계", list(range(1, max_lv + 1)), index=max_lv - 1, format_func=lambda x: f"{x}단계까지")

bl = {int(r.id): (service.to_date(r.baseline_start), service.to_date(r.baseline_finish)) for r in tasks.itertuples()}
fig = charts.gantt(
    sched, deps, show_critical=crit, show_deps=dep, show_progress=prog, show_baseline=base,
    baseline=bl, status_date=service.to_date(p.get("status_date")) if stat else None,
    collapse_levels=lv,
)
st.plotly_chart(fig, use_container_width=True)
st.caption("파란 막대 = 일반 작업 · 빨간 막대 = 주공정 작업 · 진한 회색 = 요약 작업 · 검은 띠 = 진척 · "
           "회색 얇은 막대 = 기준선 · ◆ = 마일스톤 · 회색 음영 = 주말. 마우스를 올리면 상세 정보, 드래그하면 확대됩니다.")
