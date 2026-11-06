import pandas as pd
import streamlit as st

from core import db
from views.common import CRITICALITY, EQ_DISCIPLINES, EQ_STATUS, flash, get_conn, show_flash, to_date_col

st.title("⚙️ 설비대장")
st.caption("정비 대상 전기·기계 설비 목록입니다. 중요도 A = 고장 시 생산 정지(최우선), B = 영향 있음, C = 영향 적음.")
show_flash()
conn = get_conn()
eq = db.table_df(conn, "equipment")
v = to_date_col(eq, ["install_date"])

f1, f2, f3 = st.columns(3)
disc = f1.multiselect("분야", EQ_DISCIPLINES)
crit = f2.multiselect("중요도", CRITICALITY)
kw = f3.text_input("검색 (코드·설비명·위치)")
mask = pd.Series(True, index=v.index)
if disc:
    mask &= v["discipline"].isin(disc)
if crit:
    mask &= v["criticality"].isin(crit)
if kw:
    mask &= v[["code", "name", "location"]].astype(str).apply(lambda c: c.str.contains(kw, case=False)).any(axis=1)
filtered = bool(disc or crit or kw)

ed = st.data_editor(
    v[mask][["id", "code", "name", "discipline", "location", "criticality", "maker", "install_date", "status", "notes"]],
    num_rows="fixed" if filtered else "dynamic", hide_index=True, use_container_width=True, key="eq_editor",
    column_config={
        "id": None,
        "code": st.column_config.TextColumn("설비코드", required=True),
        "name": st.column_config.TextColumn("설비명", required=True, width="large"),
        "discipline": st.column_config.SelectboxColumn("분야", options=EQ_DISCIPLINES, default="전기"),
        "location": st.column_config.TextColumn("설치 위치"),
        "criticality": st.column_config.SelectboxColumn("중요도", options=CRITICALITY, default="B"),
        "maker": st.column_config.TextColumn("제작사"),
        "install_date": st.column_config.DateColumn("설치일", format="YYYY-MM-DD"),
        "status": st.column_config.SelectboxColumn("상태", options=EQ_STATUS, default="가동"),
        "notes": st.column_config.TextColumn("비고"),
    },
)
if filtered:
    st.caption("필터 사용 중에는 행 추가·삭제가 잠깁니다. (수정만 가능)")
if st.button("💾 저장", type="primary"):
    e = ed.dropna(subset=["code", "name"])
    orig = v[mask]["id"] if filtered else eq["id"]
    n = db.sync_table(conn, "equipment", e, orig)
    flash(f"설비대장을 저장했습니다. (추가 {n[0]} · 수정 {n[1]} · 삭제 {n[2]})")
    st.rerun()

st.divider()
st.markdown("#### 🔎 설비별 정비 이력")
if not eq.empty:
    sel = st.selectbox("설비 선택", eq["id"].tolist(),
                       format_func=lambda i: " ".join(eq.set_index("id").loc[i, ["code", "name"]].astype(str)))
    hist = db.query_df(conn, """
        SELECT w.wo_no AS 작업지시번호, w.title AS 제목, w.wo_type AS 유형, w.status AS 상태,
               w.requested_date AS 요청일, w.completed_date AS 완료일, w.actual_hours AS 실적공수, w.result AS 조치결과
        FROM work_orders w WHERE w.equipment_id=? ORDER BY w.requested_date DESC""", [sel])
    pms = db.query_df(conn, "SELECT name AS 예방정비항목, pm_type AS 유형, interval_days AS 주기일, last_done AS 최근실시 "
                            "FROM pm_plans WHERE equipment_id=?", [sel])
    tk = db.query_df(conn, """SELECT p.name AS 프로젝트, t.wbs AS WBS, t.name AS 작업, t.percent_complete AS 진척률
                             FROM tasks t JOIN projects p ON p.id=t.project_id WHERE t.equipment_id=?""", [sel])
    a, b = st.columns(2)
    a.markdown("**작업지시 이력**")
    a.dataframe(hist, hide_index=True, use_container_width=True)
    b.markdown("**예방정비 계획**")
    b.dataframe(pms, hide_index=True, use_container_width=True)
    b.markdown("**프로젝트(정기보수) 작업**")
    b.dataframe(tk, hide_index=True, use_container_width=True)
    if not hist.empty:
        bm = hist[hist["유형"] == "사후정비(BM)"]
        st.caption(f"사후정비(고장) {len(bm)}건 · 누적 정비공수 {hist['실적공수'].fillna(0).sum():g}시간")
