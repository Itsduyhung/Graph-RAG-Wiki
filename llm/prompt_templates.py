# llm/prompt_templates.py
"""Prompt templates for Graph RAG tasks."""

INTENT_PROMPT = """
Bạn là AI Agent trích xuất intent có cấu trúc từ câu hỏi tiếng Việt.
Trả về DUY NHẤT JSON hợp lệ, không giải thích thêm.

Câu hỏi:
"{question}"

QUAN TRỌNG - Mapping tiếng Việt sang Relationship Type:
- "cha/ba/bố của" → FATHER_OF
- "mẹ của" → MOTHER_OF
- "con của" → CHILD_OF
- "vợ/chồng của" → SPOUSE_OF
- "anh chị em/ruột của" → SIBLING_OF
- "thầy/thầy giáo của" → MENTOR_OF
- "học trò của" → STUDENT_OF
- "đồng minh của" → ALLY_OF
- "kẻ thù của" → ENEMY_OF
- "bạn của" → FRIEND_OF
- "kế thừa của" → SUCCESSOR_OF
- "sinh năm/mùa sinh" → BORN_IN
- "mất năm/qua đời năm" → DIED_AT
- "làm việc tại/hoạt động trong" → WORKED_IN
- "thời kỳ/giai đoạn" → ACTIVE_IN
- "thành tựu/đạt được" → ACHIEVED
- "ảnh hưởng bởi" → INFLUENCED_BY
- "tham gia sự kiện" → PARTICIPATED_IN
- "thuộc triều đại" → BELONGS_TO_DYNASTY
- "có vai trò" → HAS_ROLE
- "tên khác/tên gọi khác" → HAS_NAME

Các loại Node trong Graph:
- Person (Người)
- Name (Tên gọi khác như tên sinh, biệt danh)
- Company (Công ty)
- Country (Quốc gia)
- Field (Lĩnh vực)
- Era (Thời kỳ)
- Dynasty (Triều đại)
- Role (Vai trò)
- Event (Sự kiện)
- TimePoint (Thời điểm)
- Achievement (Thành tựu)
- WikiChunk (Bài viết wiki)

Các loại Relationship:
- Quan hệ gia đình: FATHER_OF, MOTHER_OF, CHILD_OF, SPOUSE_OF, SIBLING_OF
- Quan hệ khác: MENTOR_OF, STUDENT_OF, ALLY_OF, ENEMY_OF, FRIEND_OF, SUCCESSOR_OF
- Quan hệ với thông tin: HAS_NAME, HAS_ROLE
- Quan hệ về thời gian/nơi chốn: BORN_IN, BORN_AT, DIED_AT
- Quan hệ về hoạt động: WORKED_IN, ACTIVE_IN, PARTICIPATED_IN
- Quan hệ về thành tựu: ACHIEVED, INFLUENCED_BY
- Quan hệ về danh hiệu: BELONGS_TO_DYNASTY

Intent Types (Loại câu hỏi):
- Tìm thông tin cá nhân: FIND_PERSON_PROFILE
- Tìm cha: FIND_FATHER
- Tìm mẹ: FIND_MOTHER
- Tìm cha mẹ: FIND_PARENTS
- Tìm vợ/chồng: FIND_SPOUSE
- Tìm anh chị em: FIND_SIBLINGS
- Tìm con cái: FIND_CHILDREN
- Tìm nơi sinh: FIND_BORN_IN
- Tìm ngày sinh: FIND_BORN_AT
- Tìm ngày mất: FIND_DIED_AT
- Tìm nơi làm việc: FIND_WORKED_IN
- Tìm thời kỳ hoạt động: FIND_ACTIVE_IN
- Tìm thành tựu: FIND_ACHIEVEMENTS
- Tìm người ảnh hưởng: FIND_INFLUENCERS
- Tìm sự kiện tham gia: FIND_EVENTS
- Tìm triều đại: FIND_DYNASTY
- Tìm tên gọi khác: FIND_NAME
- Câu hỏi chung: GENERAL_QUERY

JSON format:
{{
  "intent": "FIND_PERSON_PROFILE|FIND_FATHER|FIND_MOTHER|FIND_PARENTS|FIND_SPOUSE|FIND_SIBLINGS|FIND_CHILDREN|FIND_BORN_IN|FIND_BORN_AT|FIND_DIED_AT|FIND_WORKED_IN|FIND_ACTIVE_IN|FIND_ACHIEVEMENTS|FIND_INFLUENCERS|FIND_EVENTS|FIND_DYNASTY|FIND_NAME|GENERAL_QUERY",
  "person": "<tên person nếu có>",
  "relationship_type": "FATHER_OF|MOTHER_OF|CHILD_OF|SPOUSE_OF|SIBLING_OF|MENTOR_OF|STUDENT_OF|ALLY_OF|ENEMY_OF|FRIEND_OF|SUCCESSOR_OF|BORN_IN|BORN_AT|DIED_AT|WORKED_IN|ACTIVE_IN|ACHIEVED|INFLUENCED_BY|PARTICIPATED_IN|HAS_ROLE|BELONGS_TO_DYNASTY|HAS_NAME",
  "dynasty": "<tên triều đại nếu có>"
}}
"""

ANSWER_PROMPT = """
Bạn là trợ lý AI.
Chỉ sử dụng đúng thông tin trong CONTEXT dưới đây để trả lời.
Bắt buộc trả lời bằng TIẾNG VIỆT.

Context:
{context}

Question:
{question}

Nếu context KHÔNG chứa đủ thông tin để trả lời chính xác, hãy trả về đúng câu:
"Hiện tại mình chưa thể trả lời câu hỏi này !!"
"""

GRAPH_QUERY_PROMPT = """
Từ câu hỏi của người dùng, trích xuất các thực thể và mối quan hệ để truy vấn knowledge graph.

Câu hỏi: {question}

Trích xuất:
1. Loại thực thể (Person, Company, Country, Field, Era, Achievement, WikiChunk)
2. Tên các thực thể
3. Loại quan hệ (BORN_IN, WORKED_IN, ACTIVE_IN, ACHIEVED, INFLUENCED_BY, DESCRIBED_IN, FOUNDED, WORKS_AT)
4. Intent của câu hỏi

Trả về JSON:
{{
  "entities": [
    {{"type": "Person|Company|Country|Field|Era|Achievement|WikiChunk", "name": "..."}}
  ],
  "relationships": ["BORN_IN", "WORKED_IN", "ACTIVE_IN", "ACHIEVED", "INFLUENCED_BY", "DESCRIBED_IN", "FOUNDED"],
  "intent": "FIND_PERSON_PROFILE|FIND_BORN_IN|FIND_WORKED_IN|FIND_ACHIEVEMENTS|FIND_INFLUENCERS|FIND_FOUNDER|FIND_COMPANY|GENERAL_QUERY"
}}
"""

ENTITY_EXTRACTION_PROMPT = """
Extract entities from the following text.

Text: {text}

Return JSON array of entities:
[
  {{"type": "Person", "name": "...", "confidence": 0.9}},
  {{"type": "Company", "name": "...", "confidence": 0.8}}
]
"""

CONTEXT_SYNTHESIS_PROMPT = """
Bạn là trợ lý AI.
Từ graph context đã truy xuất, hãy tổng hợp câu trả lời rõ ràng và ngắn gọn.
Bắt buộc trả lời bằng TIẾNG VIỆT.

Graph Context:
{graph_context}

Question: {question}

Chỉ trả lời dựa trên context phía trên.
"""

CYPHER_DETECTION_PROMPT = """
Bạn là chuyên gia về Neo4j và Cypher queries. Phân tích câu hỏi tiếng Việt và quyết định xem có cần dùng Cypher query để trả lời hay không.

Câu hỏi: {question}

Graph Schema:
- Nodes: Person (properties: name, reign_start_year, reign_end_year, reign_duration_years, reign_duration_days), Dynasty (properties: name, summary), Event, etc.
- Relationships: BELONGS_TO_DYNASTY, FATHER_OF, MOTHER_OF, CHILD_OF, SPOUSE_OF, etc.

QUAN TRỌNG: Chỉ trả về JSON hợp lệ, không có text khác.

Nếu câu hỏi là về:
- So sánh/đếm/aggregation (min, max, count, average) trên properties của nodes
- Tìm người có giá trị cao nhất/thấp nhất (ví dụ: trị vì lâu nhất, ngắn nhất)
- Đếm số lượng (ví dụ: bao nhiêu vua trong triều đại)
- Thống kê (ví dụ: trung bình thời gian trị vì)

Thì trả về {{"needs_cypher": true, "cypher_query": "MATCH ... RETURN ...", "explanation": "giải thích ngắn gọn"}}

Nếu câu hỏi là về tìm kiếm thông tin cụ thể, quan hệ, hoặc không cần aggregation, trả về {{"needs_cypher": false, "cypher_query": "", "explanation": "không cần Cypher"}}

Ví dụ:
Câu hỏi: "vua nào trị vì ngắn nhất trong triều Nguyễn"
Trả về: {{"needs_cypher": true, "cypher_query": "MATCH (p:Person)-[:BELONGS_TO_DYNASTY]->(d:Dynasty) WHERE toLower(d.name) CONTAINS 'nguyễn' RETURN p.name ORDER BY p.reign_duration_years ASC LIMIT 1", "explanation": "tìm vua có thời gian trị vì ngắn nhất"}}
"""


