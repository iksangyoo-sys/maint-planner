"""화면 공통 도우미: DB 연결, 현재 프로젝트, 일정 계산 캐시, 표시 형식."""
from __future__ import annotations

import sqlite3
from datetime import date

import pandas as pd
import streamlit as st

from core import db, sample_data, service
from core.scheduler import CycleError

DISCIPLINES = ["공통", "전기", "기계", "계장", "토목·건축", "안전"]
EQ_DISCIPLINES = ["전기", "기계", "계장", "유틸리티"]
CRITICALITY = ["A", "B", "C"]
EQ_STATUS = ["가동", "정지", "정비중", "예비", "폐기"]
RTYPES = ["인력", "장비", "자재"]
WO_TYPES = ["예방정비(PM)", "예측정비(PdM)", "사후정비(BM)", "개량정비(CM)", "점검"]
PRIORITIES = ["긴급", "높음", "보통", "낮음"]
WO_STATUS = ["요청", "승인", "진행중", "보류", "완료", "취소"]


@st.cache_resource
def _conn(path: str) -> sqlite3.Connection:
    conn = db.connect(path)
    db.init_db(conn)
    if db.is_empty(conn):
        sample_data.load_sample(conn)
    return conn


def get_conn() -> sqlite3.Connection:
    conn = _conn(str(db.db_path()))
    if not db.TABLE_COLUMNS:
        db.init_db(conn)
    return conn


def projects_df() -> pd.DataFrame:
    return db.table_df(get_conn(), "projects")


def project_selector() -> None:
    pdf = projects_df()
    if pdf.empty:
        st.info("프로젝트가 없습니다. '프로젝트·데이터 설정'에서 만드세요.")
        st.session_state["project_id"] = None
        return
    ids = pdf["id"].astype(int).tolist()
    names = dict(zip(ids, pdf["name"]))
    cur = st.session_state.get("project_id")
    if cur not in ids:
        cur = ids[0]
    st.session_state["project_id"] = st.selectbox(
        "📁 프로젝트", ids, index=ids.index(cur), format_func=lambda i: names[i])


def current_project() -> dict | None:
    pid = st.session_state.get("project_id")
    if not pid:
        return None
    return service.get_project(get_conn(), int(pid))


def require_project() -> dict:
    p = current_project()
    if not p:
        st.warning("먼저 왼쪽에서 프로젝트를 선택하거나 '프로젝트·데이터 설정'에서 새로 만드세요.")
        st.stop()
    return p


def load_schedule(project_id: int):
    """일정 계산. 순환 관계 등 오류가 있으면 안내 후 중단."""
    conn = get_conn()
    try:
        return service.build_schedule(conn, project_id)
    except CycleError as e:
        tasks = db.table_df(conn, "tasks", "project_id=?", [project_id])
        names = tasks.set_index("id")
        lst = ", ".join(f"{names.loc[i, 'wbs']} {names.loc[i, 'name']}" for i in e.task_ids if i in names.index)
        st.error(f"선후행 관계에 순환(되돌아가는 연결)이 있어 일정을 계산할 수 없습니다. "
                 f"'선후행 관계' 화면에서 다음 작업 관련 연결을 확인하세요: {lst}")
        st.stop()
    except ValueError as e:
        st.error(f"일정 계산 오류: {e}")
        st.stop()


def to_date_col(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    df = df.copy()
    for c in cols:
        if c in df.columns:
            df[c] = [service.to_date(v) for v in df[c]]
            df[c] = df[c].astype("object")
    return df


def id_map(table: str, label_cols: tuple[str, ...], where: str = "", params=()) -> dict[int, str]:
    df = db.table_df(get_conn(), table, where, params)
    return {int(r["id"]): " ".join(str(r[c]) for c in label_cols) for _, r in df.iterrows()}


def label_to_id(series: pd.Series, mapping: dict[int, str]) -> list:
    rev = {v: k for k, v in mapping.items()}
    return [rev.get(v) if isinstance(v, str) else None for v in series]


def won(x: float | None) -> str:
    if x is None or pd.isna(x):
        return "-"
    return f"{x:,.0f}원"


def fmt_date(d: date | None) -> str:
    return d.strftime("%Y-%m-%d") if d else "-"


def flash(msg: str) -> None:
    st.session_state["_flash"] = msg


def show_flash() -> None:
    msg = st.session_state.pop("_flash", None)
    if msg:
        st.success(msg)
