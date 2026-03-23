# 🔄 Sequence Diagrams - Graph RAG System

Tài liệu này mô tả các luồng hoạt động của hệ thống thông qua sequence diagrams.

---

## 📊 1. Query Processing Flow - Xử Lý Câu Hỏi

Luồng xử lý khi người dùng đặt câu hỏi:

```mermaid
sequenceDiagram
    participant User as 👤 User
    participant UI as api/app.py<br/>(Streamlit UI)
    participant Pipeline as pipeline/query_pipeline.py<br/>(QueryPipeline)
    participant Extractor as retriever/entity_extractor.py<br/>(EntityExtractor)
    participant Retriever as retriever/graph_retriever.py<br/>(GraphRetriever)
    participant GraphDB as graph/storage.py<br/>(GraphDB)
    participant Neo4j as 🗄️ Neo4j Database
    participant AnswerGen as llm/answer_generator.py<br/>(AnswerGenerator)
    participant LLMClient as llm/llm_client.py<br/>(call_llm)
    participant Ollama as 🤖 Ollama LLM

    User->>UI: Nhập câu hỏi<br/>"Ai là người sáng lập của Fintech X?"
    UI->>Pipeline: ask_agent(question)
    
    Note over Pipeline: Bước 1: Extract Intent
    Pipeline->>Extractor: extract_intent(question)
    Extractor->>LLMClient: call_llm(INTENT_PROMPT)
    LLMClient->>Ollama: HTTP POST /api/generate
    Ollama-->>LLMClient: {"response": "{\"intent\": \"FIND_FOUNDER\", \"company\": \"Fintech X\"}"}
    LLMClient-->>Extractor: JSON response
    Extractor->>Extractor: Parse JSON
    Extractor-->>Pipeline: {"intent": "FIND_FOUNDER", "company": "Fintech X"}
    
    Note over Pipeline: Bước 2: Retrieve Context
    Pipeline->>Retriever: retrieve_by_company("Fintech X")
    Retriever->>GraphDB: get_founder("Fintech X")
    GraphDB->>Neo4j: Cypher Query<br/>MATCH (p:Person)-[:FOUNDED]->(c:Company)
    Neo4j-->>GraphDB: [{"founder": "John Doe"}]
    GraphDB-->>Retriever: ["John Doe"]
    Retriever->>Retriever: Build context string
    Retriever-->>Pipeline: {"context": "Company: Fintech X\nFounders: John Doe"}
    
    Note over Pipeline: Bước 3: Generate Answer
    Pipeline->>AnswerGen: generate_answer(question, context)
    AnswerGen->>AnswerGen: Format prompt với<br/>CONTEXT_SYNTHESIS_PROMPT
    AnswerGen->>LLMClient: call_llm(formatted_prompt)
    LLMClient->>Ollama: HTTP POST /api/generate
    Ollama-->>LLMClient: {"response": "John Doe là người sáng lập..."}
    LLMClient-->>AnswerGen: Answer text
    AnswerGen-->>Pipeline: "John Doe là người sáng lập của Fintech X"
    
    Pipeline-->>UI: Answer
    UI->>UI: Save to session state
    UI-->>User: Hiển thị câu trả lời
```

**Mô tả các bước:**

1. **User Input**: Người dùng nhập câu hỏi vào Streamlit UI
2. **Intent Extraction**: EntityExtractor sử dụng LLM để parse câu hỏi thành structured intent
3. **Graph Retrieval**: GraphRetriever query Neo4j để lấy thông tin liên quan
4. **Answer Generation**: AnswerGenerator format prompt và gọi LLM để tạo câu trả lời
5. **Display**: UI hiển thị kết quả cho người dùng

---

## 📥 2. Data Ingestion Flow - Nạp Dữ Liệu Vào Graph

Luồng xử lý khi nạp dữ liệu từ file vào Neo4j:

```mermaid
sequenceDiagram
    participant Dev as 👨‍💻 Developer
    participant Ingest as pipeline/ingest.py<br/>(DataIngestionPipeline)
    participant Builder as graph/builder.py<br/>(GraphBuilder)
    participant GraphDB as graph/storage.py<br/>(GraphDB)
    participant Neo4j as 🗄️ Neo4j Database
    participant FileSystem as 📁 File System

    Dev->>Ingest: ingest_from_file("data/raw/companies.json")
    
    Note over Ingest: Bước 1: Read & Parse File
    Ingest->>FileSystem: Read file
    FileSystem-->>Ingest: File content
    Ingest->>Ingest: _process_file()<br/>Parse JSON/CSV/TXT
    Ingest->>Ingest: Extract structured data<br/>[{"type": "Person", "identifier": "John", ...}]
    
    Note over Ingest: Bước 2: Build Graph
    Ingest->>Builder: build_from_data(processed_data)
    
    loop For each node in data
        Builder->>Builder: create_node(node_type, identifier, properties)
        Builder->>GraphDB: Execute Cypher MERGE
        GraphDB->>Neo4j: MERGE (n:Person {name: $name})<br/>SET n += $properties
        Neo4j-->>GraphDB: Node created
        GraphDB-->>Builder: Success
    end
    
    loop For each relationship in data
        Builder->>Builder: create_relationship(from, rel_type, to)
        Builder->>GraphDB: Execute Cypher MERGE
        GraphDB->>Neo4j: MATCH (from), (to)<br/>MERGE (from)-[r:FOUNDED]->(to)
        Neo4j-->>GraphDB: Relationship created
        GraphDB-->>Builder: Success
    end
    
    Builder-->>Ingest: {"nodes_created": 10, "relationships_created": 5}
    Ingest-->>Dev: {"status": "success", "nodes_created": 10, ...}
```

**Mô tả các bước:**

1. **File Reading**: Đọc file từ `data/raw/`
2. **Processing**: Parse và extract structured data (nodes, relationships)
3. **Node Creation**: Tạo các nodes trong Neo4j với `create_node()`
4. **Relationship Creation**: Tạo các relationships với `create_relationship()`
5. **Return Results**: Trả về số lượng nodes và relationships đã tạo

---

## 🎨 3. UI Interaction Flow - Tương Tác Giao Diện

Luồng tương tác giữa người dùng và Streamlit UI:

```mermaid
sequenceDiagram
    participant User as 👤 User
    participant Streamlit as api/app.py<br/>(Streamlit)
    participant SessionState as 💾 Session State
    participant Pipeline as pipeline/query_pipeline.py

    Note over User,Streamlit: Khởi tạo ứng dụng
    Streamlit->>SessionState: Initialize messages = []
    Streamlit->>User: Hiển thị chat interface
    
    loop Mỗi lần user nhập câu hỏi
        User->>Streamlit: Nhập câu hỏi vào chat_input
        Streamlit->>Streamlit: st.chat_message("user").write(prompt)
        Streamlit->>SessionState: Append {"role": "user", "content": prompt}
        
        Streamlit->>Pipeline: ask_agent(prompt)
        Note over Pipeline: Xử lý query (xem diagram 1)
        Pipeline-->>Streamlit: Answer
        
        Streamlit->>Streamlit: st.chat_message("assistant").write(answer)
        Streamlit->>SessionState: Append {"role": "assistant", "content": answer}
        Streamlit->>User: Hiển thị câu trả lời
        
        Note over Streamlit,SessionState: Lưu lịch sử chat
    end
    
    Note over User,Streamlit: Refresh page
    Streamlit->>SessionState: Load messages
    Streamlit->>User: Hiển thị lại toàn bộ lịch sử chat
```

**Tính năng:**

- **Chat History**: Lưu tất cả messages trong session state
- **Real-time**: Hiển thị ngay khi có câu trả lời
- **Persistent**: Giữ lịch sử trong suốt session

---

## 🔍 4. Entity Extraction Detail - Chi Tiết Trích Xuất Entity

Luồng chi tiết của quá trình trích xuất intent từ câu hỏi:

```mermaid
sequenceDiagram
    participant Question as ❓ User Question
    participant Extractor as retriever/entity_extractor.py<br/>(EntityExtractor)
    participant PromptTemplate as llm/prompt_templates.py<br/>(INTENT_PROMPT)
    participant LLMClient as llm/llm_client.py
    participant Ollama as 🤖 Ollama

    Question->>Extractor: extract_intent("Ai là người sáng lập của Fintech X?")
    
    Extractor->>PromptTemplate: INTENT_PROMPT.format(question)
    PromptTemplate-->>Extractor: Formatted prompt string
    
    Extractor->>LLMClient: call_llm(prompt, temperature=0.3)
    LLMClient->>LLMClient: Build payload<br/>{"model": "mistral", "prompt": "...", "options": {"temperature": 0.3}}
    LLMClient->>Ollama: POST http://localhost:11434/api/generate
    Ollama->>Ollama: Process prompt<br/>Extract intent
    Ollama-->>LLMClient: {"response": "{\"intent\": \"FIND_FOUNDER\", \"company\": \"Fintech X\"}"}
    
    LLMClient-->>Extractor: Raw response string
    
    alt JSON Parse Success
        Extractor->>Extractor: json.loads(response)
        Extractor-->>Question: {"intent": "FIND_FOUNDER", "company": "Fintech X"}
    else JSON Parse Failed
        Extractor->>Extractor: Extract JSON from text<br/>(find '{' and '}')
        Extractor->>Extractor: json.loads(extracted_json)
        Extractor-->>Question: Parsed intent dict
    else All Failed
        Extractor-->>Question: None (return error)
    end
```

**Xử lý lỗi:**

- **JSON Parse**: Tự động extract JSON nếu LLM trả về text có JSON
- **Error Handling**: Trả về None nếu không parse được
- **Low Temperature**: Dùng temperature=0.3 để có kết quả JSON ổn định hơn

---

## 🏗️ 5. Graph Building Detail - Chi Tiết Xây Dựng Graph

Luồng chi tiết khi tạo node và relationship trong Neo4j:

```mermaid
sequenceDiagram
    participant Data as 📊 Structured Data
    participant Builder as graph/builder.py<br/>(GraphBuilder)
    participant GraphDB as graph/storage.py<br/>(GraphDB)
    participant Neo4j as 🗄️ Neo4j Database

    Data->>Builder: build_from_data([<br/>  {"type": "Person", "identifier": "John", ...},<br/>  {"type": "Company", "identifier": "Fintech X", ...}<br/>])
    
    Note over Builder: Process Nodes
    loop For each node
        Builder->>Builder: Parse node data<br/>Extract type, identifier, properties
        Builder->>Builder: create_node("Person", "John", {"age": 30})
        Builder->>Builder: Build Cypher query<br/>MERGE (n:Person {name: $match_name})<br/>SET n += $props
        Builder->>GraphDB: session.run(query, params)
        GraphDB->>Neo4j: Execute MERGE query
        Neo4j->>Neo4j: Check if node exists<br/>Create or update
        Neo4j-->>GraphDB: Node created/updated
        GraphDB-->>Builder: Success
    end
    
    Note over Builder: Process Relationships
    loop For each relationship
        Builder->>Builder: Parse relationship data<br/>Extract from, to, rel_type
        Builder->>Builder: create_relationship(<br/>  "Person", "John",<br/>  "FOUNDED",<br/>  "Company", "Fintech X"<br/>)
        Builder->>Builder: Build Cypher query<br/>MATCH (from:Person {name: $from_name})<br/>MATCH (to:Company {name: $to_name})<br/>MERGE (from)-[r:FOUNDED]->(to)
        Builder->>GraphDB: session.run(query, params)
        GraphDB->>Neo4j: Execute MERGE query
        Neo4j->>Neo4j: Match nodes<br/>Create relationship if not exists
        Neo4j-->>GraphDB: Relationship created
        GraphDB-->>Builder: Success
    end
    
    Builder->>Builder: Count nodes & relationships
    Builder-->>Data: {"nodes_created": 2, "relationships_created": 1}
```

**Đặc điểm:**

- **MERGE Operation**: Tự động tạo hoặc cập nhật node nếu đã tồn tại
- **Batch Processing**: Xử lý nhiều nodes/relationships cùng lúc
- **Generic**: Hoạt động với bất kỳ node/relationship type nào

---

## 🔄 6. Complete System Flow - Luồng Hệ Thống Hoàn Chỉnh

Tổng quan toàn bộ hệ thống từ đầu đến cuối:

```mermaid
sequenceDiagram
    participant User as 👤 User
    participant UI as Streamlit UI
    participant Pipeline as Query Pipeline
    participant Extractor as Entity Extractor
    participant Retriever as Graph Retriever
    participant GraphDB as GraphDB
    participant Neo4j as Neo4j
    participant AnswerGen as Answer Generator
    participant LLM as Ollama LLM

    rect rgb(200, 220, 255)
        Note over User,LLM: Phase 1: Setup (One-time)
        User->>Neo4j: Start Neo4j server
        User->>LLM: Start Ollama (ollama serve)
        User->>LLM: Pull model (ollama pull mistral)
    end
    
    rect rgb(220, 255, 220)
        Note over User,Neo4j: Phase 2: Data Ingestion (One-time or periodic)
        User->>Pipeline: ingest_from_file("data/raw/companies.json")
        Pipeline->>GraphDB: Create nodes & relationships
        GraphDB->>Neo4j: Store data
        Neo4j-->>GraphDB: Confirmed
        GraphDB-->>Pipeline: Success
        Pipeline-->>User: Data ingested
    end
    
    rect rgb(255, 255, 200)
        Note over User,LLM: Phase 3: Query Processing (Every user query)
        User->>UI: Enter question
        UI->>Pipeline: ask_agent(question)
        Pipeline->>Extractor: extract_intent(question)
        Extractor->>LLM: Call LLM for intent
        LLM-->>Extractor: Intent JSON
        Extractor-->>Pipeline: Parsed intent
        
        Pipeline->>Retriever: retrieve_by_company(name)
        Retriever->>GraphDB: Query graph
        GraphDB->>Neo4j: Cypher query
        Neo4j-->>GraphDB: Results
        GraphDB-->>Retriever: Context data
        Retriever-->>Pipeline: Formatted context
        
        Pipeline->>AnswerGen: generate_answer(q, context)
        AnswerGen->>LLM: Call LLM with context
        LLM-->>AnswerGen: Answer text
        AnswerGen-->>Pipeline: Final answer
        Pipeline-->>UI: Answer
        UI-->>User: Display answer
    end
```

**3 Phases chính:**

1. **Setup**: Khởi động Neo4j và Ollama (một lần)
2. **Data Ingestion**: Nạp dữ liệu vào graph (một lần hoặc định kỳ)
3. **Query Processing**: Xử lý câu hỏi người dùng (mỗi lần query)

---

## 🔀 7. Error Handling Flow - Xử Lý Lỗi

Luồng xử lý các trường hợp lỗi:

```mermaid
sequenceDiagram
    participant User as 👤 User
    participant Pipeline as Query Pipeline
    participant Extractor as Entity Extractor
    participant Retriever as Graph Retriever
    participant GraphDB as GraphDB
    participant Neo4j as 🗄️ Neo4j
    participant LLM as 🤖 Ollama

    User->>Pipeline: ask_agent(question)
    
    Pipeline->>Extractor: extract_intent(question)
    
    alt LLM không khả dụng
        Extractor->>LLM: call_llm(prompt)
        LLM-->>Extractor: ConnectionError
        Extractor-->>Pipeline: None
        Pipeline-->>User: "❌ Không hiểu câu hỏi. Vui lòng thử lại."
    else Intent parse failed
        Extractor->>LLM: call_llm(prompt)
        LLM-->>Extractor: Invalid JSON response
        Extractor->>Extractor: Try extract JSON from text
        Extractor-->>Extractor: Still failed
        Extractor-->>Pipeline: None
        Pipeline-->>User: "❌ Không hiểu câu hỏi. Vui lòng thử lại."
    else Intent OK, nhưng không tìm thấy data
        Extractor-->>Pipeline: {"intent": "FIND_FOUNDER", "company": "Unknown"}
        Pipeline->>Retriever: retrieve_by_company("Unknown")
        Retriever->>GraphDB: Query Neo4j
        GraphDB->>Neo4j: Cypher query
        Neo4j-->>GraphDB: Empty results
        GraphDB-->>Retriever: []
        Retriever-->>Pipeline: Empty context
        Pipeline-->>User: "❌ Không tìm thấy dữ liệu liên quan."
    else Neo4j không khả dụng
        Retriever->>GraphDB: Query
        GraphDB->>Neo4j: Connection attempt
        Neo4j-->>GraphDB: ConnectionError
        GraphDB-->>Retriever: Exception
        Retriever-->>Pipeline: Exception
        Pipeline-->>User: "❌ Lỗi kết nối database."
    else Tất cả OK
        Extractor-->>Pipeline: Valid intent
        Retriever-->>Pipeline: Valid context
        Pipeline->>LLM: Generate answer
        LLM-->>Pipeline: Answer
        Pipeline-->>User: "✅ [Answer]"
    end
```

**Các trường hợp lỗi được xử lý:**

- ✅ LLM không khả dụng
- ✅ JSON parse failed
- ✅ Không tìm thấy data trong graph
- ✅ Neo4j connection error
- ✅ LLM generation error

---

## 📈 8. Batch Processing Flow - Xử Lý Hàng Loạt

Luồng xử lý khi ingest nhiều files hoặc tạo nhiều nodes cùng lúc:

```mermaid
sequenceDiagram
    participant Dev as 👨‍💻 Developer
    participant Ingest as DataIngestionPipeline
    participant Builder as GraphBuilder
    participant GraphDB as GraphDB
    participant Neo4j as 🗄️ Neo4j

    Dev->>Ingest: ingest_from_directory("data/raw")
    
    loop For each file
        Ingest->>Ingest: Read file
        Ingest->>Ingest: Parse & extract data
        Ingest->>Builder: build_from_data(data)
        
        Note over Builder: Batch Create Nodes
        Builder->>Builder: batch_create_nodes(nodes_list)
        loop For each node (parallel processing possible)
            Builder->>GraphDB: create_node(...)
            GraphDB->>Neo4j: MERGE query
            Neo4j-->>GraphDB: Success
        end
        
        Note over Builder: Batch Create Relationships
        Builder->>Builder: batch_create_relationships(rels_list)
        loop For each relationship
            Builder->>GraphDB: create_relationship(...)
            GraphDB->>Neo4j: MERGE query
            Neo4j-->>GraphDB: Success
        end
        
        Builder-->>Ingest: Count results
    end
    
    Ingest->>Ingest: Aggregate all results
    Ingest-->>Dev: Summary report<br/>{"files_processed": 5, "total_nodes": 50, ...}
```

**Tối ưu hóa:**

- **Batch Operations**: Xử lý nhiều items cùng lúc
- **Error Handling**: Tiếp tục với file tiếp theo nếu một file lỗi
- **Progress Tracking**: Trả về summary report

---

## 🎯 Tóm Tắt

Các sequence diagrams trên mô tả:

1. ✅ **Query Processing**: Luồng xử lý câu hỏi từ đầu đến cuối
2. ✅ **Data Ingestion**: Luồng nạp dữ liệu vào graph
3. ✅ **UI Interaction**: Tương tác với Streamlit
4. ✅ **Entity Extraction**: Chi tiết trích xuất intent
5. ✅ **Graph Building**: Chi tiết tạo nodes/relationships
6. ✅ **Complete System**: Tổng quan toàn hệ thống
7. ✅ **Error Handling**: Xử lý các trường hợp lỗi
8. ✅ **Batch Processing**: Xử lý hàng loạt

**Lưu ý:** Các diagrams này sử dụng Mermaid syntax và sẽ được render tự động trong các markdown viewers hỗ trợ (GitHub, GitLab, VS Code với extension, ...).
