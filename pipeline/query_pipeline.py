# pipeline/query_pipeline.py
"""Query processing pipeline for Graph RAG."""
from typing import Dict, Any, Optional
from graph.storage import GraphDB
from retriever.entity_extractor import EntityExtractor
from retriever.graph_retriever import GraphRetriever
from llm.answer_generator import AnswerGenerator


class QueryPipeline:
    """Main query processing pipeline - sử dụng Ollama và Neo4j."""
    
    def __init__(
        self, 
        graph_db: GraphDB = None,
        model: Optional[str] = None
    ):
        """
        Initialize query pipeline.
        
        Args:
            graph_db: Neo4j database connection (mặc định tự tạo)
            model: Tên model Ollama (mặc định từ env OLLAMA_MODEL)
        """
        self.graph_db = graph_db or GraphDB()
        self.model = model
        self.entity_extractor = EntityExtractor(model=model)
        self.graph_retriever = GraphRetriever(graph_db=self.graph_db)
        self.answer_generator = AnswerGenerator(model=model)
    
    def process_query(self, question: str) -> str:
        """
        Process a user question through the complete pipeline.
        
        Args:
            question: User question
            
        Returns:
            Generated answer
        """
        # 1. Intent extraction
        intent = self.entity_extractor.extract_intent(question)
        
        if not intent:
            return "❌ Không hiểu câu hỏi. Vui lòng thử lại."
        
        # 2. Graph retrieval based on intent
        context = self._retrieve_context(intent)
        
        # 2b. Fallback: nếu chưa có context, thử tìm Person theo văn bản câu hỏi
        if not context:
            fallback = self.graph_retriever.search_person_by_text(question)
            context = fallback.get("context", "")
        
        if not context:
            return "❌ Không tìm thấy dữ liệu liên quan."
        
        # 3. Answer generation
        answer = self.answer_generator.generate_answer(
            question=question,
            context=context
        )
        
        return answer
    
    def _retrieve_context(self, intent: Dict[str, Any]) -> str:
        """Retrieve context from graph based on intent."""
        intent_type = intent.get("intent", "").upper()
        person_name = intent.get("person", "")
        company_name = intent.get("company", "")
        relationship_type = intent.get("relationship_type", "")
        
        # Handle person-related queries
        if person_name:
            if intent_type == "FIND_PERSON_PROFILE":
                result = self.graph_retriever.retrieve_person_full_profile(person_name)
                return result.get("context", "")
            
            elif intent_type in ["FIND_BORN_IN", "FIND_WORKED_IN", "FIND_ACTIVE_IN", 
                                 "FIND_ACHIEVEMENTS", "FIND_INFLUENCERS"]:
                # Map intent to relationship type
                intent_to_rel = {
                    "FIND_BORN_IN": "BORN_IN",
                    "FIND_WORKED_IN": "WORKED_IN",
                    "FIND_ACTIVE_IN": "ACTIVE_IN",
                    "FIND_ACHIEVEMENTS": "ACHIEVED",
                    "FIND_INFLUENCERS": "INFLUENCED_BY"
                }
                rel_type = intent_to_rel.get(intent_type) or relationship_type
                if rel_type:
                    result = self.graph_retriever.retrieve_by_relationship_type(person_name, rel_type)
                    return result.get("context", "")
            
            elif intent_type == "FIND_COMPANY":
                result = self.graph_retriever.retrieve_by_person(person_name)
                return result.get("context", "")
            
            # Default: return full profile
            else:
                result = self.graph_retriever.retrieve_person_full_profile(person_name)
                return result.get("context", "")
        
        # Handle company-related queries
        if company_name and intent_type == "FIND_FOUNDER":
            result = self.graph_retriever.retrieve_by_company(company_name)
            return result.get("context", "")
        
        # Handle relationship-specific queries
        if relationship_type and person_name:
            result = self.graph_retriever.retrieve_by_relationship_type(person_name, relationship_type)
            return result.get("context", "")
        
        return ""


def ask_agent(question: str) -> str:
    """
    Convenience function for backward compatibility.
    
    Args:
        question: User question
        
    Returns:
        Generated answer
    """
    pipeline = QueryPipeline()
    return pipeline.process_query(question)

