"""Test query Bảo Đại - KHÔNG DÙNG SEMANTIC SEARCH."""
import sys
sys.path.insert(0, '.')

from pipeline.query_pipeline import QueryPipeline
from graph.storage import GraphDB

def test_bao_dai_no_semantic():
    """Test 2 câu hỏi - KHÔNG semantic search."""
    
    print("=" * 70)
    print("TESTING: Query Pipeline - KHÔNG SEMANTIC SEARCH")
    print("=" * 70)
    
    # Khởi tạo pipeline
    pipeline = QueryPipeline()
    
    questions = [
        "Tên thật của Bảo Đại?",
        "Bảo Đại tên thật là gì?"
    ]
    
    # Patch process_query để bỏ semantic search
    original_process = pipeline.process_query
    
    def process_without_semantic(question):
        """Process query không semantic."""
        from pipeline.query_pipeline import SEMANTIC_AVAILABLE
        
        # BƯỚC 0: Classify intent
        intent_info = pipeline._classify_intent(question)
        print(f"🔍 Intent: {intent_info}")

        # THỰC HIỆN 1: Intent-based search
        if intent_info.get("intent_type") and intent_info.get("entity"):
            context = pipeline._intent_based_search(intent_info)
            if context:
                return pipeline._generate_answer_with_context(question, context, "intent")

        # THỰC HIỆN 2: Direct search
        context = pipeline._direct_search(question)
        if context:
            return pipeline._generate_answer_with_context(question, context, "direct")

        # THỰC HIỆN 3: Fuzzy search
        context = pipeline._fuzzy_search(question)
        if context:
            return pipeline._generate_answer_with_context(question, context, "fuzzy")

        # BỎ SEMANTIC SEARCH Ở ĐÂY
        # if SEMANTIC_AVAILABLE:
        #     context = pipeline._semantic_search(question)
        #     ...

        # THỰC HIỆN 4: LLM-driven retrieval
        context = pipeline._llm_driven_retrieval(question)
        if context:
            return pipeline._generate_answer_with_context(question, context, "llm")

        # FALLBACK
        fallback_context = pipeline._fallback_search(question)
        if fallback_context:
            return pipeline._generate_answer_with_context(
                question, 
                fallback_context, 
                "fallback",
                note="⚠️ Thông tin được tìm thấy qua tìm kiếm mở rộng:"
            )

        return pipeline._generate_no_data_answer(question)
    
    # Patch
    pipeline.process_query = process_without_semantic
    
    results = []
    
    for i, q in enumerate(questions, 1):
        print(f"\n{'='*70}")
        print(f"CÂU HỎI {i}: {q}")
        print("="*70)
        
        try:
            answer = pipeline.process_query(q)
            results.append({"question": q, "answer": answer, "success": True})
            print(f"\n📝 TRẢ LỜI:\n{answer}")
        except Exception as e:
            results.append({"question": q, "error": str(e), "success": False})
            print(f"\n❌ LỖI: {e}")
        
        print()
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY (KHÔNG SEMANTIC)")
    print("=" * 70)
    
    for i, r in enumerate(results, 1):
        status = "✅" if r["success"] else "❌"
        print(f"\n{status} Câu {i}: {r['question']}")
        if r["success"]:
            if "Nguyễn Phúc Vĩnh Thụy" in r["answer"]:
                print("   ✅ ĐÚNG: Trả lời chứa tên đầy đủ")
            elif "Vĩnh Thụy" in r["answer"]:
                print("   ⚠️  THIẾU: Chỉ có 'Vĩnh Thụy', thiếu 'Nguyễn Phúc'")
            elif "không" in r["answer"].lower() and "tìm" in r["answer"].lower():
                print("   ❌ SAI: Không tìm thấy dữ liệu")
            else:
                print(f"   ⚠️  Cần kiểm tra: {r['answer'][:100]}...")
        else:
            print(f"   ❌ Lỗi: {r.get('error', 'Unknown')}")


if __name__ == "__main__":
    test_bao_dai_no_semantic()
