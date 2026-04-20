# retriever/hybrid_retriever.py
"""Hybrid retrieval combining graph and vector search."""
from typing import List, Dict, Any, Optional, Set
from sentence_transformers import SentenceTransformer
from .graph_retriever import GraphRetriever
from graph.storage import GraphDB


class HybridRetriever:
    """
    Hybrid retrieval combining:
    1. Graph-based retrieval (structured relationships)
    2. Vector-based retrieval (semantic similarity)
    """
    
    def __init__(self, graph_db: GraphDB = None):
        self.graph_db = graph_db or GraphDB()
        self.graph_retriever = GraphRetriever(self.graph_db)
        self._semantic_model: Optional[SentenceTransformer] = None
        self.vector_indexes = [
            "PersonVectorIndex",
            "NameVectorIndex", 
            "DynastyVectorIndex",
            "EventVectorIndex"
        ]
    
    def retrieve(
        self, 
        query: str, 
        keywords: List[str] = None,
        graph_weight: float = 0.7,
        vector_weight: float = 0.3
    ) -> List[Dict[str, Any]]:
        """
        Hybrid parallel retrieval: Fulltext (graph) + Semantic (vector) → merged candidates.
        
        Args:
            query: Full query for semantic
            keywords: Extracted keywords for fulltext (synonym-expanded)
            graph_weight: Fulltext weight
            vector_weight: Semantic weight
            
        Returns:
            Merged list of candidate nodes (deduped, scored, sorted)
        """
        print(f"  [Hybrid] Parallel: fulltext(graph_weight={graph_weight}) + semantic(vector_weight={vector_weight})")
        
        # Parallel: Fulltext Level1 + Semantic Level3
        graph_candidates = self._retrieve_from_graph(keywords or []) if keywords else []
        vector_candidates = self._retrieve_from_vector(query)
        
        print(f"  [Hybrid] Fulltext: {len(graph_candidates)} | Semantic: {len(vector_candidates)}")
        
        # Merge with weighted scores
        merged = self._combine_results(
            graph_candidates, 
            vector_candidates, 
            graph_weight, 
            vector_weight
        )
        
        print(f"  [Hybrid] Merged: {len(merged)} unique candidates")
        return merged
    
    def _retrieve_from_graph(self, keywords: List[str]) -> List[Dict[str, Any]]:
        """
        Fulltext/keyword search (Level 1) - simulate pipeline._fulltext_search logic.
        Keywords should be synonym-expanded.
        """
        if not keywords:
            return []
        
        # Simulate pipeline fulltext: CONTAINS search on name/value (no entity param for generality)
        with self.graph_db.driver.session(database=self.graph_db.database) as session:
            candidates = []
            search_terms = keywords[:3]  # Top 3 keywords
            
            for term in search_terms:
                # Exact first
                result = session.run("""
                    MATCH (n)
                    WHERE n.name = $term OR n.value = $term
                    RETURN elementId(n) as id, labels(n)[0] as type, n.name as name, n.value as value
                    LIMIT 5
                """, term=term)
                
                for r in result:
                    candidates.append({
                        "id": r["id"],
                        "type": r["type"],
                        "name": r["name"] or r["value"] or "N/A",
                        "score": 3.0,
                        "source": "fulltext_exact"
                    })
            
            # CONTAINS fallback
            ft_terms = ' '.join(keywords)
            result = session.run("""
                MATCH (n)
                WHERE toLower(n.name) CONTAINS toLower($ft) OR ANY(val IN n.value WHERE toLower(val) CONTAINS toLower($ft))
                RETURN elementId(n) as id, labels(n)[0] as type, n.name as name, n.value as value
                LIMIT 10
            """, ft=ft_terms)
            
            for r in result:
                candidates.append({
                    "id": r["id"],
                    "type": r["type"],
                    "name": r["name"] or r["value"] or "N/A",
                    "score": 1.5,
                    "source": "fulltext_contains"
                })
            
            return candidates[:15]
    
    def _retrieve_from_vector(self, query: str) -> List[Dict[str, Any]]:
        """Semantic vector search (Level 3) across all vector indexes."""
        if not query.strip():
            return []
        
        model = self._get_semantic_model()
        if not model:
            print("  [Vector] Model unavailable")
            return []
        
        try:
            query_embedding = model.encode(query).tolist()
            print(f"  [Vector] Query embedding: {len(query_embedding)} dims")
            
            with self.graph_db.driver.session(database=self.graph_db.database) as session:
                all_candidates = []
                
                for idx_name in self.vector_indexes:
                    try:
                        result = session.run(f"""
                            CALL db.index.vector.queryNodes("{idx_name}", 8, $embedding)
                            YIELD node, score
                            RETURN elementId(node) as id, labels(node)[0] as type, 
                                   node.name as name, node.value as value, score
                            ORDER BY score DESC
                        """, embedding=query_embedding)
                        
                        for r in result:
                            all_candidates.append({
                                "id": r["id"],
                                "type": r["type"],
                                "name": r["name"] or r["value"] or "N/A",
                                "score": float(r["score"]),  # Neo4j similarity (higher=better)
                                "source": f"semantic_{idx_name}"
                            })
                    except Exception as e:
                        print(f"  [Vector] Index {idx_name} error: {e}")
                        continue
                
                # Dedup within vector results, cap at 20
                seen_ids: Set[str] = set()
                unique = []
                for c in all_candidates:
                    if c["id"] not in seen_ids:
                        seen_ids.add(c["id"])
                        unique.append(c)
                        if len(unique) >= 20:
                            break
                
                print(f"  [Vector] {len(unique)} unique semantic candidates")
                return unique
                
        except Exception as e:
            print(f"  [Vector] Error: {e}")
            return []
    
    def _get_semantic_model(self) -> Optional[SentenceTransformer]:
        """Lazy load BAAI/bge-m3."""
        if self._semantic_model is None:
            try:
                self._semantic_model = SentenceTransformer("BAAI/bge-m3")
                print("  [Vector] Loaded bge-m3 model")
            except Exception as e:
                print(f"  [Vector] Failed to load model: {e}")
        return self._semantic_model
    
    def _combine_results(
        self, 
        graph_candidates: List[Dict[str, Any]],
        vector_candidates: List[Dict[str, Any]],
        graph_weight: float,
        vector_weight: float
    ) -> List[Dict[str, Any]]:
        """Merge fulltext + semantic with Reciprocal Rank Fusion (RRF)."""
        all_cands = []
        
# Normalize scores (0-1 range)
        def normalize_score(cands: List[Dict]) -> List[Dict]:
            if not cands:
                return []
            # Filter candidates with score and handle empty scores
            scored_cands = [c for c in cands if 'score' in c and c['score'] is not None]
            if not scored_cands:
                for c in cands:
                    c['norm_score'] = 0.0
                return cands
            scores = [c["score"] for c in scored_cands]
            min_s, max_s = min(scores), max(scores)
            if max_s == min_s:
                return scored_cands
            normalized = [{**c, "norm_score": (c["score"] - min_s) / (max_s - min_s)} 
                         for c in scored_cands]
            return normalized
        
        norm_graph = normalize_score(graph_candidates)
        norm_vector = normalize_score(vector_candidates)
        
        # Weighted scores
        for c in norm_graph:
            norm = c.get('norm_score', c['score'])
            c["final_score"] = norm * graph_weight
        for c in norm_vector:
            norm = c.get('norm_score', c['score'])
            c["final_score"] = norm * vector_weight
        
        # Dedup + aggregate (take max score per ID)
        score_map: Dict[str, Dict] = {}
        for c in norm_graph + norm_vector:
            cid = c["id"]
            if cid not in score_map or c["final_score"] > score_map[cid]["final_score"]:
                score_map[cid] = {**c, "sources": score_map.get(cid, {}).get("sources", []) + [c["source"]]}
        
        # Sort by final_score
        merged = sorted(score_map.values(), key=lambda x: x["final_score"], reverse=True)
        
        if merged:
            print(f"  [Merge] Top scores: {merged[0]['final_score']:.2f} ({merged[0]['source']}) | ... | {merged[-1]['final_score']:.2f}")
        else:
            print("  [Merge] No candidates found")
        return merged[:20]


