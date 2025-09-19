# app.py
import streamlit as st
import time, json
from db import register_profile, login_profile
from mypages import compose, inbox, dashboard

PAGES = {
    "직원 문서 작성 (/compose)": compose,
    "대표 승인함 (/inbox)": inbox,
    "대시보드 (/dashboard)": dashboard,
}

# 세션 초기화
if "page" not in st.session_state:
    st.session_state.page = "login"
if "user" not in st.session_state:
    st.session_state.user = None

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
    st.title("시스템 상태 / 진단")
    with st.expander("🔎 LLM 연결 자가진단", expanded=False):
        if st.button("자가진단 실행"):
            llm_self_test()  # 버튼 클릭 시점에 호출되므로 함수가 파일 하단에 있어도 OK

    st.sidebar.title("메뉴")
    choice = st.sidebar.radio("이동", list(PAGES.keys()))
    page = PAGES[choice]
    page.app(st.session_state.user)  # ✅ 여기서만 페이지 렌더

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

# --------- 유틸: LLM 자가진단 ---------
def llm_self_test():
    st.subheader("LLM 연결 자가진단")
    t0 = time.time()
    try:
        test_fields = {"required": ["amount", "reason", "due"]}
        test_filled = {"reason": "테스트 비용", "due": "2025-09-30"}
        res_q = generate_questions(test_fields, test_filled)
        dt_q = (time.time() - t0) * 1000

        t1 = time.time()
        res_c = generate_confirm_text({"amount":"1200000","reason":"장비 구입","due":"2025-09-30"})
        dt_c = (time.time() - t1) * 1000

        st.success(f"질문 생성 OK ({dt_q:.0f} ms) → missing={res_q.get('missing_fields')}")
        st.success(f"컨펌 생성 OK ({dt_c:.0f} ms)")
        with st.expander("raw 출력 확인"):
            st.code(json.dumps(res_q, ensure_ascii=False, indent=2))
            st.markdown(res_c)
        return True
    except Exception as e:
        st.error(f"LLM 테스트 실패: {e}")
        st.info("APP_MODE=mock 로 전환해 UI/DB 흐름만 먼저 확인할 수 있어요.")
        return False
