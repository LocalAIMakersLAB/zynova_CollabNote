import os
from dotenv import load_dotenv
from supabase import create_client
import bcrypt
from datetime import date

# .env 불러오기
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# -----------------------
# 템플릿 불러오기
# -----------------------
def get_templates():
    response = supabase.table("templates").select("*").execute()
    if response.data:
        return response.data
    return []

# drafts -> 직원이 작성 중/제출 전 초안 저장
# approvals -> 대표 inbox용 승인 요청 저장

# -----------------------
# 직원 Draft 관련
# -----------------------
def create_draft(creator_id: str, doc_type: str, filled: dict, missing: list, confirm_text: str):
    """직원이 초안 생성"""
    response = supabase.table("drafts").insert({
        "creator": creator_id,
        "type": doc_type,
        "filled": filled,
        "missing": missing,
        "confirm_text": confirm_text,
        "status": "editing"
    }).execute()
    return response.data

def submit_draft(draft_id: str, title: str, summary: str, assignee: str, due_date: str):
    """승인 요청 제출 → drafts 상태 업데이트 + approvals 생성"""
    # 1) draft 상태 업데이트
    supabase.table("drafts").update({"status": "submitted"}).eq("draft_id", draft_id).execute()

    # 2) approvals 생성
    draft = supabase.table("drafts").select("*").eq("draft_id", draft_id).execute().data[0]
    response = supabase.table("approvals").insert({
        "draft_id": draft_id,
        "title": title,
        "summary": summary,
        "confirm_text": draft["confirm_text"],
        "assignee": assignee,
        "due_date": due_date,
        "status": "pending"
    }).execute()
    return response.data

# -----------------------
# 대표 Approval 관련
# -----------------------
def get_pending_approvals(assignee_id: str):
    """대표 Inbox: 승인 대기 문서 조회"""
    response = supabase.table("approvals").select("*").eq("assignee", assignee_id).eq("status", "pending").execute()
    return response.data

def update_approval_status(approval_id: str, status: str, reject_reason: str = None):
    """대표가 승인/반려 처리"""
    update_data = {"status": status, "decided_at": "now()"}
    if status == "rejected":
        update_data["reject_reason"] = reject_reason

    response = supabase.table("approvals").update(update_data).eq("approval_id", approval_id).execute()
    return response.data

# -----------------------
# 후속 일정 (Todo)
# -----------------------
def create_todo(approval_id: str, owner_id: str, title: str, due_at: str):
    """승인 완료 시 후속 일정 생성"""
    response = supabase.table("todos").insert({
        "approval_id": approval_id,
        "owner": owner_id,
        "title": title,
        "due_at": due_at,
        "done": False
    }).execute()
    return response.data

def get_todos(owner_id: str):
    """개인 Todo 조회"""
    response = supabase.table("todos").select("*").eq("owner", owner_id).execute()
    return response.data