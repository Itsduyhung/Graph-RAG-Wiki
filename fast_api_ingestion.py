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

from pipeline.custom_graph_extractor import (
    CustomGraphExtractor,
    ExtractionConfig,
    get_preset_config,
    create_custom_config,
)
from graph.storage import GraphDB
from pipeline.pg_to_neo4j import PostgresToNeo4jMigrator

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
    """Get complete person profile from Neo4j - ALL relationships"""
    db = GraphDB()
    profile = {
        "name": person_name,
        "achievements": [],
        "events": [],
        "eras": [],
        "fields": [],
        "relationships": [],
        "locations": [],
        "organizations": [],
        "all_connections": [],
        "total_nodes": 0
    }

    try:
        with db.driver.session(database=db.database) as session:
            # Count total nodes connected to this person
            total = session.run(
                """
                MATCH (p:Person {name: $name})
                OPTIONAL MATCH (p)-[r]-(n)
                RETURN COUNT(DISTINCT n) + 1 as total
                """,
                name=person_name
            ).single()
            profile["total_nodes"] = total["total"] if total else 1

            # Get ALL relationships (TẤT CẢ types)
            all_rels = session.run(
                """
                MATCH (p:Person {name: $name})-[r]-(connected)
                RETURN 
                    TYPE(r) as rel_type,
                    LABELS(connected)[0] as node_type,
                    connected.name as node_name,
                    connected.description as description,
                    properties(r) as rel_props
                ORDER BY rel_type, node_type
                """,
                name=person_name
            ).data()

            profile["all_connections"] = [
                {
                    "relationship": r["rel_type"],
                    "node_type": r["node_type"],
                    "node_name": r["node_name"],
                    "description": r.get("description", ""),
                    "rel_properties": r.get("rel_props", {})
                }
                for r in all_rels
            ]

            # Categorize relationships by type
            rel_by_type = {}
            for r in all_rels:
                rel_type = r["rel_type"]
                if rel_type not in rel_by_type:
                    rel_by_type[rel_type] = []
                rel_by_type[rel_type].append({
                    "node_name": r["node_name"],
                    "description": r.get("description", "")
                })

            # Map to categories
            family_rels = {"PARENT_OF", "CHILD_OF", "SPOUSE_OF", "SIBLING_OF", "GRANDPARENT_OF", "GRANDCHILD_OF", "EXTENDED_FAMILY_OF"}
            political_rels = {"MEMBER_OF", "LEADER_OF", "FOUNDED", "FOUNDED_BY", "SUCCEEDED", "PREDECESSOR_OF", "COMMANDED", "COMMANDED_BY", "APPOINTED_BY", "REVOLTED_AGAINST"}
            event_rels = {"PARTICIPATED_IN", "WITNESSED", "CAUSED", "LEAD_TO", "RESULTED_IN", "PERFORMED", "ORGANIZED", "HOSTED"}
            location_rels = {"BORN_IN", "DIED_AT", "RESIDED_IN", "STUDIED_AT", "WORKED_AT", "RULED", "RULED_BY", "OCCURRED_IN", "OCCURRED_AT", "LOCATED_AT"}
            achievement_rels = {"ACHIEVED", "INVENTED", "CREATED", "AUTHORED", "COMPOSED", "BUILT", "RECEIVED_AWARD", "GRANTED_TITLE", "RECEIVED_TITLE"}

            # Build categorized relationships
            for rel_type, nodes in rel_by_type.items():
                if rel_type in family_rels:
                    profile["relationships"].extend([
                        {"person": n["node_name"], "type": rel_type, "category": "family"}
                        for n in nodes
                    ])
                elif rel_type in location_rels:
                    profile["locations"].extend([
                        {"name": n["node_name"], "type": rel_type, "description": n.get("description", "")}
                        for n in nodes
                    ])
                elif rel_type in political_rels:
                    profile["organizations"].extend([
                        {"name": n["node_name"], "type": rel_type, "description": n.get("description", "")}
                        for n in nodes
                    ])
                elif rel_type in event_rels:
                    profile["events"].extend([
                        {"name": n["node_name"], "type": rel_type, "description": n.get("description", "")}
                        for n in nodes
                    ])
                elif rel_type in achievement_rels:
                    profile["achievements"].extend([
                        {"name": n["node_name"], "type": rel_type, "description": n.get("description", "")}
                        for n in nodes
                    ])

            # Deduplicate
            seen = set()
            unique_rels = []
            for r in profile["relationships"]:
                key = (r["person"], r["type"])
                if key not in seen:
                    seen.add(key)
                    unique_rels.append(r)
            profile["relationships"] = unique_rels

            seen = set()
            unique_events = []
            for e in profile["events"]:
                key = e["name"]
                if key not in seen:
                    seen.add(key)
                    unique_events.append(e)
            profile["events"] = unique_events

            seen = set()
            unique_locs = []
            for l in profile["locations"]:
                key = l["name"]
                if key not in seen:
                    seen.add(key)
                    unique_locs.append(l)
            profile["locations"] = unique_locs

            seen = set()
            unique_orgs = []
            for o in profile["organizations"]:
                key = o["name"]
                if key not in seen:
                    seen.add(key)
                    unique_orgs.append(o)
            profile["organizations"] = unique_orgs

    except Exception as e:
        profile["error"] = f"Could not retrieve full profile: {str(e)}"

    return profile


def process_ingestion(
    job_id: str, 
    file_content: str, 
    target_person: str, 
    file_type: str, 
    filename: str,
    preset: Optional[str] = None,
    use_original_prompt: bool = True,
    max_chunk_size: int = 500000,  # Max 500k chars per LLM call
):
    """
    Background task: extract, enrich, and build complete profile.
    
    Args:
        job_id: Job identifier
        file_content: Text content to extract
        target_person: Person to prioritize
        file_type: File type (html, md, text)
        filename: Source filename
        preset: Preset config name (default, vietnam_history, science_tech, etc.)
        use_original_prompt: True = dùng prompt gốc (nhiều node)
        max_chunk_size: Max characters per chunk (default 500000)
    """
    try:
        with jobs_lock:
            if job_id in ingestion_jobs:
                ingestion_jobs[job_id]["status"] = "processing"
        
        print(f"\n[JOB {job_id[:8]}] Starting extraction for '{target_person}'")
        if preset:
            print(f"[JOB {job_id[:8]}] Using preset: {preset}")
        print(f"[JOB {job_id[:8]}] Prompt mode: {'ORIGINAL (many nodes)' if use_original_prompt else 'CONFIG-BASED'}")
        
        # Extract text
        text = extract_text_from_file(file_content, file_type)
        if not text or len(text.strip()) == 0:
            raise ValueError("No content extracted from file")
        
        original_length = len(text)
        print(f"[JOB {job_id[:8]}] Extracted text length: {original_length} chars")
        
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
        
        # Create extractor
        if preset:
            extractor = CustomGraphExtractor()
            extractor.set_preset(preset)
            print(f"[JOB {job_id[:8]}] Config applied: {preset}")
        else:
            extractor = CustomGraphExtractor()
        
        # CHUNK TEXT if too long
        chunks = chunk_text(text, max_chunk_size=max_chunk_size)
        num_chunks = len(chunks)
        print(f"[JOB {job_id[:8]}] Text split into {num_chunks} chunks (max {max_chunk_size} chars each)")
        
        # Process each chunk and collect results
        total_nodes = 0
        total_rels = 0
        
        for i, chunk in enumerate(chunks):
            print(f"[JOB {job_id[:8]}] Processing chunk {i+1}/{num_chunks} ({len(chunk)} chars)...")
            
            # Extract from this chunk
            chunk_nodes, chunk_rels = extractor.enrich_text(
                chunk,
                source_chunk_id=f"{filename}_chunk_{i+1}",
                link_to_person=target_person,
                use_original_prompt=use_original_prompt,
            )
            
            total_nodes += chunk_nodes
            total_rels += chunk_rels
            print(f"[JOB {job_id[:8]}]   Chunk {i+1}: {chunk_nodes} nodes, {chunk_rels} rels")
        
        nodes_created = total_nodes
        rels_created = total_rels
        
        print(f"[JOB {job_id[:8]}] ✓ Extraction complete!")
        print(f"[JOB {job_id[:8]}]   Total nodes created: {nodes_created}")
        print(f"[JOB {job_id[:8]}]   Total relationships created: {rels_created}")
        
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
                    f"Extraction complete! Created {nodes_created} nodes and {rels_created} relationships from {num_chunks} chunks."
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


def chunk_text(text: str, max_chunk_size: int = 10000, overlap: int = 200) -> list:
    """
    Split text into chunks with overlap for context continuity.
    
    Args:
        text: Text to split
        max_chunk_size: Maximum characters per chunk
        overlap: Overlap between chunks (for context continuity)
    
    Returns:
        List of text chunks
    """
    if len(text) <= max_chunk_size:
        return [text]
    
    chunks = []
    
    # Try to split by double newlines (paragraphs) first
    paragraphs = text.split('\n\n')
    
    current_chunk = ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
            
        # If single paragraph is too long, split by sentences
        if len(para) > max_chunk_size:
            # If we have current chunk, add it first
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = ""
            
            # Split long paragraph by sentences
            sentences = re.split(r'(?<=[.!?])\s+', para)
            current_sentence_chunk = ""
            
            for sentence in sentences:
                if len(current_sentence_chunk) + len(sentence) + 1 > max_chunk_size:
                    if current_sentence_chunk:
                        chunks.append(current_sentence_chunk)
                    # Start new chunk with overlap
                    current_sentence_chunk = sentence[-overlap:] if overlap > 0 and len(sentence) > overlap else sentence
                else:
                    if current_sentence_chunk:
                        current_sentence_chunk += " " + sentence
                    else:
                        current_sentence_chunk = sentence
            
            if current_sentence_chunk:
                current_chunk = current_sentence_chunk
                
        elif len(current_chunk) + len(para) + 2 > max_chunk_size:
            # Current chunk is full, add it and start new
            chunks.append(current_chunk)
            # Start new chunk with overlap from previous
            current_chunk = para[-overlap:] if overlap > 0 and len(para) > overlap else para
        else:
            # Add to current chunk
            if current_chunk:
                current_chunk += "\n\n" + para
            else:
                current_chunk = para
    
    # Don't forget the last chunk
    if current_chunk:
        chunks.append(current_chunk)
    
    return chunks


def process_migration_new(
    job_id: str,
    pg_dsn: str,
    table_name: str = "persons",
    limit: Optional[int] = None,
):
    """
    Background task: migrate data from PostgreSQL to Neo4j.
    
    Args:
        job_id: Job identifier
        pg_dsn: PostgreSQL connection string
        table_name: Table to migrate (default: "persons")
        limit: Limit number of records
    """
    try:
        with jobs_lock:
            if job_id in ingestion_jobs:
                ingestion_jobs[job_id]["status"] = "processing"
        
        print(f"\n[JOB {job_id[:8]}] Starting migration from PostgreSQL")
        print(f"[JOB {job_id[:8]}] Table: {table_name}, Limit: {limit or 'None'}")
        
        # Create migrator
        migrator = PostgresToNeo4jMigrator(pg_dsn=pg_dsn)
        
        # Run migration based on table name
        if table_name == "persons":
            result = migrator.migrate_persons(person_table=table_name, limit=limit)
        elif table_name in ["documents", "parent_chunks", "child_chunks", "summary_documents"]:
            # Use all-in-one migration for document-related tables
            result = migrator.migrate_all_documents_and_chunks(
                document_table="documents",
                parent_table="parent_chunks",
                child_table="child_chunks",
                summary_table="summary_documents",
                assoc_table="document_summary_association",
                limit_documents=limit,
                limit_chunks=limit,
            )
        else:
            # Try persons migration as default
            result = migrator.migrate_persons(person_table=table_name, limit=limit)
        
        nodes_created = result.get("nodes_created", 0)
        rels_created = result.get("relationships_created", 0)
        
        print(f"[JOB {job_id[:8]}] ✓ Migration complete!")
        print(f"[JOB {job_id[:8]}]   Nodes created: {nodes_created}")
        print(f"[JOB {job_id[:8]}]   Relationships created: {rels_created}")
        
        # Update job
        with jobs_lock:
            if job_id in ingestion_jobs:
                ingestion_jobs[job_id]["status"] = "completed"
                ingestion_jobs[job_id]["nodes_created"] = nodes_created
                ingestion_jobs[job_id]["relationships_created"] = rels_created
                ingestion_jobs[job_id]["completed_at"] = datetime.now().isoformat()
                ingestion_jobs[job_id]["message"] = (
                    f"Migration complete! Created {nodes_created} nodes and {rels_created} relationships."
                )
        
        print(f"[JOB {job_id[:8]}] ✅ Migration job completed successfully!")
    
    except Exception as e:
        import traceback
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        print(f"[JOB {job_id[:8]}] ❌ MIGRATION ERROR: {error_msg}")
        
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
        "version": "3.0.0",
        "message": "Upload .html/.md files to extract person profiles with Neo4j",
        "endpoints": {
            "upload": "POST /upload - Upload file with target_person",
            "ingest_new": "POST /ingest_new - Text-based with preset config",
            "status": "GET /status/{job_id} - Get job status and profile",
            "jobs": "GET /jobs - List all jobs",
            "extract_direct": "POST /extract-direct - Direct extraction for testing",
            "chat": "POST /chat - Graph RAG queries",
            "docs": "GET /docs - Interactive API docs (Swagger UI)",
            "redoc": "GET /redoc - ReDoc documentation"
        },
        "presets": {
            "default": "Cân bằng, đầy đủ",
            "vietnam_history": "Tối ưu cho lịch sử VN (triều đại, tước vị...)",
            "science_tech": "Tối ưu cho khoa học (phát minh, giải thưởng...)",
            "literature_art": "Tối ưu cho văn học/nghệ thuật",
            "minimal": "Chỉ thông tin cơ bản",
            "maximum": "Trích xuất tối đa mọi thứ"
        },
        "prompt_modes": {
            "use_original_prompt=True": "Dùng prompt gốc - tạo NHIỀU node (~110 nodes)",
            "use_original_prompt=False": "Dùng config-based - linh hoạt theo preset"
        },
        "example_usage": {
            "curl_upload": "curl -F 'file=@file.html' -F 'target_person=Kim Đồng' -F 'preset=vietnam_history' http://localhost:8000/upload",
            "curl_ingest": "curl -X POST http://localhost:8000/ingest_new -H 'Content-Type: application/json' -d '{\"text\": \"...\", \"target_person\": \"Kim Đồng\", \"preset\": \"vietnam_history\"}'",
            "python": "requests.post('http://localhost:8000/upload', files={'file': open('file.html', 'rb')}, data={'target_person': 'Kim Đồng', 'preset': 'vietnam_history', 'use_original_prompt': True})"
        }
    }


@app.post("/upload", response_model=UploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    target_person: str = Form(None),
    preset: str = Form("vietnam_history"),  # Default preset
    use_original_prompt: bool = Form(True),  # Always true by default
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    """
    Upload .html or .md file for extraction with Neo4j
    
    Args:
        file: Upload .html or .md file
        target_person: Name of person to extract (default: filename without extension)
        preset: Preset config ("default", "vietnam_history", "science_tech", "literature_art", "minimal", "maximum", None)
        use_original_prompt: True = dùng prompt gốc (nhiều node ~110), False = dùng config-based prompt
    
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
    
    # Validate preset if provided
    valid_presets = ["default", "vietnam_history", "science_tech", "literature_art", "minimal", "maximum"]
    if preset and preset not in valid_presets:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid preset: '{preset}'. Valid options: {valid_presets}"
        )
    
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
                "message": "Queued for processing",
                "preset": preset,
                "use_original_prompt": use_original_prompt,
            }
        
        # Queue background processing
        background_tasks.add_task(
            process_ingestion,
            job_id,
            file_content,
            target_person,
            file_ext,
            filename,
            preset,
            use_original_prompt,
        )
        
        return {
            "job_id": job_id,
            "target_person": target_person,
            "filename": filename,
            "status": "queued",
            "message": f"Processing '{target_person}' from {filename}. Check /status/{job_id}\nPreset: {preset or 'default'}\nOriginal prompt: {use_original_prompt}"
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
    preset: str = Field("vietnam_history", description="default|vietnam_history|science_tech|literature_art|minimal|maximum")
    use_original_prompt: bool = Field(True, description="True = nhiều node, False = config-based")


@app.post("/ingest_new", response_model=JobResult)
async def ingest_new(request: IngestNewRequest, background_tasks: BackgroundTasks):
    """
    New ingestion endpoint - text-based with extra config
    
    Extended version of /upload for programmatic use.
    
    Args:
        text: Text content to extract
        source_type: Source type (wiki, doc, custom)
        target_person: Person to prioritize
        preset: Preset config name
        use_original_prompt: True = prompt gốc (nhiều node), False = config-based
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
            "preset": request.preset,
            "use_original_prompt": request.use_original_prompt,
            "message": "Queued for new ingestion pipeline"
        }
    
    # Reuse same background task with new parameters
    background_tasks.add_task(
        process_ingestion,
        job_id,
        request.text,
        request.target_person or "unknown",
        "text",
        f"{request.source_type}.txt",
        request.preset,
        request.use_original_prompt,
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
    preset: str = "vietnam_history",  # Default preset
    use_original_prompt: bool = True,  # Always true by default
    file_type: str = "text"
):
    """
    Direct text extraction (for testing without file upload)
    
    Args:
        text: Raw text content
        target_person: Person name to extract for
        preset: Preset config ("default", "vietnam_history", etc.)
        use_original_prompt: True = prompt gốc (nhiều node), False = config-based
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
        
        # Create extractor with preset if specified
        if preset:
            extractor = CustomGraphExtractor()
            extractor.set_preset(preset)
        else:
            extractor = CustomGraphExtractor()
        
        # Extract with target_person filtering
        nodes, rels = extractor.enrich_text(
            clean_text,
            source_chunk_id="direct_input",
            link_to_person=target_person,
            use_original_prompt=use_original_prompt,
        )
        
        # Get profile
        profile = get_person_profile(target_person)
        
        return {
            "status": "completed",
            "target_person": target_person,
            "preset": preset,
            "use_original_prompt": use_original_prompt,
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
    print("INGESTION API - FastAPI Server v3.0.0")
    print("Vietnamese Historical Figures - với PRESET CONFIG & ORIGINAL PROMPT")
    print("=" * 70)
    print("\nStarting server on http://localhost:8000")
    print("\nEndpoints:")
    print("  POST /upload - Upload .html/.md file với preset & use_original_prompt")
    print("  POST /ingest_new - Text-based với preset config")
    print("  GET /status/{job_id} - Get job status and full profile")
    print("  GET /jobs - List all jobs")
    print("  POST /extract-direct - Direct extraction (for testing)")
    print("  POST /chat - Graph RAG queries")
    print("  GET /health - Health check with Neo4j stats")
    print("\nPresets:")
    print("  default, vietnam_history, science_tech, literature_art, minimal, maximum")
    print("\nPrompt Modes:")
    print("  use_original_prompt=True  → NHIỀU node (~110)")
    print("  use_original_prompt=False → CONFIG-BASED (linh hoạt)")
    print("\nAPI Docs: http://localhost:8000/docs")
    print("=" * 70 + "\n")
    
    uvicorn.run(app, host="0.0.0.0", port=8000)
