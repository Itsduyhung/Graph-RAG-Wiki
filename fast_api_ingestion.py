"""
FastAPI server for data ingestion: Upload .html/.md files → Extract with Gemini → Save to Neo4j
Same mindset as test_person_extraction.py - enriches graph with target_person filtering
"""

from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks, Form
from pydantic import BaseModel
from typing import Optional, Dict, Any
import os
import uuid
from datetime import datetime
from dotenv import load_dotenv
import re
import html
from threading import Lock

from pipeline.custom_graph_extractor import CustomGraphExtractor
from graph.storage import GraphDB

from api.schemas import QueryRequest, QueryResponse
from pipeline.pg_to_neo4j import PostgresToNeo4jMigrator
from pydantic import Field
from typing import Optional, Dict, Any
from pipeline.query_pipeline import ask_agent

load_dotenv()

app = FastAPI(
    title="Ingestion API - Vietnamese Historical Figures",
    version="2.1.0",
    description="Upload files and extract person profiles with target_person filtering + new endpoints"
)

# Store ingestion jobs status (thread-safe)
ingestion_jobs = {}
jobs_lock = Lock()


class JobResult(BaseModel):
    """Complete job result with profile data"""
    job_id: str
    status: str  # queued, processing, completed, failed
    filename: str
    target_person: str
    message: str = ""
    nodes_created: int = 0
    relationships_created: int = 0
    profile: Optional[Dict[str, Any]] = None  # Full person profile from Neo4j
    error: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None
    source_type: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    pg_dsn: Optional[str] = None
    table_name: Optional[str] = None
    limit: Optional[int] = None


class UploadResponse(BaseModel):
    """Upload response"""
    job_id: str
    target_person: str
    filename: str
    status: str
    message: str


def extract_text_from_file(file_content: str, file_type: str) -> str:
    """Extract clean text from HTML or Markdown"""
    if file_type.lower() == "html":
        # Remove script and style tags
        text = re.sub(r'<script[^>]*>.*?</script>', '', file_content, flags=re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        # Decode HTML entities
        text = html.unescape(text)
        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    else:
        # Markdown: return as-is
        return file_content.strip()


def get_person_profile(person_name: str) -> Dict[str, Any]:
    """Get complete person profile from Neo4j"""
    db = GraphDB()
    profile = {
        "name": person_name,
        "achievements": [],
        "events": [],
        "eras": [],
        "fields": [],
        "relationships": [],
        "total_nodes": 0
    }
    
    try:
        with db.driver.session(database=db.database) as session:
            # Count total nodes for this person
            total = session.run(
                """
                MATCH (p:Person {name: $name})
                OPTIONAL MATCH (p)-[r]-(n)
                RETURN COUNT(DISTINCT n) + 1 as total
                """,
                name=person_name
            ).single()
            profile["total_nodes"] = total["total"] if total else 1
            
            # Get achievements
            achievements = session.run(
                """
                MATCH (p:Person {name: $name})-[:ACHIEVED]->(a:Achievement)
                RETURN a.name as name, a.description as description
                ORDER BY a.name
                """,
                name=person_name
            ).data()
            profile["achievements"] = [
                {"name": a["name"], "description": a.get("description", "")}
                for a in achievements
            ]
            
            # Get events
            events = session.run(
                """
                MATCH (p:Person {name: $name})-[:PARTICIPATED_IN]->(e:Event)
                RETURN e.name as name, e.event_type as type, e.description as description
                ORDER BY e.name
                """,
                name=person_name
            ).data()
            profile["events"] = [
                {"name": e["name"], "type": e.get("type", ""), "description": e.get("description", "")}
                for e in events
            ]
            
            # Get eras
            eras = session.run(
                """
                MATCH (p:Person {name: $name})-[:ACTIVE_IN]->(e:Era)
                RETURN e.name as name, e.period as period
                ORDER BY e.name
                """,
                name=person_name
            ).data()
            profile["eras"] = [
                {"name": e["name"], "period": e.get("period", "")}
                for e in eras
            ]
            
            # Get fields
            fields = session.run(
                """
                MATCH (p:Person {name: $name})-[:ACTIVE_IN]->(f:Field)
                RETURN f.name as name
                ORDER BY f.name
                """,
                name=person_name
            ).data()
            profile["fields"] = [f["name"] for f in fields]
            
            # Get person relationships
            relationships = session.run(
                """
                MATCH (p:Person {name: $name})-[r:STUDENT_OF|MENTOR_OF|FATHER_OF|MOTHER_OF|CHILD_OF|SPOUSE_OF|SIBLING_OF|ALLY_OF|ENEMY_OF|SUCCESSOR_OF]-(other:Person)
                RETURN other.name as related_person, TYPE(r) as relationship_type
                ORDER BY other.name
                """,
                name=person_name
            ).data()
            profile["relationships"] = [
                {"person": r["related_person"], "type": r["relationship_type"]}
                for r in relationships
            ]
            
    except Exception as e:
        profile["error"] = f"Could not retrieve full profile: {str(e)}"
    
    return profile


def process_ingestion(job_id: str, file_content: str, target_person: str, file_type: str, filename: str):
    """Background task: extract, enrich, and build complete profile"""
    try:
        with jobs_lock:
            if job_id in ingestion_jobs:
                ingestion_jobs[job_id]["status"] = "processing"
        
        print(f"\n[JOB {job_id[:8]}] Starting extraction for '{target_person}'")
        
        # Extract text
        text = extract_text_from_file(file_content, file_type)
        if not text or len(text.strip()) == 0:
            raise ValueError("No content extracted from file")
        
        print(f"[JOB {job_id[:8]}] Extracted text length: {len(text)} chars")
        
        # Create Person node if missing
        db = GraphDB()
        with db.driver.session(database=db.database) as session:
            person_exists = session.run(
                "MATCH (p:Person {name: $name}) RETURN COUNT(p) as cnt",
                name=target_person
            ).single()
            
            if person_exists["cnt"] == 0:
                session.run(
                    "CREATE (p:Person {name: $name}) RETURN p",
                    name=target_person
                )
                print(f"[JOB {job_id[:8]}] Created Person node: '{target_person}'")
            else:
                print(f"[JOB {job_id[:8]}] Person node already exists: '{target_person}'")
        
        # Extract with target_person filtering (like test_person_extraction.py)
        print(f"[JOB {job_id[:8]}] Starting LLM extraction with link_to_person='{target_person}'...")
        extractor = CustomGraphExtractor()
        nodes_created, rels_created = extractor.enrich_text(
            text,
            source_chunk_id=filename,
            link_to_person=target_person  # Enable target_person filtering!
        )
        
        print(f"[JOB {job_id[:8]}] ✓ Extraction complete!")
        print(f"[JOB {job_id[:8]}]   Nodes created: {nodes_created}")
        print(f"[JOB {job_id[:8]}]   Relationships created: {rels_created}")
        
        # Get complete profile after extraction
        print(f"[JOB {job_id[:8]}] Querying Neo4j for complete profile...")
        profile = get_person_profile(target_person)
        
        print(f"[JOB {job_id[:8]}] 📋 Profile Summary:")
        print(f"[JOB {job_id[:8]}]   Total nodes: {profile.get('total_nodes', 0)}")
        print(f"[JOB {job_id[:8]}]   Achievements: {len(profile.get('achievements', []))}")
        print(f"[JOB {job_id[:8]}]   Events: {len(profile.get('events', []))}")
        print(f"[JOB {job_id[:8]}]   Eras: {len(profile.get('eras', []))}")
        print(f"[JOB {job_id[:8]}]   Fields: {len(profile.get('fields', []))}")
        print(f"[JOB {job_id[:8]}]   Relationships: {len(profile.get('relationships', []))}")
        
        # Update job as completed
        with jobs_lock:
            if job_id in ingestion_jobs:
                ingestion_jobs[job_id]["status"] = "completed"
                ingestion_jobs[job_id]["nodes_created"] = nodes_created
                ingestion_jobs[job_id]["relationships_created"] = rels_created
                ingestion_jobs[job_id]["profile"] = profile
                ingestion_jobs[job_id]["completed_at"] = datetime.now().isoformat()
                ingestion_jobs[job_id]["message"] = (
                    f"Extraction complete! Created {nodes_created} nodes and {rels_created} relationships."
                )
        
        print(f"[JOB {job_id[:8]}] ✅ Job completed successfully!")
    
    except Exception as e:
        import traceback
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        print(f"[JOB {job_id[:8]}] ❌ ERROR: {error_msg}")
        
        with jobs_lock:
            if job_id in ingestion_jobs:
                ingestion_jobs[job_id]["status"] = "failed"
                ingestion_jobs[job_id]["error"] = str(e)
                ingestion_jobs[job_id]["completed_at"] = datetime.now().isoformat()


@app.get("/")
async def root():
    """Root endpoint with API info"""
    return {
        "status": "ok",
        "title": "Ingestion API - Vietnamese Historical Figures",
        "version": "2.0.0",
        "message": "Upload .html/.md files to extract person profiles with Neo4j",
        "endpoints": {
            "upload": "POST /upload - Upload file with target_person",
            "status": "GET /status/{job_id} - Get job status and profile",
            "jobs": "GET /jobs - List all jobs",
            "extract_direct": "POST /extract-direct - Direct extraction for testing",
            "docs": "GET /docs - Interactive API docs (Swagger UI)",
            "redoc": "GET /redoc - ReDoc documentation"
        },
        "example_usage": {
            "curl": "curl -F 'file=@file.html' -F 'target_person=Kim Đồng' http://localhost:8000/upload",
            "python": "requests.post('http://localhost:8000/upload', files={'file': open('file.html', 'rb')}, data={'target_person': 'Kim Đồng'})"
        }
    }


@app.post("/upload", response_model=UploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    target_person: str = Form(None),
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    """
    Upload .html or .md file for extraction with Neo4j
    
    Uses target_person filtering to prevent data contamination.
    Extracts according to test_person_extraction.py logic.
    
    Args:
        file: Upload .html or .md file
        target_person: Name of person to extract (default: filename without extension)
    
    Returns:
        UploadResponse with job_id for tracking
    """
    filename = file.filename
    file_ext = filename.split('.')[-1].lower()
    
    # Validate file type
    if file_ext not in ['html', 'md']:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: .{file_ext}. Use .html or .md"
        )
    
    # Set target_person from filename if not provided
    if not target_person:
        target_person = filename.rsplit('.', 1)[0]
    
    try:
        # Read file
        content = await file.read()
        file_content = content.decode('utf-8')
        
        if not file_content or len(file_content.strip()) == 0:
            raise HTTPException(status_code=400, detail="File is empty")
        
        # Create job
        job_id = str(uuid.uuid4())
        with jobs_lock:
            ingestion_jobs[job_id] = {
                "job_id": job_id,
                "filename": filename,
                "target_person": target_person,
                "status": "queued",
                "nodes_created": 0,
                "relationships_created": 0,
                "error": None,
                "created_at": datetime.now().isoformat(),
                "completed_at": None,
                "profile": None,
                "message": "Queued for processing"
            }
        
        # Queue background processing
        background_tasks.add_task(
            process_ingestion,
            job_id,
            file_content,
            target_person,
            file_ext,
            filename
        )
        
        return {
            "job_id": job_id,
            "target_person": target_person,
            "filename": filename,
            "status": "queued",
            "message": f"Processing '{target_person}' from {filename}. Check /status/{job_id}"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


class IngestNewRequest(BaseModel):
    """Request for /ingest_new - extended ingestion config"""
    text: str
    source_type: str = Field("text", description="wiki|doc|custom")
    target_person: Optional[str] = None
    config: Optional[Dict[str, Any]] = {}


@app.post("/ingest_new", response_model=JobResult)
async def ingest_new(request: IngestNewRequest, background_tasks: BackgroundTasks):
    """
    New ingestion endpoint - text-based with extra config
    
    Extended version of /upload for programmatic use.
    """
    job_id = str(uuid.uuid4())
    with jobs_lock:
        ingestion_jobs[job_id] = {
            "job_id": job_id,
            "filename": f"{request.source_type}.txt",
            "target_person": request.target_person or "unknown",
            "status": "queued",
            "nodes_created": 0,
            "relationships_created": 0,
            "error": None,
            "created_at": datetime.now().isoformat(),
            "completed_at": None,
            "profile": None,
            "source_type": request.source_type,
            "config": request.config,
            "message": "Queued for new ingestion pipeline"
        }
    
    # Reuse same background task (process_ingestion accepts file_type="text")
    background_tasks.add_task(
        process_ingestion,
        job_id,
        request.text,
        request.target_person or "unknown",
        "text",
        f"{request.source_type}.txt"
    )
    
    # Return immediate queued response
    with jobs_lock:
        queued_job = dict(ingestion_jobs[job_id])
    return JobResult(**queued_job)


class MigrateNewRequest(BaseModel):
    """Request for /migrate_new"""
    pg_dsn: str
    table_name: str = "persons"
    limit: Optional[int] = None


@app.post("/migrate_new", response_model=JobResult)
async def migrate_new(request: MigrateNewRequest, background_tasks: BackgroundTasks):
    """
    New migration endpoint - Postgres → Neo4j as background job
    """
    job_id = str(uuid.uuid4())
    with jobs_lock:
        ingestion_jobs[job_id] = {
            "job_id": job_id,
            "filename": "migration",
            "target_person": f"migrate_{request.table_name}",
            "status": "queued",
            "nodes_created": 0,
            "relationships_created": 0,
            "error": None,
            "created_at": datetime.now().isoformat(),
            "completed_at": None,
            "profile": None,
            "pg_dsn": request.pg_dsn,
            "table_name": request.table_name,
            "limit": request.limit,
            "message": "Queued for Postgres migration"
        }
    
    background_tasks.add_task(
        process_migration_new,
        job_id,
        request.pg_dsn,
        request.table_name,
        request.limit
    )
    
    with jobs_lock:
        queued_job = dict(ingestion_jobs[job_id])
    return JobResult(**queued_job)


@app.get("/status/{job_id}", response_model=JobResult)
async def get_status(job_id: str):
    """
    Get job status and extracted profile
    
    Args:
        job_id: Job ID from upload response
    
    Returns:
        Complete JobResult with profile data
    """
    with jobs_lock:
        if job_id not in ingestion_jobs:
            raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
        
        job = dict(ingestion_jobs[job_id])
    
    return JobResult(**job)


@app.get("/jobs")
async def list_jobs():
    """List all ingestion jobs with current status"""
    with jobs_lock:
        jobs = list(ingestion_jobs.values())
    
    return {
        "total": len(jobs),
        "jobs": [
            {
                "job_id": j["job_id"],
                "target_person": j["target_person"],
                "filename": j["filename"],
                "status": j["status"],
                "nodes_created": j["nodes_created"],
                "relationships_created": j["relationships_created"],
                "created_at": j["created_at"],
                "completed_at": j["completed_at"]
            }
            for j in jobs
        ]
    }


@app.post("/extract-direct")
async def extract_direct(
    text: str,
    target_person: str,
    file_type: str = "text"
):
    """
    Direct text extraction (for testing without file upload)
    
    Args:
        text: Raw text content
        target_person: Person name to extract for
        file_type: "html", "md", or "text" (default: "text")
    
    Returns:
        Profile data immediately
    """
    try:
        if not text or len(text.strip()) == 0:
            raise ValueError("No content provided")
        
        # Extract clean text
        clean_text = extract_text_from_file(text, file_type)
        
        # Create Person node if missing
        db = GraphDB()
        with db.driver.session(database=db.database) as session:
            person_exists = session.run(
                "MATCH (p:Person {name: $name}) RETURN COUNT(p) as cnt",
                name=target_person
            ).single()
            
            if person_exists["cnt"] == 0:
                session.run(
                    "CREATE (p:Person {name: $name}) RETURN p",
                    name=target_person
                )
        
        # Extract with target_person filtering
        extractor = CustomGraphExtractor()
        nodes, rels = extractor.enrich_text(
            clean_text,
            source_chunk_id="direct_input",
            link_to_person=target_person  # Enable filtering!
        )
        
        # Get profile
        profile = get_person_profile(target_person)
        
        return {
            "status": "completed",
            "target_person": target_person,
            "nodes_created": nodes,
            "relationships_created": rels,
            "profile": profile,
            "timestamp": datetime.now().isoformat()
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extraction failed: {str(e)}")


@app.get("/health")
async def health_check():
    """Detailed health check with Neo4j stats"""
    try:
        db = GraphDB()
        with db.driver.session(database=db.database) as session:
            result = session.run("MATCH (n) RETURN COUNT(n) as count").single()
            node_count = result["count"]
            
            rel_result = session.run("MATCH ()-[r]-() RETURN COUNT(r) as count").single()
            rel_count = rel_result["count"]
        
        return {
            "status": "healthy",
            "database": db.database,
            "nodes_total": node_count,
            "relationships_total": rel_count,
            "api_version": "2.0.0",
            "timestamp": datetime.now().isoformat()
        }
    
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }


@app.post("/debug-extract")
async def debug_extract(
    text: str,
    target_person: str,
):
    """
    DEBUG endpoint: Extract directly with verbose output
    Shows exactly what LLM extracts (achievements, events, fields, etc.)
    
    Use this to troubleshoot why certain nodes aren't being created!
    """
    try:
        print(f"\n{'='*70}")
        print(f"DEBUG EXTRACTION - target_person='{target_person}'")
        print(f"{'='*70}")
        
        # Call extractor directly to see what's happening
        extractor = CustomGraphExtractor()
        
        print(f"\n[STEP 1] Calling extract_from_text()...")
        extracted_data = extractor.extract_from_text(
            text,
            source_chunk_id="debug_input",
            target_person=target_person
        )
        
        # Print what was extracted
        print(f"\n[STEP 2] Extracted Data:")
        print(f"  Persons: {len(extracted_data.get('persons', []))}")
        for p in extracted_data.get('persons', []):
            print(f"    • {p.get('name')} ({p.get('role', 'no role')})")
        
        print(f"  Achievements: {len(extracted_data.get('achievements', []))}")
        for a in extracted_data.get('achievements', [])[:3]:
            print(f"    • {a.get('name')}")
        if len(extracted_data.get('achievements', [])) > 3:
            print(f"    ... and {len(extracted_data.get('achievements', [])) - 3} more")
        
        print(f"  Events: {len(extracted_data.get('events', []))}")
        for e in extracted_data.get('events', [])[:3]:
            print(f"    • {e.get('name')} ({e.get('event_type', 'no type')})")
        if len(extracted_data.get('events', [])) > 3:
            print(f"    ... and {len(extracted_data.get('events', [])) - 3} more")
        
        print(f"  Eras: {len(extracted_data.get('eras', []))}")
        for er in extracted_data.get('eras', []):
            print(f"    • {er.get('name')}")
        
        print(f"  Fields: {len(extracted_data.get('fields', []))}")
        for f in extracted_data.get('fields', []):
            print(f"    • {f.get('name')}")
        
        print(f"  Relationships: {len(extracted_data.get('relationships', []))}")
        print(f"  Person Relationships: {len(extracted_data.get('person_relationships', []))}")
        
        # Now build to see if there are errors
        print(f"\n[STEP 3] Building graph from extraction...")
        nodes, rels = extractor.build_from_extraction(extracted_data)
        print(f"  Nodes created: {nodes}")
        print(f"  Relationships created: {rels}")
        
        print(f"\n{'='*70}\n")
        
        return {
            "target_person": target_person,
            "extracted_data": extracted_data,
            "nodes_created": nodes,
            "relationships_created": rels,
            "debug": "Check API logs (terminal) for detailed output!"
        }
    
    except Exception as e:
        import traceback
        error_msg = traceback.format_exc()
        print(f"\n❌ DEBUG ERROR: {error_msg}\n")
        return {
            "error": str(e),
            "traceback": error_msg
        }


@app.post("/chat", response_model=QueryResponse)
async def chat(request: QueryRequest):
    """Chat endpoint for Graph RAG queries."""
    answer = ask_agent(request.question)
    return QueryResponse(answer=answer)

if __name__ == "__main__":
    import uvicorn
    
    print("=" * 70)
    print("INGESTION API - FastAPI Server v2.0.0")
    print("Vietnamese Historical Figures - with target_person filtering")
    print("=" * 70)
    print("\nStarting server on http://localhost:8000")
    print("\nEndpoints:")
    print("  POST /upload - Upload .html/.md file with target_person")
    print("  GET /status/{job_id} - Get job status and full profile")
    print("  GET /jobs - List all jobs")
    print("  POST /extract-direct - Direct extraction (for testing)")
    print("  GET /health - Health check with Neo4j stats")
    print("\nAPI Docs: http://localhost:8000/docs")
    print("=" * 70 + "\n")
    
    uvicorn.run(app, host="0.0.0.0", port=8000)
