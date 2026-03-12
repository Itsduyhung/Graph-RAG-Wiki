"""Integrated data ingestion pipeline: Extract Person nodes and enrich with Achievement/Era/Field.

This script is a unified data ingestion workflow that:
1. Extracts Person nodes from SummaryDocument and WikiChunk using PersonProfileExtractor
2. Enriches the graph with Achievement, Era, Field nodes using CustomGraphExtractor
3. Supports any historical figure - just change TARGET_NAME to extract different people

Usage:
    python test_person_extraction.py  # Extract for TARGET_NAME (default: Duy Tân)
    # Or modify TARGET_NAME before running to extract for different people
"""

from dotenv import load_dotenv
from graph.storage import GraphDB
from pipeline.custom_graph_extractor import CustomGraphExtractor
from pipeline.person_profile_extractor import PersonProfileExtractor

load_dotenv()

# Change this to extract different people
TARGET_NAME = "Kim Đồng"  # Example: "Duy Tân", "Minh Mạng", "Gia Long", "Trần Nhân Tông"


def run_extraction(use_person_extractor: bool = False) -> None:
    """Extract Person nodes from SummaryDocument and WikiChunk.
    
    Args:
        use_person_extractor: If True, run PersonProfileExtractor (slower).
                            If False, skip and go straight to enrichment.
    """
    if not use_person_extractor:
        print("[*] Skipping PersonProfileExtractor (slow) - go straight to enrichment")
        print("[*] If you need Person extraction, set use_person_extractor=True")
        return
    
    extractor = PersonProfileExtractor()
    print("[*] Extracting Person nodes from SummaryDocument...")
    result = extractor.extract_from_summaries(limit=200)
    print(f"[OK] Result: {result}")

    print(f"\n[*] Extracting Person nodes from WikiChunk containing '{TARGET_NAME}'...")
    result_chunks = extractor.extract_from_chunks_for_name(TARGET_NAME, limit=50)
    print(f"[OK] Result: {result_chunks}")


def run_enrichment() -> None:
    """Enrich graph with Achievement, Era, Field nodes."""
    print(f"\n{'='*70}")
    print(f"[ENRICHMENT] Enriching graph with Achievement/Era/Field for '{TARGET_NAME}'")
    print(f"{'='*70}")
    
    # Ensure Person node exists before enrichment
    db = GraphDB()
    with db.driver.session(database=db.database) as session:
        # Check if Person exists
        person_exists = session.run(
            "MATCH (p:Person {name: $name}) RETURN COUNT(p) as cnt",
            name=TARGET_NAME,
        ).single()
        
        if not person_exists or person_exists["cnt"] == 0:
            # Create Person node if it doesn't exist
            session.run(
                """
                CREATE (p:Person {name: $name})
                RETURN p
                """,
                name=TARGET_NAME,
            )
            print(f"[*] Created Person node for '{TARGET_NAME}'")
    
    # Get WikiChunk content for TARGET_NAME
    # Search only by full name (no keyword splitting) for accuracy
    chunks = []
    
    with db.driver.session(database=db.database) as session:
        # Search only by full name - don't split keywords
        result = session.run(
            f"""
            MATCH (w:WikiChunk)
            WHERE toLower(w.content) CONTAINS toLower('{TARGET_NAME}')
            RETURN w.content AS content, w.chunk_id AS chunk_id
            LIMIT 20
            """
        )
        chunks = [(r["chunk_id"] or f"chunk_{i}", r["content"]) 
                  for i, r in enumerate(result)]
    
    # Remove duplicates while preserving order
    seen = set()
    unique_chunks = []
    for chunk_id, content in chunks:
        content_hash = hash(content[:100])  # Use first 100 chars as identifier
        if content_hash not in seen:
            seen.add(content_hash)
            unique_chunks.append((chunk_id, content))
    chunks = unique_chunks[:20]  # Limit to 20
    
    if not chunks:
        print(f"[WARNING] No WikiChunk found for '{TARGET_NAME}' - skipping enrichment")
        return
    
    print(f"\n[*] Found {len(chunks)} chunks - processing enrichment...")
    
    # Extract and build with CustomGraphExtractor
    extractor = CustomGraphExtractor()
    total_nodes = 0
    total_rels = 0
    
    for i, (chunk_id, content) in enumerate(chunks, 1):
        try:
            # Enrich with auto-linking to TARGET_NAME person
            nodes, rels = extractor.enrich_text(
                content, 
                source_chunk_id=chunk_id,
                link_to_person=TARGET_NAME  # Auto-link achievements/events to person
            )
            total_nodes += nodes
            total_rels += rels
            print(f"  [{i}/{len(chunks)}] Chunk '{chunk_id}': {nodes} nodes, {rels} relationships")
        except Exception as e:
            print(f"  [{i}/{len(chunks)}] Chunk '{chunk_id}': ERROR - {str(e)[:80]}")
    
    print(f"\n[SUMMARY] Enrichment complete:")
    print(f"  - Total nodes created: {total_nodes}")
    print(f"  - Total relationships created: {total_rels}")


def inspect_person(name: str) -> None:
    """Inspect and display complete profile for person."""
    print(f"\n{'='*70}")
    print(f"[INSPECTION] Profile for '{name}'")
    print(f"{'='*70}")
    
    db = GraphDB()
    with db.driver.session(database=db.database) as session:
        # Get Person info
        person_result = session.run(
            """
            MATCH (p:Person {name: $name})
            RETURN p
            """,
            name=name,
        ).single()
        
        if not person_result:
            print(f"\n[ERROR] Person '{name}' not found in Neo4j")
            return
        
        p = dict(person_result["p"])
        print(f"\n[PERSON] {p.get('name')}")
        if p.get("birth_date"):
            print(f"  Birth: {p['birth_date']}")
        elif p.get("birth_year"):
            print(f"  Birth year: {p['birth_year']}")
        if p.get("death_date"):
            print(f"  Death: {p['death_date']}")
        elif p.get("death_year"):
            print(f"  Death year: {p['death_year']}")
        if p.get("biography"):
            bio = p['biography']
            print(f"  Bio: {bio[:150]}..." if len(bio) > 150 else f"  Bio: {bio}")
        
        # Get Connected Person nodes (family, etc)
        connected_persons = session.run(
            """
            MATCH (p:Person {name: $name})-[r]-(other:Person)
            RETURN DISTINCT other.name AS name, type(r) AS rel_type
            LIMIT 10
            """,
            name=name,
        ).data()
        
        if connected_persons:
            print(f"\n[RELATED PERSONS] ({len(connected_persons)}):")
            for cp in connected_persons:
                print(f"  - {cp['name']} [{cp['rel_type']}]")
        
        # Get Achievements
        achievements = session.run(
            """
            MATCH (p:Person {name: $name})-[:ACHIEVED]->(a:Achievement)
            RETURN DISTINCT a.name AS name, a.year AS year, a.description AS desc
            ORDER BY a.year DESC
            """,
            name=name,
        ).data()
        
        if achievements:
            print(f"\n[ACHIEVEMENTS] ({len(achievements)}):")
            for a in achievements:
                year_str = f" ({a['year']})" if a['year'] else ""
                print(f"  - {a['name']}{year_str}")
                if a['desc']:
                    print(f"    Description: {a['desc'][:70]}...")
        
        # Get Fields (domains)
        fields = session.run(
            """
            MATCH (p:Person {name: $name})-[:ACTIVE_IN]->(f:Field)
            RETURN DISTINCT f.name AS name, f.category AS category
            """,
            name=name,
        ).data()
        
        if fields:
            print(f"\n[FIELDS] ({len(fields)}):")
            for f in fields:
                cat = f" ({f['category']})" if f['category'] else ""
                print(f"  - {f['name']}{cat}")
        
        # Get Eras
        eras = session.run(
            """
            MATCH (p:Person {name: $name})-[:ACTIVE_IN]->(e:Era)
            RETURN DISTINCT e.name AS name, e.start_year AS start_yr, e.end_year AS end_yr
            """,
            name=name,
        ).data()
        
        if eras:
            print(f"\n[ERAS] ({len(eras)}):")
            for e in eras:
                years = f" ({e['start_yr']}-{e['end_yr']})" if e['start_yr'] else ""
                print(f"  - {e['name']}{years}")
        
        # Get Events
        events = session.run(
            """
            MATCH (p:Person {name: $name})-[:PARTICIPATED_IN]->(ev:Event)
            RETURN DISTINCT ev.name AS name, ev.year AS year
            LIMIT 10
            """,
            name=name,
        ).data()
        
        if events:
            print(f"\n[EVENTS] ({len(events)}):")
            for ev in events:
                year_str = f" ({ev['year']})" if ev['year'] else ""
                print(f"  - {ev['name']}{year_str}")
        
        # Get Countries
        countries = session.run(
            """
            MATCH (p:Person {name: $name})-[r]-(c:Country)
            RETURN DISTINCT c.name AS name, type(r) AS rel_type
            LIMIT 10
            """,
            name=name,
        ).data()
        
        if countries:
            print(f"\n[COUNTRIES] ({len(countries)}):")
            for c in countries:
                print(f"  - {c['name']} [{c['rel_type']}]")
        
        # DEBUG: Show all connected nodes and relationship types
        print(f"\n[DEBUG] All connected nodes and relationships:")
        all_connected = session.run(
            """
            MATCH (p:Person {name: $name})-[r]-(n)
            RETURN type(r) as rel_type, labels(n)[0] as node_type, n.name as node_name
            ORDER BY type(r), labels(n)[0]
            """,
            name=name,
        ).data()
        
        if all_connected:
            # Group by relationship type
            rel_groups = {}
            for item in all_connected:
                rel = item['rel_type']
                node_info = f"{item['node_type']}: {item['node_name']}"
                if rel not in rel_groups:
                    rel_groups[rel] = []
                rel_groups[rel].append(node_info)
            
            # Print grouped
            for rel_type in sorted(rel_groups.keys()):
                print(f"\n  {rel_type}:")
                for node_info in rel_groups[rel_type][:5]:  # Show first 5
                    print(f"    - {node_info}")
                if len(rel_groups[rel_type]) > 5:
                    print(f"    ... and {len(rel_groups[rel_type]) - 5} more")
        else:
            print(f"  (No relationships found - check if nodes exist!)")
    
    db.close()


if __name__ == "__main__":
    print("=" * 70)
    print(f"UNIFIED DATA INGESTION PIPELINE")
    print(f"Target: {TARGET_NAME}")
    print("=" * 70)
    
    # Step 1: Extract Person nodes (optional - PersonProfileExtractor is slow)
    print(f"\n[STEP 1] PERSON EXTRACTION")
    run_extraction(use_person_extractor=False)  # Set to True if you want PersonProfileExtractor
    
    # Step 2: Enrich with Achievement/Era/Field
    print(f"\n[STEP 2] GRAPH ENRICHMENT")
    run_enrichment()
    
    # Step 3: Inspect results
    print(f"\n[STEP 3] RESULTS INSPECTION")
    inspect_person(TARGET_NAME)
    
    print(f"\n{'='*70}")
    print(f"[OK] Data ingestion complete!")
    print(f"Check Neo4j to see all generated nodes and relationships")
    print(f"{'='*70}")

