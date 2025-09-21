# test_classifier.py

from potens_client import infer_doc_type
from db import get_templates # 테스트용 db.py 사용

print("--- 문서 종류 분류 기능 테스트 ---")

# 테스트 케이스
test_utterance = "프로젝트 A 때문에 장비 사야 하는데 120만원 정도 들어요. 서류 좀 쓰게 도와주세요."

# 1. DB에서 선택 가능한 템플릿 목록 전체를 가져옴
all_templates = get_templates()

# 2. LLM에게 분류 요청
result_type = infer_doc_type(test_utterance, all_templates)

# 3. 결과 출력
print(f"사용자 요청: {test_utterance}")
print(f"분류 결과: {result_type}") # 예상 결과: 품의
