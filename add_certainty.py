import sys
sys.path.append('.')
from graph.storage import GraphDB

db = GraphDB()
with db.driver.session(database=db.database) as session:
    # Add certainty properties to PREDECESSOR_OF relationships
    session.run('MATCH (p:Person)-[r:PREDECESSOR_OF]->(target:Person) SET r.type = "official"')
    print('Added certainty properties to PREDECESSOR_OF relationships')

    # Verify
    result = session.run('MATCH (p:Person)-[r:PREDECESSOR_OF]->(target:Person) RETURN p.name, target.name, r.type LIMIT 5')
    print('Updated relationships:')
    for r in result:
        print('  ' + r['p.name'] + ' -> ' + r['target.name'] + ' (type: ' + r['r.type'] + ')')