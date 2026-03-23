"""
Test client for FastAPI Data Ingestion API
"""

import requests
import json
import time
from pathlib import Path


API_BASE = "http://localhost:8000"


def test_health():
    """Test health endpoint"""
    print("\n[TEST] Health Check")
    print("=" * 70)
    try:
        r = requests.get(f"{API_BASE}/health")
        print(json.dumps(r.json(), indent=2))
    except Exception as e:
        print(f"ERROR: {e}")


def test_upload_file(file_path: str, person_name: str = None):
    """Upload and process file"""
    print(f"\n[TEST] Upload File: {file_path}")
    print("=" * 70)
    
    if not Path(file_path).exists():
        print(f"ERROR: File not found: {file_path}")
        return None
    
    try:
        with open(file_path, 'rb') as f:
            files = {'file': f}
            params = {}
            if person_name:
                params['person_name'] = person_name
            
            r = requests.post(f"{API_BASE}/upload", files=files, params=params)
            result = r.json()
            print(json.dumps(result, indent=2))
            return result.get('job_id')
    except Exception as e:
        print(f"ERROR: {e}")
        return None


def test_status(job_id: str):
    """Check job status"""
    print(f"\n[TEST] Job Status: {job_id}")
    print("=" * 70)
    try:
        r = requests.get(f"{API_BASE}/status/{job_id}")
        result = r.json()
        print(json.dumps(result, indent=2))
        return result
    except Exception as e:
        print(f"ERROR: {e}")
        return None


def test_list_jobs():
    """List all jobs"""
    print("\n[TEST] List Jobs")
    print("=" * 70)
    try:
        r = requests.get(f"{API_BASE}/jobs")
        result = r.json()
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(f"ERROR: {e}")


def test_extract_direct(content: str, person_name: str, file_type: str = "md"):
    """Direct extraction (for testing)"""
    print(f"\n[TEST] Direct Extraction: {person_name}")
    print("=" * 70)
    try:
        payload = {
            "file_content": content,
            "person_name": person_name,
            "file_type": file_type
        }
        r = requests.post(f"{API_BASE}/extract-direct", json=payload)
        result = r.json()
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(f"ERROR: {e}")


def create_sample_markdown():
    """Create sample markdown file for testing"""
    content = """# Hoàng Đế Yên Thế

Hoàng Đế Yên Thế (1839-1889), tên ban đầu là Nguyễn Phúc Anh, adalah vị vua cuối cùng của nhà Nguyễn 
tại Đại Việt trước khi Pháp thực hiện sáp nhập hành chính.

## Tiểu sử
Yên Thế sinh ra trong gia tộc hoàng gia, là con của vua Tự Đức. Ông được huấn luyện trong các kiến thức 
Nho học truyền thống và quân sự.

## Các Thành Tựu
- Tổ chức cuộc nổi dậy chống lại quân Pháp (1885-1887)
- Lập ra căn cứ kháng chiến ở vùng Hà Tĩnh
- Tổ chức những cuộc công kích quân Pháp
- Giữ gìn chủ quyền Đại Việt trong điều kiện khó khăn

## Những Mối Quan Hệ
- Cha: Tự Đức (vua trước đó)
- Người bạn đồng hành: Phan Đình Phùng
- Đối thủ: Tổng Trư Vương Pháp ở Đông Dương
"""
    
    file_path = "sample_emperor.md"
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"\n✓ Created sample file: {file_path}")
    return file_path


def wait_for_completion(job_id: str, max_wait: int = 60):
    """Wait for job completion"""
    print(f"\n[WAIT] Waiting for job {job_id} to complete...")
    start = time.time()
    
    while time.time() - start < max_wait:
        result = test_status(job_id)
        if result and result['status'] in ['completed', 'failed']:
            return result
        time.sleep(2)
    
    print(f"WARNING: Job did not complete within {max_wait} seconds")
    return test_status(job_id)


def main():
    """Run all tests"""
    print("\n" + "=" * 70)
    print("FASTAPI DATA INGESTION API - TEST CLIENT")
    print("=" * 70)
    print("\nMake sure API server is running: python fast_api_ingestion.py")
    
    # Test 1: Health check
    test_health()
    
    # Test 2: Create and upload sample markdown
    print("\n[STEP 1] Creating sample markdown file...")
    sample_file = create_sample_markdown()
    
    print("\n[STEP 2] Uploading file...")
    job_id = test_upload_file(sample_file, person_name="Hoàng Đế Yên Thế")
    
    if job_id:
        print(f"\n[STEP 3] Waiting for processing (job_id: {job_id})...")
        result = wait_for_completion(job_id, max_wait=120)
        
        print("\n[STEP 4] Final Result:")
        print("=" * 70)
        if result['status'] == 'completed':
            print(f"✓ SUCCESS")
            print(f"  Files processed: {result['filename']}")
            print(f"  Person: {result['person_name']}")
            print(f"  Nodes created: {result['nodes_created']}")
            print(f"  Relationships created: {result['relationships_created']}")
        else:
            print(f"✗ FAILED: {result.get('error', 'Unknown error')}")
    
    # Test 3: List jobs
    test_list_jobs()
    
    # Test 4: Direct extraction (quick test)
    print("\n[STEP 5] Testing direct extraction...")
    test_extract_direct(
        content="Võ Thanh là một vị tướng quân nổi tiếng. Ông đã chiến đấu chống lại quân Pháp.",
        person_name="Võ Thanh",
        file_type="md"
    )


if __name__ == "__main__":
    try:
        main()
    except requests.exceptions.ConnectionError:
        print("\nERROR: Could not connect to API server!")
        print("Make sure the API is running:")
        print("  python fast_api_ingestion.py")
    except Exception as e:
        print(f"\nERROR: {e}")
