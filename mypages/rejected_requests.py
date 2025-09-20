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

    if not rejected_requests:
        st.info("현재 반려된 문서가 없습니다. 모든 요청이 순조롭게 진행 중입니다.")
    else:
        for request in rejected_requests:
            # 문서 하나당 expander를 사용해 깔끔하게 표시
            with st.expander(f"**{request['title']}**"):
                st.subheader("반려 사유")
                # 반려 사유를 빨간색으로 강조
                st.markdown(f"<p style='color:red;'>{request['reject_reason']}</p>", unsafe_allow_html=True)
                
                st.subheader("요청 내용")
                st.markdown(f"**요약:** {request['summary']}")
                
                # 원본 문서 내용 (confirm_text)이 길 경우, 상세 내용으로 표시
                with st.expander("원본 문서 전체 내용 보기"):
                    st.text(request['confirm_text'])

                st.divider()

                # # '재작성하기' 버튼을 누르면 새 문서 작성 페이지로 이동
                # # 현재는 단순히 메시지만 표시하고, 실제 재작성 로직은 추후 구현 필요
                # if st.button("재작성하기", key=f"re_compose_{request['approval_id']}"):
                #     st.info(f"'{request['title']}' 문서를 기반으로 재작성을 시작합니다.")
                #     st.session_state.selected_page = "📝 새 문서 요청"
                #     st.experimental_rerun()
