# 대표용 /inbox
import os
import streamlit as st
from datetime import datetime, timedelta, timezone
from db import get_pending_approvals, update_approval_status, create_todo

def app(user):
    st.title("대표 승인함 (/inbox)")

    assignee_id = user["user_id"]  # 대표 자신에게 배정된 요청
    approvals = get_pending_approvals(assignee_id)
    if not approvals:
        st.info("승인 대기 문서가 없습니다.")
        return

    for ap in approvals:
        with st.expander(f"{ap['title']}"):
            st.markdown(ap.get("confirm_text") or "")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("승인", key=f"approve_{ap['approval_id']}"):
                    update_approval_status(ap["approval_id"], "approved")

                    # 간단 규칙: '송금 요청' todo 24h
                    due = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
                    owner_id = user["user_id"]  # 또는 회계 담당자 user_id
                    create_todo(ap["approval_id"], owner_id, "송금 요청", due)

                    st.success("승인 및 후속 업무 생성 완료")
                    st.rerun()
            with c2:
                if st.button("반려", key=f"reject_{ap['approval_id']}"):
                    update_approval_status(ap["approval_id"], "rejected", reject_reason="사유 보완 필요")
                    st.warning("반려 처리 완료")
                    st.rerun()
