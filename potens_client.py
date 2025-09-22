import os, json, requests
import streamlit as st
from typing import Optional, List, Dict, Any, Union, Tuple
from utils_llm import backoff_sleep, try_parse_json, normalize_keys, validate_keys  # 있으면 사용

# ========== Env ==========
APP_MODE = os.getenv("APP_MODE", "live").lower()      # live | mock
POTENS_API_STYLE = os.getenv("POTENS_API_STYLE", "chat").lower()  # chat | prompt
POTENS_API_URL = os.getenv("POTENS_API_URL")
POTENS_API_KEY = os.getenv("POTENS_API_KEY")

REQUEST_TIMEOUT_CONNECT = int(os.getenv("POTENS_TIMEOUT_CONNECT_SEC", "6"))
REQUEST_TIMEOUT_READ    = int(os.getenv("POTENS_TIMEOUT_READ_SEC", "12"))
MAX_RETRIES             = int(os.getenv("POTENS_MAX_RETRIES", "2"))

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

# 2) 초발화 분석 + 질문 (LLM담당자 함수)
def analyze_request_and_ask(user_utterance: str, template: dict) -> dict:
    prompt = f"""
    ## 역할 및 목표
    당신은 직원의 문서 작성을 돕는 꼼꼼한 AI 어시스턴트입니다.
    당신의 목표는 사용자의 첫 발화에서 가능한 모든 정보를 추출하고, 누락된 필수 필드에 대해 명확한 질문을 생성하는 것입니다.



    ## 문서 템플릿 정보
    - 종류: "{template['type']}"
    - 필수 필드: {template['fields']}

    ## 작성 가이드 (참고)
    {template.get('guide_md', '가이드 없음')}

    ## 출력 규칙
    
    - 질문은 절대 "‘필드명’ 값을 알려주세요" 형식을 쓰지 마세요.
    - 질문은 항상 친근하고 자연스러운 대화체 문장으로 작성하세요.
    - 예: "사유를 말씀해 주실 수 있을까요?", "언제까지 필요하신가요?" 
    - `filled_fields`: 사용자의 발화에서 추출한 값들을 채워주세요.
    - `missing_fields`: 값이 아직 비어있는 필드의 키 목록을 알려주세요.
    - `ask`: 누락된 각 필드에 대해 질문을 생성해주세요.
    - 질문은 친근하고 자연스러운 한국어 대화체로 작성하세요.
    - 단, 업무 문맥을 해치지 않도록 정중한 어투를 유지하세요.
    - 예: "사유를 알려주실 수 있을까요?" / "언제까지 필요하신가요?"

    ## JSON 출력 형식
    {{
      "filled_fields": {{ "필드키": "추출한 값", ... }},
      "missing_fields": ["누락된 필드키1", "누락된 필드키2", ...],
      "ask": [
        {{ "key": "누락된 필드키1", "question": "자연스럽게 만든 질문" }},
        {{ "key": "누락된 필드키2", "question": "자연스럽게 만든 질문" }}
      ]
    }}

    ## 사용자 최초 발화
    "{user_utterance}"
    """
    return _call_potens_llm(prompt, is_json=True)

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

# 3) 컨펌 텍스트
def generate_confirm_text(filled_data: dict, template_type: str) -> str:
    prompt = f"""
    ## 역할
    당신은 전문적인 비즈니스 문서 작성가입니다. 당신의 임무는 정형화된 데이터를 바탕으로, 관리자가 승인을 위해 검토할 간결하고 공식적인 보고서를 작성하는 것입니다.

    ## 원본 데이터
    {json.dumps(filled_data, ensure_ascii=False, indent=2)}

    ## 작성 규칙
    - 6~10개 문장 내외의 공식적인 보고서 텍스트를 작성하세요.
    - 문체는 정중하고 전문적이어야 합니다.
    - 금액, 기한, 핵심 사유 등 의사결정에 중요한 부분은 마크다운 굵은 글씨(`**텍스트**`)로 강조하세요.
    - 만약 값이 비어있는 항목이 있다면, `[입력 필요]` 라고 명확하게 표시하세요.
    - 출력은 마크다운 형식의 본문 텍스트만 포함해야 합니다.
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
    '{approved_data.get('creator_name', '담당 직원')}' 직원이 제출한 '{approved_data.get('type', '요청')}' 요청이 방금 승인되었습니다.
    일반적인 업무 절차에 따라, 가장 논리적인 다음 후속 조치는 무엇인가요?
    
    ## 임무
    방금 요청을 승인한 관리자를 위해, 승인 사실과 다음 후속 조치를 알려주는 짧은 한 문장의 알림 메시지를 생성하세요.

    ## 예시
    입력: 김민준 직원의 출장 경비 보고서.
    출력: 출장 경비 보고서 승인을 완료했습니다. 회계팀에 김민준 님의 출장비 지급을 요청해야 합니다.
    """
    return _call_potens_llm(prompt)

# 6) 컨펌 텍스트 검증(LLM담당자)
def validate_confirm_text(confirm_text: str, required_fields: list) -> dict:
    """생성된 컨펌 텍스트에 빈 값이나 논리적 오류가 있는지 최종 검증합니다."""
    
    prompt = f"""
    ## 역할: 당신은 매우 꼼꼼한 문서 검수관입니다.
    ## 임무: 아래 보고서 본문을 읽고, '필수 항목'이 모두 채워졌는지, 논리적 오류는 없는지 검증하세요.

    ## 보고서 본문:
    {confirm_text}

    ## 필수 항목 목록:
    {required_fields}

    ## 출력 규칙:
    - 만약 본문에 `[입력 필요]`와 같은 빈 칸이 있거나, 필수 항목 내용이 비어있다면 `missing` 목록에 해당 항목을 추가하세요.
    - 만약 내용에 논리적 모순이 있다면 `suggestion`에 수정 제안을 담아주세요.
    - 문제가 없다면 `is_valid`를 true로 설정하세요.
    - 반드시 JSON 형식으로만 응답하세요.
    
    ## JSON 출력 형식:
    {{ "is_valid": boolean, "missing": ["누락된 필드명"], "suggestion": "수정 제안 문구" }}
    """
    return _call_potens_llm(prompt, is_json=True)

# 7) 반려 안내문(LLM담당자)
def generate_rejection_note(rejection_memo: str, creator_name: str, doc_title: str) -> str:
    """
    대표가 남긴 반려 메모를 바탕으로 직원에게 보낼 안내문 초안을 생성합니다.
    """
    prompt = f"""
    ## 역할: 당신은 감정적이지 않고 명확하게 의사를 전달하는 중간 관리자입니다.
    ## 임무: 대표님이 남긴 간단한 '반려 메모'를 바탕으로, 직원에게 보낼 정중하고 명확한 '반려 사유 안내문'을 작성하세요.

    ## 상황 정보
    - 문서 제목: "{doc_title}"
    - 작성 직원: "{creator_name}"
    - 대표님의 반려 메모: "{rejection_memo}"

    ## 작성 규칙
    1. 직원의 기분이 상하지 않도록 정중하고 부드러운 어조를 사용하세요.
    2. 왜 반려되었는지 '대표님의 반려 메모'를 바탕으로 명확하게 설명하세요.
    3. 직원이 다음에 무엇을 해야 하는지(예: "견적서를 다시 첨부하여 제출해주세요", "예산을 재검토해주세요") 구체적인 행동을 안내해주세요.
    4. 2~3 문장으로 간결하게 작성하세요.

    ## 예시
    - 입력 메모: "예산 초과. 100만원 이하로 다시."
    - 출력 안내문: "{creator_name}님, 요청하신 '{doc_title}' 건은 예산 초과 사유로 반려되었습니다. 대표님께서 100만원 이하로 예산을 재조정하여 다시 제출해달라고 요청하셨습니다."
    """
    return _call_potens_llm(prompt)
