import os, requests, json
from os import getenv
import streamlit as st
from typing import List, Dict, Any

APP_MODE = os.getenv("APP_MODE", "live")
POTENS_API_URL = os.getenv("POTENS_API_URL")
POTENS_API_KEY = os.getenv("POTENS_API_KEY")
TIMEOUT = int(os.getenv("POTENS_TIMEOUT_SEC", "12"))

HEADERS = {"Authorization": f"Bearer {POTENS_API_KEY}", "Content-Type": "application/json"}

# API 호출을 시도하고, 오류 발생 시 오류 메시지 반환
def _safe_post(payload: dict) -> dict:
    if not POTENS_API_URL or not POTENS_API_KEY:
        st.error("Potens AI API URL 또는 Key가 설정되지 않았습니다. Mock 모드로 작동합니다.")
        return {"__error__": "API Key not configured"}
    
    try:
        r = requests.post(f"{POTENS_API_URL}/chat", headers=HEADERS, json=payload, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    
    except Exception as e:
        return {"__error__": str(e)}
        print("API에 전송되는 페이로드:")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        res = _safe_post(payload)
        

# 1) 문서 유형 및 필드 추론
def infer_doc_type_and_fields(user_utterance: str, templates: list[dict]):
    """입력 문장을 받아 적합한 문서 유형과 필수 필드를 리턴합니다."""
    # 라이브 모드: 템플릿 후보를 최소한으로 요약해 컨텍스트에 넘김 (LLM 응답 속도 최적화)
    context = [{"type": t["type"], "required": t["fields"].get("required", [])} for t in templates]
    prompt = f"""
    ## 역할: 문서 어시스턴트
    ## 임무: 다음 템플릿 후보 중, 사용자의 요청에 가장 맞는 문서 유형과 필수 필드를 찾아 JSON으로만 응답하세요.
    ## 사용자 요청: {user_utterance}
    ## 후보 템플릿: {context}
    ## 응답 스키마: {{"doc_type": str, "required": [str]}}"""
    
    res = _safe_post({"messages":[{"role":"user","content":prompt}]})

    # 오류 시 Mock으로 폴백
    if "__error__" in res:
        return _mock_infer_doc_type(user_utterance, templates)

    try:
        return res["output"] if "output" in res else json.loads(res["choices"][0]["message"]["content"])
    except Exception as e:
        st.error(f"LLM 응답 파싱 실패: {e}")
        return _mock_infer_doc_type(user_utterance, templates)

# 2) 누락 필드 질문 생성
def generate_questions(template_fields: dict, user_filled: dict):
    required = template_fields.get("required", [])
    prompt = f"""You are a form-assistant. Given the required field keys and current partial values,
return JSON with required_fields, missing_fields, and ask[] (key, question, optional options).
Only ask for fields that are missing. Be concise, Korean output.

required_keys = {json.dumps(required, ensure_ascii=False)}
current_values = {json.dumps(user_filled, ensure_ascii=False)}"""

    payload = {
        "messages":[{"role":"user","content":prompt}],
        "response_format":{
            "type":"json_schema",
            "json_schema":{
                "name":"missing_fields_schema",
                "schema":{
                    "type":"object",
                    "properties":{
                        "required_fields":{"type":"array","items":{"type":"string"}},
                        "missing_fields":{"type":"array","items":{"type":"string"}},
                        "ask":{"type":"array","items":{
                            "type":"object",
                            "properties":{
                                "key":{"type":"string"},
                                "question":{"type":"string"},
                                "options":{"type":"array","items":{"type":"string"}}
                            },
                            "required":["key","question"]
                        }}},
                    "required":["required_fields","missing_fields","ask"]
                }
            }
        }
    }
    res = _safe_post(payload)

    if "__error__" in res:
        return _mock_questions(required, user_filled)
    try:
        return res["output"] if "output" in res else res
    except Exception as e:
        st.error(f"LLM 응답 파싱 실패: {e}")
        return _mock_questions(required, user_filled)

# 3) 컨펌 텍스트 생성 
def generate_confirm_text(user_filled: dict):
    prompt = f"""
    ## 역할: 문서 요약 전문가
    ## 임무: 아래 key-value를 바탕으로 대표가 30초 내 의사결정할 수 있게 컨펌용 본문을 만들어줘.
    - 금액, 기한, 사유, 근거 등 의사결정 포인트는 굵게(**) 처리
    - 누락/빈값은 [ ] 로 명확히 표시
    - 톤은 간결하고 공손하게

    ## 데이터:
    {json.dumps(user_filled, ensure_ascii=False, indent=2)}"""

    payload = {"messages":[{"role":"user","content":prompt}]}
    res = _safe_post(payload)

    if "__error__" in res:
        return _mock_confirm(user_filled)
    try:
        return res.get("output") or res["choices"][0]["message"]["content"]
    except Exception as e:
        st.error(f"LLM 응답 파싱 실패: {e}")
        return _mock_confirm(user_filled)

# --- Mock 함수들 (오류 시 폴백용) ---
def _mock_infer_doc_type(user_utterance: str, templates: list[dict]):
    if "연차" in user_utterance: t = "연차"
    elif "지출" in user_utterance or "구매" in user_utterance: t = "지출"
    else: t = templates[0]["type"] if templates else "품의"
    tpl = next((x for x in templates if x["type"] == t), None) or templates[0]
    return {
        "doc_type": t,
        "required": tpl["fields"].get("required", []),
        "guide_md": tpl.get("guide_md","")
    }

def _mock_questions(required: List[str], user_filled: Dict[str, Any]) -> Dict[str, Any]:
    missing = [k for k in required if not user_filled.get(k)]
    return {
        "required_fields": required,
        "missing_fields": missing,
        "ask": [{"key": m, "question": f"{m} 값을 입력해주세요."} for m in missing]
    }

def _mock_confirm(filled: Dict[str, Any]) -> str:
    lines = [f"- {k}: {v}" for k,v in filled.items()]
    return "다음과 같이 확인되었습니다:\n" + "\n".join(lines)
