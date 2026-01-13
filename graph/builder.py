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
