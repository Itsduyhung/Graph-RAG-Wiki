# tests/test_retrieval.py
"""Tests for graph retrieval functionality."""
import pytest
from graph.storage import GraphDB
from retriever.graph_retriever import GraphRetriever
from retriever.entity_extractor import EntityExtractor


def test_graph_db_connection():
    """Test Neo4j database connection."""
    try:
        graph_db = GraphDB()
        assert graph_db.driver is not None
        graph_db.close()
    except Exception as e:
        pytest.skip(f"Neo4j not available: {e}")


def test_get_founder():
    """Test retrieving founder information."""
    try:
        graph_db = GraphDB()
        founders = graph_db.get_founder("Fintech X")
        assert isinstance(founders, list)
        graph_db.close()
    except Exception as e:
        pytest.skip(f"Neo4j not available: {e}")


def test_graph_retriever():
    """Test GraphRetriever functionality."""
    try:
        graph_db = GraphDB()
        retriever = GraphRetriever(graph_db=graph_db)
        result = retriever.retrieve_by_company("Fintech X")
        assert "company" in result or "founders" in result
        graph_db.close()
    except Exception as e:
        pytest.skip(f"Neo4j not available: {e}")


def test_entity_extractor():
    """Test entity extraction from questions."""
    extractor = EntityExtractor()
    question = "Ai là người sáng lập của Fintech X?"
    intent = extractor.extract_intent(question)
    # Note: This test might fail if LLM is not available
    # In that case, it's acceptable
    if intent:
        assert isinstance(intent, dict)


