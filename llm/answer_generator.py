# llm/answer_generator.py
"""Answer generation from retrieved context."""
from typing import Dict, Any, Optional
from .llm_client import call_llm
from .prompt_templates import ANSWER_PROMPT, CONTEXT_SYNTHESIS_PROMPT


class AnswerGenerator:
    """Generate answers from retrieved graph context - sử dụng Ollama."""
    
    def __init__(self, model: Optional[str] = None):
        """
        Initialize answer generator.
        
        Args:
            model: Tên model Ollama (mặc định từ env OLLAMA_MODEL)
        """
        self.model = model
    
    def generate_answer(
        self, 
        question: str, 
        context: str, 
        use_synthesis: bool = True,
        temperature: Optional[float] = None
    ) -> str:
        """
        Generate answer from question and context.
        
        Args:
            question: User question
            context: Retrieved context from graph
            use_synthesis: Use advanced synthesis prompt
            temperature: Temperature cho LLM generation
        
        Returns:
            Generated answer
        """
        if not context:
            return "❌ Không tìm thấy dữ liệu liên quan."
        
        if use_synthesis:
            prompt = CONTEXT_SYNTHESIS_PROMPT.format(
                graph_context=context,
                question=question
            )
        else:
            prompt = ANSWER_PROMPT.format(
                context=context,
                question=question
            )
        
        try:
            answer = call_llm(prompt, model=self.model, temperature=temperature)
            return answer
        except Exception as e:
            return f"❌ Lỗi khi tạo câu trả lời: {str(e)}"

