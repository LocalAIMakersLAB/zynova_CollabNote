# test_2_confirm.py

from potens_client import generate_confirm_text

print("--- 2. 컨펌 텍스트 생성 기능 테스트 ---")

# 모든 정보가 채워졌다고 가정한 테스트 데이터
filled_data = {
    "금액": "1,200,000원",
    "사유": "프로젝트 A 테스트용 장비 노후화로 인한 교체",
    "근거": "기존 장비 구매 내역 및 신규 장비 견적서 첨부",
    "기한": "2025-09-30",
    "승인선": "김철수 대표님"
}

confirm_text = generate_confirm_text(filled_data, "품의서")
print(confirm_text)