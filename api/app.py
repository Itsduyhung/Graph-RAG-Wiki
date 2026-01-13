# api/app.py
"""API application for Graph RAG (Streamlit UI)."""
import streamlit as st
from pipeline.query_pipeline import ask_agent

st.set_page_config(page_title="Graph RAG Agent")

st.title("🤖 Graph RAG AI Agent")

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    st.chat_message(msg["role"]).write(msg["content"])

prompt = st.chat_input("Hỏi về doanh nghiệp...")

if prompt:
    st.chat_message("user").write(prompt)
    answer = ask_agent(prompt)
    st.chat_message("assistant").write(answer)

    st.session_state.messages.append(
        {"role": "user", "content": prompt}
    )
    st.session_state.messages.append(
        {"role": "assistant", "content": answer}
    )


