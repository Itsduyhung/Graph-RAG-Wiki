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
    result = ask_agent(prompt)
    # Handle both dict and string returns for backward compatibility
    if isinstance(result, dict):
        answer = result.get("answer", str(result))
        active_person = result.get("active_person")
        if active_person:
            st.chat_message("assistant").write(f"{answer}\n\n**Active Person:** {active_person}")
        else:
            st.chat_message("assistant").write(answer)
    else:
        st.chat_message("assistant").write(result)

    st.session_state.messages.append(
        {"role": "user", "content": prompt}
    )
    # Store the answer appropriately
    if isinstance(result, dict):
        st.session_state.messages.append(
            {"role": "assistant", "content": result.get("answer", str(result))}
        )
    else:
        st.session_state.messages.append(
            {"role": "assistant", "content": result}
        )


