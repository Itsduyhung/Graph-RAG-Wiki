# Graph RAG - Knowledge Graph Retrieval Augmented Generation

Hệ thống Graph RAG sử dụng Knowledge Graph để cải thiện chất lượng câu trả lời của LLM bằng cách kết hợp thông tin cấu trúc từ đồ thị tri thức.

## 📁 Cấu trúc Dự án

```
graph-rag/
│
├── data/
│   ├── raw/                    # Dữ liệu gốc (pdf, txt, docx, csv...)
│   ├── processed/              # Dữ liệu đã làm sạch
│   └── embeddings/             # Vector embedding
│
├── graph/
│   ├── builder.py              # Tạo graph từ dữ liệu
│   ├── schema.py               # Định nghĩa node & edge
│   ├── storage.py              # Neo4j / NetworkX / ArangoDB
│   └── graph_utils.py          # Utility functions
│
├── retriever/
│   ├── entity_extractor.py     # Trích xuất entity từ câu hỏi
│   ├── graph_retriever.py      # Lấy subgraph liên quan
│   ├── hybrid_retriever.py     # (graph + vector)
│   └── ranker.py               # Ranking results
│
├── llm/
│   ├── prompt_templates.py     # Prompt cho Graph RAG
│   ├── llm_client.py           # OpenAI / Azure / Ollama
│   └── answer_generator.py     # Generate answers
│
├── pipeline/
│   ├── ingest.py               # Nạp dữ liệu → graph
│   ├── query_pipeline.py       # Luồng xử lý câu hỏi
│   └── context_builder.py      # Build context from graph
│
├── api/
│   ├── app.py                  # FastAPI / Flask / Streamlit
│   └── schemas.py              # API schemas
│
├── config/
│   ├── settings.yaml           # Configuration
│   └── secrets.env.template    # Environment variables template
│
├── tests/
│   ├── test_retrieval.py       # Test retrieval
│   └── test_env.py             # Test environment
│
├── requirements.txt
└── README.md
```

## 🚀 Cài đặt

### 1. Cài đặt Dependencies

```bash
pip install -r requirements.txt
```

### 2. Cấu hình Environment Variables

Sao chép file template và điền thông tin:

```bash
cp config/secrets.env.template config/secrets.env
```

Chỉnh sửa `config/secrets.env`:
- Neo4j connection: URI, USER, PASSWORD, DB
- LLM provider: Ollama (mặc định), OpenAI, hoặc Azure OpenAI

### 3. Khởi động Neo4j

Đảm bảo Neo4j đang chạy và có thể kết nối với thông tin trong `config/secrets.env`.

### 4. Khởi động Ollama (nếu sử dụng)

```bash
ollama serve
ollama pull mistral
```

## 📖 Sử dụng

### Chạy Streamlit UI

```bash
streamlit run api/app.py
```

Hoặc sử dụng file tương thích ngược:

```bash
streamlit run ui.py
```

### Sử dụng trong Code

```python
from pipeline.query_pipeline import ask_agent

# Hỏi câu hỏi
answer = ask_agent("Ai là người sáng lập của Fintech X?")
print(answer)
```

### Ingest dữ liệu vào Graph

```python
from pipeline.ingest import DataIngestionPipeline

ingest = DataIngestionPipeline()

# Ingest từ file
result = ingest.ingest_from_file("data/raw/companies.json", "json")

# Ingest từ thư mục
result = ingest.ingest_from_directory("data/raw", file_types=["pdf", "txt"])
```

## 🔧 Cấu hình

### LLM Model

Project sử dụng Ollama local. Để thay đổi model:

```python
from pipeline.query_pipeline import QueryPipeline

# Sử dụng model khác (llama2, codellama, phi, etc.)
pipeline = QueryPipeline(model="llama2")
```

Hoặc set environment variable:
```bash
export OLLAMA_MODEL=llama2
```

### Graph Builder - Linh hoạt và Generic

GraphBuilder giờ đây hoàn toàn linh hoạt, không cần viết từng hàm cho mỗi node type:

```python
from graph.builder import GraphBuilder

builder = GraphBuilder()

# Tạo node với bất kỳ type nào
builder.create_node("Person", "John Doe", {"age": 30})
builder.create_node("Company", "Fintech X", {"industry": "Finance"})
builder.create_node("Product", {"code": "P001"}, {"name": "Product 1"})

# Tạo relationship giữa bất kỳ node types nào
builder.create_relationship("Person", "John", "FOUNDED", "Company", "Fintech X")
builder.create_relationship("Product", {"code": "P001"}, "BELONGS_TO", "Category", {"name": "Tech"})

# Batch processing
nodes = [
    {"type": "Person", "identifier": "Alice", "properties": {"age": 25}},
    {"type": "Company", "identifier": "Tech Corp", "properties": {"industry": "IT"}},
]
builder.batch_create_nodes(nodes)

# Build từ data với format linh hoạt
data = [
    {"person": "Bob", "company": "Startup Y", "relationship": "FOUNDED"},
]
result = builder.build_from_data(data)
```

Xem thêm ví dụ trong `examples/builder_example.py`.

### Graph Schema

Schema được định nghĩa trong `graph/schema.py` để tham khảo, nhưng không bắt buộc. Bạn có thể tạo bất kỳ node type và relationship type nào.

## 🧪 Testing

```bash
# Chạy tests
pytest tests/

# Test Neo4j connection
python test_neo4j.py

# Test environment
python test_env.py
```

## 📝 Tương thích Ngược

Code cũ vẫn hoạt động nhờ các file wrapper:
- `main.py` → `pipeline/query_pipeline.py`
- `graph.py` → `graph/storage.py`
- `llm.py` → `llm/llm_client.py`
- `prompts.py` → `llm/prompt_templates.py`
- `ui.py` → `api/app.py`

## 🔄 Workflow

1. **Ingest**: Dữ liệu raw → processed → graph
2. **Query**: Câu hỏi → entity extraction → graph retrieval → answer generation
3. **Retrieval**: Graph retrieval + (optional) Vector retrieval → Hybrid results
4. **Generation**: Context + Question → LLM → Answer

## 📚 Modules

### Graph Module
- `storage.py`: Neo4j connection và queries
- `schema.py`: Định nghĩa node và relationship types (tham khảo)
- `builder.py`: **Generic và linh hoạt** - tạo bất kỳ node/relationship type nào mà không cần viết từng hàm
- `graph_utils.py`: Utility functions cho graph operations

### Retriever Module
- `entity_extractor.py`: Trích xuất entities và intent từ câu hỏi
- `graph_retriever.py`: Lấy subgraph liên quan từ knowledge graph
- `hybrid_retriever.py`: Kết hợp graph và vector retrieval
- `ranker.py`: Ranking và scoring results

### LLM Module
- `llm_client.py`: Ollama client (local LLM) - đơn giản và tập trung
- `prompt_templates.py`: Templates cho các tasks
- `answer_generator.py`: Generate answers từ context sử dụng Ollama

### Pipeline Module
- `query_pipeline.py`: Main query processing pipeline
- `ingest.py`: Data ingestion pipeline
- `context_builder.py`: Build context từ retrieved data

## 🤝 Đóng góp

Pull requests are welcome! Vui lòng mở issue để thảo luận thay đổi lớn.

## 📄 License

MIT License

