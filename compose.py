# compose.py
import streamlit as st
import json
from db import get_templates, create_draft, submit_draft
from potens_client import generate_questions, generate_confirm_text

def app():
    st.title("문서 작성 (/compose)")

    # --------------------------
    # 1) 템플릿 선택
    # --------------------------
    templates = get_templates()
    template_types = [t["type"] for t in templates]
    selected_type = st.selectbox("문서 유형 선택", template_types)

    template = next((t for t in templates if t["type"] == selected_type), None)

    if template:
        st.markdown(f"**가이드:** {template['guide_md']}")

    # --------------------------
    # 2) 채팅 UI (카카오톡 스타일)
    # --------------------------
    if "messages" not in st.session_state:
        st.session_state.messages = []
        st.session_state.filled = {}
        st.session_state.missing = []
        st.session_state.confirm_text = ""
        st.session_state.draft_id = None

    # 채팅 메시지 출력
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # --------------------------
    # 3) 입력창
    # --------------------------
    if user_input := st.chat_input("챗봇에게 질문"):
        st.session_state.messages.append({"role": "user", "content": user_input})

        # 질문 처리 (임시 로직: 필수 필드 기반)
        required_fields = template["fields"].get("required", [])

        # 직원 입력 저장
        st.session_state.filled["last_input"] = user_input  

        # Potens API로 누락 필드 확인
        check = generate_questions(template["fields"], st.session_state.filled)
        st.session_state.missing = check["missing_fields"]

        # 챗봇 응답
        if st.session_state.missing:
            ask_msgs = "\n".join([q["question"] for q in check["ask"]])
            reply = f"확인했습니다. 현재 누락 항목은 **{', '.join(st.session_state.missing)}** 입니다.\n\n{ask_msgs}"
        else:
            reply = "모든 필수 항목이 채워졌습니다. 이제 컨펌 텍스트를 생성할까요?"

        st.session_state.messages.append({"role": "assistant", "content": reply})
        st.rerun()

    # --------------------------
    # 4) 컨펌 텍스트 생성
    # --------------------------
    if st.button("컨펌 텍스트 생성"):
        confirm = generate_confirm_text(st.session_state.filled)
        st.session_state.confirm_text = confirm
        st.session_state.messages.append({"role": "assistant", "content": f"컨펌 텍스트를 생성했습니다:\n\n{confirm}"})
        st.rerun()

    # --------------------------
    # 5) 승인 요청 제출 → DB 저장
    # --------------------------
    if st.button("승인요청 제출"):
        if not st.session_state.confirm_text:
            st.warning("먼저 컨펌 텍스트를 생성해주세요.")
        else:
            # Draft 생성
            draft = create_draft(
                creator_id="홍길동-user-id",  # TODO: 로그인 연동
                doc_type=selected_type,
                filled=st.session_state.filled,
                missing=st.session_state.missing,
                confirm_text=st.session_state.confirm_text
            )
            draft_id = draft[0]["draft_id"]
            st.session_state.draft_id = draft_id

            # Approval 생성
            approval = submit_draft(
                draft_id=draft_id,
                title=f"{selected_type} 요청",
                summary="요약 텍스트 (임시)",   # Potens LLM 결과로 대체 가능
                assignee="대표-user-id",       # TODO: 로그인 연동
                due_date="2025-09-30"          # TODO: UI 입력값으로 변경
            )

            st.session_state.messages.append({"role": "assistant", "content": "✅ 승인 요청이 제출되었습니다. 대표에게 전달됩니다."})
            st.success("승인 요청이 제출되었습니다.")
            st.rerun()
