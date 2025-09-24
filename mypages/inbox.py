import time
import streamlit as st
import db
import potens_client
from datetime import datetime, timedelta, timezone

# ---------------------------
# Main Page
# ---------------------------
def app(user):
    st.title("📬 문서 승인 처리")
    st.markdown(f"환영합니다, **{user['name']}**님! (역할: **{user['role']}**)")

    # --- 권한 체크 ---
    if user["role"] != "rep":
        st.warning("권한 없음 (대표만 접근 가능)")
        st.stop()

    message_placeholder = st.empty()

    # -------------------------
    # 오늘 승인해야 할 문서 (알림창)
    # -------------------------
    today = db.today_local_iso(9)

    # Todo 목록 ---
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

            todos = db.get_todos(user_id=user["user_id"])  # 매번 새로 조회

            for todo in todos:
                c1, c2, c3 = st.columns([4, 2, 1])
                with c1: 
                    st.write(todo["title"])
                with c2: 
                    st.write(todo["due_at"].split("T")[0] if "T" in str(todo["due_at"]) else todo["due_at"])
                with c3:
                    # 완료 버튼 클릭
                    if st.button("완료 처리", key=f"todo-done-btn-{todo['todo_id']}"):
                        db.delete_todo(todo["todo_id"])
                        st.success(f"'{todo['title']}' 완료로 삭제되었습니다.")
                        st.rerun()  # 화면 새로고침


   # --- 오늘 승인 요청 ---
    approvals_today = db.get_pending_approvals(user["user_id"], "대기중")

    if approvals_today:
        st.success(f"🚀 오늘 {len(approvals_today)}건의 문서가 승인 대기 중입니다!")

        for approval in approvals_today:
            approval_id = approval["approval_id"]
            title = approval.get("title", "(제목 없음)")
            summary = approval.get("summary", "")
            confirm_text = approval.get("confirm_text", "")

            with st.expander(f"📝 {title}", expanded=True):
                st.markdown(f"**요약:** {summary}")
                st.markdown(f"**[본문]**\n\n{confirm_text}")

                # --- 마감일 선택 ---
                due_date = st.date_input(
                    "📅 문서 관련 마감일 선택",
                    value=(datetime.utcnow() + timedelta(days=1)).date(),
                    key=f"due-{approval_id}"
                )

                # — 후속 담당자 토글 —
                employees = db.get_profiles()
                staff_employees = [e for e in employees if e.get("role") == "staff"]

                if staff_employees:
                    st.markdown("📌 후속 담당자 지정 (토글에서 선택 가능, '선택 안함' 포함)")

                    # staff 이름 리스트 + 선택 안함 옵션
                    staff_names = ["선택 안함"] + [s["name"] for s in staff_employees]

                    selected_assignee = st.selectbox(
                        "후속 담당자 선택",
                        staff_names,
                        key=f"assignee-{approval_id}"
                    )

                    # 선택된 결과 정리
                    if selected_assignee == "선택 안함":
                        selected_assignees = []
                    else:
                        selected_assignees = [selected_assignee]

                else:
                    st.warning("⚠️ 후속 담당자로 지정할 staff가 없습니다.")
                    selected_assignees = []
                    
                # --- 승인 버튼 ---
                if st.button("✅ 승인", key=f"approve-btn-{approval_id}"):
                    db.update_approval_status(approval_id, "승인완료")

                    draft = db.get_draft(approval["draft_id"])
                    creator_id = draft.get("creator") if draft else None
                    creator_profile = db.get_profile(creator_id) if creator_id else {}
                    creator_name = creator_profile.get("name", "알 수 없음")
                    confirm_text = (draft.get("confirm_text") or "").strip()

                    due_at_str = due_date.isoformat()

                    # LLM 기반 후속 조치 문구
                    alert_msg = potens_client.generate_next_step_alert({
                        "type": title,
                        "creator_name": creator_name,
                        "title": title,
                        "due_date": due_at_str
                    }) or f"'{title}' 승인 완료 – 후속 조치 필요"

                    if selected_assignees:
                        employee_map = {e["name"]: e["user_id"] for e in staff_employees}
                        for assignee in selected_assignees:
                            assignee_id = employee_map[assignee]

                            # ✅ 직원 Todo
                            db.create_todo(
                                approval_id=approval_id,
                                owner=assignee_id,
                                # 제목에 후속업무(alert_msg)를 직접 넣음
                                title=f"{creator_name}님의 요청 – {alert_msg}",
                                due_at=due_at_str
                            )

                            # 알림 전송
                            db.create_notification(
                                user_id=assignee_id,
                                message=(
                                    f"📌 {creator_name}님이 제출한 '{title}' 요청이 대표 승인되었습니다.\n\n"
                                    f"➡️ 후속업무: {alert_msg}\n"
                                    f"📅 마감일: {due_at_str}"
                                )
                            )

                        st.success(f"✅ 승인 완료! {', '.join(selected_assignees)}에게 후속업무가 전달되었습니다.")

                    else:
                        # ✅ 담당자 없으면 대표 Todo만 생성
                        db.create_todo(
                            approval_id=approval_id,
                            owner=user["user_id"],  # 대표 본인
                            title=f"[대표 Todo] {alert_msg}",
                            due_at=due_at_str
                        )
                        st.success(f"✅ 승인 완료! 후속 담당자가 없어 대표님 Todo로 등록되었습니다.")

                # --- 반려 버튼 ---
                reject_reason = st.text_input("반려 사유 입력", key=f"reason-{approval_id}")
                if st.button("❌ 반려", key=f"reject-btn-{approval_id}"):
                    if not reject_reason.strip():
                        st.warning("반려 사유를 입력해주세요.")
                    else:
                        db.update_approval_status(approval_id, "반려", reject_reason.strip())
                        rejection_note = potens_client.generate_rejection_note(
                            rejection_memo=reject_reason,
                            creator_name=approval.get("creator_name", "담당 직원"),
                            doc_title=title
                        )
                        db.create_notification(
                            user_id=approval["creator_id"],
                            message=rejection_note
                        )
                        st.error("❌ 반려 완료!")

    else:
        st.info("✅ 오늘의 승인 처리는 모두 끝났습니다!")

