import pandas as pd
import streamlit as st

from core import db, service
from core.scheduler import wbs_key
from views.common import (
    DISCIPLINES, flash, get_conn, id_map, label_to_id, load_schedule, require_project, show_flash, to_date_col,
)

st.title("📋 작업·WBS")
st.caption("WBS 번호로 계층을 만듭니다. 예) 2 = 요약 작업, 2.1 · 2.2 = 하위 작업. "
           "하위 작업이 있는 작업은 자동으로 '요약 작업'이 되어 기간이 하위 작업에서 계산됩니다. "
           "기간 0 = 마일스톤.")
show_flash()
conn = get_conn()
p = require_project()
pid = p["id"]

tasks = db.table_df(conn, "tasks", "project_id=?", [pid])
tasks = tasks.iloc[sorted(range(len(tasks)), key=lambda i: wbs_key(tasks.iloc[i]["wbs"]))] if not tasks.empty else tasks
eq_map = id_map("equipment", ("code", "name"))
summ = service.summary_ids(tasks) if not tasks.empty else set()

view = tasks.copy()
view["equipment"] = [eq_map.get(int(x)) if pd.notna(x) else None for x in view["equipment_id"]]
view["구분"] = ["요약" if int(i) in summ else ("마일스톤" if (d or 0) == 0 else "작업")
               for i, d in zip(view["id"], view["duration"])]
view = to_date_col(view, ["constraint_start"])
cols = ["id", "wbs", "name", "구분", "duration", "discipline", "equipment", "constraint_start", "percent_complete", "notes"]

tab1, tab2 = st.tabs(["✏️ 작업 편집", "📅 계산된 일정"])
with tab1:
    edited = st.data_editor(
        view[cols], num_rows="dynamic", hide_index=True, use_container_width=True, key=f"task_editor_{pid}",
        column_config={
            "id": None,
            "wbs": st.column_config.TextColumn("WBS", required=True, width="small"),
            "name": st.column_config.TextColumn("작업명", required=True, width="large"),
            "구분": st.column_config.TextColumn("구분", disabled=True, width="small"),
            "duration": st.column_config.NumberColumn("기간(작업일)", min_value=0, step=1, default=1),
            "discipline": st.column_config.SelectboxColumn("분야", options=DISCIPLINES, default="공통"),
            "equipment": st.column_config.SelectboxColumn("대상 설비", options=list(eq_map.values())),
            "constraint_start": st.column_config.DateColumn("시작 제약(이후 시작)", format="YYYY-MM-DD"),
            "percent_complete": st.column_config.NumberColumn("진척률(%)", min_value=0, max_value=100, step=5, default=0),
            "notes": st.column_config.TextColumn("비고"),
        },
    )
    c1, c2 = st.columns([1, 4])
    if c1.button("💾 저장", type="primary"):
        e = edited.copy()
        e = e[e["wbs"].notna() & e["name"].notna()]
        e["wbs"] = e["wbs"].astype(str).str.strip()
        dup = e["wbs"][e["wbs"].duplicated()].tolist()
        if dup:
            st.error(f"WBS 번호가 중복되었습니다: {', '.join(dup)}")
        else:
            e["equipment_id"] = label_to_id(e["equipment"], eq_map)
            e["duration"] = e["duration"].fillna(1)
            e["percent_complete"] = e["percent_complete"].fillna(0)
            e["discipline"] = e["discipline"].fillna("공통")
            n = db.sync_table(conn, "tasks", e.drop(columns=["equipment", "구분"]), tasks["id"], {"project_id": pid})
            flash(f"저장했습니다. (추가 {n[0]} · 수정 {n[1]} · 삭제 {n[2]})")
            st.rerun()
    c2.caption("행 추가는 표 아래 '+' , 삭제는 행 선택 후 휴지통 아이콘. 변경 후 반드시 [저장]을 누르세요.")

    with st.expander("➕ 정비 작업 템플릿으로 빠르게 추가"):
        templates = {
            "변압기 정기점검": [("절연유 채취·분석", 1, "전기"), ("절연저항·권선저항 측정", 1, "전기"),
                          ("부싱·탭절환기 점검", 1, "전기"), ("냉각장치·보호장치 점검", 1, "전기")],
            "회전기기(펌프/모터) 오버홀": [("LOTO 및 분해", 1, "기계"), ("베어링·씰 교체", 2, "기계"),
                                   ("조립 및 축정렬", 1, "기계"), ("진동측정·시운전", 1, "기계")],
            "수배전반 점검": [("정전 및 접지", 1, "전기"), ("차단기 점검·청소", 1, "전기"),
                        ("보호계전기 시험", 1, "전기"), ("복전 및 부하 확인", 1, "전기")],
            "공기압축기 정비": [("오일·필터 교환", 1, "기계"), ("흡입밸브·언로더 점검", 1, "기계"),
                         ("냉각기 세척", 1, "기계"), ("누설점검·시운전", 1, "기계")],
        }
        tname = st.selectbox("템플릿", list(templates))
        tpl_eq = st.selectbox("대상 설비", [None] + list(eq_map), format_func=lambda i: "선택 안 함" if i is None else eq_map[i])
        if st.button("템플릿 추가 (순차 연결 포함)"):
            tops = [int(str(w).split(".")[0]) for w in tasks["wbs"] if str(w).split(".")[0].isdigit()]
            top = (max(tops) + 1) if tops else 1
            db.insert(conn, "tasks", {"project_id": pid, "wbs": str(top), "name": tname, "duration": 0,
                                      "discipline": templates[tname][0][2], "equipment_id": tpl_eq})
            prev = None
            for k, (nm, d, disc) in enumerate(templates[tname], 1):
                tid = db.insert(conn, "tasks", {"project_id": pid, "wbs": f"{top}.{k}", "name": nm, "duration": d,
                                                "discipline": disc, "equipment_id": tpl_eq})
                if prev:
                    db.insert(conn, "dependencies", {"project_id": pid, "pred_id": prev, "succ_id": tid,
                                                     "dep_type": "FS", "lag": 0})
                prev = tid
            flash(f"'{tname}' 템플릿을 WBS {top} 으로 추가했습니다.")
            st.rerun()

with tab2:
    if tasks.empty:
        st.info("작업을 먼저 입력하세요.")
    else:
        sched, t2, _ = load_schedule(pid)
        sdf = service.schedule_frame(sched, t2)
        show = sdf[["WBS", "작업명", "기간(일)", "시작", "완료", "늦은시작", "늦은완료", "총여유", "주공정", "진척률(%)", "분야"]]
        st.dataframe(
            show.style.apply(lambda r: ["color:#dc2626;font-weight:600" if r["주공정"] else "" for _ in r], axis=1)
                .apply(lambda r: ["background:#f1f5f9;font-weight:700" if sdf.loc[r.name, "요약"] else "" for _ in r], axis=1),
            hide_index=True, use_container_width=True, height=min(800, 38 * len(show) + 40),
            column_config={"시작": st.column_config.DateColumn(format="YYYY-MM-DD"),
                           "완료": st.column_config.DateColumn(format="YYYY-MM-DD"),
                           "늦은시작": st.column_config.DateColumn(format="YYYY-MM-DD"),
                           "늦은완료": st.column_config.DateColumn(format="YYYY-MM-DD")},
        )
        st.caption(f"프로젝트 완료 예정일: **{sched.project_finish:%Y-%m-%d}** · 빨간 글씨 = 주공정 작업")
