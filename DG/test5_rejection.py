# test_5_rejection.py

from potens_client import generate_rejection_note

print("--- 5. 반려문 자동 생성 기능 테스트 ---")

# 대표가 남긴 간단한 메모 (입력값)
manager_memo = "견적서 업체 정보가 불분명함. 공식 견적서로 다시 받을 것."

# 반려된 문서 정보 (입력값)
doc_info = {
    "creator_name": "이영희",
    "title": "프로젝트 A 장비 구매 건"
}

# LLM을 호출하여 반려 안내문 생성
rejection_note = generate_rejection_note(
    rejection_memo=manager_memo,
    creator_name=doc_info["creator_name"],
    doc_title=doc_info["title"]
)

print(f"대표 메모: {manager_memo}")
print("-" * 20)
print(f"생성된 안내문:\n{rejection_note}")