import streamlit as st
import db
from datetime import datetime

def app(user):
    st.title("📊 대표 대시보드 — To-Do")

    if user["role"] != "rep":
        st.warning("권한 없음 (대표만 접근 가능)")
        st.stop()

    # 데이터 로드
    todos = db.get_todos(user["user_id"]) or []

    # 분류
    open_todos = [t for t in todos if not t.get("done")]
    done_todos = [t for t in todos if t.get("done")]

    # 상단 배지
    st.markdown(f"**진행 중:** {len(open_todos)}개 · **완료:** {len(done_todos)}개")

    tab_open, tab_done = st.tabs(["🟢 진행 중", "✅ 완료"])

    # 진행 중
    with tab_open:
        if not open_todos:
            st.info("진행 중인 할 일이 없습니다.")
        else:
            for t in sorted(open_todos, key=lambda x: str(x.get("due_at") or "")):
                with st.container():
                    title = t.get("title", "(제목 없음)")
                    due = str(t.get("due_at") or "").split("T")[0]
                    st.markdown(f"**{title}**  ·  마감일: `{due}`")
                    c1, c2 = st.columns([1, 5])
                    with c1:
                        if st.button("완료 처리", key=f"done-{t['todo_id']}"):
                            db.set_todo_done(t["todo_id"], True)
                            st.success("완료로 이동했습니다.")
                            st.rerun()
                    with c2:
                        st.caption(f"todo_id: {t['todo_id']} · approval_id: {t.get('approval_id','-')}")

                    st.divider()

    # 완료
    with tab_done:
        if not done_todos:
            st.info("완료된 항목이 없습니다.")
        else:
            for t in sorted(done_todos, key=lambda x: str(x.get("due_at") or ""), reverse=True):
                with st.container():
                    title = t.get("title", "(제목 없음)")
                    due = str(t.get("due_at") or "").split("T")[0]
                    st.markdown(f"**{title}**  ·  마감일: `{due}`")
                    c1, c2 = st.columns([1, 5])
                    with c1:
                        if st.button("되돌리기", key=f"undone-{t['todo_id']}"):
                            db.set_todo_done(t["todo_id"], False)
                            st.info("다시 진행 중으로 이동했습니다.")
                            st.rerun()
                    with c2:
                        st.caption(f"todo_id: {t['todo_id']} · approval_id: {t.get('approval_id','-')}")
                    st.divider()
