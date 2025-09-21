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

def _llm_call(
    prompt: Optional[str] = None,
    messages: Optional[List[Dict[str, str]]] = None,
    is_json: bool = False
) -> Union[dict, str]:
    """
    - APP_MODE=mock → mock marker 반환
    - POTENS_API_STYLE=prompt → POST {POTENS_API_URL} with {"prompt": ...}
    - POTENS_API_STYLE=chat   → POST {POTENS_API_URL}/chat with {"messages":[...], ...}
    """
    if APP_MODE == "mock":
        st.info("APP_MODE=mock: LLM 호출 대신 Mock 응답을 사용합니다.")
        return {"__error__": "APP_MODE=mock"} if is_json else "[MOCK]"

    if not POTENS_API_URL or not POTENS_API_KEY:
        st.error("POTENS_API_URL 또는 POTENS_API_KEY 가 설정되지 않았습니다. Mock으로 동작합니다.")
        return {"__error__": "API Key not configured"} if is_json else "[MOCK]"

    # 공통 파라미터(벤더별로 무시될 수 있음)
    params = {
        "temperature": float(os.getenv("POTENS_TEMPERATURE", "0.2")),
        "top_p": float(os.getenv("POTENS_TOP_P", "0.9")),
        "max_tokens": int(os.getenv("POTENS_MAX_TOKENS", "800")),
    }

    if POTENS_API_STYLE == "prompt":
        if not prompt:
            return {} if is_json else ""
        url = POTENS_API_URL  # ex: https://ai.potens.ai/api/chat (LLM담당자 버전은 루트에 바로 POST)
        payload = {**params, "prompt": prompt}
        res, err = _http_post_json(url, payload)
        if err or not isinstance(res, dict):
            return {} if is_json else ""
        return _parse_prompt_style(res, is_json)

    # default: chat
    if not messages:
        return {} if is_json else ""
    url = POTENS_API_URL.rstrip("/") + "/chat"
    payload = {**params, "messages": messages}
    res, err = _http_post_json(url, payload)
    if err or not isinstance(res, dict):
        return {} if is_json else ""
    return _parse_chat_style(res, is_json)

# ========== 기능 함수들 ==========
# 1) 템플릿 분류
def infer_doc_type(user_utterance: str, templates: List[dict]) -> str:
    """
    LLM담당자 함수 호환: 문자열 타입만.
    Chat 스타일에서는 system/user 합성으로 동일하게 동작.
    """
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
    doc = str(out).strip()
    # 후보 미스매치 보정
    if doc not in options:
        low = doc.lower()
        cand = next((t for t in options if t.lower()==low), options[0] if options else "품의")
        return cand
    return doc

def infer_doc_type_and_fields(user_utterance: str, templates: List[dict]) -> dict:
    """
    우리 함수 호환: {"doc_type": str, "required": [str]}
    """
    if not templates:
        return {"doc_type": "품의", "required": []}
    # chat 모드에 최적화된 프롬프트
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
    if not obj or not obj.get("doc_type"):
        # 폴백: infer_doc_type 만이라도
        t = infer_doc_type(user_utterance, templates)
        req = next((x["fields"].get("required", []) for x in templates if x["type"] == t), [])
        return {"doc_type": t, "required": req}
    # 템플릿 존재성 보정
    if not any(t["type"] == obj["doc_type"] for t in templates):
        cand = next((t["type"] for t in templates if t["type"].lower()==str(obj["doc_type"]).lower()), templates[0]["type"])
        obj["doc_type"] = cand
    return obj

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
