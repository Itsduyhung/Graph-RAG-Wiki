"""Quick test: Albert Einstein enrichment"""
from pipeline.custom_graph_extractor import CustomGraphExtractor
from graph.storage import GraphDB
from dotenv import load_dotenv

load_dotenv()

TARGET_NAME = "Albert Einstein"

print(f"\n{'='*70}")
print(f"[TEST] Enriching graph with Albert Einstein")
print(f"{'='*70}\n")

# Get WikiChunk content for TARGET_NAME
db = GraphDB()
chunks = []

with db.driver.session(database=db.database) as session:
    # Strategy 1: Case-insensitive full name match
    result = session.run(
        """
        MATCH (w:WikiChunk)
        WHERE toLower(w.content) CONTAINS toLower($name)
        RETURN w.content AS content, w.chunk_id AS chunk_id
        LIMIT 20
        """,
        name=TARGET_NAME,
    )
    chunks = [(r["chunk_id"] or f"chunk_{i}", r["content"]) 
              for i, r in enumerate(result)]
    
    print(f"[SEARCH] Strategy 1 (case-insensitive full name): {len(chunks)} chunks found\n")
    
    # Strategy 2: If no match, try searching by first/last name keywords
    if not chunks and len(TARGET_NAME.split()) > 1:
        keywords = TARGET_NAME.split()
        print(f"[SEARCH] Full match not found, trying keywords: {keywords}")
        for keyword in keywords:
            result = session.run(
                """
                MATCH (w:WikiChunk)
                WHERE w.content CONTAINS $keyword
                RETURN w.content AS content, w.chunk_id AS chunk_id
                LIMIT 10
                """,
                keyword=keyword,
            )
            keyword_chunks = [(r["chunk_id"] or f"chunk_{i}", r["content"]) 
                             for i, r in enumerate(result)]
            chunks.extend(keyword_chunks)
            if chunks:
                print(f"  Found {len(keyword_chunks)} chunks for keyword '{keyword}'")
                break

# Remove duplicates while preserving order
seen = set()
unique_chunks = []
for chunk_id, content in chunks:
    content_hash = hash(content[:100])  # Use first 100 chars as identifier
    if content_hash not in seen:
        seen.add(content_hash)
        unique_chunks.append((chunk_id, content))
chunks = unique_chunks[:20]

print(f"\n[RESULT] Total unique chunks: {len(chunks)}")

if chunks:
    print(f"\n[PROCESSING] Enriching with {len(chunks)} chunks...")
    extractor = CustomGraphExtractor()
    total_nodes = 0
    total_rels = 0
    
    for i, (chunk_id, content) in enumerate(chunks, 1):
        try:
            nodes, rels = extractor.enrich_text(content, source_chunk_id=chunk_id)
            total_nodes += nodes
            total_rels += rels
            print(f"  [{i}/{len(chunks)}] Chunk '{chunk_id}': {nodes} nodes, {rels} relationships")
        except Exception as e:
            print(f"  [{i}/{len(chunks)}] Chunk '{chunk_id}': ERROR - {str(e)[:80]}")
    
    print(f"\n[SUMMARY]")
    print(f"  - Total nodes created: {total_nodes}")
    print(f"  - Total relationships created: {total_rels}")
else:
    print(f"\n[FAILED] No chunks found for '{TARGET_NAME}'")
