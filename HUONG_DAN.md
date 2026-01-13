# 🎯 Hướng Dẫn Nhanh - Giải Thích Từng Folder/File

Tài liệu tóm tắt ngắn gọn về chức năng của từng phần trong project.

---

## 📂 **data/** - Lưu Trữ Dữ Liệu

| Thư mục | Chức năng | Ví dụ |
|---------|-----------|-------|
| `raw/` | Dữ liệu gốc chưa xử lý | PDF, TXT, CSV, JSON files |
| `processed/` | Dữ liệu đã làm sạch | JSON đã normalize |
| `embeddings/` | Vector embeddings (tương lai) | Cho semantic search |

**→ Đây là nơi bạn đặt dữ liệu đầu vào và kết quả xử lý**

---

## 📂 **graph/** - Quản Lý Knowledge Graph (Neo4j)

| File | Chức năng Chính | Ví Dụ Sử Dụng |
|------|-----------------|---------------|
| `storage.py` | **Kết nối Neo4j**, thực hiện queries | `GraphDB().get_founder("Fintech X")` |
| `schema.py` | Định nghĩa node/relationship types (tham khảo) | Constants: PERSON, COMPANY, FOUNDED |
| `builder.py` ⭐ | **Tạo nodes/relationships LINH HOẠT** | `builder.create_node("Person", "John", {...})` |
| `graph_utils.py` | Các hàm utility (subgraph, degree) | `query_subgraph(...)` |

**→ Đây là module CORE để tương tác với Neo4j**

### ⭐ `builder.py` - QUAN TRỌNG NHẤT:

```python
# Không cần viết từng hàm, làm việc với BẤT KỲ node type nào
builder.create_node("Person", "John", {"age": 30})
builder.create_node("Company", "Fintech X", {"industry": "Finance"})
builder.create_node("Product", {"code": "P001"}, {"name": "Product 1"})

# Tạo relationship giữa bất kỳ nodes nào
builder.create_relationship("Person", "John", "FOUNDED", "Company", "Fintech X")
```

---

## 📂 **retriever/** - Truy Vấn và Lấy Dữ Liệu

| File | Chức năng Chính | Input → Output |
|------|-----------------|----------------|
| `entity_extractor.py` | **Trích xuất intent từ câu hỏi** | "Ai là người sáng lập?" → `{"intent": "FIND_FOUNDER", "company": "..."}` |
| `graph_retriever.py` | **Query Neo4j để lấy context** | Company name → Founders + relationships |
| `hybrid_retriever.py` | Kết hợp graph + vector (tương lai) | ⚠️ Placeholder |
| `ranker.py` | Ranking kết quả theo relevance | List results → Sorted by score |

**→ Đây là module để "hiểu" câu hỏi và "tìm" dữ liệu từ graph**

### Workflow:
```
Câu hỏi → entity_extractor (hiểu ý) → graph_retriever (tìm data) → Context
```

---

## 📂 **llm/** - Xử Lý LLM (Ollama)

| File | Chức năng Chính | Input → Output |
|------|-----------------|----------------|
| `llm_client.py` ⭐ | **Gọi Ollama API** | Prompt → LLM Response |
| `prompt_templates.py` | Các prompt templates | INTENT_PROMPT, ANSWER_PROMPT, ... |
| `answer_generator.py` | **Generate câu trả lời từ context** | Question + Context → Answer |

**→ Đây là module để giao tiếp với Ollama và tạo câu trả lời**

### ⭐ `llm_client.py` - Đơn Giản:

```python
from llm.llm_client import call_llm

response = call_llm("Ai là người sáng lập của Fintech X?", model="mistral")
```

**Lưu ý:** 
- ⚠️ Phải chạy `ollama serve` trước
- ⚠️ Phải pull model: `ollama pull mistral`

---

## 📂 **pipeline/** - Orchestrate Toàn Bộ Quá Trình

| File | Chức năng Chính | Workflow |
|------|-----------------|----------|
| `query_pipeline.py` ⭐⭐ | **Main pipeline xử lý câu hỏi** | Question → Intent → Retrieve → Generate → Answer |
| `ingest.py` | **Pipeline nạp data vào graph** | Raw file → Process → Extract → Build Graph |
| `context_builder.py` | Build context string từ results | Graph results → Formatted context |

**→ Đây là module ORCHESTRATE - điều phối toàn bộ quá trình**

### ⭐⭐ `query_pipeline.py` - CORE:

**Workflow chi tiết:**
```
1. User Question
   ↓
2. entity_extractor.extract_intent() 
   → {"intent": "FIND_FOUNDER", "company": "Fintech X"}
   ↓
3. graph_retriever.retrieve_by_company()
   → {"founders": ["John"], "context": "..."}
   ↓
4. answer_generator.generate_answer()
   → Format prompt với context
   ↓
5. llm_client.call_llm()
   → "John Doe là người sáng lập của Fintech X"
```

**Sử dụng:**
```python
from pipeline.query_pipeline import ask_agent

answer = ask_agent("Ai là người sáng lập của Fintech X?")
```

### `ingest.py` - Nạp Data:

```python
from pipeline.ingest import DataIngestionPipeline

ingest = DataIngestionPipeline()
result = ingest.ingest_from_file("data/raw/companies.json", "json")
# → Tạo nodes và relationships trong Neo4j
```

---

## 📂 **api/** - Interface Người Dùng

| File | Chức năng Chính |
|------|-----------------|
| `app.py` | **Streamlit UI** - Chat interface |
| `schemas.py` | Pydantic schemas cho API (tương lai) |

**→ Đây là giao diện để người dùng tương tác**

### `app.py` - Streamlit UI:

```bash
streamlit run api/app.py
```

**Features:**
- Chat interface
- Lưu lịch sử chat
- Sử dụng `ask_agent()` để xử lý

---

## 📂 **config/** - Cấu Hình

| File | Chức năng Chính |
|------|-----------------|
| `settings.yaml` | Cấu hình tổng thể (Ollama, Neo4j, ...) |
| `secrets.env.template` | Template cho environment variables |

**→ Đây là nơi cấu hình project**

### Setup:

```bash
# 1. Copy template
cp config/secrets.env.template config/secrets.env

# 2. Edit secrets.env với giá trị thực
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password
OLLAMA_URL=http://localhost:11434/api/generate
OLLAMA_MODEL=mistral
```

---

## 📂 **tests/** - Testing

| File | Chức năng Chính |
|------|-----------------|
| `test_retrieval.py` | Test retrieval functionality |
| `test_env.py` | Test environment variables |

**→ Đây là tests để verify code hoạt động đúng**

---

## 📂 **examples/** - Ví Dụ

| File | Chức năng Chính |
|------|-----------------|
| `builder_example.py` | 5 ví dụ sử dụng GraphBuilder |

**→ Đây là code mẫu để học cách sử dụng**

---

## 📄 **Root Files** - Tương Thích Ngược

| File | Chức năng |
|------|-----------|
| `main.py` | Wrapper → `pipeline.query_pipeline` |
| `graph.py` | Wrapper → `graph.storage` |
| `llm.py` | Wrapper → `llm.llm_client` |
| `prompts.py` | Wrapper → `llm.prompt_templates` |
| `ui.py` | Wrapper → `api.app` |

**→ Để code cũ vẫn hoạt động, không cần sửa**

---

## 🔄 **Luồng Hoạt Động Tổng Quan**

### **1. Ingest Data (Nạp dữ liệu vào graph):**
```
data/raw/companies.json
    ↓
pipeline/ingest.py (parse file)
    ↓
graph/builder.py (tạo nodes & relationships)
    ↓
Neo4j Database
```

### **2. Query Processing (Xử lý câu hỏi):**
```
User: "Ai là người sáng lập của Fintech X?"
    ↓
pipeline/query_pipeline.py
    ↓
retriever/entity_extractor.py (hiểu câu hỏi)
    ↓
retriever/graph_retriever.py (tìm trong Neo4j)
    ↓
llm/answer_generator.py (format prompt)
    ↓
llm/llm_client.py (gọi Ollama)
    ↓
Answer: "John Doe là người sáng lập..."
```

### **3. UI Flow:**
```
User nhập vào Streamlit
    ↓
api/app.py
    ↓
pipeline/query_pipeline.py (ask_agent)
    ↓
Hiển thị answer
```

---

## 🎯 **Tóm Tắt Ngắn Gọn**

| Module | Nhiệm Vụ Chính | File Quan Trọng Nhất |
|--------|----------------|---------------------|
| **graph/** | Quản lý Neo4j | `builder.py` ⭐ |
| **retriever/** | Tìm dữ liệu từ graph | `graph_retriever.py` |
| **llm/** | Giao tiếp với Ollama | `llm_client.py` ⭐ |
| **pipeline/** | Điều phối quá trình | `query_pipeline.py` ⭐⭐ |
| **api/** | Giao diện người dùng | `app.py` |
| **config/** | Cấu hình | `secrets.env.template` |
| **data/** | Lưu trữ dữ liệu | - |

---

## 💡 **Quick Start**

1. **Setup environment:**
   ```bash
   cp config/secrets.env.template config/secrets.env
   # Edit secrets.env
   ```

2. **Chạy Neo4j và Ollama:**
   ```bash
   # Terminal 1: Neo4j (hoặc Docker)
   # Terminal 2:
   ollama serve
   ollama pull mistral
   ```

3. **Chạy UI:**
   ```bash
   streamlit run api/app.py
   ```

4. **Hoặc dùng code:**
   ```python
   from pipeline.query_pipeline import ask_agent
   answer = ask_agent("Ai là người sáng lập của Fintech X?")
   ```

---

**Tài liệu chi tiết hơn:** Xem `ARCHITECTURE.md`


