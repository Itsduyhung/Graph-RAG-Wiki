# llm/answer_generator.py
"""Answer generation from retrieved context."""
from typing import Dict, Any, Optional
from .llm_client import call_llm
from .prompt_templates import ANSWER_PROMPT, CONTEXT_SYNTHESIS_PROMPT


# Prompt gộp - vừa trích xuất intent vừa trả lời
COMBINED_PROMPT = """=== TRÍ TRỢ LÝ GRAPH RAG - TRẢ LỜI BẰNG TIẾNG VIỆT 100% ===

Câu hỏi từ người dùng: {question}

Dữ liệu từ Knowledge Graph:
{context}

=== RELATIONSHIP MAPPING (Dịch sang tiếng Việt) ===
Khi thấy các từ này → dịch sang tiếng Việt:
- LED, PARTICIPATED_IN → "lãnh đạo", "tham gia"
- CHILD_OF → "con của"
- FATHER_OF → "cha của", MOTHER_OF → "mẹ của"
- SPOUSE_OF → "vợ/chồng của"
- FOUNDED → "sáng lập"
- WORKS_AT → "làm việc tại"
- BORN_IN/BORN_AT → "sinh tại", "sinh năm"
- CARED_BY → "được nuôi dạy bởi"
- SUCCESSOR_OF → "kế nhiệm"

=== QUY TẮC LỚN - ĐỌC VÀ TUÂN THỦ CHẶT CHẼ ===

🔴 RULE 1: TRẢ LỜI BẰNG TIẾNG VIỆT - KHÔNG CÓ TIẾNG ANH NGOÀI TỀN RIÊNG
- TẤT CẢ từ, cụm từ, giải thích phải hoàn toàn bằng tiếng Việt
- CẤM dùng: "LED", "PARTICIPATED_IN", "CHILD_OF", "FATHER_OF", "SPOUSE_OF", relationship names, field names...
- CẤM dùng ngoại lệ: chỉ dùng tiếng Anh cho tên riêng nếu bắt buộc (vd: Pháp, Việt Nam)

🔴 RULE 2: KHÔNG BỘCH LỘ CẤPDETAIL GRAPH CONSTRUCTION
- KHÔNG nói "relationship", "PARTICIPATED_IN", "LED", "properties", "node types"
- KHÔNG nói relationships bằng tiếng Anh - dịch sang tiếng Việt tự nhiên
- VÍ DỤ relationship dùng từ tự nhiên:
  * CHILD_OF → "là con của"
  * FATHER_OF → "là cha của"
  * SPOUSE_OF → "là vợ/chồng của"
  * PARTICIPATED_IN → "tham gia" / "nắm giữ" / "lãnh đạo"
  * LED → "lãnh đạo" / "nắm quyền" / "chủ trì"
  * FOUNDED → "sáng lập" / "xây dựng"
  * WORKS_AT → "làm việc tại"

🔴 RULE 3: CHỈ DỰA VÀO CONTEXT - KHÔNG HALLUCINATION
- Những gì context không có thì TUYỆT ĐỐI KHÔNG PHÁT MINH
- KHÔNG dùng kiến thức ngoài context
- NẾU KHÔNG CÓ THÔNG TIN → trả lời: "Hiện tại mình chưa tìm thấy thông tin này trong dữ liệu."

🔴 RULE 4: ĐỌC ĐẦY ĐỦ CONTEXT
- Xem TẤT CẢ properties
- Xem TẤT CẢ related nodes
- Tổng hợp thành câu trả lời hoàn chỉnh

=== VÍ DỤ ĐỐI CHIẾU ===

✅ ĐÚNG:
- Context: "Bảo Đại PARTICIPATED_IN (LED) Quốc gia Việt Nam, birth_name: Nguyễn Phúc Vĩnh San"
- Câu hỏi: "Bảo Đại là ai?"
- Trả lời: "Bảo Đại (tên khai sinh: Nguyễn Phúc Vĩnh San) là hoàng đế lãnh đạo Quốc gia Việt Nam."

❌ SAI:
- Trả lời: "Bảo Đại LED Quốc gia Việt Nam"
- Trả lời: "Bảo Đại có PARTICIPATED_IN relationship với Quốc gia Việt Nam"
- Trả lời: "Bảo Đại is the founder of Việt Nam"

✅ ĐÚNG:
- Context: "Nguyễn Trãi PARTICIPATED_IN Khởi nghĩa Lam Sơn, MENTOR_OF Lê Lợi"
- Câu hỏi: "Nguyễn Trãi là ai?"
- Trả lời: "Nguyễn Trãi là người tham gia khởi nghĩa Lam Sơn với vai trò là cố vấn chính sách cho Lê Lợi."

❌ SAI:
- Trả lời: "Nguyễn Trãi PARTICIPATED_IN the Lam Son Uprising"
- Trả lời: "He was a MENTOR_OF Lê Lợi"

=== CÂU TRẢ LỜI ===
(trả lời hoàn toàn bằng tiếng Việt, rõ ràng, tự nhiên, dễ hiểu)"""


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

