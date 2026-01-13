# graph/graph_utils.py
"""Utility functions for graph operations."""
from typing import List, Dict, Any
from .storage import GraphDB


def query_subgraph(graph_db: GraphDB, node_type: str, node_name: str, depth: int = 2) -> List[Dict]:
    """Extract subgraph around a specific node."""
    query = f"""
    MATCH path = (n:{node_type} {{name: $name}})-[*1..{depth}]-(connected)
    RETURN path, n, connected
    LIMIT 100
    """
    
    with graph_db.driver.session(database=graph_db.database) as session:
        result = session.run(query, name=node_name)
        return [dict(record) for record in result]


def get_node_degree(graph_db: GraphDB, node_type: str, node_name: str) -> int:
    """Get the degree (number of connections) of a node."""
    query = f"""
    MATCH (n:{node_type} {{name: $name}})-[r]-()
    RETURN count(r) AS degree
    """
    
    with graph_db.driver.session(database=graph_db.database) as session:
        result = session.run(query, name=node_name)
        record = result.single()
        return record["degree"] if record else 0


