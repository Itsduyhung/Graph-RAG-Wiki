# graph/builder.py
"""Graph construction utilities - generic và linh hoạt cho bất kỳ node/relationship type nào."""
from typing import List, Dict, Any, Optional, Union
from .storage import GraphDB


class GraphBuilder:
    """Build và populate graph từ data - hoàn toàn generic và linh hoạt."""
    
    def __init__(self, graph_db: GraphDB = None):
        self.graph_db = graph_db or GraphDB()
    
    def create_node(
        self, 
        node_type: str, 
        identifier: Union[str, Dict[str, Any]], 
        properties: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Tạo node với bất kỳ type nào - generic và linh hoạt.
        
        Args:
            node_type: Loại node (Person, Company, Product, ...)
            identifier: Tên node hoặc dict với các thuộc tính để identify (ví dụ: {"name": "..."} hoặc {"id": "..."})
            properties: Thuộc tính của node
        
        Examples:
            create_node("Person", "John Doe", {"age": 30, "email": "john@example.com"})
            create_node("Company", {"name": "Fintech X"}, {"industry": "Finance", "founded_year": 2020})
            create_node("Product", {"code": "P001"}, {"name": "Product 1", "price": 100})
        """
        props = properties or {}
        
        # Xử lý identifier - có thể là string hoặc dict
        if isinstance(identifier, str):
            # Nếu là string, dùng "name" làm key mặc định
            identifier_key = "name"
            identifier_value = identifier
            match_props = {identifier_key: identifier_value}
        else:
            # Nếu là dict, dùng các keys trong dict làm match properties
            match_props = identifier.copy()
            identifier_key = list(identifier.keys())[0]  # Lấy key đầu tiên
            identifier_value = identifier[identifier_key]
        
        # Tách properties khỏi match_props để tránh conflict
        # Chỉ set những properties không có trong match_props
        props_to_set = {k: v for k, v in (props or {}).items() if k not in match_props}
        
        # Tạo query động với MERGE và SET
        match_keys = ", ".join([f"{k}: $match_{k}" for k in match_props.keys()])
        
        query = f"""
        MERGE (n:{node_type} {{{match_keys}}})
        """
        
        # Set properties nếu có (chỉ những properties không dùng để match)
        if props_to_set:
            # Sử dụng SET n += $props để set nhiều properties cùng lúc
            query += "SET n += $props\n"
        
        query += "RETURN n"
        
        # Tạo parameters riêng cho match và properties
        params = {f"match_{k}": v for k, v in match_props.items()}
        if props_to_set:
            params["props"] = props_to_set
        
        with self.graph_db.driver.session(database=self.graph_db.database) as session:
            session.run(query, **params)
    
    def create_relationship(
        self,
        from_type: str,
        from_identifier: Union[str, Dict[str, Any]],
        rel_type: str,
        to_type: str,
        to_identifier: Union[str, Dict[str, Any]],
        rel_properties: Optional[Dict[str, Any]] = None,
        direction: str = "->"
    ) -> None:
        """
        Tạo relationship giữa 2 nodes - generic và linh hoạt.
        
        Args:
            from_type: Loại node nguồn
            from_identifier: Identifier của node nguồn (string hoặc dict)
            rel_type: Loại relationship (FOUNDED, WORKS_AT, OWNS, ...)
            to_type: Loại node đích
            to_identifier: Identifier của node đích (string hoặc dict)
            rel_properties: Thuộc tính của relationship
            direction: Hướng relationship ("->" hoặc "<-")
        
        Examples:
            create_relationship("Person", "John", "FOUNDED", "Company", "Fintech X")
            create_relationship("Person", {"id": "P1"}, "WORKS_AT", "Company", {"name": "Bank Y"}, {"role": "CEO"})
        """
        rel_props = rel_properties or {}
        
        # Xử lý identifiers
        def get_match_props(identifier):
            if isinstance(identifier, str):
                return {"name": identifier}
            return identifier
        
        from_match = get_match_props(from_identifier)
        to_match = get_match_props(to_identifier)
        
        # Tạo match conditions
        from_keys = ", ".join([f"{k}: $from_{k}" for k in from_match.keys()])
        to_keys = ", ".join([f"{k}: $to_{k}" for k in to_match.keys()])
        
        # Tạo relationship properties
        rel_set = ""
        if rel_props:
            rel_set_props = ", ".join([f"r.{k} = $rel_{k}" for k in rel_props.keys()])
            rel_set = f"SET {rel_set_props}\n"
        
        query = f"""
        MATCH (from:{from_type} {{{from_keys}}})
        MATCH (to:{to_type} {{{to_keys}}})
        MERGE (from)-[r:{rel_type}]{direction}(to)
        {rel_set}RETURN r
        """
        
        # Tạo parameters
        params = {}
        for k, v in from_match.items():
            params[f"from_{k}"] = v
        for k, v in to_match.items():
            params[f"to_{k}"] = v
        for k, v in rel_props.items():
            params[f"rel_{k}"] = v
        
        with self.graph_db.driver.session(database=self.graph_db.database) as session:
            session.run(query, **params)
    
    def batch_create_nodes(self, nodes: List[Dict[str, Any]]) -> int:
        """
        Tạo nhiều nodes cùng lúc - batch processing để tăng hiệu suất.
        
        Args:
            nodes: List các dict với format:
                [
                    {"type": "Person", "identifier": "John", "properties": {"age": 30}},
                    {"type": "Company", "identifier": {"name": "Fintech X"}, "properties": {"industry": "Finance"}},
                    ...
                ]
        
        Returns:
            Số lượng nodes đã tạo
        """
        created = 0
        for node in nodes:
            node_type = node.get("type")
            identifier = node.get("identifier", node.get("id", node.get("name")))
            properties = node.get("properties", {})
            
            if not node_type:
                continue
            
            # Nếu identifier không có, dùng properties làm identifier
            if identifier is None:
                # Tìm key phù hợp làm identifier (ưu tiên: id, name, code)
                for key in ["id", "name", "code", "identifier"]:
                    if key in properties:
                        identifier = {key: properties.pop(key)}
                        break
                if identifier is None:
                    continue
            
            try:
                self.create_node(node_type, identifier, properties)
                created += 1
            except Exception as e:
                print(f"Error creating node {node_type}: {e}")
                continue
        
        return created
    
    def batch_create_relationships(self, relationships: List[Dict[str, Any]]) -> int:
        """
        Tạo nhiều relationships cùng lúc - batch processing.
        
        Args:
            relationships: List các dict với format:
                [
                    {"from_type": "Person", "from_id": "John", "rel_type": "FOUNDED", 
                     "to_type": "Company", "to_id": "Fintech X", "properties": {"year": 2020}},
                    ...
                ]
        
        Returns:
            Số lượng relationships đã tạo
        """
        created = 0
        for rel in relationships:
            from_type = rel.get("from_type")
            from_id = rel.get("from_id") or rel.get("from_identifier")
            rel_type = rel.get("rel_type") or rel.get("rel_type")
            to_type = rel.get("to_type")
            to_id = rel.get("to_id") or rel.get("to_identifier")
            properties = rel.get("properties", {})
            direction = rel.get("direction", "->")
            
            if not all([from_type, from_id, rel_type, to_type, to_id]):
                continue
            
            try:
                self.create_relationship(
                    from_type, from_id, rel_type, to_type, to_id, 
                    properties, direction
                )
                created += 1
            except Exception as e:
                print(f"Error creating relationship: {e}")
                continue
        
        return created
    
    def build_from_data(self, data: List[Dict[str, Any]]) -> Dict[str, int]:
        """
        Build graph từ structured data - linh hoạt với format bất kỳ.
        
        Args:
            data: List các dict, có thể có format:
                - Format 1: {"nodes": [...], "relationships": [...]}
                - Format 2: [{"type": "Person", "identifier": "...", "properties": {...}}]
                - Format 3: [{"person": "John", "company": "Fintech X", "relationship": "FOUNDED"}]
        
        Returns:
            Dict với số lượng nodes và relationships đã tạo
        """
        nodes_created = 0
        rels_created = 0
        
        # Format 1: {"nodes": [...], "relationships": [...]}
        if isinstance(data, dict) and "nodes" in data:
            nodes_created = self.batch_create_nodes(data.get("nodes", []))
            rels_created = self.batch_create_relationships(data.get("relationships", []))
        
        # Format 2 hoặc 3: List of dicts
        elif isinstance(data, list):
            nodes = []
            relationships = []
            
            for item in data:
                # Format 2: {"type": "...", "identifier": "...", "properties": {...}}
                if "type" in item:
                    nodes.append(item)
                
                # Format 3: {"person": "...", "company": "...", "relationship": "..."}
                elif "person" in item and "company" in item:
                    # Legacy format - convert to new format
                    person = item.get("person")
                    company = item.get("company")
                    rel_type = item.get("relationship", "FOUNDED")
                    
                    nodes.append({"type": "Person", "identifier": person, "properties": item.get("person_props", {})})
                    nodes.append({"type": "Company", "identifier": company, "properties": item.get("company_props", {})})
                    relationships.append({
                        "from_type": "Person",
                        "from_id": person,
                        "rel_type": rel_type,
                        "to_type": "Company",
                        "to_id": company,
                        "properties": item.get("relationship_props", {})
                    })
                
                # Format khác - thử parse tự động
                else:
                    # Nếu có "type", coi như node
                    if "type" in item or any(key in item for key in ["name", "id", "code"]):
                        nodes.append(item)
            
            nodes_created = self.batch_create_nodes(nodes)
            rels_created = self.batch_create_relationships(relationships)
        
        return {
            "nodes_created": nodes_created,
            "relationships_created": rels_created,
            "total": nodes_created + rels_created
        }
    
    # Backward compatibility methods
    def create_person(self, name: str, properties: Dict[str, Any] = None):
        """Backward compatibility - dùng create_node thay thế."""
        self.create_node("Person", name, properties)
    
    def create_company(self, name: str, properties: Dict[str, Any] = None):
        """Backward compatibility - dùng create_node thay thế."""
        self.create_node("Company", name, properties)
    
    def create_founded_relationship(self, person_name: str, company_name: str, properties: Dict[str, Any] = None):
        """Backward compatibility - dùng create_relationship thay thế."""
        self.create_relationship("Person", person_name, "FOUNDED", "Company", company_name, properties)
    
    def create_person_with_profile(
        self,
        person_name: str,
        person_properties: Optional[Dict[str, Any]] = None,
        born_in: Optional[Dict[str, Any]] = None,
        worked_in: Optional[List[Dict[str, Any]]] = None,
        active_in: Optional[List[Dict[str, Any]]] = None,
        achievements: Optional[List[Dict[str, Any]]] = None,
        influenced_by: Optional[List[Dict[str, Any]]] = None,
        described_in: Optional[List[Dict[str, Any]]] = None,
        companies_founded: Optional[List[Dict[str, Any]]] = None,
        parents: Optional[List[Dict[str, Any]]] = None,
        events: Optional[List[Dict[str, Any]]] = None,
        roles: Optional[List[str]] = None,
        dynasty: Optional[str] = None,
    ) -> None:
        """
        Tạo Person node với đầy đủ profile và các relationships.
        
        Args:
            person_name: Tên của person
            person_properties: Thuộc tính của person (age, email, birth_date, biography, ...)
            born_in: {"country": "Country Name", "year": 1990, "city": "City Name"}
            worked_in: [{"field": "Field Name", "years": 10, "role": "..."}, ...]
            active_in: [{"era": "Era Name", "start_year": 2000, "end_year": 2010}, ...]
            achievements: [{"achievement": "Achievement Name", "year": 2020, "significance": "..."}, ...]
            influenced_by: [{"person": "Person Name", "influence_type": "...", "description": "..."}, ...]
            described_in: [{"chunk_id": "chunk_123", "relevance_score": 0.9}, ...]
            companies_founded: [{"company": "Company Name", "year": 2020}, ...]
            parents: [{"name": "Tên cha/mẹ", "relation": "cha|mẹ|..."}]
            events: [{"name": "Tên sự kiện", "year": 0, "description": "...", "significance": "..."}, ...]
            roles: ["Vua", "Thiền sư", ...]
            dynasty: "Tiền Lê|Trần|Lý|Nguyễn|..."
        
        Example:
            builder.create_person_with_profile(
                "Albert Einstein",
                person_properties={"birth_date": "1879-03-14", "biography": "Theoretical physicist"},
                born_in={"country": "Germany", "year": 1879, "city": "Ulm"},
                worked_in=[{"field": "Physics", "years": 50, "role": "Theoretical Physicist"}],
                active_in=[{"era": "Early 20th Century", "start_year": 1900, "end_year": 1955}],
                achievements=[{"achievement": "Nobel Prize in Physics", "year": 1921}],
                influenced_by=[{"person": "Max Planck", "influence_type": "Academic"}]
            )
        """
        if person_properties:
            reign_start = person_properties.get("reign_start_year") or person_properties.get("reign_start")
            reign_end = person_properties.get("reign_end_year") or person_properties.get("reign_end")
            try:
                start_year = int(reign_start) if reign_start is not None else None
            except Exception:
                start_year = None
            try:
                end_year = int(reign_end) if reign_end is not None else None
            except Exception:
                end_year = None

            if start_year is not None and end_year is not None:
                if "reign_duration_years" not in person_properties:
                    person_properties["reign_duration_years"] = abs(end_year - start_year)

        # Tạo Person node
        self.create_node("Person", person_name, person_properties)

        # Helpers: TimePoint
        def timepoint_label(year=None, month=None, day=None):
            if year is None:
                return None
            if month is None:
                return str(year)
            if day is None:
                return f"{int(year):04d}-{int(month):02d}"
            return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"

        def create_timepoint(year=None, month=None, day=None):
            label = timepoint_label(year, month, day)
            if not label:
                return None
            self.create_node(
                "TimePoint",
                {"label": label},
                {"year": year, "month": month, "day": day},
            )
            return {"label": label}

        def parse_ymd(date_str: Any):
            if not isinstance(date_str, str):
                return None, None, None
            s = date_str.strip()
            # simple YYYY-MM-DD or YYYY/MM/DD
            for sep in ("-", "/"):
                parts = s.split(sep)
                if len(parts) == 3 and all(p.isdigit() for p in parts):
                    y, m, d = parts
                    try:
                        return int(y), int(m), int(d)
                    except ValueError:
                        return None, None, None
            # YYYY-MM or YYYY/MM
            for sep in ("-", "/"):
                parts = s.split(sep)
                if len(parts) == 2 and all(p.isdigit() for p in parts):
                    y, m = parts
                    try:
                        return int(y), int(m), None
                    except ValueError:
                        return None, None, None
            # YYYY
            if s.isdigit() and len(s) == 4:
                return int(s), None, None
            return None, None, None

        def best_timepoint(
            year=None, month=None, day=None, date_str: Any = None
        ):
            """
            Trả về (y,m,d) cụ thể nhất.
            Ưu tiên lấy từ date_str nếu parse được; sau đó dùng day/month/year rời.
            Không tự tạo thêm TimePoint chỉ-năm khi đã có YYYY-MM-DD.
            """
            py, pm, pd = parse_ymd(date_str)
            y = py if py is not None else year
            m = pm if pm is not None else month
            d = pd if pd is not None else day
            if y is None:
                return None, None, None
            # normalize: nếu có day mà thiếu month thì bỏ day (không hợp lệ)
            if d is not None and m is None:
                d = None
            return y, m, d

        # BORN_AT / DIED_AT from person_properties if available (single most-specific node)
        if person_properties:
            birth_year = person_properties.get("birth_year")
            birth_month = person_properties.get("birth_month")
            birth_day = person_properties.get("birth_day")
            death_year = person_properties.get("death_year")
            death_month = person_properties.get("death_month")
            death_day = person_properties.get("death_day")

            by, bm, bd = best_timepoint(
                birth_year, birth_month, birth_day, person_properties.get("birth_date")
            )
            born_tp = create_timepoint(by, bm, bd)
            if born_tp:
                self.create_relationship(
                    "Person", person_name, "BORN_AT", "TimePoint", born_tp, {}
                )

            dy, dm, dd = best_timepoint(
                death_year, death_month, death_day, person_properties.get("death_date")
            )
            died_tp = create_timepoint(dy, dm, dd)
            if died_tp:
                self.create_relationship(
                    "Person", person_name, "DIED_AT", "TimePoint", died_tp, {}
                )

        # HAS_ROLE (from explicit roles list or person_properties.role)
        role_values: List[str] = []
        if roles:
            role_values.extend([r for r in roles if r])
        if person_properties and person_properties.get("role"):
            role_values.append(person_properties.get("role"))
        # de-dup while preserving order
        seen = set()
        role_values = [r for r in role_values if not (r in seen or seen.add(r))]

        for r in role_values:
            self.create_node("Role", r, {})
            self.create_relationship("Person", person_name, "HAS_ROLE", "Role", r, {})

        # BELONGS_TO_DYNASTY
        if dynasty:
            self.create_node("Dynasty", dynasty, {})
            self.create_relationship("Person", person_name, "BELONGS_TO_DYNASTY", "Dynasty", dynasty, {})
        
        # BORN_IN relationship
        if born_in:
            country_name = born_in.get("country")
            if country_name:
                self.create_node("Country", country_name, {
                    "code": born_in.get("code"),
                    "region": born_in.get("region")
                })
                self.create_relationship(
                    "Person", person_name,
                    "BORN_IN",
                    "Country", country_name,
                    {"year": born_in.get("year"), "city": born_in.get("city")}
                )
        
        # WORKED_IN relationships
        if worked_in:
            for work in worked_in:
                field_name = work.get("field")
                if field_name:
                    self.create_node("Field", field_name, {
                        "category": work.get("category"),
                        "description": work.get("description")
                    })
                    self.create_relationship(
                        "Person", person_name,
                        "WORKED_IN",
                        "Field", field_name,
                        {"years": work.get("years"), "role": work.get("role")}
                    )
        
        # ACTIVE_IN relationships
        if active_in:
            for era_info in active_in:
                era_name = era_info.get("era")
                if era_name:
                    self.create_node("Era", era_name, {
                        "start_year": era_info.get("start_year"),
                        "end_year": era_info.get("end_year"),
                        "description": era_info.get("description")
                    })
                    self.create_relationship(
                        "Person", person_name,
                        "ACTIVE_IN",
                        "Era", era_name,
                        {
                            "start_year": era_info.get("start_year"),
                            "end_year": era_info.get("end_year")
                        }
                    )
        
        # ACHIEVED relationships
        if achievements:
            for achievement_info in achievements:
                achievement_name = achievement_info.get("achievement")
                if achievement_name:
                    self.create_node("Achievement", achievement_name, {
                        "year": achievement_info.get("year"),
                        "description": achievement_info.get("description"),
                        "award": achievement_info.get("award")
                    })
                    self.create_relationship(
                        "Person", person_name,
                        "ACHIEVED",
                        "Achievement", achievement_name,
                        {
                            "year": achievement_info.get("year"),
                            "significance": achievement_info.get("significance")
                        }
                    )
        
        # INFLUENCED_BY relationships
        if influenced_by:
            for influence_info in influenced_by:
                influencer_name = influence_info.get("person")
                if influencer_name:
                    # Tạo influencer person nếu chưa có
                    self.create_node("Person", influencer_name, {})
                    self.create_relationship(
                        "Person", person_name,
                        "INFLUENCED_BY",
                        "Person", influencer_name,
                        {
                            "influence_type": influence_info.get("influence_type"),
                            "description": influence_info.get("description")
                        }
                    )
        
        # DESCRIBED_IN relationships
        if described_in:
            for chunk_info in described_in:
                chunk_id = chunk_info.get("chunk_id")
                if chunk_id:
                    # Tạo WikiChunk nếu chưa có
                    self.create_node("WikiChunk", {"chunk_id": chunk_id}, {
                        "content": chunk_info.get("content"),
                        "source": chunk_info.get("source"),
                        "page_title": chunk_info.get("page_title")
                    })
                    self.create_relationship(
                        "Person", person_name,
                        "DESCRIBED_IN",
                        "WikiChunk", {"chunk_id": chunk_id},
                        {"relevance_score": chunk_info.get("relevance_score", 1.0)}
                    )
        
        # FOUNDED relationships
        if companies_founded:
            for company_info in companies_founded:
                company_name = company_info.get("company")
                if company_name:
                    self.create_node("Company", company_name, {
                        "industry": company_info.get("industry"),
                        "founded_year": company_info.get("year")
                    })
                    self.create_relationship(
                        "Person", person_name,
                        "FOUNDED",
                        "Company", company_name,
                        {"year": company_info.get("year")}
                    )

        # CHILD_OF relationships (parents)
        if parents:
            for parent in parents:
                parent_name = parent.get("name")
                if parent_name:
                    # Tạo parent person nếu chưa có
                    self.create_node("Person", parent_name, {})
                    self.create_relationship(
                        "Person", person_name,
                        "CHILD_OF",
                        "Person", parent_name,
                        {"relation_type": parent.get("relation")}
                    )

        # PARTICIPATED_IN relationships (events)
        if events:
            for event in events:
                event_name = event.get("name")
                if event_name:
                    self.create_node("Event", event_name, {
                        "year": event.get("year"),
                        "description": event.get("description"),
                        "significance": event.get("significance"),
                    })
                    self.create_relationship(
                        "Person", person_name,
                        "PARTICIPATED_IN",
                        "Event", event_name,
                        {
                            "year": event.get("year"),
                            "role": person_properties.get("role") if person_properties else None,
                            "description": event.get("description"),
                            "significance": event.get("significance"),
                        }
                    )

                    # Event timepoint (HAPPENED_AT)
                    event_year = event.get("year")
                    event_month = event.get("month")
                    event_day = event.get("day")
                    tp = create_timepoint(event_year, event_month, event_day)
                    if tp:
                        self.create_relationship("Event", event_name, "HAPPENED_AT", "TimePoint", tp, {})