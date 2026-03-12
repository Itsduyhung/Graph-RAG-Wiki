import requests

job_id = '0311483b-78f0-4222-a3eb-cce0c90c21ae'
response = requests.get(f'http://localhost:8000/status/{job_id}')
if response.status_code == 200:
    data = response.json()
    print(f'Status: {data.get("status")}')
    profile = data.get('profile', {})
    print(f'Profile Achievements: {len(profile.get("achievements", []))}')
    print(f'Profile Events: {len(profile.get("events", []))}')
    print(f'Profile Fields: {profile.get("fields", [])}')
else:
    print(f"Error: {response.status_code}")
