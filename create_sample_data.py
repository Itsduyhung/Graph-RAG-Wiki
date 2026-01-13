# create_sample_data.py
"""Script tạo dữ liệu mẫu để test ứng dụng."""
from graph.builder import GraphBuilder

def create_sample_data():
    """Tạo dữ liệu mẫu về công ty và người sáng lập."""
    print("🚀 Đang tạo dữ liệu mẫu...")
    
    builder = GraphBuilder()
    
    # Tạo các Person nodes
    print("📝 Tạo Person nodes...")
    builder.create_node("Person", "John Doe", {
        "age": 35,
        "expertise": "AI và Machine Learning",
        "email": "john@example.com"
    })
    
    builder.create_node("Person", "Jane Smith", {
        "age": 30,
        "expertise": "Fintech",
        "email": "jane@example.com"
    })
    
    builder.create_node("Person", "Bob Johnson", {
        "age": 40,
        "expertise": "Blockchain",
        "email": "bob@example.com"
    })
    
    # Tạo các Company nodes
    print("🏢 Tạo Company nodes...")
    builder.create_node("Company", "Fintech X", {
        "industry": "Finance",
        "founded_year": 2020,
        "location": "Ho Chi Minh City"
    })
    
    builder.create_node("Company", "Bank Y", {
        "industry": "Banking",
        "founded_year": 2015,
        "location": "Hanoi"
    })
    
    builder.create_node("Company", "Tech Startup Z", {
        "industry": "Technology",
        "founded_year": 2022,
        "location": "Da Nang"
    })
    
    # Tạo các relationships
    print("🔗 Tạo Relationships...")
    builder.create_relationship(
        "Person", "John Doe",
        "FOUNDED",
        "Company", "Fintech X",
        {"year": 2020, "role": "CEO"}
    )
    
    builder.create_relationship(
        "Person", "Jane Smith",
        "FOUNDED",
        "Company", "Fintech X",
        {"year": 2020, "role": "CTO"}
    )
    
    builder.create_relationship(
        "Person", "Bob Johnson",
        "FOUNDED",
        "Company", "Bank Y",
        {"year": 2015, "role": "Founder"}
    )
    
    builder.create_relationship(
        "Person", "John Doe",
        "WORKS_AT",
        "Company", "Tech Startup Z",
        {"role": "Advisor", "start_date": "2022-01-01"}
    )
    
    print("✅ Dữ liệu mẫu đã được tạo thành công!")
    print("\n📊 Dữ liệu bao gồm:")
    print("  - 3 Person nodes: John Doe, Jane Smith, Bob Johnson")
    print("  - 3 Company nodes: Fintech X, Bank Y, Tech Startup Z")
    print("  - 4 Relationships: FOUNDED và WORKS_AT")
    print("\n💡 Bây giờ bạn có thể hỏi:")
    print("  - 'Ai là người sáng lập của Fintech X?'")
    print("  - 'John Doe thành lập công ty nào?'")
    print("  - 'Fintech X được thành lập bởi ai?'")

if __name__ == "__main__":
    try:
        create_sample_data()
    except Exception as e:
        print(f"❌ Lỗi: {e}")
        print("\n🔍 Kiểm tra:")
        print("  1. Neo4j đang chạy chưa?")
        print("  2. config/secrets.env đã được cấu hình đúng chưa?")
        print("  3. Kết nối Neo4j có thành công không?")
