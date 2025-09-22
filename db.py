import os
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv
from supabase import create_client
import bcrypt
from datetime import datetime, timedelta, timezone
from potens_client import generate_approval_summary

# .env 불러오기
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL / SUPABASE_KEY not configured")

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

def get_rag_context(doc_type: str) -> str:
    """
    LLM 프롬프트 컨텍스트(가이드 문서) 조회
    """
    try:
        res = supabase.table("templates").select("guide_md").eq("type", doc_type).single().execute()
        return res.data.get("guide_md", "") if res.data else ""
    except Exception:
        return ""
    
# compose용 create_draft/submit_draft는 남겨도 되나 이번 스프린트에선 직접 호출 X (추후 RAG-주도 작성기 준비되면 재사용)
# drafts -> 직원이 작성 중/제출 전 초안 저장
# approvals -> 대표 inbox용 승인 요청 저장

# -----------------------
# 직원 Draft 관련
# -----------------------
def create_draft(creator_id: str, doc_type: str, filled: dict, missing: list, confirm_text: str):
    """
    drafts: (draft_id, creator, type, filled jsonb, missing jsonb, confirm_text text, status)
    """
    response = supabase.table("drafts").insert({
        "creator": creator_id,
        "type": doc_type,
        "filled": filled,
        "missing": missing,
        "confirm_text": confirm_text,
        "status": "editing"
    }).execute()

    # Supabase는 리스트로 반환하므로 draft_id만 추출
    if response.data:
        return response.data[0]["draft_id"]
    return None

def submit_draft(draft_id: str, confirm_text: str, assignee: str, due_date: str, creator_id: str):
    """
    승인 요청 제출 → drafts.status='submitted' 업데이트 + approvals 생성
    approvals: (approval_id, draft_id, title, summary, confirm_text, assignee, due_date, status)
    """
    # 1) draft 상태 업데이트
    supabase.table("drafts").update({"status": "submitted"}).eq("draft_id", draft_id).execute()

    # 2) LLM 요약 생성
    summary_obj = generate_approval_summary(confirm_text) or {}
    title = summary_obj.get("title", "제목없음")
    summary = summary_obj.get("summary", "")

    # 3) approvals 생성
    response = supabase.table("approvals").insert({
        "draft_id": draft_id,
        "title": title,
        "summary": summary,
        "confirm_text": confirm_text,
        "assignee": assignee,
        "due_date": due_date,
        "status": "대기중",
        "creator_id": creator_id
    }).execute()
    return response.data

def get_draft(draft_id: str) -> Optional[Dict[str, Any]]:
    res = supabase.table("drafts").select("*").eq("draft_id", draft_id).limit(1).execute()
    return res.data[0] if res.data else None

# -----------------------
# 대표 Approval 관련
# -----------------------
def get_pending_approvals(assignee_id: str, status: str = "대기중") -> List[Dict[str, Any]]:
    """특정 대표의 승인 요청 가져오기"""
    res = (
        supabase.table("approvals")
        .select("*")
        .eq("assignee", assignee_id)
        .eq("status", status)
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []

def update_approval_status(approval_id: str, status: str, reason: Optional[str] = None):
    """승인/반려 처리"""
    update_data: Dict[str, Any] = {"status": status, "decided_at": now_utc_iso()}
    if reason:
        update_data["reject_reason"] = reason
    res = supabase.table("approvals").update(update_data).eq("approval_id", approval_id).execute()
    return res.data

def get_rep_user_ids() -> List[str]:
    """role = 'rep' 인 대표 user_id 리스트 반환"""
    res = supabase.table("profiles").select("user_id").eq("role", "rep").execute()
    return [row["user_id"] for row in (res.data or [])]

def get_rep_user_id() -> Optional[str]:
    ids = get_rep_user_ids()
    return ids[0] if ids else None

# -----------------------
# 후속 일정 (Todo)
# -----------------------
def create_todo(approval_id: str, owner: str, title: str, due_at: Optional[str] = None):
    """
    todos: (todo_id, approval_id, owner, title, due_at timestamptz, done bool)
    due_at: ISO8601 문자열 권장 (예: '2025-09-25T09:00:00+09:00')
    """
    if due_at is None:
        due_at = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        

    """승인 완료 시 후속 일정 생성"""
    response = supabase.table("todos").insert({
        "approval_id": approval_id,
        "owner": owner,
        "title": title,
        "due_at": due_at,
        "done": False
    }).execute()
    return response.data

def get_todos(owner_id: str) -> List[Dict[str, Any]]:
    response = supabase.table("todos").select("*").eq("owner", owner_id).order("due_at").execute()
    return response.data or []

# --- Todo 업데이트 (done 토글) ---
def set_todo_done(todo_id: str, done: bool = True):
    res = supabase.table("todos").update({"done": done}).eq("todo_id", todo_id).execute()
    return res.data

# (레거시 호환) 완전 삭제가 필요한 경우 호출될 수 있어 유지
def delete_todo(todo_id: str):
    response = supabase.table("todos").delete().eq("todo_id", todo_id).execute()
    return response.data

def _local_day_bounds_to_utc(the_date_iso: str, tz_hours: int = 9) -> tuple[str, str]:
    """
    로컬타임존(기본 KST=+9)에서의 하루 경계를 UTC ISO8601로 변환.
    입력: 'YYYY-MM-DD'
    출력: (start_utc_iso, end_utc_iso)  # end는 다음날 00:00:00 (exclusive)
    """
    y, m, d = map(int, the_date_iso.split("-"))
    tz = timezone(timedelta(hours=tz_hours))
    start_local = datetime(y, m, d, 0, 0, 0, tzinfo=tz)
    end_local = start_local + timedelta(days=1)  # exclusive
    start_utc = start_local.astimezone(timezone.utc).isoformat()
    end_utc = end_local.astimezone(timezone.utc).isoformat()
    return start_utc, end_utc

def get_due_todos_for_date(owner_id: str, the_date_iso: str, tz_hours: int = 9):
    """
    the_date_iso: 'YYYY-MM-DD' (앱 기준 로컬 날짜, 기본 KST)
    due_at(timestamptz)을 로컬 하루 경계 기준으로 필터링.
    """
    start_utc, end_utc = _local_day_bounds_to_utc(the_date_iso, tz_hours)
    res = (
        supabase.table("todos")
        .select("*")
        .eq("owner", owner_id)
        .gte("due_at", start_utc)   # 시작 포함
        .lt("due_at", end_utc)      # 끝 배타
        .eq("done", False)
        .execute()
    )
    return res.data or []

def today_local_iso(tz_hours: int = 9) -> str:
    now_local = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=tz_hours)))
    return now_local.date().isoformat()

# -----------------------
# 반려 문서 조회
# -----------------------
def get_user_rejected_requests(user_id: str) -> List[Dict[str, Any]]:

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
        res = (
            supabase.table("approvals")
            .select("*")
            .in_("draft_id", draft_ids)
            .eq("status", "반려")
            .order("created_at", desc=True)
            .execute()
        )        

        return res.data if res.data else []
        
    except Exception as e:
        print(f"Error fetching rejected requests: {e}")
        return []

# -----------------------
# 직원 알림 (Notifications)
# -----------------------
def create_notification(user_id: str, message: str):
    """
    특정 직원(user_id)에게 알림을 생성합니다.
    """
    response = supabase.table("notifications").insert({
        "user_id": user_id,
        "message": message,
        "read": False
    }).execute()
    return response.data

def get_notifications(user_id: str, only_unread: bool = True) -> List[Dict[str, Any]]:
    """
    특정 직원(user_id)의 알림 목록을 가져옵니다.
    """
    query = supabase.table("notifications").select("*").eq("user_id", user_id)
    if only_unread:
        query = query.eq("read", False)
    res = query.order("created_at", desc=True).execute()
    return res.data or []

def mark_notification_as_read(notification_id: str):
    """
    특정 알림을 읽음 처리합니다.
    """
    res = supabase.table("notifications").update({"read": True}).eq("notification_id", notification_id).execute()
    return res.data
