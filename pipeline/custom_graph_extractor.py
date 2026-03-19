"""Custom graph extractor - 1 LLM call cho cả node + relationship (CÁCH B - Linh hoạt)."""

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

from graph.builder import GraphBuilder
from graph.storage import GraphDB
from llm.llm_client import call_llm

load_dotenv()


# ============================================================================
# PROMPT SIÊU TOÀN DIỆN - 1 LLM CALL = NODE + RELATIONSHIP
# ============================================================================

EXTRACTION_PROMPT = """Bạn là chuyên gia Knowledge Graph. Phân tích đoạn văn và trích xuất ĐẦY ĐỦ nodes + relationships.

QUY TẮC VÀNG:
1. KHÔNG có node "mồ côi" - MỌI node phải có ÍT NHẤT 1 relationship
2. Nếu thấy thông tin về ai đó → tạo node + kết nối ngay
3. Tất cả nodes phải liên quan đến nhau, không tạo node "treo lơ lửng"

==============================================================
PHÂN LOẠI NODE VÀ RELATIONSHIP TỰ ĐỘNG
==============================================================

**LOẠI 1: NGƯỜI (Person)**
├── Tên chính + Các tên khác (bí danh, tên lúc sinh, tước vị)
│   └── HAS_NAME → Name (birth_name, reign_name, title, alias, nickname)
├── Quan hệ gia đình:
│   └── PARENT_OF, CHILD_OF, SPOUSE_OF, SIBLING_OF
├── Quan hệ thầy-trò:
│   └── MENTOR_OF, STUDENT_OF, TAUGHT_BY
├── Quan hệ chính trị/quân sự:
│   └── SUCCEEDED, PREDECESSOR_OF, ADVISOR_TO, ALLY_OF, ENEMY_OF
├── Vai trò:
│   └── SERVED_AS → Role (vua, thủ tướng, tướng lĩnh...)
└── Nơi sinh/nơi mất:
    └── BORN_IN, DIED_AT → Location

**LOẠI 2: SỰ KIỆN (Event)**
├── Sự kiện chính trị (đăng quang, thoái vị, cải cách...)
│   └── Người thực hiện → PERFORMED
├── Sự kiện quân sự (chiến tranh, trận đánh, chiến thắng...)
│   └── Người tham gia → PARTICIPATED_IN, COMMANDED, DEFEATED
├── Sự kiện ngoại giao (ký kết, hiệp ước...)
│   └── Người ký → SIGNED
├── Sự kiện cá nhân (sinh, mất, kết hôn...)
│   └── Người liên quan → OCCURRED_AT, STARTED, ENDED
└── Địa điểm sự kiện:
    └── LOCATED_AT → Location

**LOẠI 3: THỜI KỲ/ TRIỀU ĐẠI (Era/Dynasty)**
├── Triều đại
│   └── Người trị vì → RULED_DURING
├── Thời kỳ lịch sử
│   └── Người hoạt động → ACTIVE_DURING
└── Năm/thập niên
    └── ACTIVE_IN, REIGNED_IN

**LOẠI 4: TỔ CHỨC/ĐOÀN THỂ**
├── Thành lập
│   └── Người sáng lập → FOUNDED
├── Tham gia/làm việc
│   └── Người → MEMBER_OF, EMPLOYED_AT, LED_BY
└── Vai trò trong tổ chức
    └── POSITION_HELD → Organization

**LOẠI 5: ĐỊA ĐIỂM (Location)**
├── Quê quán
│   └── Người → FROM_PLACE, BORN_IN
├── Nơi mất
│   └── Người → DIED_AT
├── Nơi cư trú/học tập
│   └── Người → RESIDED_IN, STUDIED_AT
└── Địa danh trong sự kiện
    └── Sự kiện → LOCATED_AT

**LOẠI 6: THÀNH TỰU/GIẢI THƯỞNG (Achievement)**
├── Thành tựu chính
│   └── Người đạt được → ACHIEVED
├── Giải thưởng
│   └── Người nhận → RECEIVED_AWARD
└── Công trình sáng tạo
    └── Người tạo → CREATED

**LOẠI 7: TÁC PHẨM/VĂN HÓA (Work)**
├── Sách, bài viết
│   └── Tác giả → AUTHORED
├── Nghệ thuật
│   └── Nghệ sĩ → CREATED
└── Phát minh
    └── Người phát minh → INVENTED

**LOẠI 8: KHÁI NIỆM/LĨNH VỰC (Field)**
├── Lĩnh vực hoạt động
│   └── Người → EXPERT_IN, WORKED_IN
└── Trường phái
    └── Người → BELONGED_TO

==============================================================
VÍ DỤ MINH HỌA (QUAN TRỌNG!)
==============================================================

Input: "Bảo Đại, tên thật Nguyễn Phúc Vĩnh San, sinh năm 1913 tại Huế, là vua cuối cùng của Việt Nam. Ông đăng quang năm 1926 tại Đại Nội Huế. Năm 1945, ông thoái vị. Vợ ông là Nam Phương hoàng hậu."

Output ĐÚNG:
```json
{{
  "nodes": [
    {{"id": "p1", "type": "Person", "name": "Bảo Đại", "properties": {{"title": "Vua cuối cùng Việt Nam"}}}},
    {{"id": "n1", "type": "Name", "name": "Nguyễn Phúc Vĩnh San", "properties": {{"name_type": "birth_name"}}}},
    {{"id": "l1", "type": "Location", "name": "Huế", "properties": {{"description": "Thành phố Huế"}}}},
    {{"id": "l2", "type": "Location", "name": "Đại Nội Huế", "properties": {{"description": "Hoàng cung Huế"}}}},
    {{"id": "e1", "type": "Event", "name": "Đăng quang năm 1926", "properties": {{"year": 1926}}}},
    {{"id": "e2", "type": "Event", "name": "Thoái vị năm 1945", "properties": {{"year": 1945}}}},
    {{"id": "p2", "type": "Person", "name": "Nam Phương hoàng hậu", "properties": {{"title": "Vợ vua Bảo Đại"}}}}
  ],
  "relationships": [
    {{"from": "p1", "type": "HAS_NAME", "to": "n1", "properties": {{"name_type": "birth_name"}}}},
    {{"from": "p1", "type": "BORN_IN", "to": "l1", "properties": {{"year": 1913}}}},
    {{"from": "e1", "type": "LOCATED_AT", "to": "l2"}},
    {{"from": "p1", "type": "PERFORMED", "to": "e1"}},
    {{"from": "p1", "type": "PERFORMED", "to": "e2"}},
    {{"from": "p1", "type": "SPOUSE_OF", "to": "p2"}}
  ]
}}
```

Input: "Trần Hưng Đạo là con trai Trần Thánh Đạo, nổi tiếng với chiến thắng Bạch Đằng 1288 chống quân Nguyên. Ông được phong làm Đại Hành Hiếu Hoàng Đế."

Output ĐÚNG:
```json
{{
  "nodes": [
    {{"id": "p1", "type": "Person", "name": "Trần Hưng Đạo", "properties": {{"title": "Đại Hành Hiếu Hoàng Đế"}}}},
    {{"id": "p2", "type": "Person", "name": "Trần Thánh Đạo", "properties": {{"relation": "Cha của Trần Hưng Đạo"}}}},
    {{"id": "e1", "type": "Event", "name": "Chiến thắng Bạch Đằng 1288", "properties": {{"year": 1288, "description": "Chống quân Nguyên"}}}},
    {{"id": "l1", "type": "Location", "name": "Sông Bạch Đằng", "properties": {{"description": "Địa điểm trận đánh"}}}}
  ],
  "relationships": [
    {{"from": "p1", "type": "CHILD_OF", "to": "p2"}},
    {{"from": "p1", "type": "PARTICIPATED_IN", "to": "e1"}},
    {{"from": "p1", "type": "COMMANDED", "to": "e1"}},
    {{"from": "e1", "type": "LOCATED_AT", "to": "l1"}},
    {{"from": "p1", "type": "RECEIVED_TITLE", "to": "e1", "properties": {{"title": "Đại Hành Hiếu Hoàng Đế"}}}}
  ]
}}
```

==============================================================
THỰC HÀNH
==============================================================

Đoạn văn cần phân tích:
{{text}}

YÊU CẦU QUAN TRỌNG:
- MỖI node phải có ÍT NHẤT 1 relationship đến node khác
- Nếu node "tên" (Name) → PHẢI có relationship HAS_NAME đến Person
- Nếu node "sự kiện" → PHẢI có relationship đến người tham gia/thực hiện
- Nếu node "địa điểm" → PHẢI có relationship đến người hoặc sự kiện
- KHÔNG tạo node "treo lơ lửng" không kết nối gì

Output JSON:
{{
    "nodes": [...],
    "relationships": [...]
}}

CHỈ TRẢ VỀ JSON, KHÔNG CÓ TEXT KHÁC.
"""


class CustomGraphExtractor:
    """Extract nodes + relationships trong 1 LLM call DUY NHẤT."""

    def __init__(self, graph_db: Optional[GraphDB] = None, model: Optional[str] = None):
        self.graph_db = graph_db or GraphDB()
        self.builder = GraphBuilder(graph_db=self.graph_db)
        self.model = model or os.getenv("YESCALE_MODEL", "gemini-2.0-flash")
        
        api_key = os.getenv("YESCALE_API_KEY")
        if not api_key:
            raise RuntimeError("YESCALE_API_KEY chưa được cấu hình trong env.")

    def extract_from_text(
        self,
        text: str,
        source_chunk_id: Optional[str] = None,
        target_person: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Extract nodes và relationships TRONG 1 LLM CALL.
        
        Returns:
            dict với "nodes" và "relationships" - đảm bảo mọi node đều có relationship!
        """
        # Build prompt
        additional_filter = ""
        if target_person:
            additional_filter = f"\n\n⚠️ LƯU Ý: Ưu tiên thông tin về '{target_person}'. Nếu có người khác, chỉ trích xuất nếu họ có quan hệ TRỰC TIẾP với '{target_person}'."

        prompt = EXTRACTION_PROMPT.replace("{{text}}", text) + additional_filter

        try:
            print(f"[DEBUG] Calling LLM once for extraction...")
            response = call_llm(prompt, model=self.model, temperature=0.2)
            
            # Parse JSON
            data = json.loads(response)
            
        except json.JSONDecodeError:
            # Fallback: try to extract JSON from response
            try:
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group())
                else:
                    print(f"⚠️ Failed to parse LLM response as JSON")
                    print(f"Response (first 300 chars): {response[:300]}")
                    return {"nodes": [], "relationships": []}
            except Exception as e:
                print(f"⚠️ Error parsing LLM response: {e}")
                return {"nodes": [], "relationships": []}

        # Validate: ensure no orphan nodes
        data = self._validate_and_fix_relationships(data)

        # Debug output
        print(f"[DEBUG] Extracted: {len(data.get('nodes', []))} nodes, {len(data.get('relationships', []))} relationships")
        
        return data

    def _validate_and_fix_relationships(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate và fix orphan nodes - đảm bảo mọi node đều có relationship.
        """
        nodes = data.get("nodes", [])
        relationships = data.get("relationships", [])
        
        # Build set of connected node IDs
        connected_ids = set()
        for rel in relationships:
            if rel.get("from"):
                connected_ids.add(rel["from"])
            if rel.get("to"):
                connected_ids.add(rel["to"])
        
        # Find orphan nodes
        orphan_nodes = []
        for node in nodes:
            node_id = node.get("id")
            if node_id and node_id not in connected_ids:
                orphan_nodes.append(node)
        
        if orphan_nodes:
            print(f"[DEBUG] Found {len(orphan_nodes)} orphan nodes, trying to fix...")
            # Try to auto-link orphans based on name similarity or type
            for orphan in orphan_nodes:
                fixed = self._fix_orphan_node(orphan, nodes, relationships)
                if fixed:
                    print(f"[DEBUG] Fixed orphan: {orphan.get('name', orphan.get('id'))}")
        
        return data

    def _fix_orphan_node(self, orphan: Dict, all_nodes: List[Dict], relationships: List[Dict]) -> bool:
        """
        Thử fix một orphan node bằng cách tạo relationship thông minh.
        """
        orphan_id = orphan.get("id")
        orphan_type = orphan.get("type")
        orphan_name = orphan.get("name", "")
        
        # Strategy 1: Name nodes → link to Person with similar name context
        if orphan_type == "Name":
            # Find a Person node that might own this name
            for node in all_nodes:
                if node.get("type") == "Person":
                    # Check if Person name is similar to Name node context
                    person_name = node.get("name", "")
                    if any(word in orphan_name for word in person_name.split() if len(word) > 3):
                        relationships.append({
                            "from": node.get("id"),
                            "type": "HAS_NAME",
                            "to": orphan_id,
                            "properties": orphan.get("properties", {})
                        })
                        return True
        
        # Strategy 2: Event nodes → try to link to any Person mentioned
        if orphan_type == "Event":
            for node in all_nodes:
                if node.get("type") == "Person":
                    person_name = node.get("name", "")
                    if person_name and person_name in orphan_name:
                        relationships.append({
                            "from": node.get("id"),
                            "type": "PERFORMED",
                            "to": orphan_id,
                            "properties": {}
                        })
                        return True
        
        # Strategy 3: Location nodes → try to link to Person or Event
        if orphan_type == "Location":
            for node in all_nodes:
                if node.get("type") in ["Person", "Event"]:
                    node_name = node.get("name", "")
                    if node_name and node_name in orphan_name:
                        rel_type = "BORN_IN" if node.get("type") == "Person" else "LOCATED_AT"
                        relationships.append({
                            "from": node.get("id"),
                            "type": rel_type,
                            "to": orphan_id,
                            "properties": {}
                        })
                        return True
        
        return False

    def build_from_extraction(self, extracted_data: Dict[str, Any]) -> Tuple[int, int]:
        """
        Build graph từ extracted data (flexible format).
        
        Returns:
            (nodes_created, relationships_created)
        """
        nodes = []
        rels = []
        node_lookup = {}

        # Process nodes
        for node in extracted_data.get("nodes", []):
            node_id = node.get("id")
            node_type = node.get("type", "Unknown")
            node_name = node.get("name", "")
            node_props = node.get("properties", {})

            if node_id:
                node_lookup[node_id] = node

            # Determine identifier based on type
            if node_type == "Name":
                identifier = {"value": node_name}
            else:
                identifier = {"name": node_name}

            nodes.append({
                "type": node_type,
                "identifier": identifier,
                "properties": node_props
            })

        # Process relationships
        for rel in extracted_data.get("relationships", []):
            from_id = rel.get("from")
            to_id = rel.get("to")
            rel_type = rel.get("type", "RELATED_TO")

            from_node = node_lookup.get(from_id, {})
            to_node = node_lookup.get(to_id, {})

            from_type = from_node.get("type", "Unknown")
            to_type = to_node.get("type", "Unknown")
            from_name = from_node.get("name", from_id)
            to_name = to_node.get("name", to_id)

            # Determine identifiers based on types
            if from_type == "Name":
                from_id_dict = {"value": from_name}
            else:
                from_id_dict = {"name": from_name}

            if to_type == "Name":
                to_id_dict = {"value": to_name}
            else:
                to_id_dict = {"name": to_name}

            rels.append({
                "from_type": from_type,
                "from_id": from_id_dict,
                "rel_type": rel_type,
                "to_type": to_type,
                "to_id": to_id_dict,
                "properties": rel.get("properties", {}),
            })

        # Legacy support for old format (persons, achievements, events, etc.)
        for person in extracted_data.get("persons", []):
            person_name = person.get("name")
            if not person_name:
                continue

            nodes.append({
                "type": "Person",
                "identifier": {"name": person_name},
                "properties": {
                    "role": person.get("role"),
                    "birth_year": person.get("birth_year"),
                    "death_year": person.get("death_year"),
                }
            })

            for name_entry in person.get("names", []):
                name_value = name_entry.get("value")
                name_type = name_entry.get("type", "alias")
                if name_value:
                    nodes.append({
                        "type": "Name",
                        "identifier": {"value": name_value},
                        "properties": {"name_type": name_type}
                    })
                    rels.append({
                        "from_type": "Person",
                        "from_id": {"name": person_name},
                        "rel_type": "HAS_NAME",
                        "to_type": "Name",
                        "to_id": {"value": name_value},
                        "properties": {"name_type": name_type},
                    })

        for achievement in extracted_data.get("achievements", []):
            nodes.append({
                "type": "Achievement",
                "identifier": {"name": achievement.get("name")},
                "properties": {"year": achievement.get("year"), "description": achievement.get("description")}
            })

        for event in extracted_data.get("events", []):
            nodes.append({
                "type": "Event",
                "identifier": {"name": event.get("name")},
                "properties": {"year": event.get("year"), "description": event.get("description")}
            })

        for era in extracted_data.get("eras", []):
            nodes.append({
                "type": "Era",
                "identifier": {"name": era.get("name")},
                "properties": {"start_year": era.get("start_year"), "end_year": era.get("end_year")}
            })

        for field in extracted_data.get("fields", []):
            nodes.append({
                "type": "Field",
                "identifier": {"name": field.get("name")},
                "properties": {"category": field.get("category")}
            })

        # Build to Neo4j
        if nodes or rels:
            result = self.builder.batch_create_nodes(nodes)
            if isinstance(result, dict):
                nodes_created = result.get("nodes_created", 0)
            else:
                nodes_created = result if result else len(nodes)
            
            relationships_created = 0
            for rel in rels:
                try:
                    self.builder.create_relationship(
                        rel["from_type"],
                        rel["from_id"],
                        rel["rel_type"],
                        rel["to_type"],
                        rel["to_id"],
                        rel_properties=rel.get("properties", {})
                    )
                    relationships_created += 1
                except Exception as e:
                    pass  # Relationship might already exist

        else:
            nodes_created = 0
            relationships_created = 0

        return nodes_created, relationships_created

    def enrich_text(
        self,
        text: str,
        source_chunk_id: Optional[str] = None,
        link_to_person: Optional[str] = None,
    ) -> Tuple[int, int]:
        """
        Enrich text: extract và build graph trong 1 LLM call.
        
        Args:
            text: Text to extract from
            source_chunk_id: Source chunk identifier  
            link_to_person: Person name to focus extraction on
        
        Returns:
            (nodes_created, relationships_created)
        """
        # Single LLM call for both extraction and relationship
        extracted = self.extract_from_text(text, source_chunk_id, target_person=link_to_person)
        nodes_created, rels_created = self.build_from_extraction(extracted)
        
        return nodes_created, rels_created

    def enrich_from_wikichunks(self, limit: int = 100) -> Dict[str, int]:
        """Enrich from WikiChunk nodes in Neo4j."""
        with self.graph_db.driver.session(database=self.graph_db.database) as session:
            result = session.run(
                """
                MATCH (w:WikiChunk)
                WHERE w.content IS NOT NULL
                RETURN coalesce(w.chunk_id, toString(w.id)) AS cid, w.content AS content
                LIMIT $limit
                """,
                limit=limit,
            )
            chunks = [(r["cid"], r["content"]) for r in result]

        total_nodes = 0
        total_rels = 0
        for cid, content in chunks:
            try:
                n, r = self.enrich_text(content, source_chunk_id=cid)
                total_nodes += n
                total_rels += r
                print(f"  Chunk {cid}: {n} nodes, {r} rels")
            except Exception as e:
                print(f"  Error chunk {cid}: {e}")

        return {"nodes_created": total_nodes, "relationships_created": total_rels}
