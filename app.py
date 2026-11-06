"""설비정비 일정관리 (maint-planner) - Streamlit 진입점.

실행:  streamlit run app.py
"""
import streamlit as st

st.set_page_config(page_title="설비정비 일정관리", page_icon="🛠️", layout="wide")

from views.common import get_conn, project_selector  # noqa: E402

get_conn()  # DB 초기화 (처음 실행 시 예제 데이터 자동 생성)

pages = {
    "현황": [
        st.Page("views/dashboard.py", title="대시보드", icon="🏠", default=True),
    ],
    "프로젝트 일정 (정기보수·공사)": [
        st.Page("views/tasks.py", title="작업·WBS", icon="📋"),
        st.Page("views/dependencies.py", title="선후행 관계", icon="🔗"),
        st.Page("views/gantt.py", title="간트차트", icon="📊"),
        st.Page("views/cpm.py", title="주공정(CPM)", icon="🛤️"),
        st.Page("views/resources.py", title="자원 배정·부하", icon="👷"),
        st.Page("views/progress.py", title="진척관리", icon="📈"),
    ],
    "설비 정비": [
        st.Page("views/equipment.py", title="설비대장", icon="⚙️"),
        st.Page("views/pm_plans.py", title="예방정비 계획", icon="🗓️"),
        st.Page("views/work_orders.py", title="작업지시", icon="🧾"),
    ],
    "관리": [
        st.Page("views/reports.py", title="보고서", icon="📑"),
        st.Page("views/settings.py", title="프로젝트·데이터 설정", icon="🛠️"),
        st.Page("views/help.py", title="사용 안내", icon="❓"),
    ],
}

nav = st.navigation(pages, expanded=True)
with st.sidebar:
    project_selector()
    st.caption("학생 실습용 · 비상업적 사용")
nav.run()
