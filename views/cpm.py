import streamlit as st

from core import charts, service
from views.common import load_schedule, require_project

st.title("🛤️ 주공정(CPM) 분석")
p = require_project()
sched, tasks, deps = load_schedule(p["id"])
if not sched.tasks:
    st.info("작업을 먼저 입력하세요.")
    st.stop()
sdf = service.schedule_frame(sched, tasks)
leaf = sdf[~sdf["요약"]]
crit = leaf[leaf["주공정"]]

c = st.columns(4)
c[0].metric("총 공기", f"{sched.finish_index} 작업일")
c[1].metric("완료 예정일", f"{sched.project_finish:%Y-%m-%d}")
c[2].metric("주공정 작업", f"{len(crit)} / {len(leaf)}개")
c[3].metric("여유 있는 작업", f"{int((leaf['총여유'] > 0).sum())}개")

st.markdown("**주공정 경로:** " + " → ".join(f"`{w}` {n}" for w, n in zip(crit["WBS"], crit["name"])))

with st.expander("📘 CPM 용어 설명", expanded=False):
    st.markdown(
        "- **ES/EF (빠른 시작/완료)**: 선행 작업이 허용하는 가장 빠른 시점 (전진 계산)\n"
        "- **LS/LF (늦은 시작/완료)**: 프로젝트 완료일을 늦추지 않는 가장 늦은 시점 (후진 계산)\n"
        "- **총여유(TF) = LS − ES**: 이 작업이 늦어져도 전체 공기에 영향이 없는 일수\n"
        "- **자유여유(FF)**: 바로 다음 작업의 빠른 시작을 늦추지 않는 일수\n"
        "- **주공정(Critical Path)**: 총여유가 0 이하인 작업의 연결. 이 작업이 하루 늦으면 정기보수 전체가 하루 늦어짐\n"
        "- ES/EF/LS/LF 숫자는 프로젝트 시작일로부터의 **작업일 수** 입니다 (EF는 작업 종료 다음 시점)."
    )

tab1, tab2 = st.tabs(["📋 CPM 계산표", "🕸️ 네트워크 다이어그램"])
with tab1:
    show = leaf[["WBS", "name", "기간(일)", "ES", "EF", "LS", "LF", "총여유", "자유여유", "주공정", "시작", "완료"]].rename(
        columns={"name": "작업명"})
    st.dataframe(
        show.style.apply(lambda r: ["background:#fee2e2" if r["주공정"] else "" for _ in r], axis=1),
        hide_index=True, use_container_width=True,
        column_config={"시작": st.column_config.DateColumn(format="YYYY-MM-DD"),
                       "완료": st.column_config.DateColumn(format="YYYY-MM-DD")},
    )
with tab2:
    st.plotly_chart(charts.network_diagram(sched, deps), use_container_width=True)
    st.caption("노드 = 작업(WBS·기간), 빨간 테두리/굵은 화살표 = 주공정. FS 이외 관계와 Lag는 화살표 위에 표시됩니다.")

st.divider()
st.markdown("#### 🔍 What-if: 작업 기간을 바꾸면 공기가 어떻게 변할까?")
labels = {int(r.id): f"{r.WBS} {r.name}" for r in leaf.itertuples()}
col1, col2 = st.columns([3, 1])
tid = col1.selectbox("작업 선택", list(labels), format_func=lambda i: labels[i])
cur = int(sched.tasks[tid].duration)
nd = col2.number_input("새 기간(일)", min_value=0, value=cur, step=1)
if nd != cur:
    from core.scheduler import TaskInput, compute_schedule
    tin = [TaskInput(id=int(r.id), wbs=str(r.wbs), name=str(r.name),
                     duration=(nd if int(r.id) == tid else r.duration),
                     constraint_start=service.to_date(r.constraint_start),
                     actual_start=service.to_date(r.actual_start), actual_finish=service.to_date(r.actual_finish),
                     percent_complete=float(r.percent_complete or 0) if r.percent_complete == r.percent_complete else 0.0) for r in tasks.itertuples()]
    alt = compute_schedule(tin, deps, sched.calendar)
    diff = alt.finish_index - sched.finish_index
    msg = f"완료 예정일 {sched.project_finish:%Y-%m-%d} → **{alt.project_finish:%Y-%m-%d}** ({diff:+d} 작업일)"
    (st.error if diff > 0 else st.success if diff < 0 else st.info)(msg)
    if diff == 0 and nd > cur:
        st.caption(f"이 작업의 총여유가 {sched.tasks[tid].total_float}일이라 공기에 영향이 없습니다.")
