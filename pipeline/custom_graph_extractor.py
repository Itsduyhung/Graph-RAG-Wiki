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
        target_person: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Extract nodes and relationships from text using LLM.
        
        Args:
            text: Content to extract from
            source_chunk_id: ID of source chunk
            target_person: Name of main person (optional) - if provided, filter results to only include info about this person
        
        Returns:
            dict with keys: persons, achievements, events, eras, fields, relationships, person_relationships
        """
        # Build prompt by substituting text into template
        additional_instruction = ""
        if target_person:
            additional_instruction = f"\n\n⚠️ QUAN TRỌNG: Chỉ trích xuất thông tin TRỰC TIẾP liên quan đến '{target_person}'. KHÔNG trích xuất thông tin của các người khác trừ khi họ có quan hệ trực tiếp với '{target_person}'."
        
        prompt = EXTRACTION_PROMPT.replace("{{text}}", text) + additional_instruction
        
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
        link_to_person: Optional[str] = None,
    ) -> Tuple[int, int]:
        """
        Enrich text: extract and build graph.
        
        Args:
            text: Text to extract from
            source_chunk_id: Source chunk identifier
            link_to_person: Person name to link achievements/events/etc to (if None, uses from_name from relationships)
        
        Returns:
            (nodes_created, relationships_created)
        """
        # Pass target_person to extraction for filtering
        extracted = self.extract_from_text(text, source_chunk_id, target_person=link_to_person)
        nodes_created, rels_created = self.build_from_extraction(extracted)
        
        # Auto-link achievements/events/eras/fields to main person if specified
        if link_to_person:
            rels_created += self._auto_link_to_person(
                extracted_data=extracted,
                person_name=link_to_person
            )
        
        return nodes_created, rels_created

    def _auto_link_to_person(self, extracted_data: Dict[str, Any], person_name: str) -> int:
        """
        Auto-create relationships from person to achievements/events/eras/fields.
        
        Returns:
            Number of relationships created
        """
        relationships_created = 0
        
        # Link to Achievements
        for achievement in extracted_data.get("achievements", []):
            try:
                self.builder.create_relationship(
                    "Person",
                    {"name": person_name},
                    "ACHIEVED",
                    "Achievement",
                    {"name": achievement.get("name")},
                )
                relationships_created += 1
            except:
                pass
        
        # Link to Events
        for event in extracted_data.get("events", []):
            try:
                self.builder.create_relationship(
                    "Person",
                    {"name": person_name},
                    "PARTICIPATED_IN",
                    "Event",
                    {"name": event.get("name")},
                )
                relationships_created += 1
            except:
                pass
        
        # Link to Eras
        for era in extracted_data.get("eras", []):
            try:
                self.builder.create_relationship(
                    "Person",
                    {"name": person_name},
                    "ACTIVE_IN",
                    "Era",
                    {"name": era.get("name")},
                )
                relationships_created += 1
            except:
                pass
        
        # Link to Fields
        for field in extracted_data.get("fields", []):
            try:
                self.builder.create_relationship(
                    "Person",
                    {"name": person_name},
                    "ACTIVE_IN",
                    "Field",
                    {"name": field.get("name")},
                )
                relationships_created += 1
            except:
                pass
        
        # FALLBACK: If no explicit relationships extracted, try to link to any Achievement/Event/Era/Field nodes
        # This handles cases where LLM didn't extract proper relationships
        try:
            db = GraphDB()
            with db.driver.session(database=db.database) as session:
                # Get all Achievement nodes and link them
                achievements = session.run(
                    "MATCH (a:Achievement) RETURN a.name as name LIMIT 100"
                ).data()
                for a in achievements:
                    try:
                        self.builder.create_relationship(
                            "Person",
                            {"name": person_name},
                            "ACHIEVED",
                            "Achievement",
                            {"name": a["name"]},
                        )
                        relationships_created += 1
                    except:
                        pass
                
                # Get all Event nodes and link them
                events = session.run(
                    "MATCH (e:Event) RETURN e.name as name LIMIT 100"
                ).data()
                for e in events:
                    try:
                        self.builder.create_relationship(
                            "Person",
                            {"name": person_name},
                            "PARTICIPATED_IN",
                            "Event",
                            {"name": e["name"]},
                        )
                        relationships_created += 1
                    except:
                        pass
        except:
            pass
        
        return relationships_created

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
