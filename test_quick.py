"""
Simple test: Upload README.md to API
"""
import requests
import json
import time

API_BASE = "http://localhost:8000"


def quick_test():
    print("\n" + "=" * 70)
    print("FASTAPI DATA INGESTION - QUICK TEST")
    print("=" * 70)
    
    # Test 1: Health check
    print("\n[1/3] Health Check...")
    try:
        r = requests.get(f"{API_BASE}/health", timeout=5)
        if r.status_code == 200:
            print("✓ API is online")
            print(json.dumps(r.json(), indent=2))
        else:
            print(f"✗ API returned {r.status_code}")
            return
    except Exception as e:
        print(f"✗ Cannot connect to API: {e}")
        print("  → Start API server first: python fast_api_ingestion.py")
        return
    
    # Test 2: Upload README.md
    print("\n[2/3] Uploading README.md...")
    try:
        with open('README.md', 'rb') as f:
            r = requests.post(
                f"{API_BASE}/upload",
                files={'file': f},
                params={'person_name': 'Project Documentation'},
                timeout=10
            )
        
        if r.status_code == 200:
            result = r.json()
            job_id = result.get('job_id')
            print(f"✓ File uploaded successfully")
            print(f"  Job ID: {job_id}")
            print(f"  Status: {result.get('status')}")
            print(f"  Person: {result.get('person_name')}")
            
            # Test 3: Check status
            print("\n[3/3] Checking job progress...")
            print("  Waiting for processing...")
            
            for i in range(30):  # Wait up to 60 seconds
                time.sleep(2)
                try:
                    status_r = requests.get(f"{API_BASE}/status/{job_id}", timeout=5)
                    status = status_r.json()
                    
                    if status['status'] == 'completed':
                        print(f"\n✓ Processing completed!")
                        print(f"  Nodes created: {status['nodes_created']}")
                        print(f"  Relationships created: {status['relationships_created']}")
                        return True
                    elif status['status'] == 'failed':
                        print(f"\n✗ Processing failed!")
                        print(f"  Error: {status.get('error')}")
                        return False
                    else:
                        status_text = status['status']
                        print(f"  → {status_text}... ({i*2}s)")
                        
                except Exception as e:
                    print(f"  Error checking status: {e}")
            
            print("\nⓘ Job still processing (timeout after 60s)")
            print(f"  Check status later: GET /status/{job_id}")
            
        else:
            print(f"✗ Upload failed: {r.status_code}")
            print(r.text)
    
    except FileNotFoundError:
        print("✗ README.md not found")
        print("  Try with another file: ARCHITECTURE.md, HUONG_DAN.md, etc.")
    except Exception as e:
        print(f"✗ Error: {e}")


if __name__ == "__main__":
    quick_test()
