import os, json, requests
import streamlit as st
from typing import Optional, List, Dict, Any, Union, Tuple
from mypages.utils_llm import backoff_sleep, try_parse_json, normalize_keys  # 있으면 사용

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

def _parse_prompt_style(res: dict, is_json: bool) -> Union[dict, str]:
    """
    LLM담당자 구현: { "message": "... 혹은 ```json ... ```" }
    """
    content = (res or {}).get("message", "")
    if is_json:
        txt = content.strip()
        if txt.startswith("```json"):
            txt = txt.replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(txt) if txt else {}
        except Exception:
            ok, obj = try_parse_json(txt) if 'try_parse_json' in globals() else (False, None)
            return obj if ok else {}
    return content.strip()

def _parse_chat_style(res: dict, is_json: bool) -> Union[dict, str]:
    """
    우리 구현: { "output": ..., "choices":[{"message":{"content": "..."}}, ...] }
    """
    if is_json:
        out = res.get("output")
        if isinstance(out, dict):
            return out
        # choices 경로에서 텍스트 → json 파싱
        try:
            txt = res["choices"][0]["message"]["content"]
            # 코드블록 제거 대응
            txt_clean = txt.strip()
            if txt_clean.startswith("```json"):
                txt_clean = txt_clean.replace("```json", "").replace("```", "").strip()
            try:
                return json.loads(txt_clean)
            except Exception:
                ok, obj = try_parse_json(txt_clean) if 'try_parse_json' in globals() else (False, None)
                return obj if ok else {}
        except Exception:
            return {}
    # text
    out = res.get("output")
    if isinstance(out, str) and out.strip():
        return out
    try:
        return res["choices"][0]["message"]["content"]
    except Exception:
        return ""
    
def _heuristic_doc_type(user_utterance: str, templates: List[dict]) -> str:
    """키워드로 안전하게 doc_type 추정 (LLM 실패/모호 응답 대비)"""
    text = (user_utterance or "").lower()
    options = [t["type"] for t in templates] or ["품의"]

    # 키워드 → 템플릿 이름 매핑 (원하는대로 추가/수정 가능)
    rules = [
        ("품의", ["품의"]),
        ("견적", ["견적", "quotation", "quote"]),
        ("연차", ["연차", "휴가", "annual leave"]),
        ("지출", ["지출", "구매", "발주", "결재", "경비", "송금", "대금", "청구"]),
    ]

    for label, keys in rules:
        if label in options and any(k in text for k in keys):
            return label

    # 그래도 못찾으면 첫 템플릿으로 폴백
    return options[0]

def _llm_call(
    prompt: Optional[str] = None,
    messages: Optional[List[Dict[str, str]]] = None,
    is_json: bool = False,
) -> Union[dict, str]:
    """
    - APP_MODE=mock  → mock 마커 반환
    - POTENS_API_STYLE=prompt → POST {POTENS_API_URL}             with {"prompt": ...}
    - POTENS_API_STYLE=chat   → POST {POTENS_API_URL or */chat* } with {"messages":[...]}
    - 응답 스키마 자동 감지: LLM담당자형({"message":...}) / 우리형({"choices":[...],"output":...})
    """
    # 0) 모드/환경 체크
    if APP_MODE == "mock":
        st.info("APP_MODE=mock: LLM 호출 대신 Mock 응답을 사용합니다.")
        return {"__error__": "APP_MODE=mock"} if is_json else "[MOCK]"

    if not POTENS_API_URL or not POTENS_API_KEY:
        st.error("POTENS_API_URL 또는 POTENS_API_KEY 가 설정되지 않았습니다. Mock으로 동작합니다.")
        return {"__error__": "API Key not configured"} if is_json else "[MOCK]"

    # 1) 공통 파라미터
    params = {
        "temperature": float(os.getenv("POTENS_TEMPERATURE", "0.2")),
        "top_p": float(os.getenv("POTENS_TOP_P", "0.9")),
        "max_tokens": int(os.getenv("POTENS_MAX_TOKENS", "800")),
    }

    # 2) URL 보정 + payload 구성
    style = POTENS_API_STYLE or "chat"
    base = (POTENS_API_URL or "").rstrip("/")

    if style == "prompt":
        if not prompt:
            return {} if is_json else ""
        url = base  # LLM담당자 버전은 루트에 바로 POST
        payload = {**params, "prompt": prompt}
    else:
        # chat(default): 이미 /chat로 끝나있으면 그대로, 아니면 붙인다.
        url = base if base.endswith("/chat") else (base + "/chat")
        if not messages:
            return {} if is_json else ""
        payload = {**params, "messages": messages}

    # 3) 호출
    res, err = _http_post_json(url, payload)
    if err or not isinstance(res, dict):
        return {} if is_json else ""

    # 4) 응답 스키마 자동 파싱
    #   - LLM담당자 스타일: {"message": "..."} (코드펜스 포함 가능)
    if "message" in res and not res.get("choices"):
        return _parse_prompt_style(res, is_json)

    #   - 우리 스타일: {"output": ..., "choices":[{"message":{"content":"..."}}]}
    if res.get("choices") or "output" in res:
        return _parse_chat_style(res, is_json)

    #   - 예외: 둘 다 아니면 안전 폴백
    if is_json:
        # 가능한 텍스트 필드 추출 후 JSON 시도
        text = res.get("message") or res.get("output") or ""
        try:
            return json.loads(text) if text else {}
        except Exception:
            return {}
    else:
        return (res.get("message") or res.get("output") or "").strip()


# ========== 기능 함수들 ==========
# 1) 템플릿 분류
def infer_doc_type(user_utterance: str, templates: List[dict]) -> str:
    options = [t["type"] for t in templates]
    prompt = f"""
## 역할: 직원 요청을 올바른 서식으로 매핑하는 어시스턴트
## 임무: 아래 '선택 가능 서식' 중에서 딱 하나만, 설명 없이 반환하세요.

선택 가능 서식: {json.dumps(options, ensure_ascii=False)}
사용자 요청: "{user_utterance}"
"""
    if POTENS_API_STYLE == "prompt":
        out = _llm_call(prompt=prompt, is_json=False)
    else:
        out = _llm_call(messages=[{"role":"user","content":prompt}], is_json=False)

    doc = str(out).strip() if out else ""
    # LLM 결과가 비었거나 후보에 없으면 휴리스틱으로 보정
    if not doc or doc not in options:
        return _heuristic_doc_type(user_utterance, templates)
    return doc

def infer_doc_type_and_fields(user_utterance: str, templates: List[dict]) -> dict:
    if not templates:
        return {"doc_type": "품의", "required": []}

    context = [{"type": t["type"], "required": t["fields"].get("required", [])} for t in templates][:20]
    prompt = (
        "당신은 문서 템플릿 어시스턴트입니다.\n"
        "아래 사용자 요청에 가장 맞는 문서 유형(doc_type)과 필수필드(required)만 JSON으로 응답하세요.\n"
        "반드시 키는 doc_type, required만 포함하세요.\n\n"
        f"사용자 요청: {user_utterance}\n"
        f"템플릿 후보(요약): {context}\n"
        '출력 예: {"doc_type": "품의", "required": ["금액","근거","기한","승인선"]}'
    )

    if POTENS_API_STYLE == "prompt":
        res = _llm_call(prompt=prompt, is_json=True)
    else:
        res = _llm_call(messages=[{"role":"user","content":prompt}], is_json=True)

    obj = res if isinstance(res, dict) else {}
    obj = normalize_keys(obj) if 'normalize_keys' in globals() else obj

    doc_type = obj.get("doc_type")
    if not doc_type:
        # 완전 실패 → 휴리스틱
        doc_type = _heuristic_doc_type(user_utterance, templates)

    # 템플릿 존재성 보정
    if not any(t["type"] == doc_type for t in templates):
        # 대소문자 보정 후에도 없으면 휴리스틱
        cand = next((t["type"] for t in templates if t["type"].lower() == str(doc_type).lower()), None)
        doc_type = cand or _heuristic_doc_type(user_utterance, templates)

    required = next((x["fields"].get("required", []) for x in templates if x["type"] == doc_type), [])
    return {"doc_type": doc_type, "required": required}

# 2) 초발화 분석 + 질문 (LLM담당자 함수)
def analyze_request_and_ask(user_utterance: str, template: dict) -> dict:
    prompt = f"""
## 역할 및 목표
당신은 직원의 문서 작성을 돕는 꼼꼼한 AI 어시스턴트입니다.
목표: 사용자의 첫 발화에서 가능한 정보를 추출하고, 누락된 필수 필드에 대한 질문을 생성.

문서 종류: "{template.get('type')}"
필수 필드: {json.dumps(template.get('fields', {}), ensure_ascii=False)}
사용자 최초 발화: "{user_utterance}"

JSON 형식으로만 응답:
{{
  "filled_fields": {{}},
  "missing_fields": [],
  "ask": [{{"key":"","question":""}}]
}}
"""
    if POTENS_API_STYLE == "prompt":
        res = _llm_call(prompt=prompt, is_json=True)
    else:
        res = _llm_call(messages=[{"role":"user","content":prompt}], is_json=True)
    # 안전보정
    if not isinstance(res, dict):
        return {"filled_fields": {}, "missing_fields": [], "ask": []}
    return {
        "filled_fields": res.get("filled_fields", {}) or {},
        "missing_fields": res.get("missing_fields", []) or [],
        "ask": res.get("ask", []) or [],
    }

# 2-b) 누락질문 전용 (우리 함수)
def generate_questions(template_fields: dict, user_filled: dict) -> dict:
    required = template_fields.get("required", [])
    pruned = dict(list(user_filled.items())[:50])
    prompt = (
        "당신은 양식 어시스턴트입니다. 다음의 필수 키와 현재 값으로부터 누락된 필드를 찾고, "
        "사용자에게 물어볼 질문 배열을 만드세요. 한국어로 간결히.\n"
        "반드시 JSON으로 응답하며, 키는 required_fields, missing_fields, ask 만 포함하세요.\n"
        f"required_keys = {json.dumps(required, ensure_ascii=False)}\n"
        f"current_values = {json.dumps(pruned, ensure_ascii=False)}\n"
        '출력 예: {"required_fields":["금액","기한"],"missing_fields":["기한"],"ask":[{"key":"기한","question":"기한은 언제까지인가요?"}]}'
    )
    if POTENS_API_STYLE == "prompt":
        res = _llm_call(prompt=prompt, is_json=True)
    else:
        messages=[{"role":"user","content":prompt}]
        # chat 스타일은 json_schema 옵션도 붙일 수 있지만 서버마다 달라 생략
        res = _llm_call(messages=messages, is_json=True)

    if not isinstance(res, dict):
        return {"required_fields": required, "missing_fields": [], "ask": []}

    res = normalize_keys(res) if 'normalize_keys' in globals() else res
    # 스키마 보정
    return {
        "required_fields": list(map(str, res.get("required_fields", required))),
        "missing_fields": list(map(str, res.get("missing_fields", []))),
        "ask": [
            {
                "key": str(x.get("key","")).strip(),
                "question": str(x.get("question","")).strip(),
                "options": [str(o) for o in x.get("options", [])]
            }
            for x in (res.get("ask", []) or []) if isinstance(x, dict)
        ]
    }

# 3) 컨펌 텍스트
def generate_confirm_text(user_filled: dict, template_type: str | None = None) -> str:
    pruned = dict(list(user_filled.items())[:80])
    prompt = (
        "당신은 문서 요약 전문가입니다. 아래 key-value를 바탕으로 대표가 30초 내 의사결정을 할 수 있게 "
        "간결하고 공손한 본문을 생성하세요. 금액/기한/사유/근거는 굵게(**) 표시하고, "
        "누락이나 빈 값은 [ ] 로 표시하세요. 한국어로 작성하세요.\n\n"
        f"{json.dumps(pruned, ensure_ascii=False, indent=2)}"
    )
    if POTENS_API_STYLE == "prompt":
        out = _llm_call(prompt=prompt, is_json=False)
    else:
        out = _llm_call(messages=[{"role":"user","content":prompt}], is_json=False)
    return out if isinstance(out, str) else ""

# 4) 승인용 요약(LLM담당자)
def generate_approval_summary(confirm_text: str) -> dict:
    prompt = f"""
## 역할: 바쁜 경영진용 요약
원본:
{confirm_text}

아래 JSON으로만 응답:
{{"title":"","summary":"","points":["","",""]}}
"""
    if POTENS_API_STYLE == "prompt":
        res = _llm_call(prompt=prompt, is_json=True)
    else:
        res = _llm_call(messages=[{"role":"user","content":prompt}], is_json=True)
    return {
        "title": (res or {}).get("title",""),
        "summary": (res or {}).get("summary",""),
        "points": (res or {}).get("points",[]) or []
    }

# 5) 후속조치 알림(LLM담당자)
def generate_next_step_alert(approved_data: dict) -> str:
    prompt = f"""
## 상황
'{approved_data.get('creator_name','담당 직원')}'의 '{approved_data.get('type','요청')}' 요청이 승인됨.
가장 논리적인 후속 조치 한 문장을 생성.

출력: 한국어 한 문장
"""
    if POTENS_API_STYLE == "prompt":
        out = _llm_call(prompt=prompt, is_json=False)
    else:
        out = _llm_call(messages=[{"role":"user","content":prompt}], is_json=False)
    return str(out).strip()

# 6) 컨펌 텍스트 검증(LLM담당자)
def validate_confirm_text(confirm_text: str, required_fields: list) -> dict:
    prompt = f"""
## 역할: 문서 검수관
본문:
{confirm_text}

필수 항목: {json.dumps(required_fields, ensure_ascii=False)}
JSON으로만 응답:
{{"is_valid": false, "missing": [], "suggestion": ""}}
"""
    if POTENS_API_STYLE == "prompt":
        res = _llm_call(prompt=prompt, is_json=True)
    else:
        res = _llm_call(messages=[{"role":"user","content":prompt}], is_json=True)
    if not isinstance(res, dict):
        return {"is_valid": False, "missing": [], "suggestion": ""}
    return {
        "is_valid": bool(res.get("is_valid", False)),
        "missing": res.get("missing", []) or [],
        "suggestion": res.get("suggestion","") or ""
    }

# 7) 반려 안내문(LLM담당자)
def generate_rejection_note(rejection_memo: str, creator_name: str, doc_title: str) -> str:
    prompt = f"""
## 역할: 정중하고 명확한 반려 안내
문서 제목: "{doc_title}"
작성자: "{creator_name}"
대표 메모: "{rejection_memo}"

2~3문장, 한국어, 정중/구체적으로 작성.
"""
    if POTENS_API_STYLE == "prompt":
        out = _llm_call(prompt=prompt, is_json=False)
    else:
        out = _llm_call(messages=[{"role":"user","content":prompt}], is_json=False)
    return str(out).strip()

# --- Quick debug helper ---
def debug_llm_status():
    return {
        "APP_MODE": os.getenv("APP_MODE"),
        "POTENS_API_STYLE": os.getenv("POTENS_API_STYLE"),
        "POTENS_API_URL": os.getenv("POTENS_API_URL"),
        "HAS_API_KEY": bool(os.getenv("POTENS_API_KEY")),
    }

def debug_llm_ping():
    """엔드포인트 스타일별 최소 호출로 실제 응답을 확인"""
    try:
        if os.getenv("POTENS_API_STYLE","chat").lower() == "prompt":
            payload = {"prompt": "ping"}
            r = requests.post(os.getenv("POTENS_API_URL"), headers=HEADERS, json=payload, timeout=(6,12))
        else:
            payload = {"messages":[{"role":"user","content":"ping"}]}
            url = os.getenv("POTENS_API_URL").rstrip("/") + "/chat"
            r = requests.post(url, headers=HEADERS, json=payload, timeout=(6,12))
        return {"status": r.status_code, "body": r.text[:500]}
    except Exception as e:
        return {"error": str(e)}
