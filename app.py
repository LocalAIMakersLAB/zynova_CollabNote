import streamlit as st
import time, json
from db import register_profile, login_profile
from mypages import inbox, compose, rejected_requests, dashboard 

# PAGES = {
#     # 이제 compose는 라우팅에 포함시키지 않습니다.
#     "대표 승인함 (/inbox)": inbox,
#     "직원 문서 작성 (/compose)": compose,
#     "반려된 문서 (/rejected)": rejected_requests
#     # "대시보드 (/dashboard)": dashboard
# }


# 세션 초기화
if "page" not in st.session_state:
    st.session_state.page = "login"
if "user" not in st.session_state:
    st.session_state.user = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "filled_fields" not in st.session_state:
    st.session_state.filled_fields = {}
if "is_confirmed" not in st.session_state:
    st.session_state.is_confirmed = False
if "current_draft_id" not in st.session_state:
    st.session_state.current_draft_id = None
if "confirm_text" not in st.session_state:
    st.session_state.confirm_text = ""
    
# 로그인 상태에 따라 페이지를 보여주는 함수
def show_login():
    st.title("🔐 로그인")
    email = st.text_input("이메일")
    pw = st.text_input("비밀번호", type="password")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("로그인"):
            user = login_profile(email, pw)
            if user:
                st.session_state.user = user
                st.session_state.page = "main"
                st.rerun()
            else:
                st.error("이메일/비밀번호가 올바르지 않습니다.")
    with c2:
        if st.button("회원가입으로"):
            st.session_state.page = "register"
            st.rerun()

def show_register():
    st.title("📝 회원가입")
    name  = st.text_input("이름")
    email = st.text_input("이메일")
    role  = st.radio("역할", ["대표(rep)", "직원(staff)"], horizontal=True)
    role_value = "rep" if "대표" in role else "staff"
    pw = st.text_input("비밀번호", type="password")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("가입"):
            ok, msg = register_profile(name, email, role_value, pw)
            if ok:
                st.success(msg)
                st.session_state.page = "login"
                st.rerun()
            else:
                st.error(msg)
    with c2:
        if st.button("로그인으로"):
            st.session_state.page = "login"
            st.rerun()
            
def show_main():
    user = st.session_state.user
    
    st.sidebar.title("메뉴")
    
    # 대표(rep)만 볼 수 있는 메뉴
    if user['role'] == 'rep':
        page = st.sidebar.radio("대표 메뉴", ("📬 승인함", "📊 대시보드"))
        if page == "📬 승인함":
            st.sidebar.info("대표님용 문서 승인 처리 페이지입니다.")
            inbox.app(user)
        else:
            dashboard.app(user)
            st.sidebar.info("대표님용 문서 후속 처리 대시보드 페이지입니다.")

    else:
        # 직원은 사이드바 메뉴로 페이지 선택
        st.sidebar.info("직원용 문서 업무 페이지입니다.")
        
        selected_page = st.sidebar.radio(
            "메뉴를 선택해주세요.",
            ("📝 새 문서 요청", "❌ 반려된 문서")
        )
        
        if selected_page == "📝 새 문서 요청":
            compose.run_compose_page(st.session_state.user)
        elif selected_page == "❌ 반려된 문서":
            rejected_requests.run_rejected_requests_page(st.session_state.user)

    if st.sidebar.button("로그아웃"):
        st.session_state.user = None
        st.session_state.page = "login"
        st.rerun()

# --------- 엔트리 분기 ---------
if st.session_state.page == "login" and not st.session_state.user:
    show_login()
elif st.session_state.page == "register" and not st.session_state.user:
    show_register()
else:
    if not st.session_state.user:
        st.session_state.page = "login"
        st.rerun()
    show_main()
