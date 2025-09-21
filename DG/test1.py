# test_llm.py
import json
from potens_client_dg import analyze_request_and_ask
from db import get_templates_by_type # db.py에 이 함수가 있다고 가정

print("LLM 기능 테스트 시작...")

# 테스트 케이스
test_utterance = "품의서 작성 도와줘. 프로젝트 A 장비 구매 건이고, 금액은 120만원이야."
template = get_templates_by_type("품의") # DB에서 품의서 템플릿 정보 가져오기

if template:
    # 함수 호출
    result = analyze_request_and_ask(test_utterance, template)

    # 결과 출력
    print("----- LLM 응답 결과 -----")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("-------------------------")
else:
    print("오류: '품의서' 템플릿을 찾을 수 없습니다.")
