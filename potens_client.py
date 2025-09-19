# Potens API 호출 모듈 
import os
import requests
from dotenv import load_dotenv

load_dotenv()
POTENS_API_URL = os.getenv("POTENS_API_URL")
POTENS_API_KEY = os.getenv("POTENS_API_KEY")

headers = {"Authorization": f"Bearer {POTENS_API_KEY}"}

def generate_questions(template_fields, user_input):
    """Mock: 필수 필드 중 빠진 항목을 질문으로 반환"""
    required = template_fields.get("required", [])
    missing = [f for f in required if f not in user_input]

    return {
        "required_fields": required,
        "missing_fields": missing,
        "ask": [{"key": m, "question": f"{m}을 입력해주세요."} for m in missing]
    }

def generate_confirm_text(filled):
    """Mock confirm text"""
    text = "다음과 같이 확인되었습니다:\n"
    for k,v in filled.items():
        text += f"- {k}: {v}\n"
    return text

# 실제 Potens API 호출할 경우
def call_potens_api(payload):
    response = requests.post(
        f"{POTENS_API_URL}/chat",
        headers=headers,
        json=payload
    )
    return response.json()
