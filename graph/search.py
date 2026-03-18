# graph/search.py
"""Hybrid search module combining keyword, semantic, and graph traversal."""

from typing import List, Dict, Any, Optional, Union
from dataclasses import dataclass, field
from enum import Enum
import json

# TODO: Install sentence-transformers for bge-m3
# pip install sentence-transformers
try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False

from graph.storage import GraphDB
from retriever.graph_retriever import GraphRetriever


class SearchType(Enum):
    KEYWORD = "keyword"
    SEMANTIC = "semantic"
    GRAPH = "graph"
    HYBRID = "hybrid"


@dataclass
class SearchResult:
    """Single search result."""
    content: str
    source: str  # keyword, semantic, graph
    score: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "content": self.content,
            "source": self.source,
            "score": self.score,
            "metadata": self.metadata
        }


@dataclass
class SearchConfig:
    """Configuration for hybrid search."""
    # Weights for combining results
    keyword_weight: float = 0.3
    semantic_weight: float = 0.3
    graph_weight: float = 0.4
    
    # Semantic search
    embedding_model: str = "BAAI/bge-m3"
    top_k: int = 5
    
    # Graph traversal
    graph_depth: int = 2
    include_neighbors: bool = True
    
    # Output
    return_raw_nodes: bool = False


class KeywordSearcher:
    """
    Keyword search using Neo4j full-text index.
    Optimized for exact matches on names (vua, triều đại, địa danh).
    """
    
    def __init__(self, graph_db: GraphDB = None):
        self.graph_db = graph_db or GraphDB()
    
    def search(
        self, 
        query: str, 
        node_types: Optional[List[str]] = None,
        limit: int = 10
    ) -> List[SearchResult]:
        """
        Search using full-text index.
        
        Args:
            query: Search query (supports fuzzy matching)
            node_types: Filter by node types (e.g., ["Person", "Dynasty"])
            limit: Max results
            
        Returns:
            List of search results
        """
        results = []
        
        # Use CALL db.index.fulltext.queryNodes for full-text search
        if node_types:
            for node_type in node_types:
                results.extend(self._search_node_type(query, node_type, limit))
        else:
            # Search all indexed nodes
            results.extend(self._search_all_nodes(query, limit))
        
        # Sort by score
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:limit]
    
    def _search_node_type(
        self, 
        query: str, 
        node_type: str, 
        limit: int
    ) -> List[SearchResult]:
        """Search within specific node type."""
        cypher = f"""
        CALL db.index.fulltext.queryNodes("{node_type}Index", $query, {limit})
        YIELD node, score
        RETURN labels(node)[0] AS node_type, properties(node) AS props, score
        """
        
        results = []
        with self.graph_db.driver.session(database=self.graph_db.database) as session:
            result = session.run(cypher, query=query)
            for record in result:
                node_type = record["node_type"]
                props = dict(record["props"])
                name = props.get("name", props.get("value", str(props)))
                
                content = self._format_node_content(node_type, props)
                
                results.append(SearchResult(
                    content=content,
                    source="keyword",
                    score=float(record["score"]),
                    metadata={
                        "node_type": node_type,
                        "properties": props,
                        "id": props.get("id", name)
                    }
                ))
        
        return results
    
    def _search_all_nodes(self, query: str, limit: int) -> List[SearchResult]:
        """Search across all indexed nodes."""
        # First get all node types with indexes
        cypher = """
        CALL db.indexes()
        YIELD name, labelsOrTypes, type
        WHERE type = "FULLTEXT"
        RETURN labelsOrTypes
        """
        
        all_results = []
        with self.graph_db.driver.session(database=self.graph_db.database) as session:
            result = session.run(cypher)
            indexes = [r["labelsOrTypes"][0] for r in result if r["labelsOrTypes"]]
            
            for idx in indexes:
                all_results.extend(self._search_node_type(query, idx, limit))
        
        return all_results
    
    def _format_node_content(self, node_type: str, props: Dict[str, Any]) -> str:
        """Format node properties into readable content."""
        name = props.get("name", props.get("value", "Unknown"))
        
        # Build content based on node type
        parts = [f"{node_type}: {name}"]
        
        # Add key properties
        for key in ["biography", "description", "role", "title", "birth_year", "death_year"]:
            if key in props:
                parts.append(f"{key}: {props[key]}")
        
        return "\n".join(parts)


class SemanticSearcher:
    """
    Semantic search using vector embeddings (bge-m3).
    """
    
    def __init__(
        self, 
        graph_db: GraphDB = None,
        embedding_model: str = "BAAI/bge-m3"
    ):
        self.graph_db = graph_db or GraphDB()
        self.embedding_model = embedding_model
        self._model = None
        self._embedding_dimension = None
    
    @property
    def model(self):
        """Lazy load embedding model."""
        if not SENTENCE_TRANSFORMERS_AVAILABLE:
            raise RuntimeError(
                "sentence-transformers not installed. "
                "Install with: pip install sentence-transformers"
            )
        
        if self._model is None:
            self._model = SentenceTransformer(self.embedding_model)
            # Get embedding dimension
            test_emb = self._model.encode("test")
            self._embedding_dimension = len(test_emb)
        
        return self._model
    
    def search(
        self, 
        query: str, 
        node_types: Optional[List[str]] = None,
        top_k: int = 5
    ) -> List[SearchResult]:
        """
        Search using semantic similarity.
        
        Args:
            query: Search query
            node_types: Filter by node types
            top_k: Number of results
            
        Returns:
            List of search results sorted by similarity
        """
        # Generate embedding for query
        query_embedding = self.model.encode(query).tolist()
        
        # Build Cypher for vector search
        if node_types:
            # Search within specific node types
            results = []
            for node_type in node_types:
                results.extend(self._vector_search(
                    query_embedding, node_type, top_k
                ))
        else:
            # Search all nodes with embeddings
            results = self._vector_search_all(query_embedding, top_k)
        
        return results
    
    def _vector_search(
        self, 
        embedding: List[float], 
        node_type: str,
        top_k: int
    ) -> List[SearchResult]:
        """Vector search on specific node type."""
        cypher = f"""
        CALL db.index.vector.queryNodes("{node_type}VectorIndex", {top_k}, $embedding)
        YIELD node, score
        RETURN labels(node)[0] AS node_type, properties(node) AS props, score
        """
        
        results = []
        with self.graph_db.driver.session(database=self.graph_db.database) as session:
            result = session.run(cypher, embedding=embedding)
            for record in result:
                node_type = record["node_type"]
                props = dict(record["props"])
                name = props.get("name", props.get("value", str(props)))
                
                content = self._format_node_content(node_type, props)
                
                results.append(SearchResult(
                    content=content,
                    source="semantic",
                    score=float(record["score"]),
                    metadata={
                        "node_type": node_type,
                        "properties": props,
                        "embedding_used": True
                    }
                ))
        
        return results
    
    def _vector_search_all(
        self, 
        embedding: List[float], 
        top_k: int
    ) -> List[SearchResult]:
        """Vector search across all vector indexes."""
        # Get all vector indexes
        cypher = """
        SHOW VECTOR INDEXES
        """
        
        all_results = []
        with self.graph_db.driver.session(database=self.graph_db.database) as session:
            result = session.run(cypher)
            indexes = list(result)
            
            for idx in indexes:
                idx_name = idx.get("name", "")
                # Extract node type from index name (assumes format: NodeTypeVectorIndex)
                node_type = idx_name.replace("VectorIndex", "")
                all_results.extend(self._vector_search(embedding, node_type, top_k))
        
        # Sort by score and return top_k
        all_results.sort(key=lambda x: x.score, reverse=True)
        return all_results[:top_k]
    
    def _format_node_content(self, node_type: str, props: Dict[str, Any]) -> str:
        """Format node for display."""
        name = props.get("name", props.get("value", "Unknown"))
        parts = [f"{node_type}: {name}"]
        
        for key in ["biography", "description", "role", "birth_year", "death_year"]:
            if key in props:
                parts.append(f"{key}: {props[key]}")
        
        return "\n".join(parts)
    
    def get_embedding_dimension(self) -> int:
        """Get embedding dimension for vector index creation."""
        if self._embedding_dimension is None:
            _ = self.model  # Trigger lazy load
        return self._embedding_dimension


class GraphSearcher:
    """
    Graph traversal search using relationships.
    Wraps and extends GraphRetriever functionality.
    """
    
    def __init__(self, graph_db: GraphDB = None):
        self.graph_db = graph_db or GraphDB()
        self.retriever = GraphRetriever(graph_db)
    
    def search(
        self, 
        query: str,
        entity_name: Optional[str] = None,
        entity_type: str = "Person",
        relationship_types: Optional[List[str]] = None,
        depth: int = 2
    ) -> List[SearchResult]:
        """
        Search using graph traversal.
        
        Args:
            query: Original user query (for context)
            entity_name: Specific entity to search around
            entity_type: Type of entity (Person, Dynasty, Event, etc.)
            relationship_types: Specific relationships to follow
            depth: Traversal depth
            
        Returns:
            List of search results from graph
        """
        results = []
        
        if entity_name:
            # Search around specific entity
            results.extend(self._search_entity(
                entity_name, entity_type, relationship_types, depth
            ))
        else:
            # Extract entity from query (simple keyword extraction)
            # In production, use NER or LLM for this
            results.extend(self._search_by_query_text(query, depth))
        
        return results
    
    def _search_entity(
        self,
        entity_name: str,
        entity_type: str,
        relationship_types: Optional[List[str]],
        depth: int
    ) -> List[SearchResult]:
        """Search around specific entity."""
        results = []
        
        # Get full profile for Person entities
        if entity_type == "Person":
            profile = self.retriever.retrieve_person_full_profile(entity_name)
            
            if profile.get("found"):
                content = profile.get("context", "")
                results.append(SearchResult(
                    content=content,
                    source="graph",
                    score=1.0,
                    metadata={
                        "entity_type": entity_type,
                        "entity_name": entity_name,
                        "relationships": profile
                    }
                ))
            else:
                # Try fallback search
                fallback = self.retriever.search_person_by_text(entity_name)
                if fallback.get("persons"):
                    results.append(SearchResult(
                        content=fallback.get("context", ""),
                        source="graph",
                        score=0.8,
                        metadata={
                            "entity_type": entity_type,
                            "entity_name": entity_name,
                            "method": "fallback"
                        }
                    ))
        
        else:
            # Generic graph traversal for other types
            subgraph = self._get_subgraph(entity_name, entity_type, depth)
            
            results.append(SearchResult(
                content=self._format_subgraph(entity_name, entity_type, subgraph),
                source="graph",
                score=1.0,
                metadata={
                    "entity_type": entity_type,
                    "entity_name": entity_name,
                    "subgraph": subgraph
                }
            ))
        
        return results
    
    def _search_by_query_text(self, query: str, depth: int) -> List[SearchResult]:
        """Search using query text (fallback)."""
        results = []
        
        # Try to find person by name
        person_result = self.retriever.find_person_by_name(query)
        
        if person_result.get("person"):
            person = person_result["person"]
            name = person.get("name", query)
            profile = self.retriever.retrieve_person_full_profile(name)
            
            if profile.get("found"):
                results.append(SearchResult(
                    content=profile.get("context", ""),
                    source="graph",
                    score=0.9,
                    metadata={
                        "entity_type": "Person",
                        "entity_name": name,
                        "via": person_result.get("via")
                    }
                ))
        
        return results
    
    def _get_subgraph(
        self, 
        entity_name: str, 
        entity_type: str, 
        depth: int
    ) -> Dict[str, Any]:
        """Get subgraph around entity."""
        cypher = f"""
        MATCH (start:{entity_type} {{name: $name}})
        CALL apoc.path.subgraphAll(start, {{
            maxLevel: {depth}
        }})
        YIELD nodes, relationships
        RETURN nodes, relationships
        """
        
        with self.graph_db.driver.session(database=self.graph_db.database) as session:
            result = session.run(cypher, name=entity_name)
            record = result.single()
            
            if record:
                return {
                    "nodes": [dict(n) for n in record["nodes"]],
                    "relationships": [dict(r) for r in record["relationships"]]
                }
        
        return {"nodes": [], "relationships": []}
    
    def _format_subgraph(
        self, 
        entity_name: str, 
        entity_type: str, 
        subgraph: Dict[str, Any]
    ) -> str:
        """Format subgraph into readable content."""
        lines = [f"{entity_type}: {entity_name}"]
        
        nodes_by_label = {}
        for node in subgraph.get("nodes", []):
            label = node.get("labels", ["Unknown"])[0]
            if label not in nodes_by_label:
                nodes_by_label[label] = []
            nodes_by_label[label].append(node)
        
        for label, nodes in nodes_by_label.items():
            if label == entity_type:
                continue
            names = [n.get("name", str(n)) for n in nodes[:5]]
            lines.append(f"  {label}: {', '.join(names)}")
        
        return "\n".join(lines)


class HybridSearch:
    """
    Hybrid search combining keyword, semantic, and graph search.
    
    This is the main entry point for retrieval.
    """
    
    def __init__(
        self,
        config: SearchConfig = None,
        graph_db: GraphDB = None
    ):
        self.config = config or SearchConfig()
        self.graph_db = graph_db or GraphDB()
        
        # Initialize individual searchers
        self.keyword_searcher = KeywordSearcher(self.graph_db)
        self.semantic_searcher = SemanticSearcher(
            self.graph_db,
            embedding_model=self.config.embedding_model
        )
        self.graph_searcher = GraphSearcher(self.graph_db)
    
    def search(
        self,
        query: str,
        entity_name: Optional[str] = None,
        entity_type: str = "Person",
        search_types: Optional[List[SearchType]] = None,
        node_types: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Main search method combining all search methods.
        
        Args:
            query: User query
            entity_name: Specific entity to search (optional)
            entity_type: Type of entity to search
            search_types: Which search methods to use (default: all)
            node_types: Filter by node types
            
        Returns:
            Dictionary with results from each search type and combined output
        """
        if search_types is None:
            search_types = [
                SearchType.KEYWORD,
                SearchType.SEMANTIC,
                SearchType.GRAPH
            ]
        
        results = {
            "query": query,
            "keyword_results": [],
            "semantic_results": [],
            "graph_results": [],
            "combined_context": ""
        }
        
        # Keyword search
        if SearchType.KEYWORD in search_types:
            results["keyword_results"] = self.keyword_searcher.search(
                query, node_types, self.config.top_k
            )
        
        # Semantic search
        if SearchType.SEMANTIC in search_types:
            try:
                results["semantic_results"] = self.semantic_searcher.search(
                    query, node_types, self.config.top_k
                )
            except RuntimeError as e:
                # Vector index might not exist yet
                results["semantic_results"] = []
                results["semantic_error"] = str(e)
        
        # Graph search
        if SearchType.GRAPH in search_types:
            results["graph_results"] = self.graph_searcher.search(
                query, entity_name, entity_type, depth=self.config.graph_depth
            )
        
        # Combine results
        results["combined_context"] = self._combine_context(
            results["keyword_results"],
            results["semantic_results"],
            results["graph_results"]
        )
        
        # Build scored results for ranking
        results["scored_results"] = self._score_and_rank(
            results["keyword_results"],
            results["semantic_results"],
            results["graph_results"]
        )
        
        return results
    
    def _combine_context(
        self,
        keyword_results: List[SearchResult],
        semantic_results: List[SearchResult],
        graph_results: List[SearchResult]
    ) -> str:
        """Combine contexts from all sources."""
        sections = []
        
        if graph_results:
            sections.append("=== GRAPH RESULTS ===")
            for r in graph_results:
                sections.append(r.content)
            sections.append("")
        
        if keyword_results:
            sections.append("=== KEYWORD RESULTS ===")
            for r in keyword_results:
                sections.append(r.content)
            sections.append("")
        
        if semantic_results:
            sections.append("=== SEMANTIC RESULTS ===")
            for r in semantic_results:
                sections.append(r.content)
        
        return "\n".join(sections)
    
    def _score_and_rank(
        self,
        keyword_results: List[SearchResult],
        semantic_results: List[SearchResult],
        graph_results: List[SearchResult]
    ) -> List[Dict[str, Any]]:
        """Score and rank results from all sources."""
        scored = []
        
        # Add weights to scores
        for r in keyword_results:
            scored.append({
                "content": r.content,
                "source": r.source,
                "weighted_score": r.score * self.config.keyword_weight,
                "metadata": r.metadata
            })
        
        for r in semantic_results:
            scored.append({
                "content": r.content,
                "source": r.source,
                "weighted_score": r.score * self.config.semantic_weight,
                "metadata": r.metadata
            })
        
        for r in graph_results:
            scored.append({
                "content": r.content,
                "source": r.source,
                "weighted_score": r.score * self.config.graph_weight,
                "metadata": r.metadata
            })
        
        # Sort by weighted score
        scored.sort(key=lambda x: x["weighted_score"], reverse=True)
        
        return scored[:self.config.top_k * 3]
    
    def search_by_intent(
        self,
        query: str,
        intent: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Search with parsed intent from LLM.
        
        Args:
            query: Original query
            intent: Parsed intent from LLM containing:
                - entity_name: Specific entity
                - entity_type: Type (Person, Dynasty, etc.)
                - search_types: List of search methods to use
                - filters: Node type filters
                
        Returns:
            Search results
        """
        entity_name = intent.get("entity_name")
        entity_type = intent.get("entity_type", "Person")
        filters = intent.get("filters", {}).get("node_types")
        
        # Parse search types
        search_types = []
        for st in intent.get("search_types", ["keyword", "semantic", "graph"]):
            try:
                search_types.append(SearchType(st))
            except ValueError:
                pass
        
        return self.search(
            query=query,
            entity_name=entity_name,
            entity_type=entity_type,
            search_types=search_types,
            node_types=filters
        )


# ============================================================================
# Dynamic Schema Mapper for LLM
# ============================================================================

class DynamicSchemaMapper:
    """
    Generates dynamic schema for LLM to create/query nodes flexibly.
    Uses JSON output + light validation.
    """
    
    def __init__(self, graph_db: GraphDB = None):
        self.graph_db = graph_db or GraphDB()
    
    def get_dynamic_schema(self) -> Dict[str, Any]:
        """
        Get dynamic schema showing all node types and their properties.
        LLM can use this to generate flexible node structures.
        """
        cypher = """
        MATCH (n)
        RETURN labels(n)[0] AS node_type, keys(n) AS properties
        LIMIT 100
        """
        
        schema = {}
        with self.graph_db.driver.session(database=self.graph_db.database) as session:
            result = session.run(cypher)
            
            for record in result:
                node_type = record["node_type"]
                properties = record["properties"]
                
                if node_type not in schema:
                    schema[node_type] = set()
                
                schema[node_type].update(properties)
        
        # Convert to dict with sample values
        schema_dict = {}
        for node_type, props in schema.items():
            schema_dict[node_type] = {
                "common_properties": list(props),
                "description": self._get_node_description(node_type)
            }
        
        return schema_dict
    
    def get_relationship_types(self) -> List[Dict[str, Any]]:
        """Get all relationship types in the graph."""
        cypher = """
        MATCH ()-[r]->()
        RETURN type(r) AS rel_type, count(*) AS count
        ORDER BY count DESC
        """
        
        relationships = []
        with self.graph_db.driver.session(database=self.graph_db.database) as session:
            result = session.run(cypher)
            
            for record in result:
                relationships.append({
                    "type": record["rel_type"],
                    "count": record["count"]
                })
        
        return relationships
    
    def generate_creation_schema(self) -> str:
        """
        Generate schema for LLM to create new nodes/relationships.
        Returns JSON schema format.
        """
        schema = self.get_dynamic_schema()
        relationships = self.get_relationship_types()
        
        return json.dumps({
            "node_types": schema,
            "relationship_types": relationships,
            "creation_template": {
                "nodes": {
                    "description": "Create any node with flexible properties",
                    "example": {
                        "name": "Node Name",
                        "property1": "value1",
                        "property2": 123
                    }
                },
                "relationships": {
                    "description": "Create relationship between nodes",
                    "example": {
                        "from": {"node_type": "Person", "name": "Lý Công Uẩn"},
                        "to": {"node_type": "Dynasty", "name": "Nhà Lý"},
                        "type": "BELONGS_TO_DYNASTY",
                        "properties": {"year": 1009}
                    }
                }
            }
        }, indent=2, ensure_ascii=False)
    
    def _get_node_description(self, node_type: str) -> str:
        """Get description for node type."""
        descriptions = {
            "Person": "Người (vua, danh nhân, quan lại)",
            "Dynasty": "Triều đại",
            "Event": "Sự kiện lịch sử",
            "Country": "Quốc gia/vùng lãnh thổ",
            "Field": "Lĩnh vực hoạt động",
            "Era": "Thời kỳ",
            "Achievement": "Thành tựu",
            "TimePoint": "Thời điểm (năm, ngày)",
            "WikiChunk": "Nội dung từ Wikipedia",
            "Company": "Công ty",
            "Role": "Vai trò",
            "Name": "Tên gọi khác/biệt danh"
        }
        
        return descriptions.get(node_type, f"Node type: {node_type}")


# ============================================================================
# Light Validation for LLM Output
# ============================================================================

class NodeValidator:
    """
    Light validation for LLM-generated nodes.
    Ensures basic structure without strict schema.
    """
    
    @staticmethod
    def validate_node(node: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate and clean node from LLM.
        
        Args:
            node: Node dict from LLM
            
        Returns:
            Validated node
        """
        validated = {}
        
        # Required: name or value
        validated["name"] = node.get("name") or node.get("value")
        
        # Copy other properties
        for key, value in node.items():
            if key not in ["name", "value"]:
                validated[key] = value
        
        # Ensure at least one identifier
        if not validated.get("name"):
            raise ValueError("Node must have 'name' or 'value' property")
        
        return validated
    
    @staticmethod
    def validate_relationship(rel: Dict[str, Any]) -> Dict[str, Any]:
        """Validate relationship from LLM."""
        validated = {
            "from": rel.get("from"),
            "to": rel.get("to"),
            "type": rel.get("type") or rel.get("relationship_type")
        }
        
        if not all([validated["from"], validated["to"], validated["type"]]):
            raise ValueError(
                "Relationship must have 'from', 'to', and 'type'"
            )
        
        # Copy properties
        for key in ["properties", "year", "description"]:
            if key in rel:
                validated[key] = rel[key]
        
        return validated
    
    @staticmethod
    def validate_and_clean_response(
        response: Union[Dict[str, Any], str]
    ) -> Dict[str, Any]:
        """
        Validate LLM response, trying to parse JSON if needed.
        
        Args:
            response: LLM response (dict or JSON string)
            
        Returns:
            Cleaned dict
        """
        # Try to parse if string
        if isinstance(response, str):
            try:
                response = json.loads(response)
            except json.JSONDecodeError:
                # Try to extract JSON from markdown
                import re
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    response = json.loads(json_match.group())
                else:
                    return {"error": "Could not parse JSON"}
        
        # Validate structure
        validated = {
            "nodes": [],
            "relationships": []
        }
        
        # Validate nodes
        for node in response.get("nodes", []):
            try:
                validated["nodes"].append(NodeValidator.validate_node(node))
            except ValueError as e:
                continue
        
        # Validate relationships
        for rel in response.get("relationships", []):
            try:
                validated["relationships"].append(
                    NodeValidator.validate_relationship(rel)
                )
            except ValueError:
                continue
        
        return validated


# ============================================================================
# Utility Functions
# ============================================================================

def create_vector_index(
    graph_db: GraphDB,
    node_type: str,
    property_name: str = "embedding",
    embedding_dimension: int = 1024  # bge-m3 dimension
):
    """
    Create vector index for a node type.
    
    Args:
        graph_db: GraphDB instance
        node_type: Node type to index (e.g., "Person")
        property_name: Property containing embeddings
        embedding_dimension: Dimension of embeddings
    """
    cypher = f"""
    CREATE VECTOR INDEX {node_type}VectorIndex
    FOR (n:{node_type})
    ON n.{property_name}
    OPTIONS {{indexConfig: {{`vector.dimensions`: {embedding_dimension}, `vector.similarity_function`: 'cosine'}}}}
    """
    
    with graph_db.driver.session(database=graph_db.database) as session:
        session.run(cypher)
    
    print(f"Created vector index for {node_type}")


def create_fulltext_index(
    graph_db: GraphDB,
    node_type: str,
    property_names: List[str] = None
):
    """
    Create full-text index for a node type.
    
    Args:
        graph_db: GraphDB instance
        node_type: Node type to index
        property_names: Properties to index (default: ["name", "value"])
    """
    if property_names is None:
        property_names = ["name", "value"]
    
    props = ", ".join(f"n.{p}" for p in property_names)
    
    cypher = f"""
    CREATE FULLTEXT INDEX {node_type}Index
    FOR (n:{node_type})
    ON EACH ([{props}])
    """
    
    with graph_db.driver.session(database=graph_db.database) as session:
        session.run(cypher)
    
    print(f"Created full-text index for {node_type}")


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    # Example usage
    config = SearchConfig(
        keyword_weight=0.3,
        semantic_weight=0.3,
        graph_weight=0.4,
        embedding_model="BAAI/bge-m3",
        top_k=5
    )
    
    searcher = HybridSearch(config)
    
    # Example search
    results = searcher.search(
        query="Lý Công Uẩn",
        entity_name="Lý Công Uẩn",
        entity_type="Person"
    )
    
    print("Search Results:")
    print(results["combined_context"])
