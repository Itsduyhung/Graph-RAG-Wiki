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
        
        if intent_type == "FIND_FOUNDER":
            company_name = intent.get("company", "")
            if company_name:
                result = self.graph_retriever.retrieve_by_company(company_name)
                return result.get("context", "")
        
        # Handle other intent types
        elif intent_type == "FIND_COMPANY":
            person_name = intent.get("person", "")
            if person_name:
                result = self.graph_retriever.retrieve_by_person(person_name)
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

