"""
Delete Kim Đồng and all connected nodes from Neo4j
"""

from graph.storage import GraphDB
from dotenv import load_dotenv

load_dotenv()

PERSON_TO_DELETE = "Kim Đồng"

print(f"\n{'='*70}")
print(f"[DELETE] Removing all nodes related to '{PERSON_TO_DELETE}'")
print(f"{'='*70}\n")

db = GraphDB()

with db.driver.session(database=db.database) as session:
    # 1. Count nodes before delete
    result = session.run(
        "MATCH (p:Person {name: $name}) RETURN COUNT(p) as cnt",
        name=PERSON_TO_DELETE
    )
    person_count = result.single()[0]
    
    if person_count == 0:
        print(f"❌ Person '{PERSON_TO_DELETE}' not found in database")
        exit(1)
    
    # Count connected nodes
    result = session.run(
        f"""
        MATCH (p:Person {{name: $name}})-[r]-(n)
        RETURN COUNT(DISTINCT n) as connected_count, COUNT(DISTINCT r) as rel_count
        """,
        name=PERSON_TO_DELETE
    )
    data = result.single()
    connected_count = data[0] if data[0] else 0
    rel_count = data[1] if data[1] else 0
    
    print(f"[INFO] Found:")
    print(f"  - 1 Person node: '{PERSON_TO_DELETE}'")
    print(f"  - {connected_count} Connected nodes")
    print(f"  - {rel_count} Relationships")
    print(f"\n[ACTION] Deleting...")
    
    # 2. Delete person and all relationships
    result = session.run(
        f"""
        MATCH (p:Person {{name: $name}})
        DETACH DELETE p
        RETURN COUNT(*) as deleted
        """,
        name=PERSON_TO_DELETE
    )
    
    print(f"✓ Deleted Person node: '{PERSON_TO_DELETE}'")
    print(f"✓ Deleted {rel_count} relationships")
    
    # 3. Check if orphaned nodes exist (nodes with no relationships)
    result = session.run(
        """
        MATCH (n)
        WHERE NOT (n)--()
        RETURN COUNT(n) as orphaned_count
        """
    )
    orphaned_count = result.single()[0]
    
    if orphaned_count > 0:
        print(f"\n[INFO] Found {orphaned_count} orphaned nodes (no relationships)")
        print(f"[ACTION] Deleting orphaned nodes...")
        result = session.run(
            """
            MATCH (n)
            WHERE NOT (n)--()
            DELETE n
            RETURN COUNT(n) as deleted
            """
        )
        deleted = result.single()[0]
        print(f"✓ Deleted {deleted} orphaned nodes")

print(f"\n{'='*70}")
print(f"[DONE] Cleanup complete!")
print(f"{'='*70}\n")
