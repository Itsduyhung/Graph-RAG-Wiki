"""Test SEMANTIC SEARCH - KHÔNG query lại."""
import sys
sys.path.insert(0, '.')

from pipeline.query_pipeline import QueryPipeline, SEMANTIC_AVAILABLE

def test_semantic_only():
    """Test semantic search lấy đầy đủ info ngay."""
    
    print("=" * 70)
    print("TESTING: SEMANTIC SEARCH - KHÔNG QUERY LẠI")
    print("=" * 70)
    
    pipeline = QueryPipeline()
    
    questions = [
        "Tên thật của Bảo Đại?",
        "Bảo Đại tên thật là gì?"
    ]
    
    # Patch process_query - chỉ dùng semantic
    def process_semantic_only(question):
        """Process query - CHỈ semantic."""
        
        # BƯỚC 0: Classify intent
        intent_info = pipeline._classify_intent(question)
        print(f"🔍 Intent: {intent_info}")

        # Chỉ dùng SEMANTIC SEARCH
        if SEMANTIC_AVAILABLE and pipeline._semantic_model:
            print("🔍 Đang dùng SEMANTIC SEARCH...")
            context = pipeline._semantic_search(question)
            if context:
                print(f"✅ Context found via semantic")
                return pipeline._generate_answer_with_context(question, context, "semantic-only")
        
        print("❌ Không tìm được context")
        return pipeline._generate_no_data_answer(question)
    
    results = []
    
    for i, q in enumerate(questions, 1):
        print(f"\n{'='*70}")
        print(f"CÂU HỎI {i}: {q}")
        print("="*70)
        
        try:
            answer = process_semantic_only(q)
            results.append({"question": q, "answer": answer, "success": True})
            print(f"\n📝 TRẢ LỜI:\n{answer}")
        except Exception as e:
            results.append({"question": q, "error": str(e), "success": False})
            print(f"\n❌ LỖI: {e}")
        
        print()
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY (SEMANTIC ONLY)")
    print("=" * 70)
    
    for i, r in enumerate(results, 1):
        status = "✅" if r["success"] else "❌"
        print(f"\n{status} Câu {i}: {r['question']}")
        if r["success"]:
            if "Nguyễn Phúc Vĩnh Thụy" in r["answer"]:
                print("   ✅ ĐÚNG: Trả lời chứa tên đầy đủ")
            elif "Vĩnh Thụy" in r["answer"]:
                print("   ⚠️  THIẾU: Chỉ có 'Vĩnh Thụy', thiếu 'Nguyễn Phúc'")
            elif "không" in r["answer"].lower():
                print("   ❌ SAI: Không tìm thấy dữ liệu")
            else:
                print(f"   ⚠️  Cần kiểm tra: {r['answer'][:100]}...")
        else:
            print(f"   ❌ Lỗi: {r.get('error', 'Unknown')}")


if __name__ == "__main__":
    test_semantic_only()
