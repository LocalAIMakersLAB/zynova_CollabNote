import random
import time
import streamlit as st
import db
import potens_client
from datetime import datetime, timedelta
import pandas as pd

def app(user):
    st.title("📬 대표 승인함")
    st.markdown(f"환영합니다, **{user['name']}**님! (역할: **{user['role']}**)")

    # 역할 체크
    if user["role"] != "rep":
        st.warning("권한 없음 (대표만 접근 가능)")
        st.stop()

    message_placeholder = st.empty()

    # --- Todo 보기 버튼을 상단에 배치 ---
    if st.button("할 일(Todo) 보기"):
        st.session_state['show_todos'] = not st.session_state.get('show_todos', False)

    if st.session_state.get('show_todos'):
        # st.markdown("✅ **할 일 목록**")

        todos = db.get_todos(user["user_id"])

        if not todos:
            st.info("현재 할 일이 없습니다.")
        else:
            # 헤더 표시
            h1, h2, h3 = st.columns([4, 2, 1])
            with h1:
                st.markdown("**✅ 할 일**")
            with h2:
                st.markdown("**마감일**")
            with h3:
                st.markdown("**완료**")

            for todo in todos:
                c1, c2, c3 = st.columns([4, 2, 1])

                with c1:
                    st.write(todo["title"])
                with c2:
                    # 날짜만 보이게
                    st.write(todo["due_at"].split("T")[0] if "T" in str(todo["due_at"]) else todo["due_at"])
                with c3:
                    if st.checkbox("완료", key=f"done-{todo['todo_id']}"):
                        db.delete_todo(todo["todo_id"])
                        st.success(f"'{todo['title']}' 완료! 목록에서 제거되었습니다.")
                        st.rerun()
            # st.markdown("---")

    # 1) 상태 필터
    status_filter = st.selectbox("상태", ["대기중", "승인완료", "반려"], index=0)

    # 2) 승인 요청 리스트
    approvals = db.get_pending_approvals(user["user_id"], status_filter)

    if not approvals:
        st.info("현재 처리할 업무가 없습니다.")
        return

    for approval in approvals:
        st.markdown("---")
        title = approval.get("title", "(제목 없음)")
        summary = approval.get("summary", "")
        confirm_text = approval.get("confirm_text", "")
        approval_id = approval["approval_id"]

        with st.expander(f"**{title}**"):
            st.markdown(f"**요약:** {summary}")
            st.markdown(f"**[승인 본문]**\n\n{confirm_text}")

            if approval["status"] == "대기중":
                # Mock AI → 후속 업무 제안
                suggested_task = mock_ai_generate_task(title)
                
                # 후속 업무 제안
                st.markdown(f"👉 후속 업무: **{suggested_task}**")

                # 📅 마감일 선택
                due_date = st.date_input(
                    "📅 마감일 선택",
                    value=datetime.utcnow().date() + timedelta(days=1),
                    key=f"due-{approval_id}"
                )

                # 승인 버튼
                if st.button("✅ 승인", key=f"approve-{approval_id}"):
                    db.update_approval_status(approval_id, "승인완료")

                    db.create_todo(
                        approval_id=approval_id,
                        owner=user["user_id"],
                        title=suggested_task,
                        due_at=datetime.combine(due_date, datetime.min.time()).isoformat()
                    )

                    with message_placeholder.container():
                            st.success(f"✅ 승인 완료!\n\n후속 할 일: **{suggested_task}**\n마감일: **{due_date}**")
                    time.sleep(2)
                    st.rerun()

                # 반려 사유 입력 → 반려 버튼
                reject_reason = st.text_input("반려 사유 입력", key=f"reason-{approval_id}")
                if st.button("❌ 반려", key=f"reject-{approval_id}"):
                    db.update_approval_status(approval_id, "반려", reject_reason)
                    st.error("❌ 반려 완료!")
                    st.rerun()


# Mock AI 함수: 승인된 요청을 기반으로 후속 업무를 생성
def mock_ai_generate_task(title: str) -> str:
    """승인된 요청(title)을 기반으로 후속 업무를 가상 생성"""
    if "연차" in title:
        return "직원 연차계 제출 확인 및 휴가 일정 공유"
    if "지출" in title or "구매" in title or "발주" in title:
        return f"{title} 관련 송금 요청"
    if "보고서" in title:
        return f"{title} 관련 회계팀 서류 전달"
    if "계약서" in title:
        return f"{title} 원본 서류 보관 및 스캔"
    
    return "승인 후속 조치 확인"

