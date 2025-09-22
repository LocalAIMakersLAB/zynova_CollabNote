# mypages/compose.py
from datetime import date
from typing import Dict, List, Any, Optional
import streamlit as st
import db
from potens_client import (
    infer_doc_type,
    analyze_request_and_ask,
    generate_confirm_text,
)
import potens_client

# ---------------------------
# Helpers
# ---------------------------
def _template_fields_list(template_obj: Dict[str, Any]) -> List[str]:
    f = template_obj.get("fields", [])
    if isinstance(f, dict):
        # dict 안에 "required" 키만 있는 경우 → 그 값을 그대로 반환
        if "required" in f and isinstance(f["required"], list):
            return f["required"]
        return list(f.keys())
    if isinstance(f, list):
        return [str(x) for x in f]
    return []


def _attach_keys_to_questions(template_fields: List[str], ask_list: List[Any]) -> List[Dict[str, str]]:
    """
    LLM이 만든 ask 항목에 key가 없다면, 질문문구에서 템플릿 필드명과 간단 매칭하여 key 부착.
    결과 형식: [{"key": "...", "question": "..."}]
    """
    out: List[Dict[str, str]] = []
    for item in (ask_list or []):
        if isinstance(item, dict):
            q = str(item.get("question", "")).strip()
            k = item.get("key")
        else:
            q = str(item).strip()
            k = None

        if not k:
            ql = q.lower().replace(" ", "")
            cand = None
            for f in template_fields:
                fs = str(f)
                if fs and fs.lower().replace(" ", "") in ql:
                    cand = fs
                    break
            out.append({"key": cand, "question": q})
        else:
            out.append({"key": str(k), "question": q})
    return out

def _next_remaining_key(template_fields: List[str], filled_fields: Dict[str, Any]) -> Optional[str]:
    """아직 채워지지 않은 필드 중 첫 번째 반환 (순서 필요 시 DB에서 리스트/정렬 메타 권장)"""
    for f in template_fields:
        if f not in filled_fields:
            return f
    return None


# ---------------------------
# Main Page
# ---------------------------
def run_compose_page(user: Dict[str, Any]):
    st.header("📝 새 문서 요청")

    # 초기화 부분
    if "compose_state" not in st.session_state or st.session_state.get("new_request", False):
        st.session_state.compose_state = {
            "stage": "initial",
            "chat_history": [
                {"role": "assistant", "content": "안녕하세요! 어떤 문서를 작성하시겠어요? (예: 품의서, 연차 신청)"},
            ],
            "template": None,
            "filled_fields": {},
            "questions_to_ask": [],
            "last_asked": None,
            "prefill": None,
            "confirm_rendered": False,
        }
        # ✅ 여기서는 new_request만 False로 되돌림
        st.session_state.new_request = False

    # ✅ 성공 여부 flag는 compose_state와 분리
    if "last_submit_success" not in st.session_state:
        st.session_state.last_submit_success = False

    state = st.session_state.compose_state


    # --- 기존 대화 렌더 (UI만 교체) ---
    for msg in state["chat_history"]:
        if msg["role"] == "assistant":
            st.markdown(
                f"""
                <div style="display:flex;justify-content:flex-start;margin:6px 0;">
                  <div style="
                    background:#F2F3F5;
                    color:#111;
                    padding:10px 14px;
                    border-radius:16px;
                    border-bottom-left-radius:2px;
                    max-width:70%;
                    word-wrap:break-word;
                    font-size:15px;">
                    {msg['content']}
                  </div>
                </div>
                """,
                unsafe_allow_html=True
            )
        else:  # user
            st.markdown(
                f"""
                <div style="display:flex;justify-content:flex-end;margin:6px 0;">
                  <div style="
                    background:#9FE8A8;
                    color:#000;
                    padding:10px 14px;
                    border-radius:16px;
                    border-bottom-right-radius:2px;
                    max-width:70%;
                    word-wrap:break-word;
                    font-size:15px;">
                    {msg['content']}
                  </div>
                </div>
                """,
                unsafe_allow_html=True
            )

    # --- 사용자 입력 (UI 유지) ---
    user_input = st.chat_input("요청 내용을 말씀해주세요...")
    if user_input:
        # 카톡풍 유저 말풍선 출력
        st.markdown(
            f"""
            <div style="display:flex;justify-content:flex-end;margin:6px 0;">
              <div style="
                background:#9FE8A8;
                color:#000;
                padding:10px 14px;
                border-radius:16px;
                border-bottom-right-radius:2px;
                max-width:70%;
                word-wrap:break-word;
                font-size:15px;">
                {user_input}
              </div>
            </div>
            """,
            unsafe_allow_html=True
        )
        state["chat_history"].append({"role": "user", "content": user_input})

        # ---------------- initial: 문서 타입 결정 + 질문 생성 ----------------
        if state["stage"] == "initial":
            with st.spinner("요청 내용을 분석 중입니다..."):
                # 1) 전체 템플릿 목록
                templates = db.get_templates()
                # 2) 반려 재작성 프리필에 doc_type이 있으면 우선
                pref = state.get("prefill") or {}
                if pref.get("doc_type"):
                    doc_type = pref["doc_type"]
                else:
                    doc_type = infer_doc_type(user_input, templates)

                # 3) 템플릿 객체 조회
                template_obj = db.get_templates_by_type(doc_type)
                if not template_obj:
                    err = f"'{doc_type}'에 해당하는 템플릿을 찾지 못했습니다. 관리자에게 문의하세요."
                    state["chat_history"].append({"role": "assistant", "content": err})
                    st.rerun()

                # guide_md 추가
                guide_md = db.get_rag_context(doc_type)
                if guide_md:
                    template_obj["guide_md"] = guide_md


                state["template"] = template_obj
                template_fields = _template_fields_list(template_obj)

                # 4) 첫 발화 분석 + 질문 생성(LLM)
                analysis = analyze_request_and_ask(user_input, template_obj) or {}
                filled = dict(analysis.get("filled_fields", {}))

                # 5) 반려 재작성 프리필 병합
                prefill_fields = (pref.get("filled_fields") or {})
                if prefill_fields:
                    filled.update(prefill_fields)
                state["filled_fields"] = filled

                # 6) 질문 큐 정규화(질문에 key 부착)
                raw_ask = analysis.get("ask", []) or analysis.get("questions_to_ask", [])
                ask_norm = _attach_keys_to_questions(template_fields, raw_ask)

                # 7) key가 비어있는 질문은 남은 필드에서 순차로 부여
                remaining = [f for f in template_fields if f not in state["filled_fields"]]
                fixed_ask = []
                for item in ask_norm:
                    if not item.get("key"):
                        item["key"] = remaining.pop(0) if remaining else None
                    fixed_ask.append(item)
                # None key 제거
                state["questions_to_ask"] = [x for x in fixed_ask if x.get("key")]

                # 8) 시작 멘트
                start_msg = f"네, **{doc_type}** 작성을 시작하겠습니다."
                state["chat_history"].append({"role": "assistant", "content": start_msg})

                # 9) 질문 시작 or 즉시 확인 단계
                if state["questions_to_ask"]:
                    nxt = state["questions_to_ask"].pop(0)
                    state["last_asked"] = nxt["key"]
                    state["chat_history"].append({"role": "assistant", "content": nxt["question"]})
                    state["stage"] = "gathering"
                else:
                    # 남은 필드가 있다면 기본 질문 생성, 없으면 확인
                    remaining = [f for f in template_fields if f not in state["filled_fields"]]
                    if remaining:
                        nxt_key = remaining[0]
                        state["last_asked"] = nxt_key
                        state["chat_history"].append(
                            {"role": "assistant", "content": f"'{nxt_key}' 값을 알려주세요."}
                        )
                        state["stage"] = "gathering"
                    else:
                        state["stage"] = "confirm"
            st.rerun()

        # ---------------- gathering: 마지막으로 물었던 key에 답을 매핑 ----------------
        elif state["stage"] == "gathering":
            with st.spinner("답변을 확인하고 있습니다..."):
                template_fields = _template_fields_list(state["template"])

                # 1) 직전에 물었던 key에 매핑
                last_key = state.get("last_asked")
                if not last_key:
                    last_key = _next_remaining_key(template_fields, state["filled_fields"])
                if last_key:
                    state["filled_fields"][last_key] = user_input.strip()

                # 2) 다음 질문(우선 LLM이 만든 큐)
                if state["questions_to_ask"]:
                    nxt = state["questions_to_ask"].pop(0)
                    state["last_asked"] = nxt["key"]
                    state["chat_history"].append({"role": "assistant", "content": nxt["question"]})
                else:
                    # LLM 큐가 비어도 남은 필드가 있으면 기본 질문으로 이어 묻기
                    remaining = [f for f in template_fields if f not in state["filled_fields"]]
                    if remaining:
                        nxt_key = remaining[0]
                        state["last_asked"] = nxt_key
                        state["chat_history"].append(
                            {"role": "assistant", "content": f"'{nxt_key}' 값을 알려주세요."}
                        )
                        # stage 유지(gathering)
                    else:
                        # 더 이상 질문이 없으면 확인 단계
                        state["stage"] = "confirm"
            st.rerun()

        # ---------------- confirm: (이전 버전 문제) 사용자 입력 없어도 자동 렌더가 되도록 아래로 이동 ----------------
        # (의도적으로 비워둠; 아래의 '입력 외 영역'에서 처리)

    # ---------------- confirm 단계: 최종 보고서 + 버튼 UI ----------------
    if state["stage"] == "confirm" and not state.get("confirm_rendered"):
        with st.spinner("최종 보고서를 생성 중입니다..."):
            doc_type = state["template"]["type"] if state.get("template") else "문서"
            final_text = generate_confirm_text(state["filled_fields"], doc_type)

            # confirm_text를 state에 저장 (DB 제출용)
            state["confirm_text"] = final_text

            response = (
                "모든 정보가 수집되었습니다. 아래 내용으로 제출할까요?\n\n"
                "---\n"
                f"{final_text}\n"
                "---\n\n"
                "하단 버튼을 눌러주세요."
            )
            st.text_area("📄 최종 보고서", response, height=300)
            state["confirm_rendered"] = True

    # ---------------- 버튼 UI (항상 confirm일 때는 보이도록) ----------------
    if state["stage"] == "confirm":
        col1, col2, col3 = st.columns([1, 1, 1])
        print(f"[DEBUG] stage={state['stage']}, confirm_rendered={state.get('confirm_rendered')}")
        
        # ✅ 항상 edit_result 초기화
        edit_result = {}

        with col1:
            if st.button("🔁 처음부터 다시"):
                st.session_state.new_request = True
                st.rerun()
                
        with col2:
            if st.button("✏️ 일부 수정하기"):
                st.session_state["edit_mode"] = True
                st.session_state["edit_target"] = None
                st.session_state["edit_message"] = "수정할 항목을 말씀해주세요. (예: 승인자 이름을 김이준으로 바꿔줘)"
                st.rerun()

            # edit_mode일 때만 동작
            if st.session_state.get("edit_mode"):
                st.info(st.session_state.get("edit_message", ""))

                user_edit_input = st.text_input("✏️ 수정 입력", key="edit_input")
                edit_result = {}

                if user_edit_input:
                    edit_prompt = f"""
                    사용자가 문서 내용을 수정하려 합니다. 

                    ## 현재 데이터
                    {state['filled_fields']}

                    ## 사용자 요청
                    "{user_edit_input}"

                    ## 출력 규칙
                    - 반드시 JSON만 출력하세요. (설명, 코드블록, 주석 금지)
                    - 형식: {{"key": "필드명", "value": "새 값"}}
                    """
                    edit_raw = potens_client._call_potens_llm(edit_prompt)

                    import re, json
                    if edit_raw:
                        match = re.search(r"\{.*\}", edit_raw, re.S)
                        if match:
                            try:
                                edit_result = json.loads(match.group(0))
                            except json.JSONDecodeError:
                                st.error("❌ 수정 결과 파싱 실패. 다시 시도해주세요.")
                                edit_result = {}

                # --- 수정 적용 ---
                if edit_result and "key" in edit_result:
                    key = edit_result["key"]
                    val = edit_result["value"]
                    state["filled_fields"][key] = val
                    st.success(f"✅ '{key}' 값이 '{val}'(으)로 수정되었습니다.")
                    st.session_state["edit_mode"] = False
                    state["stage"] = "confirm"
                    state["confirm_rendered"] = False
                    st.rerun()

        with col3:
            if st.button("🚀 승인 요청 제출"):
                print(f"[DEBUG] submit clicked, user={user['user_id']}")
                draft_id = db.create_draft(
                    user['user_id'],
                    state["template"]["type"],
                    state["filled_fields"],
                    state.get("missing_fields", []),
                    state["confirm_text"]
                )
                print(f"[DEBUG] draft_id={draft_id}")
                if draft_id:
                    # 대표 ID 가져오기
                    rep_id = db.get_rep_user_id()
                    print(f"[DEBUG] rep_id={rep_id}")
                    db.submit_draft(
                        draft_id=draft_id,
                        confirm_text=state["confirm_text"],
                        assignee=rep_id,
                        due_date=str(date.today()),
                        creator_id=user['user_id']
                    )
                    st.success("✅ 승인 요청이 제출되었습니다!")
                    st.session_state.last_submit_success = True
                    st.session_state.new_request = True
                    st.rerun()
                else:
                    st.error("DB 저장에 실패했습니다.")

    # ---------------- 제출 성공 메시지 유지 ----------------
    if st.session_state.get("last_submit_success"):
        st.success("✅ 승인 요청이 제출되었습니다!")
        st.session_state["last_submit_success"] = False

