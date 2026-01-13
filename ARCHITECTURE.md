# 📚 Tài Liệu Kiến Trúc Project - Graph RAG

Tài liệu này giải thích chi tiết nhiệm vụ và chức năng của từng folder/file trong project.

---

## 📁 Cấu Trúc Tổng Quan

```
graph-rag/
├── data/                    # Lưu trữ dữ liệu
├── graph/                   # Module quản lý Knowledge Graph (Neo4j)
├── retriever/              # Module truy vấn và lấy dữ liệu từ graph
├── llm/                    # Module xử lý LLM (Ollama)
├── pipeline/               # Pipeline xử lý query và ingest data
├── api/                    # API và UI (Streamlit)
├── config/                 # Cấu hình và settings
├── tests/                  # Test files
├── examples/               # Ví dụ sử dụng
└── Root files              # Files tương thích ngược
```

---

## 📂 **data/** - Lưu Trữ Dữ Liệu

**Nhiệm vụ:** Thư mục chứa dữ liệu ở các giai đoạn khác nhau trong quá trình xử lý.

### `data/raw/`
- **Chức năng:** Lưu trữ dữ liệu gốc chưa xử lý
- **Format hỗ trợ:** PDF, TXT, DOCX, CSV, JSON, ...
- **Ví dụ:** 
  - `companies.pdf` - Tài liệu về các công ty
  - `employees.csv` - Danh sách nhân viên
  - `relationships.json` - Dữ liệu quan hệ dạng JSON

### `data/processed/`
- **Chức năng:** Lưu trữ dữ liệu đã được làm sạch và chuẩn hóa
- **Format:** JSON, CSV đã được xử lý
- **Quá trình:** Raw data → Extract entities → Normalize → Processed data

### `data/embeddings/`
- **Chức năng:** Lưu trữ vector embeddings (cho tương lai - hybrid retrieval)
- **Format:** Pickle files, NumPy arrays, hoặc database vectors
- **Sử dụng:** Để thực hiện semantic search kết hợp với graph retrieval

---

## 📂 **graph/** - Module Quản Lý Knowledge Graph

**Nhiệm vụ:** Quản lý kết nối Neo4j, xây dựng graph, và các thao tác với knowledge graph.

### `graph/storage.py`
**Chức năng chính:** Kết nối và tương tác với Neo4j database

**Class:** `GraphDB`
- `__init__()`: Kết nối đến Neo4j (đọc từ env variables)
- `get_founder(company_name)`: Lấy danh sách người sáng lập của công ty
- `close()`: Đóng kết nối database

**Ví dụ sử dụng:**
```python
from graph.storage import GraphDB

db = GraphDB()
founders = db.get_founder("Fintech X")  # ["John Doe", "Jane Smith"]
db.close()
```

### `graph/schema.py`
**Chức năng chính:** Định nghĩa schema của graph (tham khảo, không bắt buộc)

**Nội dung:**
- Constants: `PERSON`, `COMPANY`, `FOUNDED`, `WORKS_AT`, `OWNS`
- `GRAPH_SCHEMA`: Dictionary mô tả các node types và relationship types
  - Properties của mỗi node type
  - Properties của mỗi relationship type
  - Mô tả ý nghĩa

**Mục đích:** 
- Tài liệu tham khảo cho developers
- Có thể dùng để validate data (tùy chọn)
- Không bắt buộc - builder.py linh hoạt hơn

### `graph/builder.py` ⭐ **QUAN TRỌNG**
**Chức năng chính:** Xây dựng graph từ data - **LINH HOẠT VÀ GENERIC**

**Class:** `GraphBuilder`

**Methods chính:**

1. **`create_node(node_type, identifier, properties)`**
   - Tạo node với **bất kỳ type nào** (Person, Company, Product, ...)
   - `node_type`: String (Person, Company, Product, ...)
   - `identifier`: String hoặc Dict để identify node
   - `properties`: Dict các thuộc tính
   
   **Ví dụ:**
   ```python
   builder.create_node("Person", "John Doe", {"age": 30})
   builder.create_node("Product", {"code": "P001"}, {"name": "Product 1"})
   ```

2. **`create_relationship(from_type, from_id, rel_type, to_type, to_id, properties, direction)`**
   - Tạo relationship giữa **bất kỳ 2 node types nào**
   - `from_type/to_type`: Loại node
   - `rel_type`: Loại relationship (FOUNDED, WORKS_AT, ...)
   - `direction`: "->" hoặc "<-"
   
   **Ví dụ:**
   ```python
   builder.create_relationship("Person", "John", "FOUNDED", "Company", "Fintech X")
   ```

3. **`batch_create_nodes(nodes)`**
   - Tạo nhiều nodes cùng lúc (hiệu suất cao)
   - Input: List of dicts với format: `{"type": "...", "identifier": "...", "properties": {...}}`

4. **`batch_create_relationships(relationships)`**
   - Tạo nhiều relationships cùng lúc

5. **`build_from_data(data)`**
   - Build graph từ data với format linh hoạt
   - Hỗ trợ nhiều format: dict với nodes/relationships, list of nodes, legacy format

**Điểm mạnh:**
- ✅ Không cần viết từng hàm cho mỗi node type
- ✅ Linh hoạt với bất kỳ schema nào
- ✅ Backward compatible (vẫn có `create_person()`, `create_company()`)

### `graph/graph_utils.py`
**Chức năng chính:** Các utility functions cho graph operations

**Functions:**

1. **`query_subgraph(graph_db, node_type, node_name, depth)`**
   - Lấy subgraph xung quanh một node cụ thể
   - `depth`: Độ sâu của subgraph (số bước từ node gốc)
   - Trả về: List các paths và nodes liên quan

2. **`get_node_degree(graph_db, node_type, node_name)`**
   - Đếm số lượng connections của một node
   - Dùng để tính importance/centrality

### `graph/__init__.py`
**Chức năng:** Export các classes và functions chính từ module

**Exports:**
- `GraphDB`, `GraphBuilder`
- `GRAPH_SCHEMA`, constants (PERSON, COMPANY, ...)
- Utility functions

---

## 📂 **retriever/** - Module Truy Vấn Dữ Liệu

**Nhiệm vụ:** Trích xuất entities từ câu hỏi, truy vấn graph, và ranking kết quả.

### `retriever/entity_extractor.py`
**Chức năng chính:** Trích xuất entities và intent từ câu hỏi người dùng

**Class:** `EntityExtractor`

**Methods:**

1. **`extract_intent(question)`**
   - Phân tích câu hỏi và trích xuất intent dạng structured
   - Sử dụng LLM (Ollama) để parse
   - Trả về: Dict với format `{"intent": "FIND_FOUNDER", "company": "Fintech X"}`

2. **`extract_entities(text)`**
   - Trích xuất tất cả entities từ text
   - Trả về: List of dicts `[{"type": "Person", "name": "...", "confidence": 0.9}]`

**Workflow:**
```
Câu hỏi: "Ai là người sáng lập của Fintech X?"
         ↓
    LLM Analysis
         ↓
{"intent": "FIND_FOUNDER", "company": "Fintech X"}
```

### `retriever/graph_retriever.py`
**Chức năng chính:** Truy vấn và lấy dữ liệu từ Neo4j graph

**Class:** `GraphRetriever`

**Methods:**

1. **`retrieve_by_company(company_name)`**
   - Lấy thông tin về công ty và các relationships
   - Trả về: Dict với founders, subgraph, context string

2. **`retrieve_by_person(person_name)`**
   - Lấy thông tin về người và các công ty họ thành lập

3. **`retrieve_by_relationship(entity_type, entity_name, relationship_type)`**
   - Lấy các entities được kết nối bởi relationship cụ thể
   - Generic - hoạt động với bất kỳ entity/relationship type nào

**Output format:**
```python
{
    "company": "Fintech X",
    "founders": ["John Doe"],
    "subgraph": [...],  # Raw Neo4j results
    "context": "Company: Fintech X\nFounders: John Doe"  # Formatted string
}
```

### `retriever/hybrid_retriever.py`
**Chức năng chính:** Kết hợp graph retrieval và vector retrieval (cho tương lai)

**Class:** `HybridRetriever`

**Status:** ⚠️ Đang phát triển - placeholder cho tương lai

**Ý tưởng:**
- Graph retrieval: Structured relationships (chính xác)
- Vector retrieval: Semantic similarity (linh hoạt)
- Kết hợp cả 2 để có kết quả tốt nhất

### `retriever/ranker.py`
**Chức năng chính:** Ranking và scoring các kết quả retrieval

**Class:** `ResultRanker`

**Methods:**

1. **`rank_by_relevance(results, query)`**
   - Ranking dựa trên độ liên quan với query
   - Sử dụng keyword matching, Jaccard similarity

2. **`rank_by_importance(results, importance_metric)`**
   - Ranking dựa trên graph metrics (degree, centrality)
   - Chưa implement đầy đủ - placeholder

---

## 📂 **llm/** - Module Xử Lý LLM (Ollama)

**Nhiệm vụ:** Giao tiếp với Ollama LLM, tạo prompts, và generate answers.

### `llm/llm_client.py` ⭐ **QUAN TRỌNG**
**Chức năng chính:** Client để gọi Ollama LLM API

**Functions:**

1. **`call_llm(prompt, model, stream, temperature, max_tokens)`**
   - Gọi Ollama API đơn giản và trực tiếp
   - `prompt`: Câu hỏi hoặc prompt
   - `model`: Tên model (mistral, llama2, ...) - mặc định từ env
   - `temperature`: Độ sáng tạo (0.0-1.0)
   - `max_tokens`: Số tokens tối đa
   - Trả về: Response text

2. **`call_llm_with_context(prompt, context, model, **kwargs)`**
   - Gọi LLM với context được thêm vào prompt

**Workflow:**
```
Prompt → HTTP POST to Ollama → Response JSON → Extract text
```

**Lưu ý:**
- ⚠️ Đảm bảo Ollama đang chạy: `ollama serve`
- ⚠️ Model phải được pull: `ollama pull mistral`

### `llm/prompt_templates.py`
**Chức năng chính:** Chứa các prompt templates cho các tasks khác nhau

**Templates:**

1. **`INTENT_PROMPT`**: Extract intent từ câu hỏi
2. **`ANSWER_PROMPT`**: Generate answer từ context
3. **`GRAPH_QUERY_PROMPT`**: Extract entities và relationships để query graph
4. **`ENTITY_EXTRACTION_PROMPT`**: Extract entities từ text
5. **`CONTEXT_SYNTHESIS_PROMPT`**: Synthesize context thành câu trả lời

**Ví dụ INTENT_PROMPT:**
```
You are an AI agent that extracts structured intent.
Return ONLY valid JSON.

User question: "{question}"

JSON format:
{
  "intent": "FIND_FOUNDER",
  "company": "<company name>"
}
```

### `llm/answer_generator.py`
**Chức năng chính:** Generate câu trả lời từ context đã retrieve

**Class:** `AnswerGenerator`

**Methods:**

- **`generate_answer(question, context, use_synthesis, temperature)`**
  - Nhận question và context (từ graph retrieval)
  - Format prompt với template
  - Gọi LLM để generate answer
  - Trả về: Câu trả lời đã được format

**Workflow:**
```
Question + Context → Format Prompt → LLM → Answer
```

### `llm/__init__.py`
**Chức năng:** Export các functions và classes chính

---

## 📂 **pipeline/** - Pipeline Xử Lý

**Nhiệm vụ:** Orchestrate toàn bộ quá trình xử lý query và ingest data.

### `pipeline/query_pipeline.py` ⭐ **CORE MODULE**
**Chức năng chính:** Main pipeline xử lý câu hỏi người dùng

**Class:** `QueryPipeline`

**Workflow:**
```
User Question
     ↓
1. Entity Extraction (extract_intent)
     ↓
2. Graph Retrieval (retrieve_by_company/person)
     ↓
3. Context Building
     ↓
4. Answer Generation (LLM)
     ↓
Final Answer
```

**Methods:**

- **`__init__(graph_db, model)`**: Khởi tạo với GraphDB và Ollama model
- **`process_query(question)`**: Xử lý toàn bộ pipeline
- **`_retrieve_context(intent)`**: Internal method để retrieve context từ graph

**Function:** `ask_agent(question)`
- Convenience function cho backward compatibility
- Tạo QueryPipeline mới và process query

**Ví dụ:**
```python
from pipeline.query_pipeline import ask_agent

answer = ask_agent("Ai là người sáng lập của Fintech X?")
```

### `pipeline/ingest.py`
**Chức năng chính:** Pipeline để nạp data vào graph

**Class:** `DataIngestionPipeline`

**Workflow:**
```
Raw Data (PDF/TXT/CSV/JSON)
     ↓
Process & Extract Entities
     ↓
Structured Data
     ↓
GraphBuilder.build_from_data()
     ↓
Neo4j Graph
```

**Methods:**

1. **`ingest_from_file(file_path, file_type)`**
   - Đọc file và extract structured data
   - Tự động detect file type nếu `file_type="auto"`
   - Build graph từ processed data

2. **`ingest_from_directory(directory, file_types)`**
   - Ingest tất cả files trong directory
   - Filter theo file types

3. **`ingest_from_data(data)`**
   - Ingest pre-processed structured data trực tiếp
   - Skip file processing step

4. **`_process_file(file_path, file_type)`** (internal)
   - Parse file dựa trên type
   - Extract entities và relationships
   - Trả về structured data

**Supported file types:**
- JSON: Direct parse
- CSV: Parse rows to structured format
- TXT: Placeholder (cần implement với LLM extraction)
- PDF/DOCX: Placeholder (cần libraries như PyPDF2, python-docx)

### `pipeline/context_builder.py`
**Chức năng chính:** Build context string từ graph retrieval results

**Class:** `ContextBuilder`

**Methods (static):**

1. **`build_context_from_results(results)`**
   - Convert graph retrieval results thành context string
   - Format: "Company: ...\nFounders: ..."

2. **`build_context_from_subgraph(subgraph)`**
   - Build context từ subgraph Neo4j results

3. **`combine_contexts(contexts)`**
   - Kết hợp nhiều context strings

**Mục đích:** Chuẩn bị context để đưa vào LLM prompt

### `pipeline/__init__.py`
**Chức năng:** Export các classes và functions chính

---

## 📂 **api/** - API và UI

**Nhiệm vụ:** Cung cấp interface cho người dùng (Streamlit UI và API schemas).

### `api/app.py`
**Chức năng chính:** Streamlit UI application

**Features:**
- Chat interface với AI agent
- Sử dụng `ask_agent()` từ query_pipeline
- Lưu lịch sử chat trong session state

**Cách chạy:**
```bash
streamlit run api/app.py
```

**UI Flow:**
```
User Input → ask_agent() → Display Answer → Save to History
```

### `api/schemas.py`
**Chức năng chính:** Pydantic schemas cho API (cho tương lai - FastAPI)

**Schemas:**

1. **`QueryRequest`**: Request schema cho query endpoint
   - `question`: String
   - `context`: Optional dict

2. **`QueryResponse`**: Response schema
   - `answer`: String
   - `context_used`: Optional string
   - `intent`: Optional dict

3. **`EntityRequest/Response`**: Cho entity extraction endpoint

4. **`IngestRequest/Response`**: Cho data ingestion endpoint

**Status:** ⚠️ Chuẩn bị cho FastAPI implementation trong tương lai

### `api/__init__.py`
**Chức năng:** Export schemas

---

## 📂 **config/** - Cấu Hình

**Nhiệm vụ:** Lưu trữ cấu hình và environment variables.

### `config/settings.yaml`
**Chức năng:** YAML configuration file

**Sections:**
- `ollama`: Cấu hình Ollama (URL, model, temperature, ...)
- `neo4j`: Neo4j settings (đọc từ env)
- `retrieval`: Retrieval settings (weights, max results, depth)
- `data`: Data processing settings (directories, formats)
- `api`: API configuration (host, port, title)
- `logging`: Logging settings

**Note:** Hiện tại chưa được load tự động - cần implement config loader

### `config/secrets.env.template`
**Chức năng:** Template cho environment variables

**Variables:**

- **Neo4j (Required):**
  - `NEO4J_URI`: bolt://localhost:7687
  - `NEO4J_USER`: neo4j
  - `NEO4J_PASSWORD`: your_password
  - `NEO4J_DB`: neo4j

- **Ollama (Required):**
  - `OLLAMA_URL`: http://localhost:11434/api/generate
  - `OLLAMA_MODEL`: mistral

**Cách sử dụng:**
```bash
cp config/secrets.env.template config/secrets.env
# Edit secrets.env với giá trị thực
```

---

## 📂 **tests/** - Testing

**Nhiệm vụ:** Unit tests và integration tests.

### `tests/test_retrieval.py`
**Chức năng:** Tests cho retrieval functionality

**Tests:**
- `test_graph_db_connection()`: Test Neo4j connection
- `test_get_founder()`: Test retrieving founders
- `test_graph_retriever()`: Test GraphRetriever
- `test_entity_extractor()`: Test entity extraction

**Cách chạy:**
```bash
pytest tests/test_retrieval.py
```

### `tests/test_env.py`
**Chức năng:** Test environment variables

**Action:** Print các env variables để verify

### `tests/__init__.py`
**Chức năng:** Package marker

---

## 📂 **examples/** - Ví Dụ

**Nhiệm vụ:** Ví dụ code để hướng dẫn sử dụng.

### `examples/builder_example.py`
**Chức năng:** Ví dụ sử dụng GraphBuilder

**Examples:**
1. `example_1_simple_nodes()`: Tạo nodes đơn giản
2. `example_2_relationships()`: Tạo relationships
3. `example_3_batch_processing()`: Batch operations
4. `example_4_flexible_data_format()`: Multiple data formats
5. `example_5_complex_scenario()`: Complex use case

**Cách chạy:**
```bash
python examples/builder_example.py
# Uncomment examples bạn muốn chạy
```

---

## 📄 **Root Files** - Tương Thích Ngược

**Nhiệm vụ:** Backward compatibility - giữ code cũ hoạt động.

### `main.py`
**Chức năng:** Wrapper redirect đến `pipeline.query_pipeline.ask_agent`

**Code cũ:**
```python
from main import ask_agent  # ✅ Vẫn hoạt động
```

### `graph.py`
**Chức năng:** Wrapper redirect đến `graph.storage.GraphDB`

### `llm.py`
**Chức năng:** Wrapper redirect đến `llm.llm_client.call_llm`

### `prompts.py`
**Chức năng:** Wrapper export `INTENT_PROMPT`, `ANSWER_PROMPT`

### `ui.py`
**Chức năng:** Wrapper redirect đến `api.app`

**Cách chạy:**
```bash
streamlit run ui.py  # ✅ Vẫn hoạt động
```

### `test_neo4j.py`
**Chức năng:** Test script tương thích ngược

### `test_env.py`
**Chức năng:** Test env tương thích ngược

---

## 📄 **Other Files**

### `requirements.txt`
**Chức năng:** Python dependencies

**Packages:**
- `neo4j`: Neo4j driver
- `streamlit`: UI framework
- `requests`: HTTP client cho Ollama
- `python-dotenv`: Load environment variables
- `pydantic`: Data validation (cho schemas)
- `pytest`: Testing framework
- `pyyaml`: YAML parser

### `README.md`
**Chức năng:** Documentation chính của project

### `.gitignore`
**Chức năng:** Git ignore rules
- Python cache files
- Virtual environment
- Environment files (secrets.env)
- Data files
- Logs

---

## 🔄 **Workflow Tổng Quan**

### **1. Ingest Data Workflow:**
```
Raw Data (PDF/TXT/CSV/JSON)
    ↓
pipeline/ingest.py → Process & Extract
    ↓
Structured Data
    ↓
graph/builder.py → Create Nodes & Relationships
    ↓
Neo4j Database (graph/storage.py)
```

### **2. Query Processing Workflow:**
```
User Question
    ↓
pipeline/query_pipeline.py
    ↓
retriever/entity_extractor.py → Extract Intent
    ↓
retriever/graph_retriever.py → Query Neo4j
    ↓
pipeline/context_builder.py → Build Context
    ↓
llm/answer_generator.py → Format Prompt
    ↓
llm/llm_client.py → Call Ollama
    ↓
Answer
```

### **3. UI Workflow:**
```
User Input (Streamlit)
    ↓
api/app.py
    ↓
pipeline/query_pipeline.py → ask_agent()
    ↓
Display Answer
```

---

## 🎯 **Điểm Mạnh của Kiến Trúc**

1. ✅ **Modular**: Mỗi module có trách nhiệm rõ ràng
2. ✅ **Flexible**: GraphBuilder linh hoạt với bất kỳ schema nào
3. ✅ **Simple**: LLM client đơn giản, chỉ focus Ollama
4. ✅ **Scalable**: Dễ mở rộng thêm node types, relationships
5. ✅ **Backward Compatible**: Code cũ vẫn hoạt động
6. ✅ **Well Documented**: Có ví dụ và documentation

---

## 📝 **Lưu Ý Quan Trọng**

1. **Neo4j phải đang chạy** trước khi sử dụng
2. **Ollama phải đang chạy** (`ollama serve`) và model đã được pull
3. **Environment variables** phải được set trong `config/secrets.env`
4. **GraphBuilder là generic** - không cần define schema trước
5. **LLM chỉ dùng Ollama local** - không support OpenAI/Azure nữa

---

**Last Updated:** 2026-01-10
**Version:** 1.0.0


