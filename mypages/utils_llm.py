import json, time, math
from typing import Any, Dict, Tuple

SAFE_JSON_PREFIXES = ["```json", "```", "\n", "JSON:", "Output:", "응답:"]

def strip_json_fence(s: str) -> str:
    if not isinstance(s, str):
        return s
    t = s.strip()
    for p in SAFE_JSON_PREFIXES:
        if t.startswith(p):
            t = t[len(p):].strip()
    if t.endswith("```"):
        t = t[:-3].strip()
    return t

def try_parse_json(s: str) -> Tuple[bool, Any]:
    t = strip_json_fence(s)
    try:
        return True, json.loads(t)
    except Exception:
        return False, None

def backoff_sleep(attempt: int, base: float = 0.6, cap: float = 8.0):
    # 지수 백오프 + 가드
    time.sleep(min(cap, base * (2 ** attempt)))

def normalize_keys(d: Dict[str, Any]) -> Dict[str, Any]:
    # 키 표준화(영/한 혼용 방지). 필요에 따라 확장
    if not isinstance(d, dict):
        return d
    mapping = {
        "required_fields": ["required", "필수항목", "required_fields"],
        "missing_fields": ["missing", "누락", "missing_fields"],
        "ask": ["questions", "ask", "질문"],
        "doc_type": ["type", "문서유형", "doc_type"],
    }
    out = {}
    for std_key, aliases in mapping.items():
        for a in aliases:
            if a in d:
                out[std_key] = d[a]
                break
    # 원본 키들도 유지
    for k, v in d.items():
        if k not in out:
            out[k] = v
    return out

def validate_keys(obj: Dict[str, Any], required_keys) -> bool:
    if not isinstance(obj, dict):
        return False
    return all(k in obj for k in required_keys)
