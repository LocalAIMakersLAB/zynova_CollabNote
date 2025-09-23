from ddgs import DDGS
import os, json, requests
import streamlit as st
from typing import Optional, List, Dict, Any, Union, Tuple
from mypages.utils_llm import backoff_sleep, try_parse_json, normalize_keys, validate_keys  # 있으면 

# from dotenv import load_dotenv

# load_dotenv()

# ========== Env ==========
# st.secrets.get()을 사용하여 변수 호출 시 오류 방지
APP_MODE = st.secrets.get("APP_MODE", "live").lower()
POTENS_API_STYLE = st.secrets.get("POTENS_API_STYLE", "chat").lower()
POTENS_API_URL = st.secrets.get("POTENS_API_URL")
POTENS_API_KEY = st.secrets.get("POTENS_API_KEY")
SUPABASE_URL = st.secrets.get("SUPABASE_URL")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY")

REQUEST_TIMEOUT_CONNECT = int(st.secrets.get("POTENS_TIMEOUT_CONNECT_SEC", "6"))
REQUEST_TIMEOUT_READ = int(st.secrets.get("POTENS_TIMEOUT_READ_SEC", "12"))
MAX_RETRIES = int(st.secrets.get("POTENS_MAX_RETRIES", "2"))

# 환경 변수가 없을 때 오류를 내도록 명시적인 체크 추가
if not POTENS_API_URL or not POTENS_API_KEY:
    raise RuntimeError("POTENS_API_URL or POTENS_API_KEY not configured in secrets.toml")
    
HEADERS = {"Authorization": f"Bearer {POTENS_API_KEY}", "Content-Type": "application/json"}
# ========== 공통 호출기 ==========
def _http_post_json(url: str, payload: dict) -> Tuple[Optional[dict], Optional[str]]:
    """성공 시 (json, None), 실패 시 (None, error_str) 반환"""
    for attempt in range(MAX_RETRIES + 1):
        try:
            r = requests.post(
                url,
                headers=HEADERS,
                json=payload,
                timeout=(REQUEST_TIMEOUT_CONNECT, REQUEST_TIMEOUT_READ),
            )
            # 재시도 조건
            if r.status_code == 429 or 500 <= r.status_code < 600:
                if attempt < MAX_RETRIES:
                    backoff_sleep(attempt)
                    continue
            r.raise_for_status()
            return r.json(), None
        except Exception as e:
            if attempt < MAX_RETRIES:
                backoff_sleep(attempt)
                continue
            return None, str(e)

# --- LLM 호출 공통 함수 (최종 수정) ---
def _call_potens_llm(prompt: str, is_json: bool = False) -> Union[dict, str]:
    """Potens LLM을 호출하고, 실제 응답 구조에 맞게 결과를 파싱합니다."""
    payload = {"prompt": prompt}

    try:
        response = requests.post(POTENS_API_URL, headers=HEADERS, json=payload, timeout=20)
        response.raise_for_status()
        
        # 1. 실제 응답 데이터 가져오기
        response_data = response.json()
        
        # 2. 'message' 키에서 내용을 추출
        content = response_data.get('message', '')

        # 3. 만약 내용이 JSON을 감싼 마크다운 코드 블록이라면 순수 JSON만 추출
        if is_json and content.startswith("```json"):
            content = content.strip().replace("```json", "").replace("```", "")
        
        # 4. 최종 결과 반환
        return json.loads(content) if is_json else content.strip()

    except Exception as e:
        st.error(f"LLM API 호출 또는 파싱 중 오류: {e}")
        # 오류 발생 시 실제 응답 내용을 확인하기 위해 터미널에 출력
        print(f"❌ 오류 발생 시점의 API 응답: {response.text}")
        return {} if is_json else f"오류: {e}"

# def _llm_call(
#     prompt: Optional[str] = None,
#     messages: Optional[List[Dict[str, str]]] = None,
#     is_json: bool = False
# ) -> Union[dict, str]:
#     """
#     - APP_MODE=mock → mock marker 반환
#     - POTENS_API_STYLE=prompt → POST {POTENS_API_URL} with {"prompt": ...}
#     - POTENS_API_STYLE=chat   → POST {POTENS_API_URL}/chat with {"messages":[...], ...}
#     """
#     if APP_MODE == "mock":
#         st.info("APP_MODE=mock: LLM 호출 대신 Mock 응답을 사용합니다.")
#         return {"__error__": "APP_MODE=mock"} if is_json else "[MOCK]"

#     if not POTENS_API_URL or not POTENS_API_KEY:
#         st.error("POTENS_API_URL 또는 POTENS_API_KEY 가 설정되지 않았습니다. Mock으로 동작합니다.")
#         return {"__error__": "API Key not configured"} if is_json else "[MOCK]"

#     # 공통 파라미터(벤더별로 무시될 수 있음)
#     params = {
#         "temperature": float(os.getenv("POTENS_TEMPERATURE", "0.2")),
#         "top_p": float(os.getenv("POTENS_TOP_P", "0.9")),
#         "max_tokens": int(os.getenv("POTENS_MAX_TOKENS", "800")),
#     }

#     if POTENS_API_STYLE == "prompt":
#         if not prompt:
#             return {} if is_json else ""
#         url = POTENS_API_URL  # ex: https://ai.potens.ai/api/chat (LLM담당자 버전은 루트에 바로 POST)
#         payload = {**params, "prompt": prompt}
#         res, err = _http_post_json(url, payload)
#         if err or not isinstance(res, dict):
#             return {} if is_json else ""
#         return _parse_prompt_style(res, is_json)

#     # default: chat
#     if not messages:
#         return {} if is_json else ""
#     url = POTENS_API_URL.rstrip("/") + "/chat"
#     payload = {**params, "messages": messages}
#     res, err = _http_post_json(url, payload)
#     if err or not isinstance(res, dict):
#         return {} if is_json else ""
#     return _parse_chat_style(res, is_json)

# ========== 기능 함수들 ==========
# 1) 템플릿 분류
def infer_doc_type(user_utterance: str, templates: list[dict]) -> str:
    """
    사용자의 발화를 분석하여 가장 적합한 문서 종류(type)를 분류합니다.
    """
    template_options = [t['type'] for t in templates]

    prompt = f"""
    ## 역할: 당신은 직원의 요청을 듣고 올바른 업무 서식을 찾아주는 AI 비서입니다.

    ## 임무: 사용자의 요청이 아래 '선택 가능 서식' 중 어떤 것과 가장 관련이 깊은지 정확히 판단하여, 그 서식의 이름 '하나'만 응답하세요.

    ## 선택 가능 서식:
    {json.dumps(template_options, ensure_ascii=False)}

    ## 사용자 요청:
    "{user_utterance}"

    ## 출력 규칙:
    - 반드시 '선택 가능 서식'에 있는 이름 중 하나로만 대답해야 합니다.
    - 다른 설명 없이 서식의 이름만 출력하세요.
    """
    doc_type = _call_potens_llm(prompt)
    return doc_type.strip()

def analyze_request_and_ask(user_utterance: str, template: dict) -> dict:
    prompt = f"""
    ## 역할
    당신은 회사의 다양한 행정 문서(품의서, 출장계, 기안서 등)를 작성하도록 돕는 AI 어시스턴트입니다.

    ## 목표
    1. 사용자의 첫 발화에서 추출 가능한 모든 정보를 반드시 `filled_fields`에 채워 넣으세요.
       - 숫자, 금액, 날짜, 기간, 인원수 등은 직접 계산하거나 변환해 기록하세요.
       - 예: "12월 15일부터 18일까지 출장" → 시작일=2025-12-15, 종료일=2025-12-18, 총일수=4
       - 예: "100만원 필요" → 금액=1000000
    2. 이미 채워진 필드는 다시 질문하지 않습니다.
    3. 누락된 필드만 `missing_fields`에 나열하고, 그에 맞는 자연스러운 질문(`ask`)을 생성하세요.
    4. 질문은 친근하고 정중한 대화체로 작성합니다.
       - 예: "출장 사유를 말씀해 주실 수 있을까요?" 
       - 예: "해당 금액은 언제까지 필요하신가요?"

    ## 문서 템플릿
    - 종류: "{template['type']}"
    - 필수 필드: {template['fields']}

    ## 작성 가이드 (참고)
    {template.get('guide_md', '가이드 없음')}

    ## 출력 규칙
    - 출력은 반드시 **순수 JSON**만 반환하세요. 설명 문장은 포함하지 마세요.
    - `filled_fields`: 사용자의 발화에서 추출/계산한 값 (dict)
    - `missing_fields`: 여전히 비어 있는 필드 목록 (list)
    - `ask`: 각 누락된 필드에 대해 자연스러운 질문 배열 (list of objects)
      - 각 질문은 {{ "key": "필드명", "question": "자연스러운 질문" }} 형식이어야 합니다.
    - 날짜는 ISO8601 형식("YYYY-MM-DD") 권장.

    ## 출력 예시
    {{
      "filled_fields": {{
        "금액": "1000000",
        "사유": "A 프로젝트 장비 구매"
      }},
      "missing_fields": ["근거", "기한", "승인선"],
      "ask": [
        {{ "key": "근거", "question": "이 품의의 근거가 되는 자료가 있으신가요?" }},
        {{ "key": "기한", "question": "언제까지 이 품의가 필요하신가요?" }},
        {{ "key": "승인선", "question": "승인자는 누구로 지정하시겠어요?" }}
      ]
    }}

    ## 사용자 발화
    "{user_utterance}"
    """
    return _call_potens_llm(prompt, is_json=True)

def web_search_duckduckgo(query: str, max_results: int = 3) -> list[dict]:
    """DuckDuckGo에서 웹검색 결과를 가져옵니다."""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
            return results
    except Exception as e:
        print(f"❌ 검색 오류: {e}")
        return []
    
# def infer_doc_type_and_fields(user_utterance: str, templates: List[dict]) -> dict:
#     """
#     우리 함수 호환: {"doc_type": str, "required": [str]}
#     """
#     if not templates:
#         return {"doc_type": "품의", "required": []}
#     # chat 모드에 최적화된 프롬프트
#     context = [{"type": t["type"], "required": t["fields"].get("required", [])} for t in templates][:20]
#     prompt = (
#         "당신은 문서 템플릿 어시스턴트입니다.\n"
#         "아래 사용자 요청에 가장 맞는 문서 유형(doc_type)과 필수필드(required)만 JSON으로 응답하세요.\n"
#         "반드시 키는 doc_type, required만 포함하세요.\n\n"
#         f"사용자 요청: {user_utterance}\n"
#         f"템플릿 후보(요약): {context}\n"
#         '출력 예: {"doc_type": "품의", "required": ["금액","근거","기한","승인선"]}'
#     )
#     if POTENS_API_STYLE == "prompt":
#         res = _llm_call(prompt=prompt, is_json=True)
#     else:
#         res = _llm_call(messages=[{"role":"user","content":prompt}], is_json=True)

#     obj = res if isinstance(res, dict) else {}
#     obj = normalize_keys(obj) if 'normalize_keys' in globals() else obj
#     if not obj or not obj.get("doc_type"):
#         # 폴백: infer_doc_type 만이라도
#         t = infer_doc_type(user_utterance, templates)
#         req = next((x["fields"].get("required", []) for x in templates if x["type"] == t), [])
#         return {"doc_type": t, "required": req}
#     # 템플릿 존재성 보정
#     if not any(t["type"] == obj["doc_type"] for t in templates):
#         cand = next((t["type"] for t in templates if t["type"].lower()==str(obj["doc_type"]).lower()), templates[0]["type"])
#         obj["doc_type"] = cand
#     return obj



# # 2-b) 누락질문 전용 (우리 함수)
# def generate_questions(template_fields: dict, user_filled: dict) -> dict:
#     required = template_fields.get("required", [])
#     pruned = dict(list(user_filled.items())[:50])
#     prompt = (
#         "당신은 양식 어시스턴트입니다. 다음의 필수 키와 현재 값으로부터 누락된 필드를 찾고, "
#         "사용자에게 물어볼 질문 배열을 만드세요. 한국어로 간결히.\n"
#         "반드시 JSON으로 응답하며, 키는 required_fields, missing_fields, ask 만 포함하세요.\n"
#         f"required_keys = {json.dumps(required, ensure_ascii=False)}\n"
#         f"current_values = {json.dumps(pruned, ensure_ascii=False)}\n"
#         '출력 예: {"required_fields":["금액","기한"],"missing_fields":["기한"],"ask":[{"key":"기한","question":"기한은 언제까지인가요?"}]}'
#     )
#     if POTENS_API_STYLE == "prompt":
#         res = _llm_call(prompt=prompt, is_json=True)
#     else:
#         messages=[{"role":"user","content":prompt}]
#         # chat 스타일은 json_schema 옵션도 붙일 수 있지만 서버마다 달라 생략
#         res = _llm_call(messages=messages, is_json=True)

#     if not isinstance(res, dict):
#         return {"required_fields": required, "missing_fields": [], "ask": []}

#     res = normalize_keys(res) if 'normalize_keys' in globals() else res
#     # 스키마 보정
#     return {
#         "required_fields": list(map(str, res.get("required_fields", required))),
#         "missing_fields": list(map(str, res.get("missing_fields", []))),
#         "ask": [
#             {
#                 "key": str(x.get("key","")).strip(),
#                 "question": str(x.get("question","")).strip(),
#                 "options": [str(o) for o in x.get("options", [])]
#             }
#             for x in (res.get("ask", []) or []) if isinstance(x, dict)
#         ]
#     }

def generate_confirm_text(filled_data: dict, template_type: str) -> str:
    prompt = f"""
    ## 역할
    당신은 회사 행정 문서를 정리해 대표에게 전달하는 비즈니스 보고서 작성자입니다.

    ## 문서 종류
    {template_type}

    ## 원본 데이터
    {json.dumps(filled_data, ensure_ascii=False, indent=2)}

    ## 작성 규칙
    1. 문서 종류에 맞는 **자연스러운 제목**으로 시작하세요. (예: "출장 품의 보고" / "연차 신청 보고")
    2. 전체를 4~7문장 정도로 간결하게 작성하세요. (문서 성격에 따라 길이 조절)
    3. 금액, 기한, 핵심 사유, 인원수 등 중요한 값은 마크다운 굵은 글씨(`**텍스트**`)로 강조하세요.
    4. 값이 비어있다면 본문 중간에 [입력 필요]로 표시하되, 마지막에 “추가로 필요한 정보” 섹션을 만들어 다시 안내하세요.
    5. 출력은 마크다운 형식의 본문 텍스트만 포함해야 합니다.

    ## 출력 예시 (출장계)
    ### 출장 품의 보고
    본 보고서는 **2025년 12월 15일**부터 **12월 18일**까지 진행될 출장에 관한 승인 요청입니다.  
    출장 인원은 **3명**이며, 출장 목적은 [입력 필요]입니다.  
    예상 소요 비용은 **150만원**으로 산정됩니다.  
    상기 일정과 비용을 바탕으로 승인을 요청드립니다.

    **추가로 필요한 정보:** 출장 목적
    """
    return _call_potens_llm(prompt)


# 4) 승인용 요약(LLM담당자)
def generate_approval_summary(confirm_text: str) -> dict:
    prompt = f"""
    ## 역할
    당신은 요약 전문가입니다. 당신의 임무는 업무 보고서를 읽고, 바쁜 경영진을 위해 핵심만 요약하는 것입니다.

    ## 원본 보고서
    {confirm_text}

    ## 임무
    다음 세 개의 키를 가진 JSON 객체를 생성하세요:
    - `title`: 보고서의 핵심 내용을 담은 짧고 강력한 제목 (예: "프로젝트 A 장비 구매 건").
    - `summary`: 한두 문장으로 된 요약.
    - `points`: 의사결정에 가장 중요한 핵심 포인트 3가지를 담은 리스트.

    ## JSON 출력 형식
    {{
      "title": "문자열",
      "summary": "문자열",
      "points": ["문자열", "문자열", "문자열"]
    }}
    """
    return _call_potens_llm(prompt, is_json=True)

# 5) 후속조치 알림(LLM담당자)
def generate_next_step_alert(approved_data: dict) -> str:
    prompt = f"""
    ## 상황
    '{approved_data.get('creator_name', '담당 직원')}'이(가) 제출한 '{approved_data.get('type', '요청')}' 요청이 방금 승인되었습니다.
    요청 기한: {approved_data.get('due_date', '미정')}

    일반적인 업무 절차에 따라, 가장 논리적인 다음 후속 조치는 무엇인가요?
    
    ## 임무
    - 승인 사실을 알리는 짧은 문장을 작성하세요.
    - 그 뒤, 일반적인 후속 조치를 한 문장으로 안내하세요.
    - 메시지는 최대 두 문장 이내로 유지하세요.

    ## 예시
    입력: 김민준 직원의 출장 경비 보고서.
    출력
    - 출장 경비 보고서 승인을 완료했습니다. **12월 20일까지** 회계팀에 김민준 님의 출장비 지급해야 합니다.
    - 연차 신청을 승인했습니다. 인사팀 근태 기록에 반영해 주세요.
    """
    return _call_potens_llm(prompt)

# 6) 컨펌 텍스트 검증(LLM담당자)
def validate_confirm_text(confirm_text: str, required_fields: list) -> dict:
    prompt = f"""
    ## 역할
    당신은 매우 꼼꼼한 행정 문서 검수관입니다.

    ## 임무
    아래 보고서 본문을 검토하여:
    1. '필수 항목'이 모두 채워졌는지 확인하세요.
    2. 논리적 오류(예: 종료일이 시작일보다 빠른 경우, 금액이 음수/0인 경우 등)가 있는지 확인하세요.

    ## 보고서 본문
    {confirm_text}

    ## 필수 항목 목록
    {required_fields}

    ## 출력 규칙
    - 본문에 `[입력 필요]` 또는 필수 항목 값이 비어 있으면 `missing`에 해당 항목명을 넣으세요.
    - 논리적 오류가 있으면 `suggestion`에 수정 제안을 넣으세요.
    - 문제가 없다면 `is_valid`를 true로 설정하세요.
    - suggestion이 필요 없다면 빈 문자열("")을 넣으세요.
    - 반드시 JSON 형식으로만 응답하세요.

    ## JSON 출력 형식
    {{
      "is_valid": true/false,
      "missing": ["누락된 필드명"],
      "suggestion": "수정 제안 문구 또는 빈 문자열"
    }}
    """
    return _call_potens_llm(prompt, is_json=True)


# 7) 반려 안내문(LLM담당자)
def generate_rejection_note(rejection_memo: str, creator_name: str, doc_title: str) -> str:
    """
    대표가 남긴 반려 메모를 바탕으로 직원에게 보낼 안내문 초안을 생성합니다.
    """
    prompt = f"""
    ## 역할
    당신은 감정적이지 않고 명확하게 의사를 전달하는 중간 관리자입니다.

    ## 임무
    대표님이 남긴 간단한 '반려 메모'를 바탕으로, 직원에게 보낼 정중하고 명확한 '반려 사유 안내문'을 작성하세요.

    ## 상황 정보
    - 문서 제목: "{doc_title}"
    - 작성 직원: "{creator_name}"
    - 대표님의 반려 메모: "{rejection_memo}"

    ## 작성 규칙
    1. "{creator_name}님, ..." 으로 시작하세요.
    2. 왜 반려되었는지 대표님의 메모를 바탕으로 설명하세요.
    3. 직원이 다음에 해야 할 구체적인 행동을 안내하세요.
    4. 직원이 기분 나쁘지 않도록 정중하고 부드러운 어투를 유지하세요.
    5. 내용은 2~3문장으로 간결하게 작성하세요.
    6. 출력은 순수한 안내문 텍스트만 포함하세요. (불필요한 따옴표, 리스트, 마크다운 X)

    ## 예시
    입력 메모: "예산 초과. 100만원 이하로 다시."
    출력 안내문: {creator_name}님, 요청하신 '{doc_title}' 건은 예산 초과 사유로 반려되었습니다. 대표님께서 100만원 이하로 예산을 재조정하여 다시 제출해달라고 요청하셨습니다.
    """
    return _call_potens_llm(prompt)


def web_search_duckduckgo(query: str, max_results: int = 3) -> list[dict]:
    """DuckDuckGo에서 웹검색 결과를 가져옵니다."""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
            return results
    except Exception as e:
        print(f"❌ 검색 오류: {e}")
        return []