from datetime import date

import streamlit as st

from core import db, sample_data
from views.common import current_project, flash, get_conn, show_flash

st.title("🛠️ 프로젝트·데이터 설정")
show_flash()
conn = get_conn()
p = current_project()

tab1, tab2, tab3 = st.tabs(["📁 현재 프로젝트", "➕ 새 프로젝트", "💾 백업·복원·초기화"])

with tab1:
    if not p:
        st.info("프로젝트가 없습니다.")
    else:
        with st.form("proj_edit"):
            name = st.text_input("프로젝트명", p["name"])
            a, b = st.columns(2)
            site = a.text_input("현장/공장", p.get("site") or "")
            mgr = b.text_input("책임자", p.get("manager") or "")
            c, d = st.columns(2)
            start = c.date_input("시작일", value=date.fromisoformat(p["start_date"]))
            sd = d.date_input("진척 기준일", value=date.fromisoformat(p["status_date"]) if p.get("status_date") else date.today())
            skip = st.checkbox("주말(토·일) 휴무", value=bool(p.get("skip_weekends", 1)),
                               help="정기보수처럼 주말에도 작업하면 체크를 해제하세요 (365일 달력).")
            hol = st.text_area("휴일 (YYYY-MM-DD, 쉼표 또는 줄바꿈으로 구분)", p.get("holidays") or "",
                               placeholder="2026-12-25, 2027-01-01")
            desc = st.text_area("설명", p.get("description") or "")
            if st.form_submit_button("💾 저장", type="primary"):
                db.update(conn, "projects", p["id"], {
                    "name": name, "site": site, "manager": mgr, "start_date": start.isoformat(),
                    "status_date": sd.isoformat(), "skip_weekends": int(skip), "holidays": hol, "description": desc})
                flash("프로젝트 정보를 저장했습니다.")
                st.rerun()
        with st.popover("🗑️ 이 프로젝트 삭제"):
            st.warning("작업·관계·배정이 모두 삭제됩니다. 되돌릴 수 없습니다.")
            if st.button("삭제 확인", type="primary"):
                db.delete(conn, "projects", p["id"])
                st.session_state["project_id"] = None
                flash("프로젝트를 삭제했습니다.")
                st.rerun()

with tab2:
    with st.form("proj_new", clear_on_submit=True):
        name = st.text_input("프로젝트명 *", placeholder="예) 2027년 상반기 변전설비 정기점검")
        a, b = st.columns(2)
        site = a.text_input("현장/공장")
        mgr = b.text_input("책임자")
        start = st.date_input("시작일", value=date.today())
        skip = st.checkbox("주말(토·일) 휴무", value=True)
        copy_from = st.selectbox("기존 프로젝트의 작업 구조 복사 (선택)", [None] + db.table_df(conn, "projects")["id"].tolist(),
                                 format_func=lambda i: "복사 안 함" if i is None else
                                 db.table_df(conn, "projects").set_index("id").loc[i, "name"])
        if st.form_submit_button("프로젝트 만들기", type="primary"):
            if not name:
                st.error("프로젝트명을 입력하세요.")
            else:
                pid = db.insert(conn, "projects", {"name": name, "site": site, "manager": mgr,
                                                   "start_date": start.isoformat(), "status_date": start.isoformat(),
                                                   "skip_weekends": int(skip)})
                if copy_from:
                    idmap = {}
                    for r in db.table_df(conn, "tasks", "project_id=?", [copy_from]).itertuples():
                        idmap[r.id] = db.insert(conn, "tasks", {
                            "project_id": pid, "wbs": r.wbs, "name": r.name, "duration": r.duration,
                            "discipline": r.discipline, "equipment_id": None if r.equipment_id != r.equipment_id else r.equipment_id,
                            "notes": r.notes, "percent_complete": 0})
                    for r in db.table_df(conn, "dependencies", "project_id=?", [copy_from]).itertuples():
                        db.insert(conn, "dependencies", {"project_id": pid, "pred_id": idmap[r.pred_id],
                                                         "succ_id": idmap[r.succ_id], "dep_type": r.dep_type, "lag": r.lag})
                    for r in db.table_df(conn, "assignments", "project_id=?", [copy_from]).itertuples():
                        db.insert(conn, "assignments", {"project_id": pid, "task_id": idmap[r.task_id],
                                                        "resource_id": r.resource_id, "units": r.units})
                st.session_state["project_id"] = pid
                flash(f"'{name}' 프로젝트를 만들었습니다.")
                st.rerun()

with tab3:
    st.markdown("#### 백업 (JSON 내려받기)")
    st.caption("Streamlit Community Cloud 같은 무료 호스팅은 앱이 재시작되면 DB가 초기화될 수 있습니다. "
               "실습 결과는 수시로 백업 파일로 내려받아 보관하세요.")
    st.download_button("⬇️ 전체 데이터 백업", db.export_json(conn).encode("utf-8"),
                       file_name=f"maint-planner-backup-{date.today():%Y%m%d}.json", mime="application/json")
    st.markdown("#### 복원 (JSON 올리기)")
    up = st.file_uploader("백업 파일 선택", type=["json"])
    if up and st.button("복원 실행 (현재 데이터 교체)", type="primary"):
        try:
            db.import_json(conn, up.read().decode("utf-8"))
            st.session_state["project_id"] = None
            flash("백업에서 복원했습니다.")
            st.rerun()
        except Exception as e:  # noqa: BLE001
            st.error(f"복원 실패: {e}")
    st.markdown("#### 초기화")
    with st.popover("🔄 예제 데이터로 초기화"):
        st.warning("현재 모든 데이터를 지우고 예제 데이터(공장 정기보수)를 다시 만듭니다.")
        if st.button("초기화 실행", type="primary"):
            db.clear_all(conn)
            sample_data.load_sample(conn)
            st.session_state["project_id"] = None
            flash("예제 데이터로 초기화했습니다.")
            st.rerun()
    with st.popover("🧹 빈 데이터로 시작"):
        st.warning("모든 데이터를 지웁니다.")
        if st.button("모두 삭제", type="primary"):
            db.clear_all(conn)
            st.session_state["project_id"] = None
            flash("모든 데이터를 삭제했습니다.")
            st.rerun()
