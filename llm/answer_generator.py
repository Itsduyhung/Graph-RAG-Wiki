# llm/answer_generator.py
"""Answer generation from retrieved context."""
import os
import re
from typing import Dict, Any, Optional
from .llm_client import call_llm, call_llm_stream
from .prompt_templates import ANSWER_PROMPT, CONTEXT_SYNTHESIS_PROMPT


# Prompt gộp - vừa trích xuất intent vừa trả lời
COMBINED_PROMPT = """=== TRÍ TRỢ LÝ GRAPH RAG - TRẢ LỜI BẰNG TIẾNG VIỆT 100% ===

⚠️ CẢNH BÁO QUAN TRỌNG: 
Nếu context CHỨA dữ liệu → TRẢ LỜI TRỰC TIẾP, KHÔNG NÓI "KHÔNG CÓ THÔNG TIN"
Lỗi phổ biến: "Dữ liệu không có thông tin chi tiết về X. Tuy nhiên, có..." → ĐÂY LÀ LOGIC LẠ RỒI!
Nếu bạn vừa cung cấp thông tin, thì context CÓ rồi - hãy nói trực tiếp!

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
- NẾU CONTEXT TRỐNG → trả lời: "Hiện tại mình chưa tìm thấy thông tin này trong dữ liệu."
- NẾU CÓ CONTEXT → TRẢ LỜI TRỰC TIẾP từ context, KHÔNG bắt đầu bằng "Dựa trên dữ liệu, không có thông tin nào..."
  * Ví dụ SAI: "Dựa trên dữ liệu, không có thông tin về X. Tuy nhiên, có thông tin về Y..."
  * Ví dụ ĐÚNG: "Dựa trên dữ liệu, Y liên quan đến X như sau: [chi tiết]"

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

=== RULE 5: KHÔNG BẮT ĐẦU BẰNG "KHÔNG CÓ - TUY NHIÊN CÓ" ===
🚫 BAN CẬM HOÀN TOÀN - Không được dùng những câu mở này:
- "Dữ liệu không có thông tin chi tiết về X. Tuy nhiên, có thông tin về Y..."
- "Không tìm thấy X. Nhưng có Z..."
- "Dựa trên dữ liệu, không có thông tin. Tuy nhiên..."
- "Hiện chưa tìm thấy X. Nhưng..."

✅ CÁCH LÀM ĐÚNG:
1. Nếu context CHỨA THÔNG TIN → trả lời TRỰC TIẾP từ context đó (không cần nói "không có")
2. Nếu context HOÀN TOÀN TRỐNG → chỉ trả: "Hiện tại mình chưa tìm thấy thông tin này trong dữ liệu."
3. KHÔNG bao giờ khởi đầu bằng cách nói "không có" rồi sau đó cung cấp thông tin liên quan

VÍ DỤ MINH HỌA:
❌ SAI: "Không có info xuất thân chi tiết. Tuy nhiên, Đào Cam Mộc... Lê Đại Hành trọng dụng..."
✅ ĐÚNG: "Đào Cam Mộc là quan đại thần, có công lớn trong việc đưa Lý Công Uẩn lên ngôi hoàng đế. Lê Đại Hành, vua nhà Tiền Lê, cũng trọng dụng Lý Công Uẩn."

=== CÂU TRẢ LỜI ===
(trả lời hoàn toàn bằng tiếng Việt, rõ ràng, tự nhiên, dễ hiểu - BẮT ĐẦU NGAY TỪ NỘI DUNG CHÍNH, KHÔNG MỞ BẰNG "KHÔNG CÓ")

=== RULE 6: LUÔN THÊM ACTIVE PERSON VÀO CUỐI RESPONSE ===
✅ BẮCCBUỘC phải thêm active person ở cuối mỗi câu trả lời theo format:
   Active person: [entity_name]

🔴 QUY TẮC:
- Nếu câu hỏi có entity cụ thể (tên nhân vật, địa danh, sự kiện) → PHẢI thêm "Active person: [entity]" ở cuối
- Ví dụ:
  * Câu hỏi: "Hàm Nghi sinh năm nào?"
  * Response: "Hàm Nghi sinh năm 1871.\n\nActive person: Hàm Nghi"
  
  * Câu hỏi: "Tên thật của Bảo Đại?"
  * Response: "Tên thật của Bảo Đại là Nguyễn Phúc Vĩnh Thụy.\n\nActive person: Bảo Đại"

- Format chính xác: "\n\nActive person: [tên]" (hai dòng trống rồi mới viết)
- KHÔNG bao giờ quên thêm này!

=== RULE 7: CÂU HỎI NHIỀU Ý PHẢI TRẢ LỜI ĐỦ Ý ===
- Nếu câu hỏi chứa nhiều vế (ví dụ có "và", "đồng thời", "cũng như"), PHẢI trả lời lần lượt từng ý.
- Không được chỉ trả lời một ý rồi dừng.
- Nếu dữ liệu thiếu một ý, phải nói rõ ý nào thiếu dữ liệu thay vì bỏ qua.
- Ví dụ: "X sinh năm nào và quê ở đâu?" → phải có cả năm sinh và quê quán (hoặc ghi rõ thiếu quê quán)."""



def clean_markdown_format(text: str) -> str:
    """
    Clean markdown formatting từ response - LOẠI BỎ TẤT CẢ ASTERISK.
    - Loại bỏ **text** (bold markdown)
    - Loại bỏ *text* (italic markdown)
    - Loại bỏ * ở đầu dòng (bullet list)
    - Giữ lại \n để xuống dòng
    """
    # 1. Loại bỏ **text** (bold) → text
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    
    # 2. Loại bỏ *text* (italic) → text
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    
    # 3. Loại bỏ "* " ở đầu dòng → dòng mới
    # Pattern: "\n* " hoặc "\n*   " (nhiều khoảng trắng)
    text = re.sub(r'\n\s*\*\s+', '\n', text)
    
    # 4. Loại bỏ "* " ở đầu response (nếu có)
    if text.startswith('* '):
        text = text[2:].lstrip()
    
    # 5. Loại bỏ dấu * đơn lẻ còn sót lại
    text = text.replace('*', '')
    
    return text


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
            Generated answer (with cleaned formatting)
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
            # Use temperature from env (default 0.1) or parameter
            default_temp = float(os.getenv('LLM_TEMPERATURE', '0.1'))
            # Use timeout=30s for full context (verifying all search results)
            answer = call_llm(prompt, model="gemini-2.5-flash-lite", temperature=temperature or default_temp, timeout=30)
            # Clean markdown formatting from the answer
            return clean_markdown_format(answer)
        except Exception as e:
            return f"❌ Lỗi khi tạo câu trả lời: {str(e)}"

    def generate_answer_stream(
        self,
        question: str,
        context: str,
        temperature: Optional[float] = None,
        entity: Optional[str] = None
    ):
        """
        Generate answer with streaming - yields text chunks in real-time.

        Args:
            question: User question
            context: Retrieved context from graph
            temperature: Temperature cho LLM generation
            entity: Active entity/person to append at the end

        Yields:
            Text chunks as they arrive from the API (with cleaned formatting)
        """
        if not context:
            yield "❌ Không tìm thấy dữ liệu liên quan."
            return

        # Escape { and } to avoid format string errors
        escaped_context = context.replace("{", "{{").replace("}", "}}")
        escaped_question = question.replace("{", "{{").replace("}", "}}")

        # Use combined prompt - directly answer without separate intent extraction
        prompt = COMBINED_PROMPT.format(
            context=escaped_context,
            question=escaped_question
        )

        try:
            # Collect all chunks first
            full_answer = ""
            for chunk in call_llm_stream(prompt, model="gemini-2.5-flash-lite", temperature=temperature or 0.1):
                full_answer += chunk
            
            # Clean markdown formatting from the full answer
            cleaned_answer = clean_markdown_format(full_answer)
            
            # Yield the cleaned answer (could yield line by line or all at once)
            # Yield all at once to preserve exact formatting
            yield cleaned_answer
            
            # Append active person at the end if entity is provided and not already present
            if entity and "\n\nActive person:" not in cleaned_answer:
                yield f"\n\nActive person: {entity}"
        except Exception as e:
            yield f"\n❌ Lỗi khi tạo câu trả lời: {str(e)}"

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

