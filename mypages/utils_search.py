# mypages/utils_search.py
import time
import re
from typing import List, Dict, Any, Tuple, Optional
from ddgs import DDGS

# ------------------------------
# 0) 공통 유틸 (일단 타이틀로 분류시켜봄)
# ------------------------------
def _ddg_text(query: str, *, region: Optional[str] = None, timelimit: Optional[str] = None, max_results: int = 8) -> List[Dict[str, Any]]:
    with DDGS() as ddgs:
        return list(ddgs.text(
            keywords=query,
            region=region,           # 예: 'kr-kr'
            timelimit=timelimit,     # 'd','w','m','y' 또는 None
            max_results=max_results,
            safesearch="moderate"
        ))

def _mk_attempt(q: str, hits: List[Dict[str, Any]], note: str) -> Tuple[str, int, str]:
    return (q, len(hits), note)

def _choose_text(h: Dict[str, Any]) -> Tuple[str, str, str]:
    title = h.get("title") or h.get("heading") or ""
    url   = h.get("href")  or h.get("url")     or ""
    text  = h.get("body")  or h.get("description") or ""
    return title.strip(), url, (text or "").strip()

# ------------------------------
# 1) 간단 의도 감지 (키워드 기반) -> 테스트용임 LLM응답 전
# ------------------------------
INTENTS = {
    "price":      re.compile(r"(가격|얼마|비용|cost|price|시세|견적)", re.I),
    "spec":       re.compile(r"(스펙|사양|제원|spec|규격|성능|벤치|benchmark)", re.I),
    "define":     re.compile(r"(정의|설명|무엇|what is|뜻|개념)", re.I),
    "howto":      re.compile(r"(방법|하는 법|튜토리얼|설치|해결|troubleshoot|how to)", re.I),
    "law":        re.compile(r"(법|법령|조항|규정|고시|법률|시행령|시행규칙)", re.I),
    "wiki":       re.compile(r"(위키|wikipedia|백과)", re.I),
    "news":       re.compile(r"(뉴스|보도|속보|최근 이슈|breaking|today|최근)", re.I),
    "academic":   re.compile(r"(논문|paper|arxiv|학술|cite|레퍼런스)", re.I),
    "shop":       re.compile(r"(구매|사다|최저가|쇼핑|buy|amazon|쿠팡|11번가|gmarket)", re.I),
    "devdoc":     re.compile(r"(에러|오류|문법|docs|documentation|api|reference)", re.I),
}

def detect_intent(q: str) -> str:
    for name, rx in INTENTS.items():
        if rx.search(q):
            return name
    # 기본: 정의/설명 or 일반 검색
    return "define"

# ------------------------------
# 2) 의도별 전략 프리셋
# ------------------------------
def _strategies_for_intent(q_base: str, intent: str) -> List[Tuple[str, Optional[str], Optional[str], str]]:
    """(query, region, timelimit, note) 목록 반환"""
    KR = "kr-kr"
    # 기본 후보 키워드 확장 (ko/en 혼합)
    price_terms = [" 가격", " 얼마", " KRW", " ₩", " price", " cost"]
    spec_terms  = [" 스펙", " 제원", " 사양", " spec", " specification"]
    how_terms   = [" 방법", " 튜토리얼", " 설치", " 사용법", " guide", " tutorial", " how to"]
    law_terms   = [" 법령", " 조항", " 규정", " 법률", " 시행령", " 시행규칙"]
    news_limit  = "w"  # 최근 1주 (필요시 'd','m','y' 조정)

    if intent == "price":
        cands = [q_base + t for t in price_terms]
        return [
            (cands[0], KR, "m", "KR+최근1개월"),
            (cands[1], KR, None, "KR+전체기간"),
            (q_base + " 가격 site:apple.com/kr", KR, None, "KR+공식도메인(예시)"),
            (q_base + " price site:amazon.com", None, None, "영문+아마존"),
            (q_base + " price", None, None, "영문+일반"),
            (q_base + " 가격", None, None, "전역+한글"),
        ]

    if intent == "spec":
        cands = [q_base + t for t in spec_terms]
        return [
            (cands[0], KR, None, "KR+스펙"),
            (q_base + " site:wikipedia.org", None, None, "위키"),
            (q_base + " spec site:gsmarena.com", None, None, "전자기기/폰 스펙"),
            (q_base + " datasheet", None, None, "데이터시트"),
        ]

    if intent == "howto":
        cands = [q_base + t for t in how_terms]
        return [
            (cands[0], KR, None, "KR+튜토리얼"),
            (q_base + " site:docs.python.org", None, None, "파이썬 문서(예시)"),
            (q_base + " site:stackoverflow.com", None, None, "스택오버플로"),
            (q_base + " site:learn.microsoft.com", None, None, "MS Docs"),
            (q_base + " tutorial", None, None, "영문 튜토리얼"),
        ]

    if intent == "law":
        cands = [q_base + t for t in law_terms]
        return [
            (cands[0], KR, None, "KR+법령 키워드"),
            (q_base + " site:law.go.kr", KR, None, "법제처"),
            (q_base + " site:data.go.kr", KR, None, "공공데이터"),
        ]

    if intent == "wiki":
        return [
            (q_base + " site:wikipedia.org", None, None, "위키"),
            (q_base, KR, None, "KR 일반"),
        ]

    if intent == "news":
        return [
            (q_base, KR, news_limit, "KR+최근"),
            (q_base + " site:news.naver.com", KR, news_limit, "네이버뉴스"),
            (q_base + " site:khan.co.kr", KR, news_limit, "경향"),
            (q_base + " site:hankyoreh.com", KR, news_limit, "한겨레"),
            (q_base + " site:chosun.com", KR, news_limit, "조선"),
        ]

    if intent == "academic":
        return [
            (q_base + " arxiv", None, None, "arXiv"),
            (q_base + " site:acm.org", None, None, "ACM"),
            (q_base + " site:ieee.org", None, None, "IEEE"),
            (q_base + " site:springer.com", None, None, "Springer"),
        ]

    if intent == "shop":
        return [
            (q_base + " 가격", KR, None, "KR"),
            (q_base + " site:apple.com/kr", KR, None, "공홈(예시)"),
            (q_base + " site:coupang.com", KR, None, "쿠팡"),
            (q_base + " site:gmarket.co.kr", KR, None, "G마켓"),
            (q_base + " site:11st.co.kr", KR, None, "11번가"),
        ]

    if intent == "devdoc":
        return [
            (q_base + " docs", None, None, "문서"),
            (q_base + " site:stackoverflow.com", None, None, "스택오버플로"),
            (q_base + " site:readthedocs.io", None, None, "ReadTheDocs"),
            (q_base + " site:github.com", None, None, "GitHub"),
        ]

    # 기본(정의/설명)
    return [
        (q_base, KR, None, "KR 일반"),
        (q_base + " site:wikipedia.org", None, None, "위키"),
        (q_base + " meaning", None, None, "영문 정의"),
    ]

# ------------------------------
# 3) 범용 검색 (의도 감지 → 단계적 축소/완화)
# ------------------------------
def search_general_narrow(user_query: str) -> Dict[str, Any]:
    attempts: List[Tuple[str, int, str]] = []
    errors:   List[Tuple[str, str]] = []
    results:  List[Dict[str, Any]] = []

    q_base = (user_query or "").strip()
    if not q_base:
        return {"results": [], "attempts": [], "errors": []}

    intent = detect_intent(q_base)
    strategies = _strategies_for_intent(q_base, intent)

    for q, region, tl, note in strategies:
        try:
            hits = _ddg_text(q, region=region, timelimit=tl, max_results=10)
            attempts.append(_mk_attempt(q, hits, note))
            if hits:
                results = hits
                break
        except Exception as e:
            errors.append((q, str(e)))
            time.sleep(0.8)  # rate limit 완화

    return {"results": results, "attempts": attempts, "errors": errors, "intent": intent}

# ------------------------------
# 4) 스니펫/가격 추출
# ------------------------------
_PRICE_RX = re.compile(r"(₩\s?[\d,]+|\d{2,3}\s*만\s*원|\$\s?[\d,]+)", re.I)

def extract_snippets(hits: List[Dict[str, Any]], top_k: int = 5, extract_price: bool = True) -> List[Dict[str, str]]:
    out = []
    for h in hits[:top_k]:
        title, url, text = _choose_text(h)
        price = None
        if extract_price:
            m = _PRICE_RX.search(f"{title} {text}")
            price = m.group(0) if m else None
        out.append({
            "title": title,
            "url": url,
            "snippet": text[:240],
            "price": price
        })
    return out

def render_answer_from_hits(hits: List[Dict[str, Any]], intent: str) -> str:
    items = extract_snippets(hits, top_k=5, extract_price=(intent in ("price","shop")))
    lines = []
    for it in items:
        price = f" (추정가격: {it['price']})" if it["price"] else ""
        lines.append(f"• {it['title']}{price}\n  {it['url']}\n  {it['snippet']}")
    return "관련 결과:\n" + "\n\n".join(lines)
