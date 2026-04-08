# ui.py
import streamlit as st
from pipeline.query_pipeline import QueryPipeline

st.set_page_config(page_title="Graph RAG Agent - Real-time Streaming")

st.title("🤖 Graph RAG AI Agent - Real-time Streaming")

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    st.chat_message(msg["role"]).write(msg["content"])

prompt = st.chat_input("Hỏi về lịch sử Việt Nam...")

if prompt:
    st.chat_message("user").write(prompt)
    
    # Use streaming with answer container for real-time display
    with st.chat_message("assistant"):
        answer_container = st.empty()
        
        # Initialize pipeline
        pipeline = QueryPipeline()
        
        # Step 1: Query Understanding
        query_info = pipeline._understand_query(prompt)
        
        # Step 2: Candidate Retrieval  
        candidates = pipeline._retrieve_candidates(query_info)
        
        # Step 3: Graph Expansion
        expanded = pipeline._expand_graph(candidates)
        
        # Step 4: Context Filtering
        filtered_context = pipeline._filter_context(query_info, expanded)
        
        # Step 5: Answer Generation with REAL streaming to UI
        answer_text = ""
        
        # Suppress stdout to hide [DEBUG] messages from terminal
        import io
        import sys
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        
        try:
            # Stream chunks directly from answer_generator
            import os
            default_temp = float(os.getenv('LLM_TEMPERATURE', '0.1'))
            for chunk in pipeline.answer_generator.generate_answer_stream(
                question=query_info["original_question"],
                context=filtered_context,
                temperature=default_temp
            ):
                answer_text += chunk
                # Update UI in real-time
                answer_container.write(answer_text)
        finally:
            sys.stdout = old_stdout
        
        # Final answer (without metadata)
        answer_display = answer_text.split("\n\nActive person:")[0] if "Active person:" in answer_text else answer_text
    
    # Extract active person for display
    if "Active person:" in answer_text:
        active_person = answer_text.split("Active person: ")[1].strip()
        st.success(f"✅ Active Person: {active_person}")
    
    st.session_state.messages.append(
        {"role": "user", "content": prompt}
    )
    st.session_state.messages.append(
        {"role": "assistant", "content": answer_display}
    )
