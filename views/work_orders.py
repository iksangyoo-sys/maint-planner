from datetime import date

import pandas as pd
import streamlit as st

from core import db, service
from views.common import (
    PRIORITIES, WO_STATUS, WO_TYPES, flash, get_conn, id_map, label_to_id, show_flash, to_date_col,
)

st.title("🧾 작업지시 (Work Order)")
st.caption("요청 → 승인 → 진행중 → 완료 순으로 처리합니다. 고장 수리(사후정비), 예방정비, 개량정비, 점검 작업을 모두 관리합니다.")
show_flash()
conn = get_conn()
eq_map = id_map("equipment", ("code", "name"))
rmap = id_map("resources", ("name",))
wo = db.table_df(conn, "work_orders")

tab1, tab2, tab3 = st.tabs(["📋 목록·편집", "➕ 새 작업지시", "✅ 완료 처리"])

with tab1:
    f = st.columns(4)
    fs = f[0].multiselect("상태", WO_STATUS, default=["요청", "승인", "진행중", "보류"])
    ft = f[1].multiselect("유형", WO_TYPES)
    fp = f[2].multiselect("우선순위", PRIORITIES)
    fe = f[3].multiselect("설비", list(eq_map.values()))
    v = to_date_col(wo, ["requested_date", "due_date", "completed_date"])
    v["equipment"] = [eq_map.get(int(x)) if pd.notna(x) else None for x in v["equipment_id"]]
    v["resource"] = [rmap.get(int(x)) if pd.notna(x) else None for x in v["resource_id"]]
    m = pd.Series(True, index=v.index)
    if fs:
        m &= v["status"].isin(fs)
    if ft:
        m &= v["wo_type"].isin(ft)
    if fp:
        m &= v["priority"].isin(fp)
    if fe:
        m &= v["equipment"].isin(fe)
    v = v[m].copy()
    today = date.today()
    v["지연"] = [bool(d and d < today and s not in ("완료", "취소")) for d, s in zip(v["due_date"], v["status"])]
    pri_order = {p: i for i, p in enumerate(PRIORITIES)}
    v = v.sort_values(by=["status", "priority"], key=lambda c: c.map(pri_order) if c.name == "priority" else c.map(
        {s: i for i, s in enumerate(WO_STATUS)}))
    st.caption(f"{len(v)}건 표시 · 🔴 지연 {int(v['지연'].sum())}건")
    ed = st.data_editor(
        v[["id", "wo_no", "지연", "title", "equipment", "wo_type", "priority", "status", "requested_date", "due_date",
           "resource", "est_hours", "actual_hours", "description"]],
        hide_index=True, use_container_width=True, key="wo_editor", disabled=["wo_no", "지연"],
        column_config={
            "id": None,
            "wo_no": "작업지시번호",
            "지연": st.column_config.CheckboxColumn("지연"),
            "title": st.column_config.TextColumn("제목", width="medium", required=True),
            "equipment": st.column_config.SelectboxColumn("설비", options=list(eq_map.values())),
            "wo_type": st.column_config.SelectboxColumn("유형", options=WO_TYPES),
            "priority": st.column_config.SelectboxColumn("우선순위", options=PRIORITIES),
            "status": st.column_config.SelectboxColumn("상태", options=WO_STATUS),
            "requested_date": st.column_config.DateColumn("요청일", format="YYYY-MM-DD"),
            "due_date": st.column_config.DateColumn("완료기한", format="YYYY-MM-DD"),
            "resource": st.column_config.SelectboxColumn("담당", options=list(rmap.values())),
            "est_hours": st.column_config.NumberColumn("예상공수(h)", min_value=0.0, step=0.5),
            "actual_hours": st.column_config.NumberColumn("실적공수(h)", min_value=0.0, step=0.5),
            "description": st.column_config.TextColumn("작업 내용", width="large"),
        },
    )
    c1, c2 = st.columns([1, 3])
    if c1.button("💾 변경 저장", type="primary"):
        for r in ed.itertuples():
            db.update(conn, "work_orders", int(r.id), {
                "title": r.title, "equipment_id": label_to_id(pd.Series([r.equipment]), eq_map)[0],
                "wo_type": r.wo_type, "priority": r.priority, "status": r.status,
                "requested_date": r.requested_date, "due_date": r.due_date,
                "resource_id": label_to_id(pd.Series([r.resource]), rmap)[0],
                "est_hours": r.est_hours, "actual_hours": r.actual_hours, "description": r.description,
                **({"completed_date": today.isoformat()}
                   if r.status == "완료" and pd.isna(wo.set_index("id").loc[int(r.id), "completed_date"]) else {}),
            })
        flash("작업지시를 저장했습니다.")
        st.rerun()
    with c2.popover("🗑️ 작업지시 삭제"):
        if not v.empty:
            del_id = st.selectbox("삭제할 작업지시", v["id"].tolist(),
                                  format_func=lambda i: f"{v.set_index('id').loc[i, 'wo_no']} {v.set_index('id').loc[i, 'title']}")
            if st.button("삭제", type="secondary"):
                db.delete(conn, "work_orders", int(del_id))
                flash("삭제했습니다.")
                st.rerun()

with tab2:
    with st.form("new_wo", clear_on_submit=True):
        st.markdown(f"작업지시번호: **{service.next_wo_no(conn)}** (자동)")
        a, b = st.columns(2)
        title = a.text_input("제목 *", placeholder="예) 냉각수펌프 이상진동 점검")
        eqid = b.selectbox("대상 설비", [None] + list(eq_map), format_func=lambda i: "선택 안 함" if i is None else eq_map[i])
        c, d, e = st.columns(3)
        typ = c.selectbox("유형", WO_TYPES, index=2)
        pri = d.selectbox("우선순위", PRIORITIES, index=2)
        res = e.selectbox("담당", [None] + list(rmap), format_func=lambda i: "미지정" if i is None else rmap[i])
        g, h, k = st.columns(3)
        req = g.date_input("요청일", value=date.today())
        due = h.date_input("완료기한", value=date.today())
        est = k.number_input("예상공수(h)", min_value=0.0, step=0.5, value=2.0)
        projs = db.table_df(conn, "projects")
        pj = {int(r.id): r.name for r in projs.itertuples()}
        link = st.selectbox("연결 프로젝트(선택)", [None] + list(pj), format_func=lambda i: "없음" if i is None else pj[i])
        desc = st.text_area("작업 내용 / 고장 현상")
        if st.form_submit_button("작업지시 등록", type="primary"):
            if not title:
                st.error("제목을 입력하세요.")
            else:
                no = service.next_wo_no(conn)
                db.insert(conn, "work_orders", {
                    "wo_no": no, "title": title, "equipment_id": eqid, "wo_type": typ, "priority": pri,
                    "status": "요청", "requested_date": req, "due_date": due, "resource_id": res,
                    "est_hours": est, "project_id": link, "description": desc,
                })
                flash(f"작업지시 {no} 를 등록했습니다.")
                st.rerun()

with tab3:
    opn = wo[~wo["status"].isin(["완료", "취소"])]
    if opn.empty:
        st.info("미결 작업지시가 없습니다.")
    else:
        sel = st.selectbox("완료할 작업지시", opn["id"].tolist(),
                           format_func=lambda i: f"{opn.set_index('id').loc[i, 'wo_no']} · {opn.set_index('id').loc[i, 'title']}")
        row = opn.set_index("id").loc[sel]
        st.write(f"설비: {eq_map.get(int(row['equipment_id'])) if pd.notna(row['equipment_id']) else '-'} · "
                 f"유형: {row['wo_type']} · 예상공수: {row['est_hours']}h")
        if row["description"]:
            st.info(row["description"])
        a, b = st.columns(2)
        done = a.date_input("완료일", value=date.today(), key="done_date")
        hrs = b.number_input("실적공수(h)", min_value=0.0, step=0.5, value=0.0 if pd.isna(row["est_hours"]) else float(row["est_hours"]), key="done_hrs")
        result = st.text_area("조치 결과", placeholder="예) 베어링(6312ZZ) 교체, 진동 2.1mm/s 로 정상화")
        if st.button("✅ 완료 처리", type="primary"):
            service.complete_work_order(conn, int(sel), done, hrs, result)
            flash("완료 처리했습니다." + (" 예방정비 계획의 최근 실시일도 갱신했습니다." if pd.notna(row["pm_plan_id"]) else ""))
            st.rerun()

st.divider()
if not wo.empty:
    done = wo[wo["status"] == "완료"]
    c = st.columns(4)
    c[0].metric("전체", f"{len(wo)}건")
    c[1].metric("완료", f"{len(done)}건")
    c[2].metric("실적 공수 합계", f"{done['actual_hours'].fillna(0).sum():g} h")
    pm_ratio = wo["wo_type"].isin(["예방정비(PM)", "예측정비(PdM)", "점검"]).mean() * 100
    c[3].metric("계획정비 비율", f"{pm_ratio:.0f}%", help="예방·예측정비·점검이 전체 작업지시에서 차지하는 비율. 높을수록 좋음")
