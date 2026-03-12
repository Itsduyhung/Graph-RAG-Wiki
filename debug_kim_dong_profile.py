from graph.storage import GraphDB

db = GraphDB()

with db.driver.session(database=db.database) as session:
    # Check if Person node exists
    person = session.run(
        "MATCH (p:Person {name: $name}) RETURN p",
        name="Kim Đồng"
    ).single()
    
    if person:
        print(f"✓ Person found: {dict(person['p'])}")
    else:
        print("❌ Person not found")
    
    # Check achievements
    achievements = session.run(
        """MATCH (p:Person {name: $name})-[:ACHIEVED]->(a:Achievement)
           RETURN a.name AS name, a.description AS desc
           LIMIT 10""",
        name="Kim Đồng"
    ).data()
    
    print(f"\nAchievements ({len(achievements)}):")
    for a in achievements:
        print(f"  • {a['name']}")
    
    # Check events
    events = session.run(
        """MATCH (p:Person {name: $name})-[:PARTICIPATED_IN]->(e:Event)
           RETURN e.name AS name, e.event_type AS type
           LIMIT 10""",
        name="Kim Đồng"
    ).data()
    
    print(f"\nEvents ({len(events)}):")
    for e in events:
        print(f"  • {e['name']}")
    
    # Check fields
    fields = session.run(
        """MATCH (p:Person {name: $name})-[:ACTIVE_IN]->(f:Field)
           RETURN f.name AS name
           LIMIT 10""",
        name="Kim Đồng"
    ).data()
    
    print(f"\nFields ({len(fields)}):")
    for f in fields:
        print(f"  • {f['name']}")
    
    # Check what relationships exist from Kim Đồng
    rels = session.run(
        """MATCH (p:Person {name: $name})-[r]->(n)
           RETURN type(r) AS rel_type, labels(n) AS node_type, count(*) AS cnt
           GROUP BY rel_type, node_type
           ORDER BY cnt DESC""",
        name="Kim Đồng"
    ).data()
    
    print(f"\nAll relationships from Kim Đồng:")
    for r in rels:
        print(f"  {r['rel_type']:20} -> {r['node_type']:20} ({r['cnt']} rels)")
