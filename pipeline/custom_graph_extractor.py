"""Custom graph extractor dùng YEScale API để sinh node: Achievement, Era, Field."""

import json
import os
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

from graph.builder import GraphBuilder
from graph.storage import GraphDB
from llm.llm_client import call_llm

load_dotenv()


EXTRACTION_PROMPT = """Phân tích đoạn văn bản sau và trích xuất thông tin có cấu trúc về lịch sử, thành tựu, sự kiện và khái niệm. 
LƯU Ý: TẤT CẢ DỮ LIỆU PHẢI CÓ TÊN TIẾNG VIỆT, KHÔNG ĐƯỢC DỪA TIẾNG ANH.

Phân biệt rõ giữa:
- ACHIEVEMENT (Thành tựu): Những công trình, cải cách, thành quả có ý nghĩa lãnh liều bởi một người
- EVENT (Sự kiện): Những giai đoạn, cuộc chiến, phong trào có tham gia của nhiều người

Với các mối quan hệ giữa Person, cần cụ thể loại quan hệ:
- FATHER_OF / MOTHER_OF (cha/mẹ của)
- CHILD_OF (con của)
- SPOUSE_OF / MARRIED_TO (vợ/chồng của)
- SIBLING_OF (anh em ruột của)
- MENTOR_OF / STUDENT_OF (sư phụ/học trò)
- ALLY_OF (đồng minh)
- ENEMY_OF (kẻ thù)
- FRIEND_OF (bạn)
- SUCCESSOR_OF (kế thừa)

Trả về JSON object với cấu trúc CHÍNH XÁC này:
{{
    "persons": [{{"name": "...", "role": "...", "birth_year": null, "death_year": null}}],
    "achievements": [{{"name": "...", "year": null, "description": "...", "person_name": "..."}}],
    "events": [{{"name": "...", "year": null, "description": "...", "event_type": "sự kiện|cuộc chiến|phong trào|giai đoạn"}}],
    "eras": [{{"name": "...", "start_year": null, "end_year": null, "description": "..."}}],
    "fields": [{{"name": "...", "category": "...", "description": "..."}}],
    "person_relationships": [
        {{"from_name": "...", "rel_type": "FATHER_OF|MOTHER_OF|CHILD_OF|SPOUSE_OF|SIBLING_OF|MENTOR_OF|STUDENT_OF|ALLY_OF|ENEMY_OF|FRIEND_OF|SUCCESSOR_OF", "to_name": "..."}}
    ],
    "relationships": [
        {{"from_name": "...", "from_type": "Person|Achievement|Event|Era|Field", "rel_type": "ACHIEVED|PARTICIPATED_IN|ACTIVE_IN|BELONGS_TO_DYNASTY|HAS_ROLE", "to_name": "...", "to_type": "Person|Achievement|Event|Era|Field"}}
    ]
}}

Đoạn văn bản:
{{text}}

CHỈ TRẢ VỀ JSON object, KHÔNG CÓ TEXT KHÁC.
"""


class CustomGraphExtractor:
    """Extract nodes and relationships using LLM with JSON output."""

    def __init__(self, graph_db: Optional[GraphDB] = None, model: Optional[str] = None):
        self.graph_db = graph_db or GraphDB()
        self.builder = GraphBuilder(graph_db=self.graph_db)
        self.model = model or os.getenv("YESCALE_MODEL", "gemini-2.0-flash")
        
        # Verify API key is configured
        api_key = os.getenv("YESCALE_API_KEY")
        if not api_key:
            raise RuntimeError("YESCALE_API_KEY chưa được cấu hình trong env.")

    def extract_from_text(
        self,
        text: str,
        source_chunk_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Extract nodes and relationships from text using LLM.
        
        Returns:
            dict with keys: persons, achievements, events, eras, fields, relationships, person_relationships
        """
        # Build prompt by substituting text into template
        prompt = EXTRACTION_PROMPT.replace("{{text}}", text)
        
        try:
            response = call_llm(prompt, model=self.model, temperature=0.2)
            # Parse JSON from response
            data = json.loads(response)
        except json.JSONDecodeError:
            # If JSON parsing fails, try to extract JSON from response
            try:
                import re
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group())
                else:
                    print(f"⚠️  Failed to extract JSON from response: {response[:200]}")
                    return {
                        "persons": [],
                        "achievements": [],
                        "events": [],
                        "eras": [],
                        "fields": [],
                        "relationships": [],
                        "person_relationships": [],
                    }
            except Exception as e:
                print(f"⚠️  Error parsing LLM response: {e}")
                return {
                    "persons": [],
                    "achievements": [],
                    "events": [],
                    "eras": [],
                    "fields": [],
                    "relationships": [],
                    "person_relationships": [],
                }

        # Validate structure
        data.setdefault("persons", [])
        data.setdefault("achievements", [])
        data.setdefault("events", [])
        data.setdefault("eras", [])
        data.setdefault("fields", [])
        data.setdefault("relationships", [])
        data.setdefault("person_relationships", [])

        return data

    def build_from_extraction(self, extracted_data: Dict[str, Any]) -> Tuple[int, int]:
        """
        Build graph from extracted data.
        
        Returns:
            (nodes_created, relationships_created)
        """
        nodes: List[Dict[str, Any]] = []
        rels: List[Dict[str, Any]] = []

        # Create Person nodes
        for person in extracted_data.get("persons", []):
            nodes.append({
                "type": "Person",
                "identifier": {"name": person.get("name")},
                "properties": {
                    "role": person.get("role"),
                    "birth_year": person.get("birth_year"),
                    "death_year": person.get("death_year"),
                }
            })

        # Create Achievement nodes
        for achievement in extracted_data.get("achievements", []):
            nodes.append({
                "type": "Achievement",
                "identifier": {"name": achievement.get("name")},
                "properties": {
                    "year": achievement.get("year"),
                    "description": achievement.get("description"),
                }
            })

        # Create Event nodes (NEW)
        for event in extracted_data.get("events", []):
            nodes.append({
                "type": "Event",
                "identifier": {"name": event.get("name")},
                "properties": {
                    "year": event.get("year"),
                    "description": event.get("description"),
                    "event_type": event.get("event_type"),
                }
            })

        # Create Era nodes
        for era in extracted_data.get("eras", []):
            nodes.append({
                "type": "Era",
                "identifier": {"name": era.get("name")},
                "properties": {
                    "start_year": era.get("start_year"),
                    "end_year": era.get("end_year"),
                    "description": era.get("description"),
                }
            })

        # Create Field nodes
        for field in extracted_data.get("fields", []):
            nodes.append({
                "type": "Field",
                "identifier": {"name": field.get("name")},
                "properties": {
                    "category": field.get("category"),
                    "description": field.get("description"),
                }
            })

        # Create relationships
        for rel in extracted_data.get("relationships", []):
            rels.append({
                "from_type": rel.get("from_type", "Person"),
                "from_id": {"name": rel.get("from_name")},
                "rel_type": rel.get("rel_type", "RELATED_TO"),
                "to_type": rel.get("to_type", "Achievement"),
                "to_id": {"name": rel.get("to_name")},
                "properties": {},
            })

        # Create person-to-person relationships (NEW)
        for person_rel in extracted_data.get("person_relationships", []):
            rels.append({
                "from_type": "Person",
                "from_id": {"name": person_rel.get("from_name")},
                "rel_type": person_rel.get("rel_type", "RELATED_TO"),
                "to_type": "Person",
                "to_id": {"name": person_rel.get("to_name")},
                "properties": {},
            })

        # Build to Neo4j
        if nodes or rels:
            # batch_create_nodes returns count directly
            result = self.builder.batch_create_nodes(nodes)
            if isinstance(result, dict):
                nodes_created = result.get("nodes_created", 0)
            else:
                # If it returns just the count
                nodes_created = result if result else len(nodes)
            
            # Create relationships
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
                    print(f"    ⚠️  Error creating relationship: {e}")
        else:
            nodes_created = 0
            relationships_created = 0

        return nodes_created, relationships_created

    def enrich_text(
        self,
        text: str,
        source_chunk_id: Optional[str] = None,
    ) -> Tuple[int, int]:
        """
        Enrich text: extract and build graph.
        
        Returns:
            (nodes_created, relationships_created)
        """
        extracted = self.extract_from_text(text, source_chunk_id)
        return self.build_from_extraction(extracted)

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
                print(f"  ✅ Chunk {cid}: {n} nodes, {r} rels")
            except Exception as e:
                print(f"  ⚠️  Error processing chunk {cid}: {e}")

        return {"nodes_created": total_nodes, "relationships_created": total_rels}
