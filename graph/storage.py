# graph/storage.py
"""Neo4j storage implementation for Graph RAG."""
import os
from urllib.parse import urlparse, urlunparse
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()


class GraphDB:
    """Neo4j database connection and query handler."""
    
    def __init__(self):
        self.uri = os.getenv("NEO4J_URI") or "bolt://localhost:7687"
        self.user = os.getenv("NEO4J_USER")
        self.password = os.getenv("NEO4J_PASSWORD")
        self.database = os.getenv("NEO4J_DB") or os.getenv("NEO4J_DATABASE") or "neo4j"
        self.driver = self._create_driver(self.uri)

    _DRIVER_KWARGS = dict(
        max_connection_lifetime=120,   # recycle well before server's idle timeout
        max_connection_pool_size=20,
        connection_timeout=30,
        keep_alive=True,
        liveness_check_timeout=10,    # test pooled connections before use; drops defunct ones silently
    )

    def _create_driver(self, uri: str):
        normalized_uri = self._normalize_driver_uri(uri)
        driver = GraphDatabase.driver(
            normalized_uri,
            auth=(self.user, self.password),
            **self._DRIVER_KWARGS,
        )
        self.uri = normalized_uri

        try:
            driver.verify_connectivity()
            return driver
        except Exception:
            fallback_uri = self._get_direct_fallback_uri(normalized_uri)
            if fallback_uri and fallback_uri != normalized_uri:
                driver.close()
                fallback_driver = GraphDatabase.driver(
                    fallback_uri,
                    auth=(self.user, self.password),
                    **self._DRIVER_KWARGS,
                )
                fallback_driver.verify_connectivity()
                self.uri = fallback_uri
                return fallback_driver

            driver.close()
            raise

    @staticmethod
    def _normalize_driver_uri(uri: str) -> str:
        parsed = urlparse(uri)
        force_direct = os.getenv("GRAPH_RAG_NEO4J_FORCE_DIRECT", "true").strip().lower()
        if force_direct not in {"1", "true", "yes", "y", "on"}:
            return uri

        if parsed.scheme in {"neo4j", "neo4j+s", "neo4j+ssc"}:
            return GraphDB._get_direct_fallback_uri(uri)

        return uri

    @staticmethod
    def _get_direct_fallback_uri(uri: str) -> str:
        parsed = urlparse(uri)
        if parsed.scheme not in {"neo4j", "neo4j+s", "neo4j+ssc"}:
            return uri

        fallback_scheme = "bolt+s" if "+s" in parsed.scheme else "bolt"
        return urlunparse((
            fallback_scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        ))

    def run_query(self, query, parameters=None):
        """Run a Cypher query and return results."""
        with self.driver.session(database=self.database) as session:
            result = session.run(query, parameters or {})
            return [dict(r) for r in result]
    
    def close(self):
        """Close the database connection."""
        if self.driver:
            self.driver.close()


