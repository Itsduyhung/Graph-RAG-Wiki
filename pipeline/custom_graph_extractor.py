"""Custom graph extractor dùng YEScale API để sinh node: Achievement, Era, Field."""

import json
import os
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

from graph.builder import GraphBuilder
from graph.storage import GraphDB
from llm.llm_client import call_llm

load_dotenv()


EXTRACTION_PROMPT = """Phân tích đoạn văn bản sau và trích xuất TẤT CẢ thông tin có thể được.
KHÔNG giới hạn bởi bất kỳ schema hay loại node nào - hãy để LLM tự quyết định!

Nhiệm vụ:
1. Đọc kỹ đoạn văn
2. Xác định TẤT CẢ các thực thể (entities) quan trọng
3. Xác định các mối quan hệ giữa các thực thể đó
4. Xác định các thuộc tính của mỗi thực thể

Nguyên tắc:
- Trích xuất TẤT CẢ thông tin được đề cập, không bỏ sót
- Đặc biệt chú ý: tên người, ngày tháng, địa danh, sự kiện, thành tựu, các mối quan hệ
- Nếu thấy có "tên khác", "còn gọi là", "biệt danh", "tên chữ Hán" -> trích xuất làm thực thể riêng và link với thực thể chính
- Nếu thấy có quan hệ "cha của", "con của", "vợ của", "thầy của" -> trích xuất làm relationship

Đoạn văn bản cần phân tích:
{{text}}

Format JSON output:
{{
    "nodes": [
        {{"id": "unique_id", "type": "Person", "name": "Tên chính", "properties": {{"key": "value"}}}},
        {{"id": "name_1", "type": "Name", "name": "Tên gọi khác", "properties": {{"name_type": "birth_name"}}, "linked_to": "unique_id"}}
    ],
    "relationships": [
        {{"from": "unique_id", "type": "HAS_NAME", "to": "name_1"}}
    ]
}}

CHỈ TRẢ VỀ JSON, KHÔNG CÓ TEXT KHÁC.
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
            dict with extracted nodes and relationships (flexible format)
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
                    return {"nodes": [], "relationships": []}
            except Exception as e:
                print(f"⚠️  Error parsing LLM response: {e}")
                return {"nodes": [], "relationships": []}

        # Ensure data has expected keys
        data.setdefault("nodes", [])
        data.setdefault("relationships", [])

        return data

    def build_from_extraction(self, extracted_data: Dict[str, Any]) -> Tuple[int, int]:
        """
        Build graph from extracted data - flexible format.

        Returns:
            (nodes_created, relationships_created)
        """
        nodes: List[Dict[str, Any]] = []
        rels: List[Dict[str, Any]] = []

        # Build node lookup from node id -> node info
        node_lookup: Dict[str, Dict[str, Any]] = {}

        # Process nodes from flexible format
        for node in extracted_data.get("nodes", []):
            node_id = node.get("id")
            node_type = node.get("type", "Unknown")
            node_name = node.get("name", "")
            node_props = node.get("properties", {})

            # Store for lookup
            if node_id:
                node_lookup[node_id] = node

            # Determine identifier based on node type
            if node_type == "Name":
                identifier = {"value": node_name}
            else:
                identifier = {"name": node_name}

            # Create node for Neo4j
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

            # Get source and target node info
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

            # Create relationship
            rels.append({
                "from_type": from_type,
                "from_id": from_id_dict,
                "rel_type": rel_type,
                "to_type": to_type,
                "to_id": to_id_dict,
                "properties": {},
            })

        # Legacy format support (persons, achievements, events, etc.)
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

        # Legacy relationships
        for rel in extracted_data.get("relationships", []):
            rels.append({
                "from_type": rel.get("from_type", "Person"),
                "from_id": {"name": rel.get("from_name")},
                "rel_type": rel.get("rel_type", "RELATED_TO"),
                "to_type": rel.get("to_type", "Person"),
                "to_id": {"name": rel.get("to_name")},
                "properties": {},
            })

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
