import streamlit as st
import json
import db
import potens_client
from datetime import date

def run_compose_page(user):
    st.header("📝 새로운 문서 업무 요청하기")

    # 세션 상태 초기화
    if "compose_state" not in st.session_state:
        st.session_state.compose_state = {
            "chat_history": [],
            "current_draft_id": None,
            "filled_fields": {},
            "is_template_selected": False,
            "template_info": None,
            "is_confirmed": False,
            "last_missing_fields": [],
            "last_questions": []
        }

    state = st.session_state.compose_state

    prefill = st.session_state.get("compose_prefill")
    if prefill:
        state["filled_fields"].update(prefill.get("filled_fields", {}))
        doc_type = prefill.get("doc_type")
        if doc_type:
            tpl = db.get_templates_by_type(doc_type)
            if tpl:
                state["template_info"] = tpl
                state["is_template_selected"] = True
        # ✅ 한 번 반영 후 즉시 제거
        del st.session_state["compose_prefill"]

    # 챗봇 초기 메시지 (세션당 한 번)
    if not state["chat_history"]:
        state["chat_history"].append({"role": "bot", "message": "안녕하세요! 어떤 문서를 작성하시겠어요? 자유롭게 말씀해 주세요. (예: 품의서, 견적서, 연차 신청)"})
        
    # --- 채팅 UI 렌더링 (카톡풍 말풍선) ---
    for chat in state["chat_history"]:
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

    # 챗봇 입력창 (GPT 스타일)
    if not state["is_confirmed"]:
        user_input = st.chat_input("챗봇에게 문서 정보를 알려주세요.", key="compose_chat_input")
        if user_input:
            state["chat_history"].append({"role": "user", "message": user_input})

            for chunk in user_input.split(","):
                if ":" in chunk:
                    k, v = chunk.split(":", 1)
                    state["filled_fields"][k.strip()] = v.strip()

            # --- RAG 기반 템플릿 추론 ---
            if not state["is_template_selected"]:
                all_templates = db.get_templates() # 모든 템플릿 정보 가져오기
                inferred_template = potens_client.infer_doc_type_and_fields(user_input, all_templates)
                
                # 오류 수정: get_templates() 대신 get_template_by_type() 호출
                state["template_info"] = db.get_templates_by_type(inferred_template['doc_type'])
                if state["template_info"]:
                    state["is_template_selected"] = True
                    state["chat_history"].append({"role": "bot", "message": f"확인했습니다. **{state['template_info']['type']}** 작성을 도와드릴게요."})

                    template_fields = state["template_info"]['fields']
                    questions_payload = potens_client.generate_questions(template_fields, state["filled_fields"])

                    # ★ 최초 질문/누락도 저장
                    state["last_missing_fields"] = questions_payload.get('missing_fields', [])
                    state["last_questions"] = questions_payload.get('ask', [])

                    questions_text = "\n".join([q['question'] for q in questions_payload['ask']])

                    state["chat_history"].append({"role": "bot", "message": f"필수 항목을 파악 중입니다... {questions_text}"})
                else:
                    state["chat_history"].append({"role": "bot", "message": "죄송합니다. 요청하신 문서 유형을 찾을 수 없습니다."})
            
            # --- 문서 필드 채우기 ---
            else:
                # LLM이 JSON 형식으로 필드 값을 추출
                template_fields = state["template_info"]['fields']
                extracted_data_payload = potens_client.generate_questions(template_fields, state["filled_fields"]) # mock에선 질문 생성
                state["last_missing_fields"] = extracted_data_payload.get('missing_fields', [])
                state["last_questions"] = extracted_data_payload.get('ask', [])


                # 추출된 데이터를 state에 업데이트 (실제 LLM 연동 시 추출된 JSON을 파싱해야 함)
                # 현재 mock 함수는 질문을 반환하므로, 간단한 로직으로 대체
                if extracted_data_payload:
                    missing = extracted_data_payload['missing_fields']
                    if not missing:
                        state["is_confirmed"] = True
                        state["chat_history"].append({"role": "bot", "message": "모든 항목이 채워졌습니다. 컨펌 텍스트를 생성할 수 있어요."})
                    else:
                        questions_text = "\n".join([q['question'] for q in extracted_data_payload['ask']])
                        state["chat_history"].append({"role": "bot", "message": f"현재 {', '.join(missing)} 항목이 비어 있어요. {questions_text}"})
            
            st.rerun()

    # --- 컨펌 텍스트 생성 및 제출 ---
    if state["is_confirmed"]:
        if st.button("컨펌 텍스트 생성"):
            confirm_text = potens_client.generate_confirm_text(state["filled_fields"])
            state["confirm_text"] = confirm_text
            st.session_state.confirm_text = confirm_text

            # 문서 초안 생성 함수 호출 위치 변경
            # 문서가 모두 작성된 후에만 초안을 생성
            created = db.create_draft(
                user['user_id'],
                state["template_info"]['type'],
                state["filled_fields"],
                state.get("last_missing_fields", []),
                confirm_text
            )
            if not created:
                st.error("초안 생성에 실패했습니다.")
            else:
                state["current_draft_id"] = created[0]["draft_id"]

            # 대표 선택 (여러 명일 경우)
            rep_ids = db.get_rep_user_ids()
            if not rep_ids:
                st.error("대표 계정을 찾을 수 없습니다.")
                st.stop()

            # 직원에게 대표를 선택시키고 싶다면:
            # (user_id 대신 이름을 보여주려면 별도 쿼리 필요)
            selected_rep = st.selectbox("승인자(대표) 선택", rep_ids, index=0)


            st.subheader("📄 컨펌 텍스트 미리보기")
            st.info(confirm_text)
            
            if st.button("승인요청 제출"):
                if not state.get("current_draft_id"):
                    st.error("초안 정보가 없습니다. 컨펌 텍스트 생성 후 다시 시도해주세요.")
                else:
                    db.submit_draft(
                        draft_id=state["current_draft_id"],
                        title=state["filled_fields"].get('title', '제목없음'),
                        summary=confirm_text[:100] + "...",
                        assignee=selected_rep,
                        due_date=str(date.today()) 

                    )
                    st.success("✅ 승인 요청이 제출되었습니다! 대표님의 확인을 기다려주세요.")
                    st.session_state.compose_state = {}
                    st.rerun()
