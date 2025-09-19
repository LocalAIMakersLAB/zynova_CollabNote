import streamlit as st
import pages.compose as compose

# 세션 초기화
if "user" not in st.session_state:
    st.session_state.user = None  # 로그인 전이면 None

PAGES = {
    "직원 문서 작성 (/compose)": compose,
}

st.sidebar.title("메뉴")
choice = st.sidebar.radio("이동", list(PAGES.keys()))

page = PAGES[choice]
page.app(st.session_state.user)  # ✅ user 인자 넘깁니다.
