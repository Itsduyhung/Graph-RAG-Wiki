# FastAPI Ingestion Server v2.0.0

Updated API server with **target_person filtering** - same mindset as `test_person_extraction.py`!

## Key Features

✅ **Target Person Filtering** - Prevents data contamination (like test_person_extraction.py)
✅ **Full Profile Response** - Returns complete person profile after extraction:
  - Achievements (ACHIEVED relationships)
  - Events (PARTICIPATED_IN relationships)
  - Eras (ACTIVE_IN relationships)
  - Fields (BELONGS_TO_FIELD relationships)
  - Relationships to other people (STUDENT_OF, MENTOR_OF, etc.)

✅ **File Upload Support** - .html and .md files
✅ **Async Processing** - Background task extraction with job tracking
✅ **Interactive Docs** - Swagger UI at `/docs`

## Quick Start

### 1. Start the API Server

```powershell
python fast_api_ingestion.py
```

Output:
```
======================================================================
INGESTION API - FastAPI Server v2.0.0
Vietnamese Historical Figures - with target_person filtering
======================================================================

Starting server on http://localhost:8000

Endpoints:
  POST /upload - Upload .html/.md file with target_person
  GET /status/{job_id} - Get job status and full profile
  GET /jobs - List all jobs
  POST /extract-direct - Direct extraction (for testing)
  GET /health - Health check with Neo4j stats

API Docs: http://localhost:8000/docs
======================================================================
```

### 2. Upload a File

```bash
# Using curl
curl -F "file=@kim_dong.html" -F "target_person=Kim Đồng" http://localhost:8000/upload

# Using Python
import requests

response = requests.post(
    'http://localhost:8000/upload',
    files={'file': open('kim_dong.html', 'rb')},
    data={'target_person': 'Kim Đồng'}
)
job_id = response.json()['job_id']
print(f"Job ID: {job_id}")
```

### 3. Check Job Status & Get Profile

```bash
# Using curl
curl http://localhost:8000/status/{job_id}

# Using Python
status = requests.get(f'http://localhost:8000/status/{job_id}')
result = status.json()

# When status is "completed", result includes:
# - nodes_created: int
# - relationships_created: int
# - profile: dict with achievements, events, eras, fields, relationships
```

## API Endpoints

### POST /upload
Upload file for extraction with target_person filtering

**Parameters:**
- `file` (required): .html or .md file
- `target_person` (optional): Person name (default: filename without extension)

**Response:**
```json
{
  "job_id": "uuid",
  "target_person": "Kim Đồng",
  "filename": "kim_dong.html",
  "status": "queued",
  "message": "Processing 'Kim Đồng' from kim_dong.html. Check /status/{job_id}"
}
```

### GET /status/{job_id}
Get complete job status and extracted profile

**Response (when completed):**
```json
{
  "job_id": "uuid",
  "status": "completed",
  "filename": "kim_dong.html",
  "target_person": "Kim Đồng",
  "nodes_created": 45,
  "relationships_created": 78,
  "created_at": "2026-03-12T10:30:00",
  "completed_at": "2026-03-12T10:35:00",
  "message": "Extraction complete! Created 45 nodes and 78 relationships.",
  "profile": {
    "name": "Kim Đồng",
    "total_nodes": 45,
    "achievements": [
      {
        "name": "Thành lập Tây Sơn",
        "description": "Founding of Tây Sơn dynasty"
      },
      ...
    ],
    "events": [
      {
        "name": "Chiến dịch Tây Sơn",
        "type": "military_campaign",
        "description": "..."
      },
      ...
    ],
    "eras": [
      {
        "name": "Thời kỳ Tây Sơn",
        "period": "1778-1802"
      }
    ],
    "fields": [
      "Quân sự",
      "Chính trị"
    ],
    "relationships": [
      {
        "person": "Nguyễn Ánh",
        "type": "ENEMY_OF"
      },
      {
        "person": "Quang Trung",
        "type": "ALLY_OF"
      }
    ]
  }
}
```

### GET /jobs
List all ingestion jobs

**Response:**
```json
{
  "total": 3,
  "jobs": [
    {
      "job_id": "uuid1",
      "target_person": "Kim Đồng",
      "filename": "kim_dong.html",
      "status": "completed",
      "nodes_created": 45,
      "relationships_created": 78,
      "created_at": "2026-03-12T10:30:00",
      "completed_at": "2026-03-12T10:35:00"
    },
    ...
  ]
}
```

### POST /extract-direct
Direct text extraction without file upload (for testing)

**Parameters (all as query params):**
- `text` (required): Raw text content
- `target_person` (required): Person name
- `file_type` (optional): "html", "md", or "text" (default: "text")

**Response:**
```json
{
  "status": "completed",
  "target_person": "Kim Đồng",
  "nodes_created": 25,
  "relationships_created": 40,
  "profile": { ... },
  "timestamp": "2026-03-12T10:40:00"
}
```

### GET /health
Health check with Neo4j stats

**Response:**
```json
{
  "status": "healthy",
  "database": "demo",
  "nodes_total": 1289,
  "relationships_total": 1784,
  "api_version": "2.0.0",
  "timestamp": "2026-03-12T10:45:00"
}
```

## How It Works

1. **Upload or send text** → API creates a job with unique `job_id`
2. **Background processing**:
   - Extract clean text from HTML/Markdown
   - Create Person node if needed
   - Call `CustomGraphExtractor.enrich_text()` with `link_to_person=target_person`
   - LLM extracts only information related to target_person
   - Build Achievement, Event, Era, Field, and Relationship nodes
3. **Query Neo4j** to get complete profile after extraction
4. **Return full profile** in status response

## Key Differences from v1.0

| Feature | v1.0 | v2.0 |
|---------|------|------|
| **Target Person Filtering** | ❌ No | ✅ Yes (link_to_person param) |
| **Profile Response** | Basic stats only | ✅ Full person profile |
| **Thread Safety** | ❌ No | ✅ Yes (jobs_lock) |
| **Job Tracking** | Simple | ✅ Comprehensive with timestamps |
| **Achievement/Event** | Mixed | ✅ Separate with proper typing |
| **Relationship Details** | ❌ No | ✅ All 10 relationship types |

## Testing Examples

### Test with Python script

```python
import requests
import json
import time

API_URL = "http://localhost:8000"

# 1. Upload file
with open("kim_dong.html", "rb") as f:
    response = requests.post(
        f"{API_URL}/upload",
        files={'file': f},
        data={'target_person': 'Kim Đồng'}
    )
    
job_id = response.json()['job_id']
print(f"✓ Job created: {job_id}")

# 2. Wait for completion
while True:
    status = requests.get(f"{API_URL}/status/{job_id}")
    result = status.json()
    
    if result['status'] == 'completed':
        print(f"\n✓ Extraction complete!")
        print(f"  Nodes: {result['nodes_created']}")
        print(f"  Relationships: {result['relationships_created']}")
        
        profile = result['profile']
        print(f"\n📋 Profile for {profile['name']}:")
        print(f"  - Total nodes: {profile['total_nodes']}")
        print(f"  - Achievements: {len(profile['achievements'])}")
        print(f"  - Events: {len(profile['events'])}")
        print(f"  - Eras: {len(profile['eras'])}")
        print(f"  - Fields: {len(profile['fields'])}")
        print(f"  - Relationships: {len(profile['relationships'])}")
        break
    
    print(f"Status: {result['status']}...")
    time.sleep(2)
```

### Test with curl

```bash
# 1. Upload
JOB_ID=$(curl -s -F "file=@kim_dong.html" -F "target_person=Kim Đồng" \
  http://localhost:8000/upload | jq -r '.job_id')

echo "Job ID: $JOB_ID"

# 2. Check status (wait a few seconds)
curl http://localhost:8000/status/$JOB_ID | jq .

# 3. List all jobs
curl http://localhost:8000/jobs | jq .
```

## Notes

- **target_person** - When not provided, defaults to filename without extension
- **Async Processing** - Extraction happens in background, check status with `/status/{job_id}`
- **Data Quality** - target_person filtering prevents contamination from other people's data
- **Neo4j Connection** - Requires NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD in .env
- **Limits** - WikiChunk search uses LIMIT 20 (see test_person_extraction.py for logic)

---

**Version:** 2.0.0
**Created:** 2026-03-12
**Author:** Agent
**Purpose:** Production-grade ingestion API with data quality filters
