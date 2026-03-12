"""
Quick Start Guide for Data Ingestion API
"""

def print_guide():
    guide = """
╔════════════════════════════════════════════════════════════════════════════╗
║                   DATA INGESTION API - QUICK START GUIDE                   ║
╚════════════════════════════════════════════════════════════════════════════╝

OVERVIEW:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

FastAPI server for data ingestion:
  • Upload .html or .md files
  • Extract content using Gemini 2.0 Flash (YEScale API)
  • Auto-generate Achievement, Event, Era, Field nodes
  • Create person-to-person relationships
  • Save to Neo4j


SETUP:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Install dependencies:
   
   pip install fastapi uvicorn requests

   Or in the virtual environment:
   
   .venv\\Scripts\\pip install fastapi uvicorn requests

2. Verify environment variables are set (.env file):
   
   YESCALE_API_KEY=<your_api_key>
   YESCALE_BASE_URL=https://api.yescale.io/v1
   NEO4J_URI=bolt://localhost:7687
   NEO4J_USER=neo4j
   NEO4J_PASSWORD=<your_password>
   NEO4J_DB=demo


RUNNING THE API SERVER:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Start the server:

  cd d:\\Agent_Graph
  python fast_api_ingestion.py

Or with direct uvicorn command:

  uvicorn fast_api_ingestion:app --reload --host 0.0.0.0 --port 8000

Expected output:
  
  INFO:     Uvicorn running on http://0.0.0.0:8000
  INFO:     Application startup complete


INTERACTIVE API DOCS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Open in browser:

  http://localhost:8000/docs  (Swagger UI - interactive)
  http://localhost:8000/redoc (ReDoc - documentation)


API ENDPOINTS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Health Check
   ─────────────
   GET /health
   
   Response: {
     "status": "healthy",
     "api": "running",
     "neo4j": "connected",
     "total_nodes": 1234,
     "jobs_in_queue": 2
   }


2. Upload File for Processing
   ──────────────────────────
   POST /upload
   
   Parameters:
     - file: File (.html or .md)  [required]
     - person_name: String        [optional, default: filename without extension]
   
   Example (Python):
   
     import requests
     
     with open('my_file.md', 'rb') as f:
         r = requests.post(
             'http://localhost:8000/upload',
             files={'file': f},
             params={'person_name': 'Hoàng Đế Yên Thế'}
         )
     
     job_id = r.json()['job_id']
   
   Response:
   
     {
       "job_id": "abc-123-def",
       "filename": "my_file.md",
       "person_name": "Hoàng Đế Yên Thế",
       "status": "queued",
       "message": "File queued for processing..."
     }


3. Check Job Status
   ────────────────
   GET /status/{job_id}
   
   Example:
   
     requests.get('http://localhost:8000/status/abc-123-def')
   
   Response:
   
     {
       "job_id": "abc-123-def",
       "status": "completed",
       "filename": "my_file.md",
       "person_name": "Hoàng Đế Yên Thế",
       "nodes_created": 45,
       "relationships_created": 38,
       "error": null,
       "timestamp": "2026-03-12T10:30:45.123456"
     }
   
   Status values: queued, processing, completed, failed


4. List All Jobs
   ──────────────
   GET /jobs
   
   Response:
   
     {
       "total_jobs": 3,
       "jobs": [...]
     }


5. Direct Extraction (Testing)
   ──────────────────────────
   POST /extract-direct
   
   Body (JSON):
   
     {
       "file_content": "Đoạn văn bản ở đây...",
       "person_name": "Hoàng Đế Yên Thế",
       "file_type": "md"
     }
   
   Response:
   
     {
       "status": "completed",
       "person_name": "Hoàng Đế Yên Thế",
       "nodes_created": 45,
       "relationships_created": 38,
       "timestamp": "2026-03-12T10:30:45.123456"
     }


TESTING WITH CURL:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Health check:
   
   curl http://localhost:8000/health

2. Upload file:
   
   curl -X POST http://localhost:8000/upload \\
     -F "file=@my_file.md" \\
     -F "person_name=Hoàng Đế Yên Thế"

3. Check status:
   
   curl http://localhost:8000/status/{job_id}


TESTING WITH PYTHON CLIENT:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Full test script already provided:

  python test_api_client.py

This will:
  ✓ Check API health
  ✓ Create sample markdown file
  ✓ Upload and process it
  ✓ Watch progress
  ✓ Show final results
  ✓ Test direct extraction


FILE FORMAT SUPPORT:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Markdown (.md):
  • Plain text with markdown syntax
  • Content extracted as-is
  • Example:
    
    # Hoàng Đế Yên Thế
    Các thông tin... với **chữ đậm** và _chữ nghiêng_

HTML (.html):
  • HTML files
  • Scripts and styles removed
  • Tags stripped
  • Entities decoded
  • Whitespace normalized
  • Example:
    
    <html>
      <body>
        <h1>Hoàng Đế Yên Thế</h1>
        <p>Các thông tin...</p>
      </body>
    </html>


EXTRACTION PROCESS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. File uploaded → Text extracted
2. Person node created (if not exists)
3. Content sent to Gemini 2.0 Flash
4. LLM extracts:
   - Achievements (personal accomplishments)
   - Events (historical occurrences)
   - Eras (time periods)
   - Fields (domains/categories)
   - Relationships (person-to-person connections)
5. All nodes created in Neo4j
6. All relationships established


RELATIONSHIP TYPES:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Person-to-Person:
  • FATHER_OF / MOTHER_OF
  • CHILD_OF
  • SPOUSE_OF
  • SIBLING_OF
  • MENTOR_OF / STUDENT_OF
  • ALLY_OF / ENEMY_OF
  • SUCCESSOR_OF
  • HAS_ROLE

Other:
  • ACHIEVED (Person → Achievement)
  • PARTICIPATED_IN (Person → Event)
  • ACTIVE_IN (Person → Era/Field)
  • BELONGS_TO_DYNASTY


EXAMPLE WORKFLOW:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Prepare your files:
   
   Create: hoang_de.md
   Content: Information about Hoàng Đế Yên Thế...

2. Terminal 1 - Start API:
   
   python fast_api_ingestion.py
   
   Wait for "Application startup complete"

3. Terminal 2 - Run test:
   
   python test_api_client.py
   
   Or manually:
   
   curl -X POST http://localhost:8000/upload \\
     -F "file=@hoang_de.md" \\
     -F "person_name=Hoàng Đế Yên Thế"
   
   Note the job_id from response

4. Check progress:
   
   curl http://localhost:8000/status/YOUR_JOB_ID
   
   Wait for status="completed"

5. Query Neo4j:
   
   MATCH (p:Person {name: "Hoàng Đế Yên Thế"})-[r]-()
   RETURN p, r, () ORDER BY type(r)
   
   See all connected nodes and relationships!


TROUBLESHOOTING:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Issue: fastapi not found
  → pip install fastapi uvicorn

Issue: Cannot connect to Neo4j
  → Check .env file has correct NEO4J_* settings
  → Verify Neo4j is running

Issue: No nodes created
  → Check API health: curl http://localhost:8000/health
  → Verify Gemini API key in .env
  → Check job error in /status/{job_id}

Issue: File too large
  → API may timeout for very large files
  → Try splitting into smaller chunks


FEATURES:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✓ Async/Background processing
✓ Job tracking with unique IDs
✓ Multiple file uploads simultaneously
✓ HTML and Markdown support
✓ Automatic Person node creation
✓ Vietnamese text support (UTF-8)
✓ All output in Vietnamese
✓ Detailed relationship semantics
✓ Complete API documentation
✓ Health checks and monitoring


═════════════════════════════════════════════════════════════════════════════

Ready to use? 
  
  1. pip install fastapi uvicorn requests
  2. python fast_api_ingestion.py
  3. python test_api_client.py (in another terminal)

═════════════════════════════════════════════════════════════════════════════
"""
    print(guide)


if __name__ == "__main__":
    print_guide()
