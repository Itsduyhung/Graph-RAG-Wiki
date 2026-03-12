# Person Profile Schema - Hướng dẫn sử dụng

## Tổng quan

Hệ thống đã được bổ sung để hỗ trợ Knowledge Graph với cấu trúc Person Profile đầy đủ, bao gồm các node types và relationships như trong hình minh họa.

## Schema mới

### Node Types

1. **Person** - Người (node trung tâm)
   - Properties: `name`, `age`, `email`, `birth_date`, `biography`

2. **Country** - Quốc gia
   - Properties: `name`, `code`, `region`

3. **Field** - Lĩnh vực làm việc
   - Properties: `name`, `category`, `description`

4. **Era** - Thời đại/kỷ nguyên
   - Properties: `name`, `start_year`, `end_year`, `description`

5. **Achievement** - Thành tựu
   - Properties: `name`, `year`, `description`, `award`

6. **WikiChunk** - Đoạn văn từ Wikipedia
   - Properties: `content`, `source`, `chunk_id`, `page_title`

7. **Company** - Công ty (giữ nguyên từ schema cũ)
   - Properties: `name`, `industry`, `founded_year`

### Relationships

1. **BORN_IN**: `(Person)-[:BORN_IN]->(Country)`
   - Properties: `year`, `city`

2. **WORKED_IN**: `(Person)-[:WORKED_IN]->(Field)`
   - Properties: `years`, `role`

3. **ACTIVE_IN**: `(Person)-[:ACTIVE_IN]->(Era)`
   - Properties: `start_year`, `end_year`

4. **ACHIEVED**: `(Person)-[:ACHIEVED]->(Achievement)`
   - Properties: `year`, `significance`

5. **INFLUENCED_BY**: `(Person)-[:INFLUENCED_BY]->(Person)`
   - Properties: `influence_type`, `description`

6. **DESCRIBED_IN**: `(Person)-[:DESCRIBED_IN]->(WikiChunk)`
   - Properties: `relevance_score`

7. **FOUNDED**: `(Person)-[:FOUNDED]->(Company)` (giữ nguyên)
   - Properties: `year`

## Cách sử dụng

### 1. Tạo Person với đầy đủ profile

```python
from graph.builder import GraphBuilder

builder = GraphBuilder()

builder.create_person_with_profile(
    "Albert Einstein",
    person_properties={
        "birth_date": "1879-03-14",
        "biography": "Theoretical physicist",
        "age": 76
    },
    born_in={
        "country": "Germany",
        "year": 1879,
        "city": "Ulm"
    },
    worked_in=[
        {
            "field": "Physics",
            "years": 50,
            "role": "Theoretical Physicist"
        }
    ],
    active_in=[
        {
            "era": "Early 20th Century",
            "start_year": 1900,
            "end_year": 1955
        }
    ],
    achievements=[
        {
            "achievement": "Nobel Prize in Physics",
            "year": 1921,
            "significance": "Highest recognition"
        }
    ],
    influenced_by=[
        {
            "person": "Max Planck",
            "influence_type": "Academic"
        }
    ],
    described_in=[
        {
            "chunk_id": "wiki_einstein_001",
            "content": "Albert Einstein was...",
            "source": "Wikipedia",
            "page_title": "Albert Einstein"
        }
    ]
)
```

### 2. Query Person Profile

```python
from retriever.graph_retriever import GraphRetriever

retriever = GraphRetriever()

# Lấy full profile
profile = retriever.retrieve_person_full_profile("Albert Einstein")
print(profile["context"])

# Lấy specific relationship
born_in = retriever.retrieve_by_relationship_type("Albert Einstein", "BORN_IN")
achievements = retriever.retrieve_by_relationship_type("Albert Einstein", "ACHIEVED")
```

### 3. Sử dụng Query Pipeline

```python
from pipeline.query_pipeline import QueryPipeline

pipeline = QueryPipeline()

# Các câu hỏi có thể hỏi:
answer1 = pipeline.process_query("Albert Einstein sinh ở đâu?")
answer2 = pipeline.process_query("Leonardo da Vinci làm việc trong lĩnh vực nào?")
answer3 = pipeline.process_query("Cho tôi biết về Steve Jobs")
answer4 = pipeline.process_query("Ai đã ảnh hưởng đến Albert Einstein?")
```

## Intent Types mới

Hệ thống hỗ trợ các intent types sau:

- `FIND_PERSON_PROFILE` - Lấy full profile của một person
- `FIND_BORN_IN` - Tìm nơi sinh của person
- `FIND_WORKED_IN` - Tìm các lĩnh vực person đã làm việc
- `FIND_ACTIVE_IN` - Tìm các era person đã hoạt động
- `FIND_ACHIEVEMENTS` - Tìm các thành tựu của person
- `FIND_INFLUENCERS` - Tìm những người đã ảnh hưởng đến person
- `FIND_FOUNDER` - Tìm founder của company (giữ nguyên)
- `FIND_COMPANY` - Tìm companies được thành lập bởi person (giữ nguyên)

## Tạo dữ liệu mẫu

Chạy script để tạo dữ liệu mẫu:

```bash
python create_person_profile_data.py
```

Script này sẽ tạo:
- 3 Person nodes: Albert Einstein, Leonardo da Vinci, Steve Jobs
- Các node liên quan: Country, Field, Era, Achievement, WikiChunk
- Tất cả các relationships tương ứng

## Files đã được cập nhật

1. **graph/schema.py** - Thêm node types và relationships mới
2. **retriever/graph_retriever.py** - Thêm methods:
   - `retrieve_person_full_profile()`
   - `retrieve_by_relationship_type()`
3. **graph/builder.py** - Thêm method:
   - `create_person_with_profile()`
4. **llm/prompt_templates.py** - Cập nhật prompts để hỗ trợ schema mới
5. **pipeline/query_pipeline.py** - Cập nhật để xử lý các intent mới
6. **create_person_profile_data.py** - Script tạo dữ liệu mẫu mới

## Lưu ý

- Tất cả các tính năng cũ vẫn hoạt động bình thường (backward compatible)
- GraphBuilder vẫn generic và có thể tạo bất kỳ node/relationship type nào
- Có thể sử dụng `create_node()` và `create_relationship()` trực tiếp nếu cần flexibility hơn
