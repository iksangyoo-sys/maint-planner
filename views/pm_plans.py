from datetime import date

import pandas as pd
import streamlit as st

from core import db, service
from views.common import WO_TYPES, flash, get_conn, id_map, label_to_id, show_flash, to_date_col

st.title("🗓️ 예방정비 계획")
st.caption("설비별 정기 점검·정비 항목과 주기를 관리합니다. 다음 예정일 = 최근 실시일 + 주기. "
           "기한이 다가온 항목은 버튼 한 번으로 작업지시를 발행할 수 있습니다.")
show_flash()
conn = get_conn()
eq_map = id_map("equipment", ("code", "name"))
rmap = id_map("resources", ("name",))
if not eq_map:
    st.info("설비대장에 설비를 먼저 등록하세요.")
    st.stop()

tab1, tab2 = st.tabs(["📅 도래 현황", "✏️ 계획 편집"])
with tab1:
    today = st.date_input("기준 날짜", value=date.today())
    due = service.pm_due_frame(conn, today)
    if due.empty:
        st.info("등록된 예방정비 계획이 없습니다.")
    else:
        c = st.columns(3)
        c[0].metric("기한초과", f"{int((due['상태'] == '기한초과').sum())}건")
        c[1].metric("7일 이내 도래", f"{int((due['상태'] == '임박').sum())}건")
        c[2].metric("정상", f"{int((due['상태'] == '정상').sum())}건")
        show = due.sort_values("남은일수")[["eq_code", "eq_name", "criticality", "name", "pm_type", "interval_days",
                                            "last_done", "다음예정일", "남은일수", "상태", "resource"]]
        show.columns = ["설비코드", "설비명", "중요도", "정비항목", "유형", "주기(일)", "최근실시", "다음예정일", "남은일수", "상태", "담당"]
        color = {"기한초과": "background:#fee2e2", "임박": "background:#fef9c3", "정상": ""}
        st.dataframe(show.style.apply(lambda r: [color[r["상태"]]] * len(r), axis=1),
                     hide_index=True, use_container_width=True)

        st.markdown("##### 🧾 작업지시 자동 발행")
        h = st.slider("며칠 이내 도래 항목까지 발행할까요?", 0, 60, 14)
        if st.button("작업지시 발행", type="primary"):
            created = service.generate_pm_work_orders(conn, h, today)
            flash(f"작업지시 {len(created)}건을 발행했습니다: {', '.join(created)}" if created
                  else "새로 발행할 항목이 없습니다. (이미 미결 작업지시가 있는 항목은 제외)")
            st.rerun()
        st.caption("작업지시가 '완료' 처리되면 해당 계획의 최근 실시일이 자동으로 갱신됩니다.")

        st.markdown("##### 📆 향후 90일 예방정비 달력")
        rows = []
        for r in due.itertuples():
            if not r.active or not r.interval_days:
                continue
            d = r.다음예정일
            while (d - today).days <= 90:
                rows.append({"날짜": d, "설비": r.eq_code, "항목": r.name})
                d = d + pd.Timedelta(days=int(r.interval_days)).to_pytimedelta()
        if rows:
            import plotly.express as px
            cal = pd.DataFrame(rows)
            fig = px.scatter(cal, x="날짜", y="설비", hover_name="항목", color="설비", symbol_sequence=["diamond"])
            fig.update_traces(marker=dict(size=13))
            fig.update_layout(height=320, showlegend=False, plot_bgcolor="white",
                              margin=dict(l=10, r=10, t=10, b=10), xaxis=dict(tickformat="%m/%d"))
            st.plotly_chart(fig, use_container_width=True)

with tab2:
    pm = db.table_df(conn, "pm_plans")
    v = to_date_col(pm, ["last_done"])
    v["equipment"] = [eq_map.get(int(x)) for x in v["equipment_id"]]
    v["resource"] = [rmap.get(int(x)) if pd.notna(x) else None for x in v["resource_id"]]
    v["active"] = v["active"].fillna(1).astype(bool)
    ed = st.data_editor(
        v[["id", "equipment", "name", "pm_type", "interval_days", "last_done", "est_hours", "resource", "checklist", "active"]],
        num_rows="dynamic", hide_index=True, use_container_width=True, key="pm_editor",
        column_config={
            "id": None,
            "equipment": st.column_config.SelectboxColumn("설비", options=list(eq_map.values()), required=True),
            "name": st.column_config.TextColumn("정비 항목", required=True, width="medium"),
            "pm_type": st.column_config.SelectboxColumn("유형", options=WO_TYPES, default="예방정비(PM)"),
            "interval_days": st.column_config.NumberColumn("주기(일)", min_value=1, step=1, default=30),
            "last_done": st.column_config.DateColumn("최근 실시일", format="YYYY-MM-DD"),
            "est_hours": st.column_config.NumberColumn("예상 공수(h)", min_value=0.0, step=0.5, default=1.0),
            "resource": st.column_config.SelectboxColumn("담당", options=list(rmap.values())),
            "checklist": st.column_config.TextColumn("점검 내용(체크리스트)", width="large"),
            "active": st.column_config.CheckboxColumn("사용", default=True),
        },
    )
    if st.button("💾 저장", type="primary"):
        e = ed.dropna(subset=["equipment", "name"]).copy()
        e["equipment_id"] = label_to_id(e["equipment"], eq_map)
        e["resource_id"] = label_to_id(e["resource"], rmap)
        e["active"] = e["active"].fillna(True).astype(int)
        e["interval_days"] = e["interval_days"].fillna(30)
        n = db.sync_table(conn, "pm_plans", e.drop(columns=["equipment", "resource"]), pm["id"])
        flash(f"예방정비 계획을 저장했습니다. (추가 {n[0]} · 수정 {n[1]} · 삭제 {n[2]})")
        st.rerun()
    st.caption("주기 예시: 일상점검 1일, 주간점검 7일, 월간 30일, 분기 90일, 반기 180일, 연간 365일")
