import random
import time
import streamlit as st
import db
import potens_client
from datetime import datetime, timedelta, timezone


def app(user):
    st.title("📬 대표 승인함")
    st.markdown(f"환영합니다, **{user['name']}**님! (역할: **{user['role']}**)")

    # 역할 체크
    if user["role"] != "rep":
        st.warning("권한 없음 (대표만 접근 가능)")
        st.stop()

    message_placeholder = st.empty()

    # 중복 알림 제거 + 한 번만 표시
    today = db.today_local_iso(9)
    due_today = db.get_due_todos_for_date(user["user_id"], today, tz_hours=9)
    if due_today:
        st.warning(f"⏰ 오늘 마감 {len(due_today)}건이 있습니다.")
        for t in due_today:
            st.markdown(f"- **{t['title']}** · 마감일: {str(t['due_at']).split('T')[0]}")
        st.divider()

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
                    st.write(todo["due_at"].split("T")[0] if "T" in str(todo["due_at"]) else todo["due_at"])
                with c3:
                    if st.button("완료 처리", key=f"todo-done-btn-{todo['todo_id']}"):
                        db.set_todo_done(todo["todo_id"], True)
                        st.success(f"'{todo['title']}' 완료로 이동했습니다.")

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
                approved_info = {
                        "type": approval.get("type") or title,  # 안전 보정
                        "creator_name": approval.get("creator_name", "담당 직원"),
                        "title": title
                    }
                suggested_task = potens_client.generate_next_step_alert(approved_info) or "승인 후속 조치 확인"

                
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
                    KST = timezone(timedelta(hours=9))
                    due_at = datetime.combine(due_date, datetime.min.time(), tzinfo=KST).isoformat()

                    # 1) 승인 상태 업데이트
                    db.update_approval_status(approval_id, "승인완료")

                    # 2) 후속 할 일 생성 (제목은 기존 규칙 기반 혹은 원하는 로직 유지)

                    db.create_todo(
                        approval_id=approval_id,
                        owner=user["user_id"],
                        title=suggested_task,
                        due_at=due_at
                    )

                    # 3) LLM으로 자연스러운 후속 알림 문구 생성
                    alert_msg = potens_client.generate_next_step_alert({
                        "type": title,                     # 문서/요청 유형 또는 제목
                        "creator_name": approval.get("creator_name", "담당 직원"),  # 있으면 DB에 맞게 전달
                        "title": title
                    }) or "승인을 완료했습니다. 다음 후속 조치를 진행해주세요."

                    # 4) 안내 출력
                    with message_placeholder.container():
                        st.success(f"✅ 승인 완료!\n\n{alert_msg}\n마감일: **{due_date}**")

                    time.sleep(2)
                    st.rerun()

                # 반려 사유 입력 → 반려 버튼
                reject_reason = st.text_input("반려 사유 입력", key=f"reason-{approval_id}")
                if st.button("❌ 반려", key=f"reject-{approval_id}"):
                    if not reject_reason.strip():
                        st.warning("반려 사유를 입력해주세요.")
                    else:
                        db.update_approval_status(approval_id, "반려", reject_reason.strip())
                        st.error("❌ 반려 완료!")
                        st.rerun()

# Mock AI 함수: 승인된 요청을 기반으로 후속 업무를 생성
def mock_ai_generate_task(title: str, confirm_text: str = "") -> str:
    text = f"{title} {confirm_text}".lower()
    if "연차" in text:
        return "직원 연차계 제출 확인 및 휴가 일정 공유"
    if any(k in text for k in ["지출", "구매", "발주", "송금", "대금"]):
        return f"{title} 관련 송금 요청"
    if "출장" in text:
        return "출장비 지급 및 영수증 수취 확인"
    if "계약" in text:
        return "계약 원본 보관 및 스캔 업로드"
    if "보고서" in text:
        return "보고서 관련 회계팀 서류 전달"
    return "승인 후속 조치 확인"

