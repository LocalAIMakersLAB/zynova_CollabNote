# test_4_alert.py

from potens_client import generate_next_step_alert

print("--- 4. 후속 알림 생성 기능 테스트 ---")

# 승인된 요청 정보를 가정한 테스트 데이터
approved_data = {
    "type": "품의서",
    "creator_name": "이영희",
    "title": "프로젝트 A 장비 구매 건"
}

alert_message = generate_next_step_alert(approved_data)
print(alert_message)