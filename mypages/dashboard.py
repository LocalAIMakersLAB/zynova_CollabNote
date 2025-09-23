import streamlit as st
import db
from typing import Dict, List, Any

def app(user: Dict[str, Any]):
    # 사용자의 역할에 따라 다른 대시보드 UI를 렌더링
    if user["role"] == "rep":
        render_rep_dashboard(user)
    else:
        render_staff_dashboard(user)

def render_rep_dashboard(user: Dict[str, Any]):
    st.title("📊 대표 대시보드 — To-Do")
    # 대표용 대시보드 로직 (기존 코드와 유사)
    todos = db.get_todos(user["user_id"]) or []
    open_todos = [t for t in todos if not t.get("done")]
    done_todos = [t for t in todos if t.get("done")]

    st.markdown(f"**진행 중:** {len(open_todos)}개 · **완료:** {len(done_todos)}개")
    tab_open, tab_done = st.tabs(["🟢 진행 중", "✅ 완료"])

    with tab_open:
        if not open_todos:
            st.info("진행 중인 할 일이 없습니다.")
        else:
            for t in sorted(open_todos, key=lambda x: str(x.get("due_at") or "")):
                with st.container():
                    title = t.get("title", "(제목 없음)")
                    due = str(t.get("due_at") or "").split("T")[0]
                    st.markdown(f"**{title}** ·  마감일: `{due}`")
                    c1, c2 = st.columns([1, 5])
                    with c1:
                        if st.button("완료 처리", key=f"done-{t['todo_id']}"):
                            db.set_todo_done(t["todo_id"], True)
                            st.success("완료로 이동했습니다.")
                            st.rerun()
                    with c2:
                        st.caption(f"todo_id: {t['todo_id']} · approval_id: {t.get('approval_id','-')}")
                    st.divider()

    with tab_done:
        if not done_todos:
            st.info("완료된 항목이 없습니다.")
        else:
            for t in sorted(done_todos, key=lambda x: str(x.get("due_at") or ""), reverse=True):
                with st.container():
                    title = t.get("title", "(제목 없음)")
                    due = str(t.get("due_at") or "").split("T")[0]
                    st.markdown(f"**{title}** ·  마감일: `{due}`")
                    c1, c2 = st.columns([1, 5])
                    with c1:
                        if st.button("되돌리기", key=f"undone-{t['todo_id']}"):
                            db.set_todo_done(t["todo_id"], False)
                            st.info("다시 진행 중으로 이동했습니다.")
                            st.rerun()
                    with c2:
                        st.caption(f"todo_id: {t['todo_id']} · approval_id: {t.get('approval_id','-')}")
                    st.divider()


def render_staff_dashboard(user: Dict[str, Any]):
    st.title("📊 내 문서 현황")
    st.markdown("내가 제출한 문서들의 처리 현황입니다.")
    
    # 직원의 문서 승인 기록 가져오기
    history = db.get_user_approvals_history(user['user_id']) or []

    if not history:
        st.info("아직 제출한 문서가 없습니다. '새 문서 요청' 페이지에서 문서를 작성해보세요.")
        return

    # 상태별로 문서 분류
    pending = [h for h in history if h['status'] == '대기중']
    approved = [h for h in history if h['status'] == '승인완료']
    rejected = [h for h in history if h['status'] == '반려']

    # 상태 배지
    st.markdown(f"**대기 중:** {len(pending)}개 · **승인:** {len(approved)}개 · **반려:** {len(rejected)}개")

    # 탭 UI를 사용해 상태별로 보여주기
    tab_pending, tab_approved, tab_rejected = st.tabs(["⏳ 대기 중", "✅ 승인", "❌ 반려"])

    # 1. 대기 중인 문서
    with tab_pending:
        if not pending:
            st.info("현재 대기 중인 문서가 없습니다.")
        else:
            for doc in pending:
                with st.expander(f"⏳ **{doc['title']}** (유형: {doc['doc_type']})"):
                    st.write(f"요청일: {str(doc['created_at']).split('T')[0]}")
                
                    st.markdown("---")
                    st.markdown("#### 요청 내용")

                    draft_info = db.get_draft_by_id(doc['draft_id'])
                    if draft_info:
                        st.text(draft_info.get('confirm_text', '내용 없음'))
                    
                    st.markdown("---")
                    st.caption("대표님의 검토를 기다리고 있습니다.")
    
    # 2. 승인된 문서
    with tab_approved:
        if not approved:
            st.info("아직 승인된 문서가 없습니다.")
        else:
            for doc in approved:
                with st.expander(f"✅ **{doc['title']}** (유형: {doc['doc_type']})"):
                    st.write(f"승인일: {str(doc['decided_at']).split('T')[0]}")

                    st.markdown("---")
                    st.markdown("#### 요청 내용")
                    
                    draft_info = db.get_draft_by_id(doc['draft_id'])
                    if draft_info:
                        st.text(draft_info.get('confirm_text', '내용 없음'))

                    st.markdown("---")
                    st.caption("문서가 승인되었습니다.")

    # 3. 반려된 문서
    with tab_rejected:
        if not rejected:
            st.info("반려된 문서가 없습니다.")
        else:
            for doc in rejected:
                with st.expander(f"❌ **{doc['title']}** (유형: {doc['doc_type']})"):
                    st.write(f"반려일: {str(doc['decided_at']).split('T')[0]}")
                    
                    st.markdown("---")
                    st.markdown("#### 반려 사유")
                    st.markdown(f"<p style='color:red;'>{doc.get('reject_reason', '반려 사유가 기록되지 않았습니다.')}</p>", unsafe_allow_html=True)
                    st.markdown("#### 요청 내용")
                    
                    draft_info = db.get_draft_by_id(doc['draft_id'])
                    if draft_info:
                        st.text(draft_info.get('confirm_text', '내용 없음'))
