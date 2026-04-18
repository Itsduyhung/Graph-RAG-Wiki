# graph/storage.py
"""Neo4j storage implementation for Graph RAG."""
import os
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()


class GraphDB:
    """Neo4j database connection and query handler."""
    
    def __init__(self):
        self.driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI"),
            auth=(
                os.getenv("NEO4J_USER"),
                os.getenv("NEO4J_PASSWORD")
            )
        )
        self.database = os.getenv("NEO4J_DB")

    def run_query(self, query, parameters=None):
        """Run a Cypher query and return results."""
        with self.driver.session(database=self.database) as session:
            result = session.run(query, parameters or {})
            return [dict(r) for r in result]
    
    def close(self):
        """Close the database connection."""
        if self.driver:
            self.driver.close()


