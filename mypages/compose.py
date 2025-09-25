from datetime import date
from typing import Dict, List, Any, Optional
import re  # ✅ 누락된 import
import streamlit as st
import db
from potens_client import (
    infer_doc_type,
    analyze_request_and_ask,
    generate_confirm_text,
)
import potens_client
# ✅ 범용 검색 유틸 임포트
from mypages.utils_search import search_general_narrow, render_answer_from_hits


_TEMPLATE_META_TRIGGERS = ("필수", "항목", "field", "가이드", "무엇이", "뭐가", "어떤 항목")

def _is_template_meta_question(text: str) -> bool:
    if not isinstance(text, str):
        return False
    t = text.strip().lower()
    return any(k in t for k in _TEMPLATE_META_TRIGGERS)

# ---------------------------
# Helpers
# ---------------------------
# ---- 폼 파싱/검증 (예시) ----
_MONEY_RX = re.compile(r"(\d{2,3})\s*만\s*원|₩\s?([\d,]+)|(\d{4,})\s*원", re.I)

def parse_and_validate(value: str, expected_field: str):
    v = (value or "").strip()
    if expected_field == "금액":
        m = _MONEY_RX.search(v)
        if not m:
            return False, None
        return True, m.group(0)
    elif expected_field in ("사유", "근거", "기한", "승인선"):
        return (len(v) >= 1), v
    return False, None

def save_value(state: dict, field: str, parsed_value: str):
    state["answers"][field] = parsed_value

def advance_field(state: dict):
    fields = state["fields"]
    idx = fields.index(state["current_field"])
    if idx < len(fields) - 1:
        state["current_field"] = fields[idx + 1]
    else:
        state["done"] = True

def reask_current_field(state: dict):
    field = state["current_field"]
    st.write(f"계속 진행할게요. **{field}** 값을 알려주세요. 예) 금액: 120만원")

# ---- 모든 질문을 범용 축소 검색으로 처리 ----
# -------------------------------------------------
# 질의 정제 + Fallback 재검색 + LLM 보정 버전
# -------------------------------------------------

# 0) 간단 전처리: 불필요 어미/감탄/조사 제거 + 숫자/한글 사이 공백 보정
def _clean_query(text: str) -> str:
    q = text or ""
    # 자주 나오는 말 제거 (의미 없는 종결어/구어체)
    q = re.sub(r"(얼마야|얼마임|얼마니|알려줘|구해줘|찾아줘|사고싶어|살건데|살려고|사려는데|좀|요|요\?|요\.)", "", q, flags=re.I)
    # 물음표/중복 공백 정리
    q = re.sub(r"[?]+", " ", q)
    # 숫자-문자 사이, 문자-숫자 사이 공백 넣기 (예: 아이폰16프로 → 아이폰 16 프로)
    q = re.sub(r"([가-힣A-Za-z])(\d)", r"\1 \2", q)
    q = re.sub(r"(\d)([가-힣A-Za-z])", r"\1 \2", q)
    # 여러 공백 → 하나
    q = re.sub(r"\s{2,}", " ", q).strip()
    return q

# 1) 가격 의도 간단 감지
_PRICE_TRIGGERS = re.compile(r"(가격|얼마|비용|시세|price|cost|krw|₩)", re.I)

def _is_price_intent(text: str) -> bool:
    return bool(_PRICE_TRIGGERS.search(text or ""))

# 2) 메인: 범용 Q&A (정제 → 단계적 재검색 → LLM 보강)
def answer_any_question(msg: str):
    original = msg or ""
    clean_q = _clean_query(original)
    price_intent = _is_price_intent(original)

    # 1차: 정제된 쿼리로 시도
    tried_datas = []   # [(query, data_dict)]
    data = search_general_narrow(clean_q)
    tried_datas.append((clean_q, data))
    if data["results"]:
        return render_answer_from_hits(data["results"], data.get("intent", ""))

    # 2차: 가격 의도면 '가격' 변형들로 재검색
    candidates = []
    if price_intent:
        candidates.extend([
            f"{clean_q} 가격",
            f"{clean_q} price",
            f"{clean_q} KRW",
            f"{clean_q} ₩",
        ])
        # 아이폰/애플 계열 히트 강화 (공홈)
        if re.search(r"(아이폰|iphone)", clean_q, re.I):
            candidates.append(f"site:apple.com/kr {clean_q} 가격")
    else:
        # 비가격 질문이면 위키/공식문서/뉴스 쪽으로 좁힘 시도
        candidates.extend([
            f"{clean_q} site:wikipedia.org",
            f"{clean_q} 공식",
            f"{clean_q} 소개",
        ])

    # 2차 시도 루프
    for q in candidates:
        data2 = search_general_narrow(q)
        tried_datas.append((q, data2))
        if data2["results"]:
            return render_answer_from_hits(data2["results"], data2.get("intent", ""))

    # 3차: 그래도 없으면 마지막 완화(국제/영문 일반)
    last_candidates = [
        clean_q,                       # 다시 한 번 원 쿼리
        re.sub(r"[가-힣]", "", clean_q).strip() or clean_q,  # 한글 제거 버전(영문 키워드만)
    ]
    for q in last_candidates:
        if not q:
            continue
        data3 = search_general_narrow(q)
        tried_datas.append((q, data3))
        if data3["results"]:
            return render_answer_from_hits(data3["results"], data3.get("intent", ""))

    # 4차: LLM 보강 (검색 실패 요약 + 간결 답변 요청)
    #     - 가격 의도면 "최신 가격은 변동 가능, 공홈/리셀러 참조" 가이드 포함
    tried_lines = []
    for q, d in tried_datas:
        attempts = d.get("attempts") or []
        if attempts:
            # attempts는 [(query, hits, note), ...]
            for tq, hits, note in attempts:
                tried_lines.append(f"- {tq}  (결과 {hits}건, 전략={note})")
        else:
            tried_lines.append(f"- {q}  (시도, 결과 0건)")

    tried_block = "\n".join(tried_lines) if tried_lines else "- (시도 기록 없음)"

    llm_prompt = f"""
    사용자가 다음 질문을 했습니다:
    Q: "{original}"

    웹 검색을 여러 번 시도했지만 결과가 충분하지 않았습니다.
    아래는 시도한 쿼리/전략 기록입니다:
    {tried_block}

    위 상황을 고려해, 한국어로 3~5줄 이내로 간결하게 답하세요.
    - 사실 확인이 어려우면 "검색 결과에서 관련 정보를 찾지 못했습니다."라고 명확하게 말하고,
    - 사용자가 확인할 수 있는 권장 경로를 1~2개 제시하세요.
    {"- 가격 문의로 보이며, 공홈 또는 공인 리셀러의 최신 가격을 확인하도록 안내하세요." if price_intent else ""}
    """
    ans = potens_client._call_potens_llm(llm_prompt).strip()

    # LLM이 너무 짧거나 빈약하면 기본 메시지로 대체
    if not ans or len(ans) < 15:
        ans = "검색 결과에서 관련 정보를 찾지 못했습니다. 공식 사이트나 공인 리셀러 페이지에서 최신 정보를 확인해주세요."
        if price_intent:
            ans += " (예: Apple 공홈, 통신사/오픈마켓 상품 페이지)"

    return ans



def handle_user_message(msg: str, state: dict):
    expected_field = state["current_field"]

    # 1) 먼저 '폼 값'으로 파싱해보고
    ok, parsed = parse_and_validate(msg, expected_field)
    if ok:
        save_value(state, expected_field, parsed)
        advance_field(state)
        return

    # 2) 파싱 실패하면 '질문'으로 간주 → 범용 축소 검색
    ans = answer_any_question(msg)
    st.info(ans)
    # 폼 진행은 멈추고 현재 항목을 다시 요청
    reask_current_field(state)

# --- NEW: 질문 감지 ---
QUESTION_TRIGGERS = ("?", "알려줘", "무엇", "뭐가", "어떻게", "어떤", "필수", "항목", "field", "가이드")

def _is_user_question(text: str) -> bool:
    if not isinstance(text, str):
        return False
    t = text.strip().lower()
    return t.endswith("?") or any(k in t for k in QUESTION_TRIGGERS)

# --- NEW: 질문에 바로 답해주기 ---
def _answer_user_question(user_q: str, template_obj: dict, filled: dict) -> str:
    # 템플릿 필수 항목 정리
    required = _template_fields_list(template_obj)
    missing = [k for k in required if k not in filled]
    guide = template_obj.get("guide_md") or "(가이드 없음)"

    # 사용자가 “필수/항목/가이드/필드” 류를 물으면 규칙 기반 즉답 (LLM 호출 없이 빠름)
    ql = user_q.lower()
    # 1단계: 기본 규칙 기반 답변 시도
    if any(x in ql for x in ["필수", "항목", "field", "가이드", "무엇이", "뭐가", "어떤 항목"]):
        bullets = "\n".join([f"- {k}" for k in required]) or "- (정의된 항목 없음)"
        filled_view = "\n".join([f"- {k}: {filled[k]}" for k in required if k in filled]) or "- (아직 없음)"
        missing_view = "\n".join([f"- {k}" for k in missing]) or "- (없음)"
        return (
            f"**이 문서에 필요한 필수 항목 목록**\n{bullets}\n\n"
            f"**현재 채워진 항목**\n{filled_view}\n\n"
            f"**남은 항목(미기입)**\n{missing_view}\n\n"
            f"**가이드(요약)**\n{guide}"
        )
    # 2단계: LLM으로 답변 시도
    # 그 외 일반 질문은 LLM로 간단 Q&A (컨텍스트 = 템플릿/가이드/이미 채운 값)
    prompt = f"""
    당신은 회사 행정 서식 도우미입니다. 아래 템플릿과 가이드를 참고해 사용자의 질문에 간결히 답하세요.
    - 문서 종류: {template_obj.get('type','(미정)')}
    - 필수 항목: {_template_fields_list(template_obj)}
    - 현재 입력된 값: {filled}
    - 가이드: {guide}

    질문: "{user_q}"
    답변 규칙:
    - 한국어로, 3~6줄 내외로 간결하게.
    - 목록이 적절하면 bullet로.
    """ 
    ans = potens_client._call_potens_llm(prompt).strip()

    # 3단계: 외부 지식 필요 여부 판단
    needs_search = (
        not ans or len(ans) < 20 or
        any(x in ql for x in ["가격", "얼마", "비용", "시세", "최신", "뉴스", "법", "규정", "알려", "찾아"]) or
        any(x in ans for x in ["모르", "없습니다", "찾지 못"])
    )
    if needs_search:
        query = user_q
        if any(x in ql for x in ["가격","비용","얼마","시세"]):
            query += " 평균 가격 원화"
        search_results = potens_client.web_search_duckduckgo(query, max_results=3)

        if search_results:
            ctx = "\n".join([
                f"- {r.get('title')}: {r.get('body','')} ({r.get('href')})"
                for r in search_results
            ])
            search_prompt = f"""
            사용자가 "{user_q}" 라고 물었습니다.
            아래는 검색 결과 요약입니다:

            {ctx}

            검색 결과를 참고하여 한국어로 3~6줄 이내로 답하세요.
            - 가능하면 수치/날짜/법규 등 구체적인 사실을 포함하세요.
            - 무관한 결과라면 '검색 결과에서 관련 정보를 찾지 못했습니다.' 라고만 답하세요.
            """
            ans = potens_client._call_potens_llm(search_prompt).strip()

    return ans


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
                {"role": "assistant", "content": "안녕하세요! 어떤 문서를 작성하시겠어요? (예: 품의, 연차, 견적, 기술 기안서)"},
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

                # --- NEW: 사용자가 질문을 했으면, 값 매핑 전에 즉답 후 흐름 유지 ---
                if _is_user_question(user_input):
                    if _is_template_meta_question(user_input):
                        # 템플릿/필드/가이드 관련 내부 질문 → 규칙/LLM로 빠르게
                        ans = _answer_user_question(user_input, state["template"], state["filled_fields"])
                    else:
                        # 그 외 모든 일반 질문 → 범용 축소 검색(사실/최신/브랜드/가격/수명 등)
                        ans = answer_any_question(user_input)
                    state["chat_history"].append({"role": "assistant", "content": ans})
                    st.rerun()



                    
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

    # ———————— 제출 성공 메시지 유지 ————————
    if st.session_state.get("last_submit_success"):
        st.success("✅ 승인 요청이 제출되었습니다!")
        st.session_state["last_submit_success"] = False
