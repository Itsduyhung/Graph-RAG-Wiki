# llm/prompt_templates.py
"""Prompt templates for Graph RAG tasks."""

INTENT_PROMPT = """
Bạn là AI Agent trích xuất intent có cấu trúc từ câu hỏi tiếng Việt.
Trả về DUY NHẤT JSON hợp lệ, không giải thích thêm.

Câu hỏi:
"{question}"

Graph Schema (tóm tắt):
Node Types:
- Person
- Company
- Country
- Field
- Era
- Dynasty
- Role
- Event
- TimePoint
- Achievement
- WikiChunk

Relationships (một phần):
- (Person)-[:BORN_IN]->(Country)
- (Person)-[:BORN_AT]->(TimePoint)
- (Person)-[:DIED_AT]->(TimePoint)
- (Person)-[:WORKED_IN]->(Field)
- (Person)-[:ACTIVE_IN]->(Era)
- (Person)-[:ACHIEVED]->(Achievement)
- (Person)-[:INFLUENCED_BY]->(Person)
- (Person)-[:CHILD_OF]->(Person)
- (Person)-[:PARTICIPATED_IN]->(Event)
- (Event)-[:HAPPENED_AT]->(TimePoint)
- (Person)-[:HAS_ROLE]->(Role)
- (Person)-[:BELONGS_TO_DYNASTY]->(Dynasty)

Intent Types:
- FIND_PERSON_PROFILE
- FIND_BORN_IN
- FIND_BORN_AT
- FIND_DIED_AT
- FIND_WORKED_IN
- FIND_ACTIVE_IN
- FIND_ACHIEVEMENTS
- FIND_INFLUENCERS
- FIND_PARENTS
- FIND_EVENTS
- GENERAL_QUERY

JSON format:
{{
  "intent": "FIND_PERSON_PROFILE|FIND_BORN_IN|FIND_BORN_AT|FIND_DIED_AT|FIND_WORKED_IN|FIND_ACTIVE_IN|FIND_ACHIEVEMENTS|FIND_INFLUENCERS|FIND_PARENTS|FIND_EVENTS|GENERAL_QUERY",
  "person": "<tên person nếu có>",
  "dynasty": "<tên triều đại nếu có>",
  "relationship_type": "BORN_IN|BORN_AT|DIED_AT|WORKED_IN|ACTIVE_IN|ACHIEVED|INFLUENCED_BY|CHILD_OF|PARTICIPATED_IN|HAS_ROLE|BELONGS_TO_DYNASTY"
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
Based on the user question, extract entities and relationships to query the knowledge graph.

User question: {question}

Extract:
1. Entity types (Person, Company, Country, Field, Era, Achievement, WikiChunk)
2. Entity names
3. Relationship types (BORN_IN, WORKED_IN, ACTIVE_IN, ACHIEVED, INFLUENCED_BY, DESCRIBED_IN, FOUNDED, WORKS_AT)
4. Query intent

Return JSON:
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


