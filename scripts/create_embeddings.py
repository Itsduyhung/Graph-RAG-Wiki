"""
Script để tạo embeddings cho các nodes đã có trong Neo4j.
Chạy: python scripts/create_embeddings.py
"""

import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from sentence_transformers import SentenceTransformer
from neo4j import GraphDatabase

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "graphlayer")

MODEL_NAME = "BAAI/bge-m3"


def get_driver():
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def create_vector_indexes(driver):
    """Tạo vector indexes nếu chưa có."""
    with driver.session(database=NEO4J_DATABASE) as session:
        indexes = [
            ("PersonVectorIndex", "Person"),
            ("NameVectorIndex", "Name"),
            ("DynastyVectorIndex", "Dynasty"),
            ("EventVectorIndex", "Event"),
        ]
        
        for idx_name, label in indexes:
            try:
                # Kiểm tra index đã tồn tại chưa
                result = session.run(f"""
                    SHOW INDEXES YIELD name, labelsOrTypes
                    WHERE name = '{idx_name}'
                    RETURN name
                """)
                exists = result.single()
                
                if not exists:
                    session.run(f"""
                        CREATE VECTOR INDEX {idx_name} IF NOT EXISTS
                        FOR (n:{label}) ON (n.embedding)
                        OPTIONS {{indexConfig: {{
                            `vector.dimensions`: 768,
                            `vector.similarity_function`: 'cosine'
                        }}}}
                    """)
                    print(f"  [OK] Created index: {idx_name}")
                else:
                    print(f"  [--] Index exists: {idx_name}")
            except Exception as e:
                print(f"  [ERR] Error creating {idx_name}: {e}")


def create_embedding_text(node: dict, labels: list) -> str:
    """Tạo text từ node properties để encode thành embedding."""
    parts = []
    
    # Tên
    if node.get("name"):
        parts.append(node["name"])
    if node.get("full_name"):
        parts.append(node["full_name"])
    
    # Các loại node cụ thể
    if "Person" in labels:
        if node.get("birth_name"):
            parts.append(f"Tên khai sinh: {node['birth_name']}")
        if node.get("description"):
            parts.append(node["description"])
        if node.get("title"):
            parts.append(f"Chức vụ: {node['title']}")
        if node.get("birth_year"):
            parts.append(f"Sinh năm {node['birth_year']}")
        if node.get("death_year"):
            parts.append(f"Mất năm {node['death_year']}")
    
    elif "Event" in labels:
        if node.get("description"):
            parts.append(node["description"])
        if node.get("event_type"):
            parts.append(f"Loại sự kiện: {node['event_type']}")
    
    elif "Dynasty" in labels:
        if node.get("description"):
            parts.append(node["description"])
        if node.get("start_year"):
            parts.append(f"Bắt đầu năm {node['start_year']}")
        if node.get("end_year"):
            parts.append(f"Kết thúc năm {node['end_year']}")
    
    elif "Name" in labels:
        if node.get("value"):
            parts.append(f"Tên gọi: {node['value']}")
        if node.get("name_type"):
            parts.append(f"Loại tên: {node['name_type']}")
    
    return " ".join(parts)


def generate_embeddings(driver, model):
    """Generate embeddings cho tất cả nodes."""
    with driver.session(database=NEO4J_DATABASE) as session:
        # Các loại labels cần tạo embedding
        labels_to_process = ["Person", "Name", "Dynasty", "Event"]
        
        total_count = 0
        
        for label in labels_to_process:
            print(f"\nProcessing {label} nodes...")
            
            # Lấy tất cả nodes của label này
            result = session.run(f"""
                MATCH (n:{label})
                WHERE n.embedding IS NULL
                RETURN elementId(n) as eid, n, labels(n) as lbl
                LIMIT 1000
            """)
            
            count = 0
            for record in result:
                eid = record["eid"]
                node = dict(record["n"])
                
                # Tạo text
                text = create_embedding_text(node, record["lbl"])
                
                if text.strip():
                    # Encode thành embedding
                    embedding = model.encode(text).tolist()
                    
                    # Update node với embedding
                    session.run(f"""
                        MATCH (n)
                        WHERE elementId(n) = $eid
                        SET n.embedding = $embedding
                    """, eid=eid, embedding=embedding)
                    count += 1
            
            print(f"  [OK] Created {count} embeddings for {label}")
            total_count += count
        
        return total_count


def main():
    print("=" * 60)
    print("Creating Vector Embeddings for Neo4j Nodes")
    print("=" * 60)
    
    # Load model
    print(f"\n1. Loading model: {MODEL_NAME}")
    try:
        model = SentenceTransformer(MODEL_NAME)
        print(f"  [OK] Model loaded")
    except Exception as e:
        print(f"  [ERR] Error loading model: {e}")
        print("\n  Install: pip install sentence-transformers")
        return
    
    # Connect to Neo4j
    print(f"\n2. Connecting to Neo4j...")
    try:
        driver = get_driver()
        driver.verify_connectivity()
        print(f"  [OK] Connected to {NEO4J_URI}")
    except Exception as e:
        print(f"  [ERR] Connection failed: {e}")
        return
    
    # Create indexes
    print(f"\n3. Creating vector indexes...")
    create_vector_indexes(driver)
    
    # Generate embeddings
    print(f"\n4. Generating embeddings...")
    total = generate_embeddings(driver, model)
    print(f"\n5. Total embeddings created: {total}")
    
    driver.close()
    print("\n[OK] Done!")


if __name__ == "__main__":
    main()
