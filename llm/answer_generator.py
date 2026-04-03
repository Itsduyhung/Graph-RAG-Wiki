# llm/answer_generator.py
"""Answer generation from retrieved context."""
from typing import Dict, Any, Optional
from .llm_client import call_llm
from .prompt_templates import ANSWER_PROMPT, CONTEXT_SYNTHESIS_PROMPT


# Prompt gộp - vừa trích xuất intent vừa trả lời
COMBINED_PROMPT = """Dựa vào câu hỏi và context từ graph, trả lời bằng TIẾNG VIỆT 100%.

Câu hỏi: {question}

Context từ graph:
{context}

=== QUY TẮC QUAN TRỌNG - ĐỌC KỸ ===
1. TRẢ LỜI BẰNG TIẾNG VIỆT 100% - KHÔNG dùng tiếng Anh trong câu trả lời
2. NẾU cần nhắc đến relationship (quan hệ) → CHỈ dùng khi câu hỏi hỏi về "quan hệ", "liên hệ", "mối quan hệ", "relationship"
   - Khi cần nói relationship: dùng tiếng Việt như "là con của", "là vua của", "tham gia", "sáng lập", "là tác giả của"
3. TUYỆT ĐỐI KHÔNG tự bịa thông tin (không hallucination)
4. Đọc TẤT CẢ properties và Related nodes để tìm thông tin
5. NẾU context không có thông tin → nói rõ: "Không có thông tin trong dữ liệu về vấn đề này."

Ví dụ:
- Câu hỏi: "Nguyễn Trãi có vai trò gì trong khởi nghĩa Lam Sơn?"
- Context có: Nguyễn Trãi tham gia khởi nghĩa Lam Sơn, soạn Bình Ngô đại cáo, là cố vấn của Lê Lợi
- → Trả lời: "Nguyễn Trãi tham gia khởi nghĩa Lam Sơn với vai trò là cố vấn quân sự và ngoại giao cho Lê Lợi. Ông là người soạn thảo 'Bình Ngô đại cáo' - bản tuyên ngôn độc lập nổi tiếng, cùng nhiều tác phẩm văn học và quân sự khác."
- → KHÔNG trả lời: "Nguyễn Trãi có PARTICIPATED_IN relationship với Lam Sơn"

- Câu hỏi: "Tên thật của Bảo Đại là gì?"
- Context có: birth_name: "Nguyễn Phúc Vĩnh San"
- → Trả lời: "Tên khai sinh của Bảo Đại là Nguyễn Phúc Vĩnh San."

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

