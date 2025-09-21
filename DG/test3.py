# test_3_summary.py

import json
from potens_client import generate_approval_summary

print("--- 3. 승인 요약 생성 기능 테스트 ---")

# 2번 테스트에서 생성된 것과 유사한 컨펌 텍스트 (입력값)
confirm_text_sample = """
**[프로젝트 A] 테스트 장비 교체 품의**

**사유:** 프로젝트 A 진행에 필수적인 테스트 장비의 노후화가 심각하여, 원활한 프로젝트 수행을 위해 신규 장비로 교체하고자 합니다.
**금액:** **1,200,000원**
**기한:** **2025-09-30** 까지 구매 완료 필요
**근거:** 상세 내용은 첨부된 신규 장비 견적서를 참고해 주시기 바랍니다.
**승인선:** 김철수 대표님

검토 후 승인 부탁드립니다.
"""

summary_result = generate_approval_summary(confirm_text_sample)
print(json.dumps(summary_result, indent=2, ensure_ascii=False))