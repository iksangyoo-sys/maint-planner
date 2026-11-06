import pandas as pd
import streamlit as st

from core import db, service
from core.scheduler import DEP_TYPES, CycleError, DepInput, topo_order
from views.common import flash, get_conn, label_to_id, require_project, show_flash

st.title("🔗 선후행 관계")
st.markdown(
    "| 유형 | 의미 | 정비 현장 예시 |\n|---|---|---|\n"
    "| **FS** 종료-시작 | 선행이 끝나야 후행 시작 | 정전(LOTO) 완료 → 차단기 점검 |\n"
    "| **SS** 시작-시작 | 선행이 시작되면 후행 시작 가능 | 배관 점검 시작 1일 후 컨베이어 점검 시작 |\n"
    "| **FF** 종료-종료 | 선행이 끝나야 후행 종료 가능 | 시운전 종료 후 보고서 마감 |\n"
    "| **SF** 시작-종료 | 선행이 시작되어야 후행 종료 | 교대근무 인수 시작 → 이전 근무 종료 |\n\n"
    "지연(Lag)은 작업일 단위입니다. 음수로 입력하면 앞당김(Lead)이 됩니다. 요약 작업은 연결할 수 없습니다."
)
show_flash()
conn = get_conn()
p = require_project()
pid = p["id"]
tasks = db.table_df(conn, "tasks", "project_id=?", [pid])
if tasks.empty:
    st.info("작업을 먼저 입력하세요.")
    st.stop()
leaf = set(tasks["id"].astype(int)) - service.summary_ids(tasks)
labels = service.task_labels(tasks, leaf)
deps = db.table_df(conn, "dependencies", "project_id=?", [pid])
view = deps.copy()
view["pred"] = [labels.get(int(x)) for x in view["pred_id"]]
view["succ"] = [labels.get(int(x)) for x in view["succ_id"]]
type_labels = list(DEP_TYPES.values())
view["type"] = [DEP_TYPES.get(t, DEP_TYPES["FS"]) for t in view["dep_type"]]

edited = st.data_editor(
    view[["id", "pred", "succ", "type", "lag"]], num_rows="dynamic", hide_index=True,
    use_container_width=True, key=f"dep_editor_{pid}",
    column_config={
        "id": None,
        "pred": st.column_config.SelectboxColumn("선행 작업", options=list(labels.values()), required=True, width="large"),
        "succ": st.column_config.SelectboxColumn("후행 작업", options=list(labels.values()), required=True, width="large"),
        "type": st.column_config.SelectboxColumn("관계 유형", options=type_labels, default=type_labels[0], required=True),
        "lag": st.column_config.NumberColumn("지연(Lag, 일)", step=1, default=0),
    },
)
if st.button("💾 저장", type="primary"):
    e = edited.dropna(subset=["pred", "succ"]).copy()
    e["pred_id"] = label_to_id(e["pred"], labels)
    e["succ_id"] = label_to_id(e["succ"], labels)
    rev_type = {v: k for k, v in DEP_TYPES.items()}
    e["dep_type"] = [rev_type.get(t, "FS") for t in e["type"]]
    e["lag"] = e["lag"].fillna(0)
    bad_self = e[e["pred_id"] == e["succ_id"]]
    dups = e.duplicated(subset=["pred_id", "succ_id"])
    try:
        topo_order(sorted(leaf), [DepInput(int(a), int(b)) for a, b in zip(e["pred_id"], e["succ_id"])])
        cycle = None
    except CycleError as ce:
        cycle = ce
    if not bad_self.empty:
        st.error("자기 자신과는 연결할 수 없습니다.")
    elif dups.any():
        st.error("같은 선행-후행 연결이 중복되어 있습니다.")
    elif cycle:
        names = ", ".join(labels.get(i, str(i)) for i in cycle.task_ids)
        st.error(f"순환 관계가 생깁니다. 다음 작업 사이의 연결을 확인하세요: {names}")
    else:
        n = db.sync_table(conn, "dependencies", e[["id", "pred_id", "succ_id", "dep_type", "lag"]], deps["id"],
                          {"project_id": pid})
        flash(f"저장했습니다. (추가 {n[0]} · 수정 {n[1]} · 삭제 {n[2]})")
        st.rerun()

st.divider()
st.markdown("#### 작업별 선행 작업 요약")
rows = []
for tid, lbl in labels.items():
    pr = deps[deps["succ_id"] == tid]
    rows.append({"작업": lbl, "선행 작업": ", ".join(
        f"{tasks.set_index('id').loc[int(r.pred_id), 'wbs']}{r.dep_type}{'' if not r.lag else f'{int(r.lag):+d}'}"
        for r in pr.itertuples()) or "(없음 · 시작 작업)"})
st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
