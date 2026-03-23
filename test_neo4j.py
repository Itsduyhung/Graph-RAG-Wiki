# test_neo4j.py
# Backward compatibility - redirects to new test module
from graph.storage import GraphDB

g = GraphDB()
print(g.get_founder("Fintech X"))
print(g.get_founder("Bank Y"))
g.close()
