# pipeline/query_pipeline.py
"""Query pipeline - LLM-driven retrieval (không cần embeddings)."""
import json
import re
from typing import Dict, Any, Optional
from graph.storage import GraphDB
from llm.answer_generator import AnswerGenerator
from llm.llm_client import call_llm


class QueryPipeline:
    """Query pipeline - LLM phân tích câu hỏi → Cypher query → LLM trả lời."""

    # Cache schema để không query mỗi lần
    _schema_cache: Optional[str] = None

    def __init__(self, graph_db: GraphDB = None, model: str = None):
        self.graph_db = graph_db or GraphDB()
        self.model = model
        self.answer_generator = AnswerGenerator(model=model)

    def process_query(self, question: str) -> str:
        """Process query - Luôn dùng LLM để generate answer."""
        
        # THỰC HIỆN 1: Direct search trước (nhanh nhất)
        context = self._direct_search(question)
        
        if not context:
            # THỰC HIỆN 2: LLM-driven retrieval (chỉ khi direct fail)
            context = self._llm_driven_retrieval(question)

        if not context:
            return "❌ Không tìm thấy dữ liệu liên quan."

        # THỰC HIỆN 3: LLM generate answer (luôn dùng LLM)
        answer = self.answer_generator.generate_answer(
            question=question,
            context=context
        )

        return answer

    def _direct_search(self, question: str) -> str:
        """
        Direct search - Trích xuất tên từ câu hỏi và query trực tiếp.
        Nhanh nhất - không cần LLM call cho bước này.
        """
        # Trích xuất tên người từ câu hỏi ( Vietnamesepattern)
        # Pattern: "X là ai", "X sinh năm", "X kết thúc", etc.
        name_patterns = [
            r'([A-ZÀ-Ỵ][a-zà-ỵ\s]+)(?=\s+là\s+)',  # X là ai
            r'([A-ZÀ-Ỵ][a-zà-ỵ\s]+)(?=\s+sinh\s+)',  # X sinh năm
            r'([A-ZÀ-Ỵ][a-zà-ỵ\s]+)(?=\s+mất\s+)',  # X mất năm
            r'([A-ZÀ-Ỵ][a-zà-ỵ\s]+)(?=\s+chết\s+)',  # X chết năm
        ]
        
        name = None
        for pattern in name_patterns:
            match = re.search(pattern, question)
            if match:
                name = match.group(1).strip()
                break
        
        if not name:
            return ""
        
        # Query trực tiếp không cần LLM
        return self._search_by_type("Person", name)

    def _llm_driven_retrieval(self, question: str) -> str:
        """LLM phân tích câu hỏi → trích xuất keywords → query graph."""
        schema = self._get_graph_schema()

        prompt = f"""Phân tích câu hỏi và trích xuất TÊN chính xác của nhân vật/đối tượng.

Schema graph: {schema}

Câu hỏi: {question}

Trả về JSON (chỉ 1 keyword quan trọng nhất - tên nhân vật):
{{
    "keywords": ["tên nhân vật chính"],
    "node_types": ["Person"]
}}

Chỉ trả về JSON."""

        try:
            response = call_llm(prompt, model=self.model, temperature=0.1)
            match = re.search(r'\{.*\}', response, re.DOTALL)
            if match:
                plan = json.loads(match.group())
                return self._execute_cypher_query(plan)
        except Exception as e:
            print(f"❌ Lỗi: {e}")
        return ""

    def _get_graph_schema(self) -> str:
        """Lấy schema của graph - dùng cache."""
        if QueryPipeline._schema_cache:
            return QueryPipeline._schema_cache
            
        with self.graph_db.driver.session(database=self.graph_db.database) as session:
            result = session.run("""
                MATCH (n)
                RETURN labels(n)[0] as type, count(*) as count
                LIMIT 20
            """)
            types = [f"{r['type']}: {r['count']}" for r in result]
            
            result = session.run("""
                MATCH ()-[r]->()
                RETURN type(r) as rel_type
                LIMIT 20
            """)
            rels = [r["rel_type"] for r in result]
            
        QueryPipeline._schema_cache = "Nodes: " + ", ".join(types) + " | Relationships: " + ", ".join(rels)
        return QueryPipeline._schema_cache

    def _execute_cypher_query(self, plan: Dict) -> str:
        """Execute Cypher query dựa trên plan từ LLM."""
        keywords = plan.get("keywords", [])
        node_types = plan.get("node_types", ["Person"])
        
        contexts = []
        
        # Gộp tất cả keywords thành 1 query
        all_keywords = [kw for kw in keywords for nt in node_types]
        
        for kw in all_keywords:
            for nt in node_types:
                ctx = self._search_by_type(nt, kw)
                if ctx:
                    contexts.append(ctx)
        
        if not contexts:
            ctx = self._search_all(keywords)
            if ctx:
                contexts.append(ctx)
        
        return "\n\n".join(filter(None, contexts))

    def _search_by_type(self, node_type: str, key: str) -> str:
        """Tìm node theo type và key - lấy tất cả properties."""
        with self.graph_db.driver.session(database=self.graph_db.database) as session:
            result = session.run(f"""
                MATCH (n:{node_type})
                WHERE n.name CONTAINS $key OR n.value CONTAINS $key
                OPTIONAL MATCH (n)<-[r]-(p:Person)
                RETURN n.name as name, 
                       n.role as role,
                       n.birth_year as birth_year,
                       n.death_year as death_year,
                       n.description as description,
                       n.value as value,
                       collect(DISTINCT p.name) as related_persons,
                       collect(DISTINCT type(r)) as relationships
                LIMIT 5
            """, key=key)

            lines = []
            for r in result:
                name = r["name"]
                role = r["role"] or ""
                birth = r["birth_year"] or ""
                death = r["death_year"] or ""
                desc = r["description"] or ""
                value = r["value"] or ""
                persons = [p for p in r["related_persons"] if p]
                rels = [rel for rel in r["relationships"] if rel]
                
                parts = [f"[{node_type}] {name}"]
                
                if role:
                    parts.append(f"Vai trò: {role}")
                if value:
                    parts.append(f"Tên: {value}")
                if birth:
                    parts.append(f"Sinh: {birth}")
                if death:
                    parts.append(f"Mất: {death}")
                if desc:
                    parts.append(f"Mô tả: {desc}")
                if persons:
                    parts.append(f"Liên quan: {', '.join(persons[:3])}")
                if rels:
                    parts.append(f"Quan hệ: {', '.join(set(rels))}")
                    
                lines.append(" | ".join(parts))

            return "\n".join(lines)

    def _search_all(self, keywords: list) -> str:
        """Tìm tất cả nodes khớp với keywords."""
        with self.graph_db.driver.session(database=self.graph_db.database) as session:
            or_clause = " OR ".join([f"n.name CONTAINS '{kw}'" for kw in keywords])
            
            result = session.run(f"""
                MATCH (n)
                WHERE {or_clause}
                RETURN labels(n)[0] as type, n.name as name
                LIMIT 20
            """)

            lines = []
            for r in result:
                lines.append(f"[{r['type']}] {r['name']}")
            
            return "\n".join(lines)


def ask_agent(question: str) -> str:
    pipeline = QueryPipeline()
    return pipeline.process_query(question)