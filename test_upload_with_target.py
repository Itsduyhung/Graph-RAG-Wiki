import requests
import time

# Upload file WITH target_person specified
with open('test_kim_dong.html', 'rb') as f:
    r = requests.post(
        'http://localhost:8000/upload',
        files={'file': f},
        data={'target_person': 'Kim Đồng'},  # <-- Specify target person!
        timeout=10
    )

result = r.json()
job_id = result['job_id']

print(f"✓ File uploaded")
print(f"  Job ID: {job_id}")
print(f"  Target: {result['target_person']}")

# Wait for completion
print(f"\n⏳ Waiting for completion...")
for i in range(30):
    time.sleep(1)
    
    r_status = requests.get(f'http://localhost:8000/status/{job_id}')
    status = r_status.json()
    
    if status['status'] == 'completed':
        print(f"✓ COMPLETED!")
        
        print(f"\nExtraction Results:")
        print(f"  Nodes created: {status.get('nodes_created', 0)}")
        print(f"  Relationships created: {status.get('relationships_created', 0)}")
        
        profile = status.get('profile', {})
        print(f"\n📊 Profile:")
        print(f"  Name: {profile.get('name')}")
        print(f"  Total nodes: {profile.get('total_nodes', 0)}")
        print(f"  Achievements: {len(profile.get('achievements', []))}")
        print(f"  Events: {len(profile.get('events', []))}")
        print(f"  Fields: {len(profile.get('fields', []))}")
        print(f"  Eras: {len(profile.get('eras', []))}")
        
        print(f"\n✅ Achievements ({len(profile.get('achievements', []))}):")
        for a in profile.get('achievements', [])[:5]:
            print(f"   • {a['name']}")
        if len(profile.get('achievements', [])) > 5:
            print(f"   ... and {len(profile.get('achievements', [])) - 5} more")
        
        print(f"\n✅ Events ({len(profile.get('events', []))}):")
        for e in profile.get('events', [])[:5]:
            print(f"   • {e['name']}")
        if len(profile.get('events', [])) > 5:
            print(f"   ... and {len(profile.get('events', [])) - 5} more")
        
        print(f"\n✅ Fields: {profile.get('fields', [])}")
        
        break
    elif status['status'] == 'failed':
        print(f"❌ FAILED: {status.get('error')}")
        break
    else:
        print(f"  Status: {status['status']}")
