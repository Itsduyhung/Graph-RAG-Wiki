# examples/builder_example.py
"""Ví dụ sử dụng GraphBuilder - linh hoạt và generic cho bất kỳ node/relationship type nào."""
from graph.builder import GraphBuilder
from graph.storage import GraphDB


def example_1_simple_nodes():
    """Ví dụ 1: Tạo nodes đơn giản với bất kỳ type nào."""
    builder = GraphBuilder()
    
    # Tạo Person node
    builder.create_node("Person", "John Doe", {"age": 30, "email": "john@example.com"})
    
    # Tạo Company node
    builder.create_node("Company", "Fintech X", {"industry": "Finance", "founded_year": 2020})
    
    # Tạo Product node với identifier là dict
    builder.create_node("Product", {"code": "P001"}, {"name": "Product 1", "price": 100})
    
    # Tạo Category node
    builder.create_node("Category", {"name": "Technology"}, {"description": "Tech products"})
    
    print("✅ Created nodes with any type!")


def example_2_relationships():
    """Ví dụ 2: Tạo relationships giữa bất kỳ node types nào."""
    builder = GraphBuilder()
    
    # Tạo relationship FOUNDED
    builder.create_relationship("Person", "John Doe", "FOUNDED", "Company", "Fintech X", {"year": 2020})
    
    # Tạo relationship WORKS_AT
    builder.create_relationship("Person", "Jane Smith", "WORKS_AT", "Company", "Fintech X", {"role": "CTO"})
    
    # Tạo relationship BELONGS_TO
    builder.create_relationship("Product", {"code": "P001"}, "BELONGS_TO", "Category", {"name": "Technology"})
    
    # Tạo relationship OWNS với direction
    builder.create_relationship("Person", "John Doe", "OWNS", "Company", "Fintech X", {"share": 0.8}, direction="->")
    
    print("✅ Created relationships between any node types!")


def example_3_batch_processing():
    """Ví dụ 3: Batch processing - tạo nhiều nodes và relationships cùng lúc."""
    builder = GraphBuilder()
    
    # Batch create nodes
    nodes = [
        {"type": "Person", "identifier": "Alice", "properties": {"age": 25}},
        {"type": "Person", "identifier": "Bob", "properties": {"age": 30}},
        {"type": "Company", "identifier": "Tech Corp", "properties": {"industry": "IT"}},
        {"type": "Product", "identifier": {"code": "P002"}, "properties": {"name": "Product 2"}},
    ]
    
    nodes_created = builder.batch_create_nodes(nodes)
    print(f"✅ Created {nodes_created} nodes in batch!")
    
    # Batch create relationships
    relationships = [
        {
            "from_type": "Person",
            "from_id": "Alice",
            "rel_type": "WORKS_AT",
            "to_type": "Company",
            "to_id": "Tech Corp",
            "properties": {"role": "Developer"}
        },
        {
            "from_type": "Person",
            "from_id": "Bob",
            "rel_type": "FOUNDED",
            "to_type": "Company",
            "to_id": "Tech Corp",
            "properties": {"year": 2019}
        },
    ]
    
    rels_created = builder.batch_create_relationships(relationships)
    print(f"✅ Created {rels_created} relationships in batch!")


def example_4_flexible_data_format():
    """Ví dụ 4: Build từ data với format linh hoạt."""
    builder = GraphBuilder()
    
    # Format 1: Dict với nodes và relationships riêng biệt
    data_format_1 = {
        "nodes": [
            {"type": "Person", "identifier": "Charlie", "properties": {"age": 35}},
            {"type": "Company", "identifier": "Startup Y", "properties": {"industry": "AI"}},
        ],
        "relationships": [
            {
                "from_type": "Person",
                "from_id": "Charlie",
                "rel_type": "FOUNDED",
                "to_type": "Company",
                "to_id": "Startup Y",
            }
        ]
    }
    
    result = builder.build_from_data(data_format_1)
    print(f"✅ Built from format 1: {result}")
    
    # Format 2: List of nodes với type
    data_format_2 = [
        {"type": "Person", "identifier": "David", "properties": {"age": 40}},
        {"type": "Company", "identifier": "Big Corp", "properties": {"industry": "Finance"}},
    ]
    
    result = builder.build_from_data(data_format_2)
    print(f"✅ Built from format 2: {result}")
    
    # Format 3: Legacy format (backward compatible)
    data_format_3 = [
        {"person": "Emma", "company": "Small Corp", "relationship": "FOUNDED", "relationship_props": {"year": 2021}},
    ]
    
    result = builder.build_from_data(data_format_3)
    print(f"✅ Built from legacy format: {result}")


def example_5_complex_scenario():
    """Ví dụ 5: Scenario phức tạp với nhiều node types khác nhau."""
    builder = GraphBuilder()
    
    # Tạo nhiều loại nodes khác nhau
    builder.create_node("Person", "Founder A", {"name": "Founder A", "expertise": "AI"})
    builder.create_node("Company", "AI Startup", {"name": "AI Startup", "focus": "Machine Learning"})
    builder.create_node("Product", {"name": "AI Platform"}, {"version": "1.0", "status": "beta"})
    builder.create_node("Customer", {"id": "C001"}, {"name": "Customer 1", "tier": "enterprise"})
    builder.create_node("Technology", {"name": "TensorFlow"}, {"type": "Framework"})
    
    # Tạo relationships đa dạng
    builder.create_relationship("Person", "Founder A", "FOUNDED", "Company", "AI Startup", {"year": 2022})
    builder.create_relationship("Company", "AI Startup", "DEVELOPS", "Product", {"name": "AI Platform"}, {})
    builder.create_relationship("Customer", {"id": "C001"}, "USES", "Product", {"name": "AI Platform"}, {"since": "2023"})
    builder.create_relationship("Product", {"name": "AI Platform"}, "USES", "Technology", {"name": "TensorFlow"}, {})
    
    print("✅ Created complex scenario with multiple node types and relationships!")


if __name__ == "__main__":
    print("🚀 Graph Builder Examples - Flexible và Generic\n")
    
    # Uncomment các ví dụ bạn muốn chạy
    # example_1_simple_nodes()
    # example_2_relationships()
    # example_3_batch_processing()
    # example_4_flexible_data_format()
    # example_5_complex_scenario()
    
    print("\n✅ Tất cả ví dụ đã sẵn sàng! Uncomment để chạy.")


