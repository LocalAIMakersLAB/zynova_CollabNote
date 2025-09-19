import streamlit as st
import compose
# import inbox, dashboard  # 나중에 추가

PAGES = {
    "직원 문서 작성 (/compose)": compose,
    # "대표 승인함 (/inbox)": inbox,
    # "대시보드 (/dashboard)": dashboard,
}

st.sidebar.title("메뉴")
choice = st.sidebar.radio("이동", list(PAGES.keys()))

page = PAGES[choice]
page.app()
