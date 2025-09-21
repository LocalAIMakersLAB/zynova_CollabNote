import os
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv
from supabase import create_client
import bcrypt
from datetime import datetime, timedelta, timezone

# .env 불러오기
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------- 공통 ----------
def now_utc_iso():
    return datetime.now(timezone.utc).isoformat()

# ---------- 로그인/회원가입 ----------
def register_profile(name: str, email: str, role: str, password: str):
    """
    profiles(user_id, name, role['rep'|'staff'], email unique, password_hash)
    """
    # role 체크
    if role not in ("rep", "staff"):
        return False, "역할은 rep/staff 중 하나여야 합니다."

    # 이메일 중복
    exists = supabase.table("profiles").select("user_id").eq("email", email).execute()
    if exists.data:
        return False, "이미 가입된 이메일입니다."

    pw_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    # user_id는 DB default가 없으므로 클라이언트가 넣지 않음 → Supabase의 uuid 생성 정책 사용X
    # 권장: DB에서 gen_random_uuid() default를 설정해두면 더 편함
    # 여기서는 upsert 없이 insert만:
    res = supabase.table("profiles").insert({
        "name": name,
        "email": email,
        "role": role,
        "password_hash": pw_hash
    }).execute()
    if not res.data:
        return False, "회원가입 실패(프로필 생성 실패)."
    return True, "회원가입 성공!"

def login_profile(email: str, password: str) -> Optional[Dict[str, Any]]:
    res = supabase.table("profiles").select("*").eq("email", email).execute()
    if not res.data:
        return None
    p = res.data[0]
    ph = p.get("password_hash") or ""
    if not ph:
        return None
    if bcrypt.checkpw(password.encode("utf-8"), ph.encode("utf-8")):
        return p
    return None

def get_profile(user_id: str) -> Optional[Dict[str, Any]]:
    res = supabase.table("profiles").select("*").eq("user_id", user_id).execute()
    return res.data[0] if res.data else None

# ---------- 템플릿 ----------
def get_templates() -> List[Dict[str, Any]]:
    res = supabase.table("templates").select("*").order("type").execute()
    return res.data or []

def get_templates_by_type(doc_type: str) -> Optional[Dict[str, Any]]:
    res = supabase.table("templates").select("*").eq("type", doc_type).limit(1).execute()
    return res.data[0] if res.data else None

# compose용 create_draft/submit_draft는 남겨도 되나 이번 스프린트에선 직접 호출 X (추후 RAG-주도 작성기 준비되면 재사용)
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
        "status": "대기중"
    }).execute()
    return response.data

# -----------------------
# 대표 Approval 관련
# -----------------------
def get_pending_approvals(assignee_id, status="대기중"):
    """특정 대표의 승인 요청 가져오기"""
    res = supabase.table("approvals") \
        .select("*") \
        .eq("assignee", assignee_id) \
        .eq("status", status) \
        .execute()
    return res.data

def update_approval_status(approval_id, status, reason=None):
    """승인/반려 처리"""
    update_data = {"status": status, "decided_at": "now()"}
    if reason:
        update_data["reject_reason"] = reason

    res = supabase.table("approvals").update(update_data).eq("approval_id", approval_id).execute()
    return res.data

# -----------------------
# 후속 일정 (Todo)
# -----------------------
def create_todo(approval_id: str, owner: str, title: str, due_at=None):
    if due_at is None:
        due_at = datetime.utcnow() + timedelta(days=1)
        
    # datetime → ISO string 변환
    if isinstance(due_at, datetime):
        due_at = due_at.isoformat()

    """승인 완료 시 후속 일정 생성"""
    response = supabase.table("todos").insert({
        "approval_id": approval_id,
        "owner": owner,
        "title": title,
        "due_at": due_at,
        "done": False
    }).execute()
    return response.data

    #에러 확인 
    if response.error:
        print("create_todo ERROR:", response.error)
    else:
        print("create_todo SUCCESS:", response.data)

    return response.data

def get_todos(owner_id: str):
    """개인 Todo 조회"""
    response = supabase.table("todos").select("*").eq("owner", owner_id).execute()
    return response.data

def delete_todo(todo_id: str):
    """완료된 Todo 삭제"""
    response = supabase.table("todos").delete().eq("todo_id", todo_id).execute()
    return response.data

def get_user_rejected_requests(user_id):
    """
    특정 직원의 반려된 요청 목록을 가져옵니다.
    """
    try:
        # 1. drafts 테이블에서 현재 사용자가 생성한 모든 draft_id를 가져옵니다.
        draft_res = supabase.table("drafts").select("draft_id").eq("creator", user_id).execute()
        draft_ids = [item['draft_id'] for item in draft_res.data]
        
        if not draft_ids:
            return []

        # 2. approvals 테이블에서 위 draft_id를 참조하고 status가 '반려'인 문서를 가져옵니다.
        res = supabase.table("approvals").select("*").in_("draft_id", draft_ids).eq("status", "반려").order("created_at", desc=True).execute()
        
        return res.data if res.data else []
        
    except Exception as e:
        print(f"Error fetching rejected requests: {e}")
        return []
