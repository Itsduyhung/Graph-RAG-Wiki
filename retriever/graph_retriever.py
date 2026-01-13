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


