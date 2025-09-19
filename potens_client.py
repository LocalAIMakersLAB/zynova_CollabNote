import os, requests, json
APP_MODE = os.getenv("APP_MODE", "live")
POTENS_API_URL = os.getenv("POTENS_API_URL")
POTENS_API_KEY = os.getenv("POTENS_API_KEY")
TIMEOUT = int(os.getenv("POTENS_TIMEOUT_SEC", "12"))

HEADERS = {"Authorization": f"Bearer {POTENS_API_KEY}", "Content-Type": "application/json"}

def _safe_post(payload):
    try:
        r = requests.post(f"{POTENS_API_URL}/chat", headers=HEADERS, json=payload, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"__error__": str(e)}

# 1) 누락 필드 질문 생성
def generate_questions(template_fields: dict, user_filled: dict):
    required = template_fields.get("required", [])
    if APP_MODE != "live":
        return _mock_questions(required, user_filled)

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
        return res["output"] if "output" in res else res  # Potens 응답 형식에 맞춰 조정
    except Exception:
        return _mock_questions(required, user_filled)

def _mock_questions(required, user_filled):
    missing = [k for k in required if not user_filled.get(k)]
    return {
        "required_fields": required,
        "missing_fields": missing,
        "ask":[{"key":m, "question": f"{m} 값을 입력해주세요."} for m in missing]
    }

# 2) 컨펌 텍스트 생성
def generate_confirm_text(user_filled: dict, guide_md: str = ""):
    if APP_MODE != "live":
        return _mock_confirm(user_filled)

    prompt = f"""아래 key-value를 바탕으로 대표가 30초 내 의사결정할 수 있게 컨펌용 본문을 만들어줘.
- 금액, 기한, 사유, 근거, 책임자 등 의사결정 포인트는 굵게(**) 처리
- 누락/빈값은 [ ] 로 명확히 표시
- 톤은 간결하고 공손하게

가이드(참고, 선택): {guide_md}

데이터:
{json.dumps(user_filled, ensure_ascii=False, indent=2)}"""

    payload = {"messages":[{"role":"user","content":prompt}]}
    res = _safe_post(payload)
    if "__error__" in res:
        return _mock_confirm(user_filled)
    try:
        # Potens가 text를 res["choices"][0]["message"]["content"]로 준다면 그에 맞춰 파싱
        return res.get("output") or res["choices"][0]["message"]["content"]
    except Exception:
        return _mock_confirm(user_filled)

def _mock_confirm(filled):
    lines = [f"- {k}: {v}" for k,v in filled.items()]
    return "다음과 같이 확인되었습니다:\n" + "\n".join(lines)
# potens_client.py (새 함수)
def infer_doc_type_and_fields(user_utterance: str, templates: list[dict]):
    """
    입력 문장(자연어)을 받아 적합한 문서 유형(type)과 필수/선택 필드 키를 리턴.
    templates: [{"type":"품의","fields":{required:[...], optional:[...]}, "guide_md":"..."}...]
    반환 예:
    {"doc_type":"지출", "required":["amount","reason","due","approver"], "optional":["evidence"], "guide_md":"..."}
    """
    # APP_MODE가 mock이면 간단 매핑
    from os import getenv
    if getenv("APP_MODE", "live") != "live":
        # 매우 단순한 규칙 예시
        if "연차" in user_utterance: t = "연차"
        elif "지출" in user_utterance or "구매" in user_utterance: t = "지출"
        else: t = templates[0]["type"] if templates else "품의"
        tpl = next((x for x in templates if x["type"] == t), None) or templates[0]
        return {
            "doc_type": t,
            "required": tpl["fields"].get("required", []),
            "optional": tpl["fields"].get("optional", []),
            "guide_md": tpl.get("guide_md","")
        }

    # live: 템플릿들을 짧게 요약해 context로 넘기고, 사용자 발화와 매칭
    # (실제 구현은 너희 Potens API 스펙에 맞춰 messages/response_format 구성)
    context = [{"type": t["type"], "required": t["fields"].get("required", []), "optional": t["fields"].get("optional", [])} for t in templates]
    prompt = f"""다음 템플릿 후보 중, 사용자의 요청에 가장 맞는 문서 유형과 필수/선택 필드를 골라 JSON으로만 응답하세요.
사용자요청: {user_utterance}
후보템플릿: {context}
응답 스키마: {{"doc_type": str, "required": [str], "optional":[str], "guide_md": str}}"""

    res = _safe_post({"messages":[{"role":"user","content":prompt}]})
    # 실패 시 mock으로 폴백
    try:
        return res.get("output") or json.loads(res["choices"][0]["message"]["content"])
    except Exception:
        return infer_doc_type_and_fields(user_utterance, templates)  # mock 경로
