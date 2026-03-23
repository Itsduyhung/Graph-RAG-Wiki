# llm/answer_generator.py
"""Answer generation from retrieved context."""
from typing import Dict, Any, Optional
from .llm_client import call_llm
from .prompt_templates import ANSWER_PROMPT, CONTEXT_SYNTHESIS_PROMPT


# Prompt gộp - vừa trích xuất intent vừa trả lời
COMBINED_PROMPT = """Dựa vào câu hỏi và context từ graph, trả lời bằng tiếng Việt.

Câu hỏi: {question}

Context từ graph:
{context}

Hướng dẫn:
- Đọc câu hỏi để hiểu người dùng muốn hỏi gì
- Tìm thông tin liên quan trong context
- Trả lời ngắn gọn, chính xác bằng tiếng Việt
- Nếu context không có thông tin cần thiết, trả lời: "Không có thông tin về vấn đề này."

Trả lời:"""


class AnswerGenerator:
    """Generate answers from retrieved graph context."""

    def __init__(self, model: Optional[str] = None):
        self.model = model

    def generate_answer(
        self,
        question: str,
        context: str,
        use_synthesis: bool = True,
        temperature: Optional[float] = None
    ) -> str:
        """
        Generate answer from question and context - combined approach.

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

        # Escape { and } to avoid format string errors
        escaped_context = context.replace("{", "{{").replace("}", "}}")
        escaped_question = question.replace("{", "{{").replace("}", "}}")

        # Use combined prompt - directly answer without separate intent extraction
        prompt = COMBINED_PROMPT.format(
            context=escaped_context,
            question=escaped_question
        )

        try:
            # Dùng flash-lite cho answer generation cho nhanh
            answer = call_llm(prompt, model="gemini-2.5-flash-lite", temperature=temperature or 0.7)
            return answer
        except Exception as e:
            return f"❌ Lỗi khi tạo câu trả lời: {str(e)}"

    def generate_answer_with_intent(
        self,
        question: str,
        context: str,
        intent: Dict[str, Any] = None,
        temperature: Optional[float] = None
    ) -> str:
        """
        Generate answer with pre-extracted intent (for optimization).

        Args:
            question: User question
            context: Retrieved context from graph
            intent: Pre-extracted intent (optional)
            temperature: Temperature cho LLM generation

        Returns:
            Generated answer
        """
        return self.generate_answer(question, context, temperature=temperature)

