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

    def get_founder(self, company_name):
        """Retrieve founder(s) of a company."""
        query = """
        MATCH (p:Person)-[:FOUNDED]->(c:Company)
        WHERE trim(toLower(c.name)) = trim(toLower($name))
        RETURN p.name AS founder
        """

        with self.driver.session(database=self.database) as session:
            result = session.run(query, name=company_name)
            return [r["founder"] for r in result]
    
    def close(self):
        """Close the database connection."""
        if self.driver:
            self.driver.close()


