# compose.py (핵심만 발췌)
import streamlit as st
from db import get_templates, create_draft, submit_draft
from potens_client import infer_doc_type_and_fields, generate_questions, generate_confirm_text

def app(user=None):
    if not user:
        st.info("로그인 후 이용해주세요.")
        return

    st.title("문서 작성 (/compose)")

    # 세션 상태
    if "doc_ctx" not in st.session_state:
        st.session_state.doc_ctx = {  # 현재 작성 세션 컨텍스트
            "doc_type": None,
            "required": [],
            "optional": [],
            "guide_md": "",
        }
    if "filled" not in st.session_state:
        st.session_state.filled, st.session_state.missing = {}, []
        st.session_state.confirm_text, st.session_state.draft_id = "", None
        st.session_state.messages = []

    # 대화 표시
    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    # 첫 사용자 발화 → 문서유형/필드 자동 결정
    if utter := st.chat_input("예) '지출 결재 보내야 해. 프로젝트 A, 120만원'"):
        st.session_state.messages.append({"role":"user","content":utter})

        if not st.session_state.doc_ctx["doc_type"]:
            templates = get_templates()
            inferred = infer_doc_type_and_fields(utter, templates)
            st.session_state.doc_ctx.update(inferred)

        # 자유 입력도 메모해 두고
        st.session_state.filled["notes"] = (st.session_state.filled.get("notes","") + "\n" + utter).strip()

        # 누락 검사 (필수만)
        fields_meta = {"required": st.session_state.doc_ctx["required"], "optional": st.session_state.doc_ctx["optional"]}
        check = generate_questions(fields_meta, st.session_state.filled)
        st.session_state.missing = check["missing_fields"]

        if st.session_state.missing:
            ask = "\n".join([q["question"] for q in check["ask"]])
            reply = f"문서 유형: **{st.session_state.doc_ctx['doc_type']}**\n필수 항목: {', '.join(st.session_state.doc_ctx['required'])}\n\n현재 누락: **{', '.join(st.session_state.missing)}**\n{ask}\n\n아래 폼에서 채워주세요."
        else:
            reply = "필수 항목이 모두 채워졌습니다. 컨펌 텍스트를 생성할까요?"
        st.session_state.messages.append({"role":"assistant","content":reply})
        st.rerun()

    # 누락 폼(동적)
    req = st.session_state.doc_ctx["required"]
    miss = [k for k in req if not st.session_state.filled.get(k)]
    if req:
        st.subheader("필수 항목 입력")
        for key in miss:
            st.session_state.filled[key] = st.text_input(key, value=st.session_state.filled.get(key,""))
        if miss and st.button("필수 항목 저장"):
            st.success("저장됨")
            st.rerun()

    # 컨펌 텍스트
    if st.button("컨펌 텍스트 생성"):
        st.session_state.confirm_text = generate_confirm_text(st.session_state.filled, st.session_state.doc_ctx.get("guide_md",""))
        st.session_state.messages.append({"role":"assistant", "content": f"컨펌 텍스트 생성:\n\n{st.session_state.confirm_text}"})
        st.rerun()

    # 승인요청 제출
    if st.button("승인요청 제출"):
        if not st.session_state.confirm_text:
            st.warning("먼저 컨펌 텍스트를 생성하세요.")
            return

        draft = create_draft(
            creator_id=user["user_id"],
            doc_type=st.session_state.doc_ctx["doc_type"] or "기타",
            filled=st.session_state.filled,
            missing=[k for k in req if not st.session_state.filled.get(k)],
            confirm_text=st.session_state.confirm_text
        )
        draft_id = draft[0]["draft_id"]; st.session_state.draft_id = draft_id

        # 대표 할당: 로그인된 회사 정책/ENV에 따라 결정(샘플로 env 가져오기)
        import os
        assignee_id = os.getenv("DEV_REP_ID") or user["user_id"]

        submit_draft(
            draft_id=draft_id,
            title=f"{st.session_state.doc_ctx['doc_type']} 요청",
            summary="요약(임시)",
            assignee=assignee_id,
            due_date=str(date.today())
        )
        st.success("✅ 승인 요청이 제출되었습니다.")
        st.session_state.messages.append({"role":"assistant","content":"✅ 승인 요청이 제출되었습니다."})
        st.rerun()
