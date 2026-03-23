# Hướng dẫn Config Neo4j Indexes cho Hybrid Search

## 1. Kiểm tra Neo4j Version và Vector Support

Chạy trong Neo4j Browser:

```cypher
// Kiểm tra version
CALL dbms.components() YIELD name, versions, edition RETURN name, versions, edition

// Kiểm tra vector indexes (nếu có)
SHOW VECTOR INDEXES

// Kiểm tra full-text indexes
SHOW INDEXES WHERE type = "FULLTEXT"
```

**Lưu ý:** Vector index yêu cầu Neo4j 5.16+ hoặc Neo4j Desktop với plugin vector.

---

## 2. Tạo Full-Text Indexes (cho Keyword Search)

Chạy từng lệnh trong Neo4j Browser:

```cypher
// Full-text index cho Person (tìm theo tên, biệt danh)
CREATE FULLTEXT INDEX PersonIndex 
FOR (n:Person) 
ON EACH ([n.name, n.biography])

// Full-text index cho Dynasty
CREATE FULLTEXT INDEX DynastyIndex 
FOR (n:Dynasty) 
ON EACH ([n.name, n.description])

// Full-text index cho Event
CREATE FULLTEXT INDEX EventIndex 
FOR (n:Event) 
ON EACH ([n.name, n.description])

// Full-text index cho Country
CREATE FULLTEXT INDEX CountryIndex 
FOR (n:Country) 
ON EACH ([n.name])
```

### Test full-text search:

```cypher
// Tìm kiếm fuzzy
CALL db.index.fulltext.queryNodes("PersonIndex", "Lý Công Uẩn~", 5) 
YIELD node, score 
RETURN node.name, score

// Tìm kiếm exact
CALL db.index.fulltext.queryNodes("PersonIndex", "Lý Công Uẩn", 5) 
YIELD node, score 
RETURN node.name, score
```

---

## 3. Tạo Vector Indexes (cho Semantic Search)

### Bước 3.1: Tạo embedding property (một lần)

Cần thêm embedding vào các node muốn semantic search:

```cypher
// Thêm embedding property cho Person nodes (NULL ban đầu)
MATCH (n:Person)
SET n.embedding = null

// Tương tự cho các node type khác
MATCH (n:Dynasty)
SET n.embedding = null

MATCH (n:Event)
SET n.embedding = null
```

### Bước 3.2: Tạo vector index

```cypher
// Vector index cho Person (bge-m3 dimension = 1024)
CREATE VECTOR INDEX PersonVectorIndex
FOR (n:Person)
ON n.embedding
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 1024,
    `vector.similarity_function`: 'cosine'
  }
}

// Vector index cho Dynasty
CREATE VECTOR INDEX DynastyVectorIndex
FOR (n:Dynasty)
ON n.embedding
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 1024,
    `vector.similarity_function`: 'cosine'
  }
}
```

### Bước 3.3: Generate embeddings (cần code Python)

Tạo script để generate embeddings cho existing nodes:

```python
# generate_embeddings.py
from graph.search import SemanticSearcher
from graph.storage import GraphDB

# Khởi tạo
semantic = SemanticSearcher(embedding_model="BAAI/bge-m3")
graph_db = GraphDB()

# Get all nodes without embeddings
query = """
MATCH (n:Person)
WHERE n.embedding IS NULL
RETURN id(n) AS node_id, n.name AS name, n.biography AS bio
LIMIT 1000
"""

with graph_db.driver.session(database=graph_db.database) as session:
    result = session.run(query)
    nodes = list(result)

# Generate và update embeddings
for record in nodes:
    node_id = record["node_id"]
    text = f"{record['name']} {record['bio'] or ''}"
    
    # Generate embedding
    embedding = semantic.model.encode(text).tolist()
    
    # Update node
    session.run(
        "MATCH (n) WHERE id(n) = $node_id SET n.embedding = $embedding",
        node_id=node_id,
        embedding=embedding
    )

print(f"Updated {len(nodes)} nodes")
```

---

## 4. Sử dụng trong code

```python
from graph.search import HybridSearch, SearchConfig, create_fulltext_index, create_vector_index
from graph.storage import GraphDB

# Khởi tạo với config tùy chỉnh
config = SearchConfig(
    keyword_weight=0.3,
    semantic_weight=0.3,
    graph_weight=0.4,
    embedding_model="BAAI/bge-m3",
    top_k=5
)

searcher = HybridSearch(config)

# Search đơn giản
results = searcher.search(
    query="Ai là vị vua sáng lập nhà Lý?",
    entity_name="Lý Công Uẩn",
    entity_type="Person"
)

print(results["combined_context"])

# Search với intent từ LLM
intent = {
    "entity_name": "Lý Công Uẩn",
    "entity_type": "Person",
    "search_types": ["keyword", "semantic", "graph"],
    "filters": {"node_types": ["Person", "Dynasty"]}
}
results = searcher.search_by_intent("Ai là vị vua sáng lập nhà Lý?", intent)
```

---

## 5. Dynamic Schema cho LLM

```python
from graph.search import DynamicSchemaMapper

mapper = DynamicSchemaMapper()

# Get dynamic schema
schema = mapper.get_dynamic_schema()

# Generate creation schema cho LLM
creation_schema = mapper.generate_creation_schema()
print(creation_schema)
```

Output sẽ như:

```json
{
  "node_types": {
    "Person": {
      "common_properties": ["name", "biography", "birth_year", "death_year"],
      "description": "Người (vua, danh nhân, quan lại)"
    }
  },
  "relationship_types": [
    {"type": "BELONGS_TO_DYNASTY", "count": 150},
    {"type": "BORN_IN", "count": 100}
  ]
}
```

---

## 6. Validation cho LLM Output

```python
from graph.search import NodeValidator

# LLM trả về JSON
llm_response = '''
{
  "nodes": [
    {"name": "Trần Hưng Đạo", "title": "Hưng Đạo Vương", "birth_year": 1228},
    {"name": "Nhà Trần", "description": "Triều đại phong kiến Việt Nam"}
  ],
  "relationships": [
    {"from": "Trần Hưng Đạo", "to": "Nhà Trần", "type": "BELONGS_TO_DYNASTY"}
  ]
}
'''

# Validate và clean
validated = NodeValidator.validate_and_clean_response(llm_response)
print(validated)
```

---

## 7. Troubleshooting

### Lỗi "No such index"

```cypher
// Kiểm tra tất cả indexes
SHOW INDEXES
```

### Lỗi vector search không hoạt động

1. Kiểm tra Neo4j version hỗ trợ vector
2. Hoặc dùng alternative: tính similarity bằng Python thay vì native vector index

### Performance

- Thêm indexes cho các truy vấn thường xuyên
- Giới hạn batch khi generate embeddings (100-500 nodes mỗi lần)
