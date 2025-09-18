import streamlit as st
from db import get_user, register_user, get_companies, insert_task, get_tasks, get_tasks_by_user, update_task_status

# 세션 상태 초기화
if "page" not in st.session_state:
    st.session_state.page = "login"
if "user" not in st.session_state:
    st.session_state.user = None

# ---------------------------
# 로그인 페이지
# ---------------------------
if st.session_state.page == "login":
    st.title("🔐 로그인")

    username = st.text_input("아이디")
    password = st.text_input("비밀번호", type="password")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("로그인"):
            user = get_user(username, password)
            if user:
                st.session_state.user = user
                st.session_state.page = "main"
                st.rerun()
            else:
                st.error("❌ 아이디 또는 비밀번호가 올바르지 않습니다.")

    with col2:
        if st.button("회원가입"):
            st.session_state.page = "register"
            st.rerun()

# ---------------------------
# 회원가입 페이지
# ---------------------------
elif st.session_state.page == "register":
    st.title("📝 회원가입")

    username = st.text_input("아이디")
    password = st.text_input("비밀번호", type="password")
    company_name = st.text_input("회사명")
    company_code = st.text_input("회사 코드")
    role = st.radio("역할 선택", ["대표", "직원"], horizontal=True)
    role_value = "admin" if role == "대표" else "employee"
    
    if st.button("가입하기"):
        ok, msg = register_user(username, password, company_name, company_code, role_value)
        if ok:
            st.success(msg)
            st.session_state.page = "login"
            st.rerun()
        else:
            st.error(msg)

    if st.button("⬅ 로그인으로 돌아가기"):
        st.session_state.page = "login"
        st.rerun()

# ---------------------------
# 메인 페이지
# ---------------------------
elif st.session_state.page == "main":
    user = st.session_state.user
    st.title("🏢 메인 업무 기반 챗봇")

    st.write(f"환영합니다, {user['username']} 님! (역할: {user['role']})")

    # ------------------------
    # 직원 UI
    # ------------------------
    if user["role"] == "employee":
        st.subheader("📌 새 요청 작성")
        title = st.text_input("제목")
        desc = st.text_area("설명")
        due = st.date_input("마감일", value=date.today())

        if st.button("요청 제출"):
            insert_task(title, desc, due, user["id"])
            st.success("✅ 요청이 제출되었습니다!")
            st.rerun()

        st.subheader("내 요청 현황")
        my_tasks = get_tasks_by_user(user["id"])
        if not my_tasks:
            st.info("아직 요청이 없습니다.")
        else:
            for t in my_tasks:
                st.write(f"- {t['title']} | 상태: {t['status']}")

    # ------------------------
    # 대표님 UI
    # ------------------------
    elif user["role"] == "ceo":
        st.subheader("📌 들어온 요청 확인")
        all_tasks = get_tasks(user["company_id"])
        if not all_tasks:
            st.info("아직 요청이 없습니다.")
        else:
            for t in all_tasks:
                with st.container():
                    st.write(f"**제목:** {t['title']}")
                    st.write(f"설명: {t['description']}")
                    st.write(f"마감일: {t['due_date']}")
                    st.write(f"작성자: {t['created_by']}")
                    st.write(f"상태: {t['status']}")

                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("승인", key=f"approve_{t['id']}"):
                            update_task_status(t["id"], "approved")
                            st.success(f"✅ '{t['title']}' 승인됨")
                            st.rerun()
                    with col2:
                        if st.button("거절", key=f"reject_{t['id']}"):
                            update_task_status(t["id"], "rejected")
                            st.warning(f"❌ '{t['title']}' 거절됨")
                            st.rerun()

    # ------------------------
    # 로그아웃
    # ------------------------
    if st.button("로그아웃"):
        st.session_state.user = None
        st.session_state.page = "login"
        st.rerun()