"""Check Neo4j status"""
from neo4j import GraphDatabase
import os
from dotenv import load_dotenv
load_dotenv()

uri = os.getenv('NEO4J_URI', 'bolt://localhost:7687')
user = os.getenv('NEO4J_USER', 'neo4j')
password = os.getenv('NEO4J_PASSWORD', 'password')
db = os.getenv('NEO4J_DATABASE', 'graphlayer')

print(f"Connecting to {uri}...")
driver = GraphDatabase.driver(uri, auth=(user, password))
driver.verify_connectivity()
print("Connected!")

with driver.session(database=db) as session:
    # Check existing indexes
    result = session.run("SHOW INDEXES YIELD name, type, labelsOrTypes")
    print("\nExisting indexes:")
    for r in result:
        idx_name = r["name"]
        idx_type = r["type"]
        labels = r["labelsOrTypes"]
        print(f"  {idx_name}: {idx_type} ({labels})")
    
    # Check Person nodes count
    result = session.run("MATCH (p:Person) RETURN count(p) as cnt")
    cnt = result.single()["cnt"]
    print(f"\nPerson nodes: {cnt}")
    
    # Check embeddings
    result = session.run("MATCH (p:Person) WHERE p.embedding IS NOT NULL RETURN count(p) as cnt")
    emb_cnt = result.single()["cnt"]
    print(f"Person nodes with embeddings: {emb_cnt}")

driver.close()
print("\nDone!")
