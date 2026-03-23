import requests

job_id = '89dcde6c-a850-43db-97d2-1d5e0ac2c43c'
r = requests.get(f'http://localhost:8000/status/{job_id}')
data = r.json()
print(f'✓ Status: {data["status"]}')
print(f'✓ Nodes created: {data["nodes_created"]}')
print(f'✓ Relationships created: {data["relationships_created"]}')
profile = data['profile']
print(f'✓ Achievements in Neo4j: {len(profile["achievements"])}')
print(f'✓ Events in Neo4j: {len(profile["events"])}')
print(f'✓ Fields in Neo4j: {profile["fields"]}')
print()
print('Sample achievements:')
for a in profile["achievements"][:3]:
    print(f'  - {a["name"]}')
