# db.py
import os
from datetime import datetime, timezone, date
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv
from supabase import create_client
import bcrypt

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

def get_template_by_type(doc_type: str) -> Optional[Dict[str, Any]]:
    res = supabase.table("templates").select("*").eq("type", doc_type).limit(1).execute()
    return res.data[0] if res.data else None

# ---------- Drafts ----------
def create_draft(creator_id: str, doc_type: str, filled: dict, missing: list, confirm_text: str):
    res = supabase.table("drafts").insert({
        "creator": creator_id,
        "type": doc_type,
        "filled": filled,
        "missing": missing,
        "confirm_text": confirm_text,
        "status": "editing"
    }).execute()
    return res.data

def submit_draft(draft_id: str, title: str, summary: str, assignee: str, due_date: str):
    supabase.table("drafts").update({"status": "submitted"}).eq("draft_id", draft_id).execute()
    draft = supabase.table("drafts").select("*").eq("draft_id", draft_id).single().execute().data
    res = supabase.table("approvals").insert({
        "draft_id": draft_id,
        "title": title,
        "summary": summary,
        "confirm_text": draft.get("confirm_text"),
        "assignee": assignee,
        "due_date": due_date,
        "status": "pending"
    }).execute()
    return res.data

# ---------- Approvals ----------
def get_pending_approvals(assignee_id: str):
    res = supabase.table("approvals").select("*").eq("assignee", assignee_id).eq("status","pending").order("created_at").execute()
    return res.data or []

def update_approval_status(approval_id: str, status: str, reject_reason: Optional[str] = None):
    update_data = {"status": status, "decided_at": now_utc_iso()}
    if status == "rejected" and reject_reason:
        update_data["reject_reason"] = reject_reason
    res = supabase.table("approvals").update(update_data).eq("approval_id", approval_id).execute()
    return res.data

# ---------- Todos ----------
def create_todo(approval_id: str, owner_id: str, title: str, due_at_iso: Optional[str]):
    res = supabase.table("todos").insert({
        "approval_id": approval_id,
        "owner": owner_id,
        "title": title,
        "due_at": due_at_iso,
        "done": False
    }).execute()
    return res.data

def get_todos(owner_id: str):
    res = supabase.table("todos").select("*").eq("owner", owner_id).order("due_at").execute()
    return res.data or []
