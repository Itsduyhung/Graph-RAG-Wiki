"""Debug: Kiểm tra data của Bảo Đại trong database."""
import sys
sys.path.insert(0, '.')

from graph.storage import GraphDB

def check_bao_dai_data():
    db = GraphDB()
    
    with db.driver.session(database=db.database) as session:
        # 1. Tìm Bảo Đại
        print("=" * 70)
        print("1. Tìm Bảo Đại trong database")
        print("=" * 70)
        
        result = session.run("""
            MATCH (p:Person)
            WHERE p.name CONTAINS 'Bảo Đại' OR p.name CONTAINS 'Vĩnh Thụy'
            RETURN p.name, keys(p)
            LIMIT 5
        """)
        
        for r in result:
            print(f"\nName: {r['p.name']}")
            print(f"Keys: {r['keys(p)']}")
            
            # Lấy tất cả properties
            node_result = session.run("""
                MATCH (p:Person)
                WHERE p.name CONTAINS 'Bảo Đại' OR p.name CONTAINS 'Vĩnh Thụy'
                RETURN p
                LIMIT 1
            """)
            
            for nr in node_result:
                node = nr['p']
                print("\nTất cả properties:")
                for key, value in node.items():
                    print(f"  {key}: {value}")
        
        # 2. Kiểm tra xem có Name node không
        print("\n" + "=" * 70)
        print("2. Tìm Name nodes liên quan đến Bảo Đại")
        print("=" * 70)
        
        result = session.run("""
            MATCH (p:Person)-[r]-(n:Name)
            WHERE p.name CONTAINS 'Bảo Đại' OR n.value CONTAINS 'Bảo Đại'
            RETURN p.name as person, type(r) as rel, n.value as name_value
            LIMIT 10
        """)
        
        for r in result:
            print(f"{r['person']} -{r['rel']}→ {r['name_value']}")
        
        # 3. Tìm tất cả relationships
        print("\n" + "=" * 70)
        print("3. Tất cả relationships của Bảo Đại")
        print("=" * 70)
        
        result = session.run("""
            MATCH (p:Person)-[r]-(other)
            WHERE p.name CONTAINS 'Bảo Đại'
            RETURN p.name as person, type(r) as rel, other.name as other_name, labels(other)[0] as other_type
            LIMIT 20
        """)
        
        for r in result:
            print(f"{r['person']} -{r['rel']}→ {r['other_name']} ({r['other_type']})")
        
        # 4. Tìm trong biography
        print("\n" + "=" * 70)
        print("4. Tìm trong biography")
        print("=" * 70)
        
        result = session.run("""
            MATCH (p:Person)
            WHERE p.name CONTAINS 'Bảo Đại'
            RETURN p.name, p.biography
            LIMIT 5
        """)
        
        for r in result:
            print(f"\nName: {r['p.name']}")
            bio = r['p.biography'] or "Không có biography"
            print(f"Bio: {bio[:500]}..." if len(bio) > 500 else f"Bio: {bio}")


if __name__ == "__main__":
    check_bao_dai_data()
