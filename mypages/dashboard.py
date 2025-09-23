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
    st.title("📊 승인 완료 문서")
    st.markdown("대표님이 승인한 문서 목록입니다.")

    # '승인완료' 상태인 문서만 가져오기
    approved_docs = db.get_user_inbox(user["user_id"], "승인완료") or []

    # 모든 직원 프로필을 가져와 ID를 키로 하는 딕셔너리로 변환
    profiles = db.get_profiles()
    profile_map = {p["user_id"]: p["name"] for p in profiles}

    if not approved_docs:
        st.info("아직 승인 완료된 문서가 없습니다.")
        return

    tab_all, tab_summary = st.tabs(["모든 문서", "요약"])

    with tab_all:
        for doc in approved_docs:
            # creator_id를 사용하여 작성자 이름 찾기
            creator_id = doc.get("creator_id")
            creator_name = profile_map.get(creator_id, "알 수 없음")
            
            with st.expander(f"✅ **{doc['title']}** (작성자: {creator_name})"):
                st.markdown(f"**승인일:** {str(doc.get('decided_at', '')).split('T')[0]}")
                st.markdown(f"**요약:** {doc.get('summary', '-')}")
                with st.expander("원본 문서 전체 내용 보기"):
                    st.markdown(doc.get('confirm_text', ''))
                st.divider()

    with tab_summary:
        st.info("요약 탭은 추후 개발 예정입니다.")


    # with tab_summary:
    #     st.markdown(f"**총 {len(approved_docs)}건의 문서가 승인되었습니다.**")
    #     for doc in approved_docs:
    #         st.markdown(f"- **{doc['title']}** (작성자: {doc.get('creator_name', '알 수 없음')})")
    #         st.markdown(f"  - 요약: {doc.get('summary', '-')}")


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
