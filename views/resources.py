import pandas as pd
import plotly.express as px
import streamlit as st

from core import charts, db, service
from views.common import (
    RTYPES, flash, get_conn, label_to_id, load_schedule, require_project, show_flash, won,
)

st.title("👷 자원 배정·부하")
st.caption("자원 = 정비 기술자(인력), 크레인·측정장비(장비) 등. 최대 투입량을 넘으면 '과부하'로 표시됩니다.")
show_flash()
conn = get_conn()
p = require_project()
pid = p["id"]

tab1, tab2, tab3 = st.tabs(["👥 자원 목록", "🔧 작업별 자원 배정", "📊 부하·비용 분석"])

with tab1:
    res = db.table_df(conn, "resources")
    ed = st.data_editor(
        res[["id", "name", "rtype", "skill", "max_units", "cost_per_day", "phone", "notes"]],
        num_rows="dynamic", hide_index=True, use_container_width=True, key="res_editor",
        column_config={
            "id": None,
            "name": st.column_config.TextColumn("자원명", required=True),
            "rtype": st.column_config.SelectboxColumn("유형", options=RTYPES, default="인력"),
            "skill": st.column_config.TextColumn("기능·직무 (예: 전기(고압))"),
            "max_units": st.column_config.NumberColumn("최대 투입(명·대)", min_value=0.0, step=0.5, default=1.0),
            "cost_per_day": st.column_config.NumberColumn("일 단가(원)", min_value=0, step=10000, format="localized"),
            "phone": st.column_config.TextColumn("연락처"),
            "notes": st.column_config.TextColumn("비고"),
        },
    )
    if st.button("💾 자원 저장", type="primary"):
        e = ed.dropna(subset=["name"]).copy()
        e["max_units"] = e["max_units"].fillna(1)
        e["cost_per_day"] = e["cost_per_day"].fillna(0)
        n = db.sync_table(conn, "resources", e, res["id"])
        flash(f"자원을 저장했습니다. (추가 {n[0]} · 수정 {n[1]} · 삭제 {n[2]})")
        st.rerun()
    st.caption("자원은 모든 프로젝트·작업지시에서 공통으로 사용됩니다.")

sched, tasks, deps = load_schedule(pid)
leaf = set(sched.leaf_ids())
tlabels = service.task_labels(tasks, leaf)
rmap = {int(r.id): r.name for r in db.table_df(conn, "resources").itertuples()}

with tab2:
    asg = db.table_df(conn, "assignments", "project_id=?", [pid])
    v = asg.copy()
    v["task"] = [tlabels.get(int(x)) for x in v["task_id"]]
    v["resource"] = [rmap.get(int(x)) for x in v["resource_id"]]
    v = v.sort_values("task", na_position="last")
    ed2 = st.data_editor(
        v[["id", "task", "resource", "units"]], num_rows="dynamic", hide_index=True,
        use_container_width=True, key=f"asg_editor_{pid}",
        column_config={
            "id": None,
            "task": st.column_config.SelectboxColumn("작업", options=list(tlabels.values()), required=True, width="large"),
            "resource": st.column_config.SelectboxColumn("자원", options=list(rmap.values()), required=True),
            "units": st.column_config.NumberColumn("투입량(1=1명·1대 전일)", min_value=0.1, step=0.5, default=1.0),
        },
    )
    if st.button("💾 배정 저장", type="primary"):
        e = ed2.dropna(subset=["task", "resource"]).copy()
        e["task_id"] = label_to_id(e["task"], tlabels)
        e["resource_id"] = label_to_id(e["resource"], rmap)
        e["units"] = e["units"].fillna(1)
        n = db.sync_table(conn, "assignments", e[["id", "task_id", "resource_id", "units"]], asg["id"],
                          {"project_id": pid})
        flash(f"배정을 저장했습니다. (추가 {n[0]} · 수정 {n[1]} · 삭제 {n[2]})")
        st.rerun()

with tab3:
    a = service.assignment_frame(conn, pid, sched)
    if a.empty:
        st.info("배정된 자원이 없습니다.")
        st.stop()
    load = service.resource_loading(a, sched)
    over = load[load["투입"] > load["최대"] + 1e-9]
    c = st.columns(3)
    c[0].metric("총 투입 공수", f"{a['작업량(인·일)'].sum():,.1f} 인·일")
    c[1].metric("총 자원 비용", won(a["비용"].sum()))
    c[2].metric("과부하 발생", f"{over['자원'].nunique()}개 자원 · {len(over)}일")
    if not over.empty:
        st.warning("⚠️ 과부하: " + ", ".join(
            f"{r} ({', '.join(d.strftime('%m/%d') for d in g['날짜'])})" for r, g in over.groupby("자원")))
        st.caption("해결 방법: 여유(총여유)가 있는 작업을 뒤로 미루거나(시작 제약), 다른 기술자로 교체, 협력사 인력 추가 등을 검토하세요.")

    st.markdown("##### 자원별 일일 부하 (히스토그램)")
    sel = st.selectbox("자원 선택", sorted(load["자원"].unique()))
    st.plotly_chart(charts.resource_histogram(load, sel), use_container_width=True)

    st.markdown("##### 자원 × 날짜 부하표")
    piv = load.pivot_table(index="자원", columns="날짜", values="투입", aggfunc="sum").fillna(0)
    piv.columns = [d.strftime("%m/%d") for d in piv.columns]
    caps = load.groupby("자원")["최대"].first()
    st.dataframe(piv.style.apply(lambda r: ["background:#fecaca" if v > caps[r.name] + 1e-9 else
                                            ("background:#dbeafe" if v > 0 else "") for v in r], axis=1)
                 .format("{:g}"), use_container_width=True)

    st.markdown("##### 자원별 공수·비용")
    s = a.groupby(["resource", "rtype"], as_index=False).agg(**{"작업 수": ("task_id", "nunique"),
                                                               "공수(인·일)": ("작업량(인·일)", "sum"),
                                                               "비용(원)": ("비용", "sum")})
    s = s.rename(columns={"resource": "자원", "rtype": "유형"})
    col1, col2 = st.columns([3, 2])
    col1.dataframe(s, hide_index=True, use_container_width=True,
                   column_config={"비용(원)": st.column_config.NumberColumn(format="localized")})
    fig = px.pie(s, names="자원", values="비용(원)", hole=0.4)
    fig.update_layout(height=280, margin=dict(l=0, r=0, t=10, b=0))
    col2.plotly_chart(fig, use_container_width=True)
