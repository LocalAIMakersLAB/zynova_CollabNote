import time
import streamlit as st
import db
import potens_client
from datetime import datetime, timedelta, timezone


def app(user):
    st.title("📬 대표 승인함")
    st.markdown(f"환영합니다, **{user['name']}**님! (역할: **{user['role']}**)")

    # --- 권한 체크 ---
    if user["role"] != "rep":
        st.warning("권한 없음 (대표만 접근 가능)")
        st.stop()

    message_placeholder = st.empty()

    # 오늘 마감 Todo 알림
    today = db.today_local_iso(9)
    due_today = db.get_due_todos_for_date(user["user_id"], today, tz_hours=9)
    if due_today:
        st.warning(f"⏰ 오늘 마감 {len(due_today)}건이 있습니다.")
        for t in due_today:
            st.markdown(f"- **{t['title']}** · 마감일: {str(t['due_at']).split('T')[0]}")
        st.divider()

    # --- Todo 목록 ---
    if st.button("할 일(Todo) 보기"):
        st.session_state['show_todos'] = not st.session_state.get('show_todos', False)

    if st.session_state.get('show_todos'):
        todos = db.get_todos(user["user_id"])
        if not todos:
            st.info("현재 할 일이 없습니다.")
        else:
            h1, h2, h3 = st.columns([4, 2, 1])
            with h1: st.markdown("**✅ 할 일**")
            with h2: st.markdown("**마감일**")
            with h3: st.markdown("**완료**")

            for todo in todos:
                c1, c2, c3 = st.columns([4, 2, 1])
                with c1: st.write(todo["title"])
                with c2: st.write(todo["due_at"].split("T")[0] if "T" in str(todo["due_at"]) else todo["due_at"])
                with c3:
                    if st.button("완료 처리", key=f"todo-done-btn-{todo['todo_id']}"):
                        db.set_todo_done(todo["todo_id"], True)
                        st.success(f"'{todo['title']}' 완료로 이동했습니다.")
                        st.rerun()

    # --- 승인 요청 목록 ---
    status_filter = st.selectbox("상태", ["대기중", "승인완료", "반려"], index=0)
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
                # 📅 마감일 선택
                due_date = st.date_input(
                    "📅 마감일 선택",
                    value=datetime.utcnow().date() + timedelta(days=1),
                    key=f"due-{approval_id}"
                )

                # ✅ 승인 버튼
                if st.button("✅ 승인", key=f"approve-{approval_id}"):
                    KST = timezone(timedelta(hours=9))
                    due_at = datetime.combine(due_date, datetime.min.time(), tzinfo=KST).isoformat()

                    # 1) 승인 상태 업데이트
                    db.update_approval_status(approval_id, "승인완료")

                    # 2) 후속 할 일 생성 (대표의 Todo)
                    alert_msg = potens_client.generate_next_step_alert({
                        "type": title,
                        "creator_name": approval.get("creator_name", "담당 직원"),
                        "title": title
                    }) or "승인을 완료했습니다. 후속 조치를 진행해주세요."

                    db.create_todo(
                        approval_id=approval_id,
                        owner=user["user_id"],     # 대표
                        title=alert_msg,           # 후속 알림 메시지를 Todo 제목으로
                        due_at=due_at
                    )

                    # 3) 직원에게 승인 알림 저장 (알림 테이블 필요)
                    db.create_notification(
                        user_id=approval["creator_id"],   # 문서 작성자
                        message=f"'{title}' 요청이 승인되었습니다. 후속 조치: {alert_msg}"
                    )

                    # 4) UI 알림
                    with message_placeholder.container():
                        st.success(f"✅ 승인 완료!\n\n{alert_msg}\n마감일: **{due_date}**")

                    time.sleep(2)
                    st.rerun()

                # ❌ 반려 버튼
                reject_reason = st.text_input("반려 사유 입력", key=f"reason-{approval_id}")
                if st.button("❌ 반려", key=f"reject-{approval_id}"):
                    if not reject_reason.strip():
                        st.warning("반려 사유를 입력해주세요.")
                    else:
                        # 1) 상태 업데이트
                        db.update_approval_status(approval_id, "반려", reject_reason.strip())

                        # 2) 반려 안내문 생성 + 직원 알림
                        rejection_note = potens_client.generate_rejection_note(
                            rejection_memo=reject_reason,
                            creator_name=approval.get("creator_name", "담당 직원"),
                            doc_title=title
                        )
                        db.create_notification(
                            user_id=approval["creator_id"],
                            message=rejection_note
                        )

                        # 3) UI 표시
                        st.error("❌ 반려 완료!")
                        time.sleep(2)
                        st.rerun()

# # Mock AI 함수: 승인된 요청을 기반으로 후속 업무를 생성
# def mock_ai_generate_task(title: str, confirm_text: str = "") -> str:
#     text = f"{title} {confirm_text}".lower()
#     if "연차" in text:
#         return "직원 연차계 제출 확인 및 휴가 일정 공유"
#     if any(k in text for k in ["지출", "구매", "발주", "송금", "대금"]):
#         return f"{title} 관련 송금 요청"
#     if "출장" in text:
#         return "출장비 지급 및 영수증 수취 확인"
#     if "계약" in text:
#         return "계약 원본 보관 및 스캔 업로드"
#     if "보고서" in text:
#         return "보고서 관련 회계팀 서류 전달"
#     return "승인 후속 조치 확인"
