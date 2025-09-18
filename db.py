import os
from dotenv import load_dotenv
from supabase import create_client
import bcrypt

# .env 불러오기
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------------------------
# 회원가입 / 로그인 관련
# ---------------------------

def register_user(username, password, company_name, company_code, role="직원"):
    """
    회원가입 함수
    - 같은 이메일(ID)이 있으면 실패
    - 회사가 없으면 새로 생성
    - 해당 회사의 첫 가입자는 자동으로 '대표' 역할 부여
    - 비밀번호는 bcrypt 해싱 후 저장
    """
    # 사용자 중복 확인
    exists = supabase.table("users").select("*").eq("username", username).execute()
    if exists.data:
        return False, "이미 존재하는 사용자 ID입니다."

    # 회사 ID 확보
    company_id, error = get_or_create_company(company_name, company_code)
    if error:
        return False, error

    # 회사의 첫 유저라면 '대표'로 지정
    company_users = supabase.table("users").select("*").eq("company_id", company_id).execute()
    if not company_users.data:
        role = "대표"

    # 비밀번호 해싱
    hashed_pw = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    # 사용자 삽입
    supabase.table("users").insert({
        "username": username,
        "password": hashed_pw,
        "company_id": company_id,
        "role": role
    }).execute()
    return True, f"✅ 회원가입 성공! (역할: {role})"


def get_user(username, password):
    """
    로그인 함수
    - 이메일(ID)로 사용자 조회
    - 입력 비밀번호와 해싱된 비밀번호 비교
    """
    response = supabase.table("users").select("*").eq("username", username).execute()
    if not response.data:
        return None

    user = response.data[0]
    # 비밀번호 검증
    if bcrypt.checkpw(password.encode("utf-8"), user["password"].encode("utf-8")):
        return user
    return None

# ---------------------------
# 회사 생성 또는 기존 회사 검증
# ---------------------------

def get_or_create_company(company_name, company_code):
    """
    회사명 + 회사코드로 회사 확인
    - 이미 있으면 코드 일치 여부 확인
    - 없으면 새로 생성
    """
    company = supabase.table("companies").select("*").eq("name", company_name).execute()
    if company.data:
        if company.data[0]["company_code"] == company_code:
            return company.data[0]["id"], None
        else:
            return None, "❌ 회사 코드가 올바르지 않습니다."
    else:
        new_company = supabase.table("companies").insert({
            "name": company_name,
            "company_code": company_code
        }).execute()
        return new_company.data[0]["id"], None


def get_companies():
    """
    모든 회사 목록 조회 (회원가입 시 자동완성 등에 사용)
    """
    response = supabase.table("companies").select("*").execute()
    return response.data if response.data else []


def get_user_by_id(user_id: int):
    """
    user_id로 사용자 조회
    - 승인 흐름 등에서 유저 상세 조회할 때 사용
    """
    res = supabase.table("users").select("*").eq("id", user_id).execute()
    return res.data[0] if res.data else None

# ---------------------------
# Task 관련
# ---------------------------

def insert_task(title, description, due_date, created_by):
    supabase.table("tasks").insert({
        "title": title,
        "description": description,
        "due_date": due_date.isoformat(),
        "status": "pending",
        "created_by": created_by
    }).execute()

def get_tasks(company_id):
    # 회사 내 모든 요청
    res = supabase.table("tasks").select("*").execute()
    return res.data if res.data else []

def get_tasks_by_user(user_id):
    res = supabase.table("tasks").select("*").eq("created_by", user_id).execute()
    return res.data if res.data else []

def update_task_status(task_id, status):
    supabase.table("tasks").update({"status": status}).eq("id", task_id).execute()
