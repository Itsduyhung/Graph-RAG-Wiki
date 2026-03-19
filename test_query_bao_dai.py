"""Test query pipeline với 2 câu hỏi về tên thật của Bảo Đại."""
import sys
sys.path.insert(0, '.')

from pipeline.query_pipeline import QueryPipeline
from graph.storage import GraphDB

def test_bao_dai_queries():
    """Test 2 câu hỏi về tên thật của Bảo Đại."""
    
    print("=" * 70)
    print("TESTING: Query Pipeline - Tên thật của Bảo Đại")
    print("=" * 70)
    
    # Khởi tạo pipeline
    pipeline = QueryPipeline()
    
    questions = [
        "Tên thật của Bảo Đại?",
        "Bảo Đại tên thật là gì?"
    ]
    
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
    print("SUMMARY")
    print("=" * 70)
    
    for i, r in enumerate(results, 1):
        status = "✅" if r["success"] else "❌"
        print(f"\n{status} Câu {i}: {r['question']}")
        if r["success"]:
            # Check if answer contains "Nguyễn Phúc Vĩnh Thụy"
            if "Nguyễn Phúc Vĩnh Thụy" in r["answer"]:
                print("   ✅ ĐÚNG: Trả lời chứa tên thật")
            elif "không" in r["answer"].lower() and "tìm" in r["answer"].lower():
                print("   ❌ SAI: Không tìm thấy dữ liệu")
            else:
                print(f"   ⚠️  Cần kiểm tra: {r['answer'][:100]}...")
        else:
            print(f"   ❌ Lỗi: {r.get('error', 'Unknown')}")


if __name__ == "__main__":
    test_bao_dai_queries()
