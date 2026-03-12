"""
Test client for FastAPI Ingestion Server v2.0.0
Demonstrates upload flow with target_person filtering and full profile retrieval
"""

import requests
import json
import time
import sys
from pathlib import Path

API_URL = "http://localhost:8000"


def upload_file(filepath: str, target_person: str = None) -> str:
    """Upload file and return job_id"""
    print(f"\n📤 Uploading {filepath}...")
    
    if not Path(filepath).exists():
        print(f"❌ File not found: {filepath}")
        return None
    
    with open(filepath, 'rb') as f:
        files = {'file': f}
        data = {}
        if target_person:
            data['target_person'] = target_person
        
        response = requests.post(f"{API_URL}/upload", files=files, data=data)
    
    if response.status_code == 200:
        result = response.json()
        print(f"✓ Upload successful!")
        print(f"  Job ID: {result['job_id']}")
        print(f"  Target: {result['target_person']}")
        print(f"  File: {result['filename']}")
        return result['job_id']
    else:
        print(f"❌ Upload failed: {response.status_code}")
        print(f"Error: {response.json()}")
        return None


def wait_for_completion(job_id: str, timeout_seconds: int = 120) -> dict:
    """Wait for job to complete and return full result"""
    print(f"\n⏳ Processing job {job_id}...")
    
    start_time = time.time()
    
    while True:
        elapsed = time.time() - start_time
        if elapsed > timeout_seconds:
            print(f"❌ Timeout after {timeout_seconds} seconds")
            return None
        
        response = requests.get(f"{API_URL}/status/{job_id}")
        
        if response.status_code != 200:
            print(f"❌ Error getting status: {response.status_code}")
            return None
        
        result = response.json()
        
        if result['status'] == 'completed':
            print(f"✓ Extraction complete!")
            return result
        elif result['status'] == 'failed':
            print(f"❌ Job failed!")
            print(f"Error: {result.get('error', 'Unknown error')}")
            return None
        else:
            # Still processing
            print(f"  Status: {result['status']} ({elapsed:.0f}s elapsed)")
            time.sleep(2)


def print_profile(result: dict):
    """Pretty print the extracted profile"""
    profile = result.get('profile', {})
    
    print(f"\n{'='*70}")
    print(f"📋 PROFILE: {profile.get('name', 'Unknown')}")
    print(f"{'='*70}")
    
    # Summary stats
    print(f"\n📊 Summary:")
    print(f"  Total nodes: {profile.get('total_nodes', 0)}")
    print(f"  Nodes created: {result.get('nodes_created', 0)}")
    print(f"  Relationships created: {result.get('relationships_created', 0)}")
    
    # Achievements
    achievements = profile.get('achievements', [])
    if achievements:
        print(f"\n🏆 Achievements ({len(achievements)}):")
        for ach in achievements[:5]:  # Show first 5
            print(f"  • {ach['name']}")
            if ach.get('description'):
                print(f"    → {ach['description'][:60]}...")
        if len(achievements) > 5:
            print(f"  ... and {len(achievements) - 5} more")
    
    # Events
    events = profile.get('events', [])
    if events:
        print(f"\n🎯 Events ({len(events)}):")
        for evt in events[:5]:
            print(f"  • {evt['name']} ({evt.get('type', 'unknown')})")
            if evt.get('description'):
                print(f"    → {evt['description'][:60]}...")
        if len(events) > 5:
            print(f"  ... and {len(events) - 5} more")
    
    # Eras
    eras = profile.get('eras', [])
    if eras:
        print(f"\n📅 Eras ({len(eras)}):")
        for era in eras:
            print(f"  • {era['name']} ({era.get('period', 'unknown')})")
    
    # Fields
    fields = profile.get('fields', [])
    if fields:
        print(f"\n🔬 Fields ({len(fields)}):")
        for field in fields:
            print(f"  • {field}")
    
    # Relationships
    relationships = profile.get('relationships', [])
    if relationships:
        print(f"\n👥 Relationships ({len(relationships)}):")
        for rel in relationships:
            print(f"  • {rel['person']} ({rel['type']})")
    
    print(f"\n{'='*70}\n")


def test_direct_extraction(text: str, target_person: str):
    """Test direct extraction endpoint"""
    print(f"\n📝 Testing direct extraction for '{target_person}'...")
    
    response = requests.post(
        f"{API_URL}/extract-direct",
        params={
            'text': text,
            'target_person': target_person,
            'file_type': 'text'
        }
    )
    
    if response.status_code == 200:
        result = response.json()
        print(f"✓ Direct extraction successful!")
        print_profile(result)
        return result
    else:
        print(f"❌ Direct extraction failed: {response.status_code}")
        print(f"Error: {response.json()}")
        return None


def list_jobs():
    """List all jobs"""
    print(f"\n📋 Getting all jobs...")
    
    response = requests.get(f"{API_URL}/jobs")
    
    if response.status_code == 200:
        data = response.json()
        print(f"\nTotal jobs: {data['total']}")
        
        for job in data['jobs']:
            print(f"\n  Job ID: {job['job_id'][:8]}...")
            print(f"    Person: {job['target_person']}")
            print(f"    File: {job['filename']}")
            print(f"    Status: {job['status']}")
            if job['nodes_created'] > 0:
                print(f"    Nodes: {job['nodes_created']}")
                print(f"    Relationships: {job['relationships_created']}")
    else:
        print(f"❌ Failed to get jobs: {response.status_code}")


def health_check():
    """Check API health"""
    print(f"\n🏥 Checking API health...")
    
    response = requests.get(f"{API_URL}/health")
    
    if response.status_code == 200:
        data = response.json()
        print(f"✓ API is {data['status']}")
        print(f"  Database: {data.get('database', 'unknown')}")
        print(f"  Total nodes: {data.get('nodes_total', 0)}")
        print(f"  Total relationships: {data.get('relationships_total', 0)}")
        return True
    else:
        print(f"❌ API is not responding properly")
        return False


def main():
    """Main test flow"""
    print("\n" + "="*70)
    print("FASTAPI INGESTION SERVER v2.0.0 - Test Client")
    print("="*70)
    
    # Check health
    if not health_check():
        print("\n⚠️  API is not available. Start it with: python fast_api_ingestion.py")
        sys.exit(1)
    
    # Example 1: Test with a real file if it exists
    test_file = "kim_dong.html"
    if Path(test_file).exists():
        print(f"\n{'='*70}")
        print(f"Test 1: Upload {test_file}")
        print(f"{'='*70}")
        
        job_id = upload_file(test_file, target_person="Kim Đồng")
        if job_id:
            result = wait_for_completion(job_id)
            if result:
                print_profile(result)
    else:
        print(f"\n⚠️  Test file '{test_file}' not found, skipping file upload test")
    
    # Example 2: Direct extraction test
    print(f"\n{'='*70}")
    print(f"Test 2: Direct Extraction")
    print(f"{'='*70}")
    
    sample_text = """
    Kim Đồng là một anh hùng dân tộc của Việt Nam. 
    Ông đã tham gia vào cuộc khởi nghĩa chống lại thực dân Pháp.
    Kim Đồng được mệnh danh là vua trẻ tuổi nhất.
    Ông có mối quan hệ học trò với Trần Hưng Đạo.
    """
    
    test_direct_extraction(sample_text, "Kim Đồng")
    
    # Example 3: List all jobs
    print(f"\n{'='*70}")
    print(f"Test 3: List All Jobs")
    print(f"{'='*70}")
    
    list_jobs()
    
    print(f"\n{'='*70}")
    print("✓ All tests completed!")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
