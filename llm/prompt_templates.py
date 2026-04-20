# llm/prompt_templates.py
"""Prompt templates for Graph RAG tasks."""

# ===== RELATIONSHIP TRANSLATION MAPPING (Để LLM dùng khi dịch) =====
RELATIONSHIP_TRANSLATIONS = {
    # Family relationships - biological/natural
    "CHILD_OF": "con của",
    "FATHER_OF": "cha của",
    "MOTHER_OF": "mẹ của",
    "PARENT_OF": "cha/mẹ của",
    "SPOUSE_OF": "vợ/chồng của",
    "SIBLING_OF": "anh chị em của",
    # Family relationships - adopted
    "ADOPTED_CHILD_OF": "con nuôi của",
    "ADOPTIVE_PARENT_OF": "cha/mẹ nuôi của",
    # Family relationships - foster/step
    "FOSTER_CHILD_OF": "con dâu/con rể nuôi của",
    "FOSTER_PARENT_OF": "cha/mẹ dượng/kế của",
    
    # Leadership & Activities
    "LED": "lãnh đạo",
    "PARTICIPATED_IN": "tham gia",
    "FOUNDED": "sáng lập",
    "WORKS_AT": "làm việc tại",
    "WORKS_IN": "làm việc trong",
    "WORKED_IN": "làm việc ở",
    
    # Temporal & Location
    "BORN_IN": "sinh tại",
    "BORN_AT": "sinh năm",
    "DIED_AT": "mất năm", 
    "ACTIVE_IN": "hoạt động trong, thời kỳ",
    
    # Others
    "MENTOR_OF": "là thầy của",
    "STUDENT_OF": "là học trò của",
    "ALLY_OF": "là đồng minh của",
    "ENEMY_OF": "là kẻ thù của",
    "FRIEND_OF": "là bạn của",
    "SUCCESSOR_OF": "là người kế nhiệm của",
    "PREDECESSOR_OF": "là người tiền nhiệm của",
    "ACHIEVED": "đạt được, hoàn thành",
    "INFLUENCED_BY": "bị ảnh hưởng bởi",
    "BELONGS_TO_DYNASTY": "thuộc triều đại",
    "HAS_ROLE": "có vai trò",
    "CARED_BY": "được nuôi dạy/chăm sóc bởi",
}

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
- Quan hệ gia đình (tự nhiên): FATHER_OF, MOTHER_OF, CHILD_OF, SPOUSE_OF, SIBLING_OF
- Quan hệ gia đình (con nuôi): ADOPTED_CHILD_OF, ADOPTED_PARENT_OF
- Quan hệ gia đình (dâu/rể/kế): FOSTER_CHILD_OF, FOSTER_PARENT_OF
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
- Tìm người kế nhiệm: FIND_SUCCESSOR
- Tìm người tiền nhiệm: FIND_PREDECESSOR
- Câu hỏi chung: GENERAL_QUERY

JSON format:
{{
  "intent": "FIND_PERSON_PROFILE|FIND_FATHER|FIND_MOTHER|FIND_PARENTS|FIND_SPOUSE|FIND_SIBLINGS|FIND_CHILDREN|FIND_BORN_IN|FIND_BORN_AT|FIND_DIED_AT|FIND_WORKED_IN|FIND_ACTIVE_IN|FIND_ACHIEVEMENTS|FIND_INFLUENCERS|FIND_EVENTS|FIND_DYNASTY|FIND_NAME|FIND_SUCCESSOR|FIND_PREDECESSOR|GENERAL_QUERY",
  "person": "<tên person nếu có>",
  "relationship_type": "FATHER_OF|MOTHER_OF|CHILD_OF|SPOUSE_OF|SIBLING_OF|ADOPTED_CHILD_OF|ADOPTIVE_PARENT_OF|FOSTER_CHILD_OF|FOSTER_PARENT_OF|MENTOR_OF|STUDENT_OF|ALLY_OF|ENEMY_OF|FRIEND_OF|SUCCESSOR_OF|PREDECESSOR_OF|BORN_IN|BORN_AT|DIED_AT|WORKED_IN|ACTIVE_IN|ACHIEVED|INFLUENCED_BY|PARTICIPATED_IN|HAS_ROLE|BELONGS_TO_DYNASTY|HAS_NAME",
  "dynasty": "<tên triều đại nếu có>"
}}
"""

ANSWER_PROMPT = """
=== HƯỚNG DẪN TRẢ LỜI BẰNG TIẾNG VIỆT 100% ===

Bạn là trợ lý AI thông minh.
TUYỆT ĐỐI TRẢ LỜI BẰNG TIẾNG VIỆT CHỈ.

📋 Context từ Knowledge Graph:
{context}

❓ Câu hỏi: {question}

🔴 QUY TẮC BẮT BUỘC (KHÔNG exceptions):

1️⃣ BẮTBUỘC - TRẢ LỜI BẰNG TIẾNG VIỆT 100%
   ✅ Tất cả từ, cụm, giải thích phải tiếng Việt
   ❌ BAN CẬM: "LED", "PARTICIPATED_IN", "CHILD_OF", "FATHER_OF", "properties", "node", "relationship"
   ❌ BAN CẬM: "was", "is", "the", "of", "and" (tiếng Anh)

2️⃣ CHỈ DỰA INFO trong Context
   ✅ Context có → trả lời từ context
   ❌ Context không có → "Hiện tại mình chưa tìm thấy thông tin này trong dữ liệu."
   ✅ TUÂN THỦ 100% - không bịa, không tìm thêm, không gợi ý

3️⃣ DỊCH relationships thành tiếng Việt tự nhiên:
   Ví dụ các relationship cần dịch:
   • LED, PARTICIPATED_IN → "lãnh đạo", "tham gia", "nắm giữ"
   • CHILD_OF → "con của"
   • FATHER_OF, MOTHER_OF → "cha của", "mẹ của"
   • SPOUSE_OF → "vợ/chồng của"
   • FOUNDED → "sáng lập", "thành lập"
   • WORKS_AT → "làm việc tại"

4️⃣ VÍ DỤ CỤ THỂ:
   ❌ SAI: "Bảo Đại LED Quốc gia Việt Nam"
   ✅ ĐÚNG: "Bảo Đại lãnh đạo Quốc gia Việt Nam"
   
   ❌ SAI: "He PARTICIPATED_IN creating Việt Nam"
   ✅ ĐÚNG: "Ông tham gia thành lập Quốc gia Việt Nam"

📝 Trả lời: (hoàn toàn tiếng Việt, rõ ràng, tự nhiên)
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
=== TỔNG HỢP CONTEXT → TRẢ LỜI TIẾNG VIỆT 100% ===

Bạn là trợ lý AI chuyên tổng hợp thông tin từ Knowledge Graph.
🔴 TUYỆT ĐỐI - TRẢ LỜI BẰNG TIẾNG VIỆT CHỈ, KHÔNG TIẾNG ANH

📊 Dữ liệu từ Graph (cần tổng hợp):
{graph_context}

❓ Câu hỏi của người dùng: {question}

=== CÁC RULE CẶT - KHÔNG EXCEPTIONS ===

1️⃣ TRẢ LỜI TOÀN TIẾNG VIỆT
   ❌ BAN CẬM: "LED", "PARTICIPATED_IN", "BORN_IN", "CHILD_OF", "properties", "node"
   ❌ BAN CẬM: từ tiếng Anh

2️⃣ CHỈ DÙNG THÔNG TIN TRONG CONTEXT
   ✅ Context có → tổng hợp thành câu trả lời
   ❌ Context không có → "Hiện tại mình chưa tìm thấy thông tin này."

3️⃣ DỊCH RELATIONSHIPS thành tiếng Việt tự nhiên:
   • LED, PARTICIPATED_IN → "lãnh đạo", "tham gia"
   • CHILD_OF → "con của"
   • FOUNDED → "sáng lập"
   • WORKS_AT/WORKS_IN → "làm việc tại"
   • BORN_IN/BORN_AT → "sinh tại", "sinh năm"

📝 Trả lời tổng hợp (100% tiếng Việt, rõ ràng, tự nhiên):
"""

QUERY_EXPANSION_PROMPT = """
Bạn là một chuyên gia xử lý ngôn ngữ tự nhiên (NLP) hỗ trợ cho hệ thống tìm kiếm GraphRAG.
Nhiệm vụ của bạn là phân tích câu hỏi của người dùng và trích xuất thông tin để tối ưu hóa việc truy vấn cơ sở dữ liệu.

Hãy trả về ĐÚNG MỘT đối tượng JSON bao gồm 2 mảng:
1. "entities": Chứa các danh từ riêng, tên người, địa danh, hoặc chủ thể chính (Ví dụ: "Nam Cao", "Lê Lợi").
2. "expanded_keywords": Chứa các từ khóa trong câu hỏi CỘNG VỚI các từ đồng nghĩa, từ liên quan chặt chẽ đến hành động/tính chất đó để mở rộng phạm vi tìm kiếm (Ví dụ: "chiến thắng" -> "đánh bại", "đánh thắng", "khởi nghĩa"; "nổi tiếng" -> "tiêu biểu", "đặc sắc", "chính").

{{
  "entities": ["..."],
  "expanded_keywords": ["..."]
}}
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

