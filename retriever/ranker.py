# retriever/ranker.py
"""Ranking and relevance scoring for retrieved results."""
from typing import List, Dict, Any
import math


class ResultRanker:
    """Rank and score retrieved results by relevance."""
    
    @staticmethod
    def rank_by_relevance(results: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
        """
        Rank results by relevance to query.
        
        Args:
            results: List of retrieved results
            query: Original query
            
        Returns:
            Ranked list of results
        """
        # Simple keyword-based ranking (can be enhanced with ML models)
        query_lower = query.lower()
        query_terms = set(query_lower.split())
        
        scored_results = []
        for result in results:
            score = ResultRanker._calculate_relevance_score(result, query_terms)
            result["relevance_score"] = score
            scored_results.append(result)
        
        # Sort by relevance score (descending)
        scored_results.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
        
        return scored_results
    
    @staticmethod
    def _calculate_relevance_score(result: Dict[str, Any], query_terms: set) -> float:
        """Calculate relevance score for a result."""
        score = 0.0
        
        # Check entity name
        for key in ["name", "company", "person"]:
            if key in result and result[key]:
                entity_name = str(result[key]).lower()
                entity_terms = set(entity_name.split())
                # Calculate Jaccard similarity
                intersection = len(query_terms & entity_terms)
                union = len(query_terms | entity_terms)
                if union > 0:
                    score += (intersection / union) * 0.5
        
        # Boost score if exact match
        result_text = str(result).lower()
        for term in query_terms:
            if term in result_text:
                score += 0.1
        
        return min(score, 1.0)  # Cap at 1.0
    
    @staticmethod
    def rank_by_importance(results: List[Dict[str, Any]], importance_metric: str = "degree") -> List[Dict[str, Any]]:
        """
        Rank results by graph importance metrics.
        
        Args:
            results: List of retrieved results
            importance_metric: Metric to use ('degree', 'centrality', etc.)
            
        Returns:
            Ranked list of results
        """
        # Placeholder for importance-based ranking
        # Can use graph metrics like node degree, centrality, etc.
        return sorted(results, key=lambda x: x.get(importance_metric, 0), reverse=True)


