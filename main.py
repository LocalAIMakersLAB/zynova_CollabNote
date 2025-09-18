from datetime import date
import streamlit as st
from db import get_tasks_for_ceo
import requests, os
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
    
    if st.button("가입하기"):
        ok, msg = register_user(username, password, company_name, company_code, role)
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
    # 대표님 UI (채팅 UI)
    # ------------------------
    elif user["role"] == "ceo":
        st.subheader("💬 오늘 할 일")

    # 세션 상태 초기화 (반드시 먼저!)
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "ceo_tasks_loaded" not in st.session_state:
        st.session_state.ceo_tasks_loaded = False

    from db import get_tasks_for_ceo
    import requests, os

    # Potens 설정 (.env에 넣어둔 키 사용)
    API_KEY = os.getenv("POTENS_API_KEY")
    API_URL = "https://ai.potens.ai/api/chat"

    def call_potens(prompt, max_tokens=60):
        """Potens 호출 (키 없거나 오류 시 더미/에러 문자열 반환)"""
        if not API_KEY:
            # LLM 준비 전 빠른 UI 테스트용 더미 응답
            return "오늘은 출장 보고서 제출과 계약서 승인 확인이 필요합니다."
        try:
            resp = requests.post(
                API_URL,
                headers={"Authorization": f"Bearer {API_KEY}"},
                json={"prompt": prompt, "max_tokens": max_tokens}
            )
            resp.raise_for_status()
            data = resp.json()
            # Potens 응답 구조에 따라 골라서 반환 (일반적인 키 우선순위 처리)
            return data.get("text") or data.get("message") or (data.get("choices") and data["choices"][0].get("text")) or str(data)
        except Exception as e:
            return f"[LLM 호출 에러] {e}"

    # DB에서 오늘 할 일 가져오기
    pending_tasks = get_tasks_for_ceo(user["id"])

    # tasks_str를 항상 정의 (나중 질문 처리 시 필요)
    tasks_str = ""
    if pending_tasks:
        tasks_str = "\n".join([
            f"{i+1}. {t.get('title','(제목없음)')} - {t.get('description','')}, 마감: {t.get('due_date','-')}"
            for i, t in enumerate(pending_tasks)
        ])

    # 한 번만 오늘 할 일 요약을 생성해서 chat_history에 넣음
    if not st.session_state.ceo_tasks_loaded:
        if pending_tasks:
            prompt = f"오늘 대표님이 처리해야 할 pending 업무 목록은 다음과 같습니다:\n{tasks_str}\n\n위 목록을 참고하여 오늘 해야 할 일을 한 문장으로 요약해 주세요."
            summary = call_potens(prompt)
            st.session_state.chat_history.append({"role": "bot", "message": summary})
        else:
            st.session_state.chat_history.append({"role": "bot", "message": "오늘은 처리할 업무가 없습니다."})
        st.session_state.ceo_tasks_loaded = True


    # ------------------------
    #  채팅 UI 렌더링 
    # ------------------------
    for chat in st.session_state.chat_history:
        if chat["role"] == "bot":
            st.markdown(
                f"""
                <div style="display:flex;justify-content:flex-start;margin:8px 0;">
                  <div style="
                    background:#F2F3F5;
                    color:#111;
                    padding:10px 14px;
                    border-radius:16px;
                    border-bottom-left-radius:2px;
                    max-width:70%;
                    word-wrap:break-word;
                    font-size:15px;">
                    {chat['message']}
                  </div>
                </div>
                """,
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                f"""
                <div style="display:flex;justify-content:flex-end;margin:8px 0;">
                  <div style="
                    background:#9FE8A8;
                    color:#000;
                    padding:10px 14px;
                    border-radius:16px;
                    border-bottom-right-radius:2px;
                    max-width:70%;
                    word-wrap:break-word;
                    font-size:15px;">
                    {chat['message']}
                  </div>
                </div>
                """,
                unsafe_allow_html=True
            )

    # ------------------------
    # 질문 입력 처리
    # ------------------------
    if user_input := st.chat_input("챗봇에게 질문"):
        # 사용자 메시지 추가
        st.session_state.chat_history.append({"role": "user", "message": user_input})
    
        # 프롬프트에 DB 목록 포함
        prompt = f"대표님 질문: {user_input}\n\n참고할 업무 목록:\n{tasks_str if tasks_str else '오늘은 업무가 없습니다.'}\n\n위 정보를 기반으로 자연스럽게 답변해 주세요."
        answer = call_potens(prompt)
        st.session_state.chat_history.append({"role": "bot", "message": answer})

        # 입력 후 화면 갱신
        st.rerun()


    # # 2️⃣ 후속 조치 알림
    #     for task in finished_tasks:
    #         prompt = f"{task['title']} 완료, 필요한 후속 조치 안내."
    #         follow_up_msg = call_potens(prompt)
    #         st.session_state.chat_history.append({"role": "bot", "message": follow_up_msg})
    #         mark_follow_up_notified(task["id"])



    # ------------------------
    # 로그아웃
    # ------------------------
    if st.button("로그아웃"):
        st.session_state.user = None
        st.session_state.page = "login"
        st.rerun()