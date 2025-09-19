# 공용 대시보드 
import streamlit as st
from db import get_todos

def app(user):
    st.title("대시보드 (/dashboard)")
    st.subheader("내 할 일")
    rows = get_todos(user["user_id"])
    if not rows:
        st.info("할 일이 없습니다.")
    else:
        for r in rows:
            st.write(f"- {r['title']} | 마감: {r.get('due_at','-')}")
