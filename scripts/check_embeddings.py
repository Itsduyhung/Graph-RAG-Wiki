"""Check all embeddings in Neo4j"""
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
print("Connected!\n")

with driver.session(database=db) as session:
    labels = ['Person', 'Name', 'Dynasty', 'Event']
    
    for label in labels:
        # Total count
        result = session.run(f"MATCH (n:{label}) RETURN count(n) as cnt")
        total = result.single()["cnt"]
        
        # With embeddings
        result = session.run(f"MATCH (n:{label}) WHERE n.embedding IS NOT NULL RETURN count(n) as cnt")
        with_emb = result.single()["cnt"]
        
        print(f"{label}: {with_emb}/{total} nodes with embeddings")

driver.close()
print("\nDone!")
