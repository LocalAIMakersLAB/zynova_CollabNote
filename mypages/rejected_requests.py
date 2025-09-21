import streamlit as st
import db

def run_rejected_requests_page(user):
    """
    직원에게 반려된 문서를 보여주는 페이지입니다.
    """
    st.header("❌ 반려된 문서 목록")
    st.markdown("대표님에게 반려된 요청을 확인하고 수정할 수 있습니다.")

    # 현재 사용자의 반려된 문서 목록을 DB에서 가져옴
    rejected_requests = db.get_user_rejected_requests(user['user_id'])

    # (선택) 검색
    q = st.text_input("검색 (제목/요약/사유)")
    if q:
        q_lower = q.lower()
        rejected_requests = [
            r for r in rejected_requests
            if q_lower in (r.get("title","") + r.get("summary","") + r.get("reject_reason","")).lower()
        ]

    if not rejected_requests:
        st.info("현재 반려된 문서가 없습니다. 모든 요청이 순조롭게 진행 중입니다.")
        return
    
    for request in rejected_requests:
        title = request.get("title", "(제목 없음)")
        reason = request.get("reject_reason") or "(사유가 입력되지 않았습니다)"
        summary = request.get("summary") or "(요약 없음)"
        status = request.get("status", "반려")
        created = (request.get("created_at") or "")[:19]

        with st.expander(f"**{title}**"):
            st.caption(f"상태: **{status}** · 생성: {created}")
            st.subheader("반려 사유")
            st.markdown(f"<p style='color:red;'>{reason}</p>", unsafe_allow_html=True)

            st.subheader("요청 내용")
            st.markdown(f"**요약:** {summary}")

            with st.expander("원본 문서 전체 내용 보기"):
                st.markdown(request.get('confirm_text', ''), unsafe_allow_html=False)

            st.divider()

            if st.button("이 내용으로 재작성", key=f"re_compose_{request['approval_id']}"):
                draft = db.get_draft(request.get("draft_id"))
                st.session_state.compose_prefill = {
                    "title": request.get("title"),
                    "doc_type": draft.get("type") if draft else None,            # 템플릿 선택에 쓰기
                    "filled_fields": (draft.get("filled") if draft else {}) or {},
                    "confirm_text": request.get("confirm_text", "")
                }
                st.success("재작성 준비가 되었습니다. 좌측 메뉴에서 '📝 새 문서 요청'으로 이동하세요.")    
                

                # # '재작성하기' 버튼을 누르면 새 문서 작성 페이지로 이동
                # # 현재는 단순히 메시지만 표시하고, 실제 재작성 로직은 추후 구현 필요
                # if st.button("재작성하기", key=f"re_compose_{request['approval_id']}"):
                #     st.info(f"'{request['title']}' 문서를 기반으로 재작성을 시작합니다.")
                #     st.session_state.selected_page = "📝 새 문서 요청"
                #     st.experimental_rerun()
