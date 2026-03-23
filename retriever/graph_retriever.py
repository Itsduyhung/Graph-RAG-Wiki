# retriever/graph_retriever.py
"""Graph-based retrieval from knowledge graph."""
from typing import List, Dict, Any, Optional
from graph.storage import GraphDB
from graph.graph_utils import query_subgraph


class GraphRetriever:
    """Retrieve relevant subgraphs from knowledge graph."""
    
    def __init__(self, graph_db: GraphDB = None):
        self.graph_db = graph_db or GraphDB()
    
    def retrieve_by_company(self, company_name: str) -> Dict[str, Any]:
        """
        Retrieve information about a company and its relationships.
        
        Args:
            company_name: Name of the company
            
        Returns:
            Dictionary with retrieved information
        """
        founders = self.graph_db.get_founder(company_name)
        
        # Get subgraph around company
        subgraph = query_subgraph(self.graph_db, "Company", company_name, depth=2)
        
        return {
            "company": company_name,
            "founders": founders,
            "subgraph": subgraph,
            "context": self._build_context(company_name, founders)
        }
    
    def retrieve_by_person(self, person_name: str) -> Dict[str, Any]:
        """
        Retrieve information about a person and their relationships.
        
        Args:
            person_name: Name of the person
            
        Returns:
            Dictionary with retrieved information
        """
        query = """
        MATCH (p:Person {name: $name})-[r:FOUNDED]->(c:Company)
        RETURN c.name AS company
        """
        
        with self.graph_db.driver.session(database=self.graph_db.database) as session:
            result = session.run(query, name=person_name)
            companies = [r["company"] for r in result]
        
        subgraph = query_subgraph(self.graph_db, "Person", person_name, depth=2)
        
        return {
            "person": person_name,
            "companies_founded": companies,
            "subgraph": subgraph,
            "context": self._build_person_context(person_name, companies)
        }
    
    def retrieve_person_full_profile(self, person_name: str) -> Dict[str, Any]:
        """
        Retrieve complete profile of a person including all relationships:
        BORN_IN, WORKED_IN, ACTIVE_IN, ACHIEVED, INFLUENCED_BY, DESCRIBED_IN
        
        Args:
            person_name: Name of the person
            
        Returns:
            Dictionary with complete person profile
        """
        query = """
        MATCH (p:Person {name: $name})
        OPTIONAL MATCH (p)-[:BORN_AT]->(born_tp:TimePoint)
        OPTIONAL MATCH (p)-[:DIED_AT]->(died_tp:TimePoint)
        OPTIONAL MATCH (p)-[:HAS_ROLE]->(role:Role)
        OPTIONAL MATCH (p)-[:BELONGS_TO_DYNASTY]->(dynasty:Dynasty)
        OPTIONAL MATCH (p)-[:BORN_IN]->(country:Country)
        OPTIONAL MATCH (p)-[:WORKED_IN]->(field:Field)
        OPTIONAL MATCH (p)-[:ACTIVE_IN]->(era:Era)
        OPTIONAL MATCH (p)-[:ACHIEVED]->(achievement:Achievement)
        OPTIONAL MATCH (p)-[:INFLUENCED_BY]->(influencer:Person)
        OPTIONAL MATCH (p)-[:DESCRIBED_IN]->(chunk:WikiChunk)
        OPTIONAL MATCH (p)-[:FOUNDED]->(company:Company)
        OPTIONAL MATCH (p)-[:PARTICIPATED_IN]->(event:Event)
        OPTIONAL MATCH (event)-[:HAPPENED_AT]->(event_tp:TimePoint)
        OPTIONAL MATCH (p)-[:HAS_NAME]->(name:Name)
        RETURN 
            p,
            collect(DISTINCT born_tp) AS born_timepoints,
            collect(DISTINCT died_tp) AS died_timepoints,
            collect(DISTINCT role.name) AS roles,
            collect(DISTINCT dynasty.name) AS dynasties,
            collect(DISTINCT country.name) AS countries,
            collect(DISTINCT field.name) AS fields,
            collect(DISTINCT era.name) AS eras,
            collect(DISTINCT achievement.name) AS achievements,
            collect(DISTINCT influencer.name) AS influencers,
            collect(DISTINCT chunk.chunk_id) AS wiki_chunks,
            collect(DISTINCT company.name) AS companies_founded,
            collect(DISTINCT event) AS events,
            collect(DISTINCT event_tp) AS event_timepoints,
            collect(DISTINCT {name: name.value, name_type: name.name_type}) AS names
        """
        
        with self.graph_db.driver.session(database=self.graph_db.database) as session:
            result = session.run(query, name=person_name)
            record = result.single()
            
            if not record:
                return {
                    "person": person_name,
                    "found": False,
                    "context": f"Không tìm thấy thông tin về {person_name}"
                }
            
            person_props = dict(record["p"])
            born_tps = [dict(tp) for tp in (record["born_timepoints"] or []) if tp]
            died_tps = [dict(tp) for tp in (record["died_timepoints"] or []) if tp]
            roles = [r for r in (record["roles"] or []) if r]
            dynasties = [d for d in (record["dynasties"] or []) if d]
            countries = record["countries"] or []
            fields = record["fields"] or []
            eras = record["eras"] or []
            achievements = record["achievements"] or []
            influencers = record["influencers"] or []
            wiki_chunks = record["wiki_chunks"] or []
            companies = record["companies_founded"] or []
            events = [dict(e) for e in (record["events"] or [])]
            event_tps = [dict(tp) for tp in (record["event_timepoints"] or []) if tp]
            names = [n for n in (record["names"] or []) if n and n.get("name")]
            
            context = self._build_full_person_context(
                person_name,
                person_props,
                countries,
                fields,
                eras,
                achievements,
                influencers,
                wiki_chunks,
                companies,
                events,
                roles,
                dynasties,
                born_tps,
                died_tps,
                event_tps,
                names,
            )
            
            return {
                "person": person_name,
                "found": True,
                "properties": person_props,
                "roles": roles,
                "dynasties": dynasties,
                "born_timepoints": born_tps,
                "died_timepoints": died_tps,
                "countries": countries,
                "fields": fields,
                "eras": eras,
                "achievements": achievements,
                "influencers": influencers,
                "wiki_chunks": wiki_chunks,
                "companies_founded": companies,
                "events": events,
                "context": context
            }
    
    def retrieve_by_relationship_type(
        self, 
        person_name: str, 
        relationship_type: str
    ) -> Dict[str, Any]:
        """
        Retrieve specific relationship type for a person.
        
        Args:
            person_name: Name of the person
            relationship_type: Type of relationship (BORN_IN, WORKED_IN, etc.)
            
        Returns:
            Dictionary with relationship information
        """
        # Map relationship to target node type
        rel_to_node = {
            # Family relationships
            "FATHER_OF": "Person",
            "MOTHER_OF": "Person",
            "CHILD_OF": "Person",
            "SPOUSE_OF": "Person",
            "SIBLING_OF": "Person",
            "MENTOR_OF": "Person",
            "STUDENT_OF": "Person",
            "ALLY_OF": "Person",
            "ENEMY_OF": "Person",
            "FRIEND_OF": "Person",
            "SUCCESSOR_OF": "Person",
            # Other relationships
            "BORN_IN": "Country",
            "BORN_AT": "TimePoint",
            "DIED_AT": "TimePoint",
            "WORKED_IN": "Field",
            "ACTIVE_IN": "Era",
            "ACHIEVED": "Achievement",
            "INFLUENCED_BY": "Person",
            "DESCRIBED_IN": "WikiChunk",
            "FOUNDED": "Company",
            "PARTICIPATED_IN": "Event",
            "HAS_ROLE": "Role",
            "BELONGS_TO_DYNASTY": "Dynasty",
            "HAS_NAME": "Name",
        }
        
        target_type = rel_to_node.get(relationship_type)
        if not target_type:
            return {
                "person": person_name,
                "relationship": relationship_type,
                "targets": [],
                "error": f"Unknown relationship type: {relationship_type}"
            }
        
        # Handle Name node differently (uses 'value' instead of 'name')
        if target_type == "Name":
            query = f"""
            MATCH (p:Person {{name: $name}})-[r:{relationship_type}]->(target:Name)
            RETURN target, r
            ORDER BY target.value
            """
            with self.graph_db.driver.session(database=self.graph_db.database) as session:
                result = session.run(query, name=person_name)
                targets = []
                for record in result:
                    target_props = dict(record["target"])
                    rel_props = dict(record["r"])
                    targets.append({
                        "target": {"name": target_props.get("value"), **target_props},
                        "relationship_properties": rel_props
                    })
        else:
            # For family relationships, query both directions
            family_rels = {"FATHER_OF", "MOTHER_OF", "CHILD_OF", "SPOUSE_OF", "SIBLING_OF", 
                          "MENTOR_OF", "STUDENT_OF", "ALLY_OF", "ENEMY_OF", "FRIEND_OF", "SUCCESSOR_OF"}
            
            if relationship_type in family_rels:
                # Bidirectional query for family relationships
                query = f"""
                MATCH (p:Person {{name: $name}})-[r:{relationship_type}]->(target:{target_type})
                RETURN target, r, 'outgoing' AS direction
                UNION
                MATCH (p:Person {{name: $name}})<-[r:{relationship_type}]-(target:{target_type})
                RETURN target, r, 'incoming' AS direction
                """
                with self.graph_db.driver.session(database=self.graph_db.database) as session:
                    result = session.run(query, name=person_name)
                    targets = []
                    for record in result:
                        target_props = dict(record["target"])
                        rel_props = dict(record["r"])
                        direction = record["direction"]
                        targets.append({
                            "target": target_props,
                            "relationship_properties": rel_props,
                            "direction": direction
                        })
            else:
                query = f"""
                MATCH (p:Person {{name: $name}})-[r:{relationship_type}]->(target:{target_type})
                RETURN target, r
                ORDER BY target.name
                """
                with self.graph_db.driver.session(database=self.graph_db.database) as session:
                    result = session.run(query, name=person_name)
                    targets = []
                    for record in result:
                        target_props = dict(record["target"])
                        rel_props = dict(record["r"])
                        targets.append({
                            "target": target_props,
                            "relationship_properties": rel_props
                        })
        
        return {
            "person": person_name,
            "relationship": relationship_type,
            "target_type": target_type,
            "targets": targets,
            "context": self._build_relationship_context(person_name, relationship_type, targets)
        }
    
    def retrieve_by_relationship(
        self, 
        entity_type: str, 
        entity_name: str, 
        relationship_type: str
    ) -> Dict[str, Any]:
        """
        Retrieve entities connected by a specific relationship.
        
        Args:
            entity_type: Type of entity (Person, Company, etc.)
            entity_name: Name of the entity
            relationship_type: Type of relationship (FOUNDED, WORKS_AT, etc.)
            
        Returns:
            Dictionary with retrieved relationships
        """
        query = f"""
        MATCH (source:{entity_type} {{name: $name}})-[r:{relationship_type}]->(target)
        RETURN target.name AS target_name, labels(target) AS target_type, r
        """
        
        with self.graph_db.driver.session(database=self.graph_db.database) as session:
            result = session.run(query, name=entity_name)
            relationships = [dict(record) for record in result]
        
        return {
            "source": entity_name,
            "source_type": entity_type,
            "relationship": relationship_type,
            "targets": relationships
        }
    
    def _build_context(self, company_name: str, founders: List[str]) -> str:
        """Build context string from retrieved data."""
        if not founders:
            return f"Company: {company_name} (no founders found)"
        
        return f"Company: {company_name}\nFounders: {', '.join(founders)}"
    
    def _build_person_context(self, person_name: str, companies: List[str]) -> str:
        """Build context string for person."""
        if not companies:
            return f"Person: {person_name} (no companies found)"
        
        return f"Person: {person_name}\nCompanies Founded: {', '.join(companies)}"
    
    def _build_full_person_context(
        self,
        person_name: str,
        person_props: Dict[str, Any],
        countries: List[str],
        fields: List[str],
        eras: List[str],
        achievements: List[str],
        influencers: List[str],
        wiki_chunks: List[str],
        companies: List[str],
        events: List[Dict[str, Any]],
        roles: List[str],
        dynasties: List[str],
        born_timepoints: List[Dict[str, Any]],
        died_timepoints: List[Dict[str, Any]],
        event_timepoints: List[Dict[str, Any]],
        names: List[Dict[str, Any]] = None,
    ) -> str:
        """Build comprehensive context string for person profile."""
        names = names or []
        lines = [f"Person: {person_name}"]

        if person_props.get("aliases") or person_props.get("other_names"):
            aliases = person_props.get("aliases") or person_props.get("other_names")
            if isinstance(aliases, list):
                aliases = ", ".join(str(a) for a in aliases)
            lines.append(f"Aliases / Other names: {aliases}")
        
        if person_props.get("biography"):
            lines.append(f"Biography: {person_props['biography']}")
        
        if person_props.get("birth_date"):
            lines.append(f"Birth Date: {person_props['birth_date']}")
        if person_props.get("birth_year") is not None:
            lines.append(f"Birth Year: {person_props['birth_year']}")
        if born_timepoints:
            lines.append(f"Born At: {', '.join(tp.get('label','') for tp in born_timepoints if tp.get('label'))}")

        if person_props.get("death_date"):
            lines.append(f"Death Date: {person_props['death_date']}")
        if person_props.get("death_year") is not None:
            lines.append(f"Death Year: {person_props['death_year']}")
        if died_timepoints:
            lines.append(f"Died At: {', '.join(tp.get('label','') for tp in died_timepoints if tp.get('label'))}")

        if roles:
            lines.append(f"Roles: {', '.join(roles)}")

        if dynasties:
            lines.append(f"Dynasties: {', '.join(dynasties)}")

        # Names (HAS_NAME relationships)
        if names:
            formatted_names = []
            for n in names:
                name_val = n.get("name", "")
                name_type = n.get("name_type", "")
                if name_type:
                    formatted_names.append(f"{name_val} ({name_type})")
                else:
                    formatted_names.append(name_val)
            lines.append(f"Other names: {', '.join(formatted_names)}")
        
        if countries:
            lines.append(f"Born In: {', '.join(countries)}")
        
        if fields:
            lines.append(f"Worked In Fields: {', '.join(fields)}")
        
        if eras:
            lines.append(f"Active In Eras: {', '.join(eras)}")
        
        if achievements:
            lines.append(f"Achievements: {', '.join(achievements)}")
        
        if influencers:
            lines.append(f"Influenced By: {', '.join(influencers)}")
        
        if companies:
            lines.append(f"Companies Founded: {', '.join(companies)}")
        
        if wiki_chunks:
            lines.append(f"Described In: {len(wiki_chunks)} wiki chunks")

        # Events (PARTICIPATED_IN)
        if events:
            formatted_events = []
            for e in events:
                name = e.get("name", "Unknown event")
                year = e.get("year")
                s = name
                if year:
                    s += f" ({year})"
                formatted_events.append(s)
            lines.append(f"Events: {', '.join(formatted_events)}")

        # Nếu có birth_year và có sự kiện "Lên ngôi" với year, gợi ý tuổi lên ngôi
        try:
            by = person_props.get("birth_year")
            if by is not None:
                for e in events:
                    ename = (e.get("name") or "").lower()
                    ey = e.get("year")
                    if ey and ("lên ngôi" in ename or "đăng quang" in ename):
                        lines.append(f"Estimated age at accession: {int(ey) - int(by)}")
                        break
        except Exception:
            pass

        # Bổ sung thông tin trị vì nếu có trong properties
        reign_start = person_props.get("reign_start_year")
        reign_end = person_props.get("reign_end_year")
        role = person_props.get("role")
        if reign_start or reign_end or role:
            parts = []
            if reign_start:
                parts.append(f"from {reign_start}")
            if reign_end:
                parts.append(f"to {reign_end}")
            reign_str = " ".join(parts) if parts else ""
            if role:
                lines.append(f"Role: {role}")
            if reign_str:
                lines.append(f"Reign: {reign_str}")
        
        return "\n".join(lines)
    
    def _build_relationship_context(
        self, 
        person_name: str, 
        relationship_type: str, 
        targets: List[Dict[str, Any]]
    ) -> str:
        """Build context string for specific relationship in Vietnamese."""
        # Map relationship types to Vietnamese
        rel_to_vietnamese = {
            "FATHER_OF": "cha",
            "MOTHER_OF": "mẹ", 
            "CHILD_OF": "con",
            "SPOUSE_OF": "vợ/chồng",
            "SIBLING_OF": "anh chị em",
            "MENTOR_OF": "thầy/mentor",
            "STUDENT_OF": "học trò",
            "ALLY_OF": "đồng minh",
            "ENEMY_OF": "kẻ thù",
            "FRIEND_OF": "bạn",
            "SUCCESSOR_OF": "người kế thừa",
            "BORN_IN": "sinh tại",
            "BORN_AT": "sinh năm",
            "DIED_AT": "mất năm",
            "WORKED_IN": "làm việc trong",
            "ACTIVE_IN": "hoạt động trong",
            "ACHIEVED": "đạt được",
            "INFLUENCED_BY": "bị ảnh hưởng bởi",
            "PARTICIPATED_IN": "tham gia",
            "HAS_ROLE": "có vai trò",
            "BELONGS_TO_DYNASTY": "thuộc triều đại",
            "HAS_NAME": "còn được biết đến với tên",
        }
        
        vietnamese_rel = rel_to_vietnamese.get(relationship_type, relationship_type)
        
        if not targets:
            return f"{person_name} không có thông tin về {vietnamese_rel}"
        
        # Format target names with direction info for family relationships
        family_rels = {"FATHER_OF", "MOTHER_OF", "CHILD_OF", "SPOUSE_OF", "SIBLING_OF"}
        
        formatted_targets = []
        for t in targets:
            target_name = t["target"].get("name", "Unknown")
            direction = t.get("direction", "outgoing")
            
            if relationship_type in family_rels:
                if relationship_type == "CHILD_OF" and direction == "incoming":
                    # (someone)-[:CHILD_OF]->(person) means person is the parent
                    formatted_targets.append(f"{target_name} (con của)")
                elif relationship_type == "FATHER_OF" and direction == "incoming":
                    formatted_targets.append(f"{target_name} (cha của)")
                elif relationship_type == "MOTHER_OF" and direction == "incoming":
                    formatted_targets.append(f"{target_name} (mẹ của)")
                elif relationship_type == "SPOUSE_OF":
                    formatted_targets.append(f"{target_name}")
                else:
                    formatted_targets.append(target_name)
            else:
                # For HAS_NAME, include the name type
                if relationship_type == "HAS_NAME":
                    name_type = t.get("relationship_properties", {}).get("name_type", "")
                    if name_type:
                        formatted_targets.append(f"{target_name} ({name_type})")
                    else:
                        formatted_targets.append(target_name)
                else:
                    formatted_targets.append(target_name)
        
        return f"{person_name} - {vietnamese_rel}: {', '.join(formatted_targets)}"

    def search_person_by_text(self, text: str, limit: int = 3) -> Dict[str, Any]:
        """
        Fallback search: tìm Person theo name/biography chứa text câu hỏi.
        Hữu ích cho các câu hỏi như 'Vị vua cuối cùng của triều Tiền Lê là ai?'
        khi intent không chỉ rõ person.
        """
        with self.graph_db.driver.session(database=self.graph_db.database) as session:
            result = session.run(
                """
                MATCH (p:Person)
                WHERE (p.name CONTAINS $q
                       OR (p.biography IS NOT NULL AND p.biography CONTAINS $q))
                RETURN p
                LIMIT $limit
                """,
                q=text,
                limit=limit,
            )
            persons = [dict(record["p"]) for record in result]

        if not persons:
            return {"persons": [], "context": ""}

        lines = []
        for p in persons:
            name = p.get("name", "Unknown")
            bio = p.get("biography", "")
            birth = p.get("birth_date")
            line = f"Person: {name}"
            if birth:
                line += f" (Birth Date: {birth})"
            if bio:
                line += f"\nBiography: {bio}"
            lines.append(line)

        context = "\n\n".join(lines)
        return {"persons": persons, "context": context}

    def find_person_by_name(self, name_query: str) -> Dict[str, Any]:
        """
        Tìm Person thông qua Name node (tên gọi khác, biệt danh...).
        Ví dụ: query "Vĩnh Thụy" sẽ tìm được Person "Bảo Đại" thông qua HAS_NAME relationship.
        
        Args:
            name_query: Tên cần tìm kiếm
            
        Returns:
            Dictionary với person info hoặc empty nếu không tìm thấy
        """
        with self.graph_db.driver.session(database=self.graph_db.database) as session:
            # First try direct match on Person.name
            result = session.run(
                """
                MATCH (p:Person {name: $q})
                RETURN p
                LIMIT 1
                """,
                q=name_query,
            )
            persons = [dict(record["p"]) for record in result]
            
            if persons:
                return {"person": persons[0], "via": "direct_name"}
            
            # Then try finding through Name node
            result = session.run(
                """
                MATCH (n:Name {value: $q})<-[:HAS_NAME]-(p:Person)
                RETURN p, n
                LIMIT 1
                """,
                q=name_query,
            )
            records = list(result)
            
            if records:
                person = dict(records[0]["p"])
                name_node = dict(records[0]["n"])
                return {
                    "person": person, 
                    "via": "name_node",
                    "original_name": name_node.get("value"),
                    "name_type": name_node.get("name_type")
                }
            
            # Try partial match on Name.value
            result = session.run(
                """
                MATCH (n:Name)<-[:HAS_NAME]-(p:Person)
                WHERE n.value CONTAINS $q
                RETURN p, n
                LIMIT 5
                """,
                q=name_query,
            )
            records = list(result)
            
            if records:
                persons = [{"person": dict(r["p"]), "name_node": dict(r["n"])} for r in records]
                return {"persons": persons, "via": "name_node_partial"}
        
        return {"person": None, "via": None}


