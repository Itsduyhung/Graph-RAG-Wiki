"""Debug script to check actual person names in Neo4j"""

from graph.storage import GraphDB
from dotenv import load_dotenv

load_dotenv()

db = GraphDB()

with db.driver.session(database=db.database) as session:
    # Find all persons with "Kim" in name
    result = session.run(
        """
        MATCH (p:Person)
        WHERE toLower(p.name) CONTAINS 'kim'
        RETURN p.name as name
        LIMIT 10
        """
    )
    
    print("Persons with 'kim' in name:")
    for r in result:
        print(f"  - '{r['name']}'")
    
    # Check if "Kim Đồng" exists
    result = session.run(
        """
        MATCH (p:Person {name: "Kim Đồng"})
        RETURN COUNT(p) as cnt
        """
    ).single()
    
    print(f"\nCount of 'Kim Đồng': {result['cnt']}")
    
    # Try to get connected nodes to a Kim person
    print("\n\nConnected nodes for first Kim person:")
    result = session.run(
        """
        MATCH (p:Person)-[r]-(n)
        WHERE toLower(p.name) CONTAINS 'kim'
        RETURN p.name as person, type(r) as rel_type, labels(n)[0] as node_type, n.name as node_name
        LIMIT 30
        """
    )
    
    for r in result:
        print(f"  {r['person']} -[{r['rel_type']}]-> {r['node_type']}: {r['node_name']}")

db.close()
