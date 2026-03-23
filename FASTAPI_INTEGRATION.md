"""
INTEGRATION SUMMARY: FastAPI v2.0.0 with target_person Filtering

This document explains how the new FastAPI Ingestion Server implements
the same target_person filtering logic as test_person_extraction.py
"""

# ============================================================================
# ARCHITECTURE OVERVIEW
# ============================================================================

## Flow Comparison

### test_person_extraction.py (CLI)
```
1. Set TARGET_NAME = "Kim Đồng"
2. Search WikiChunk for chunks containing full name
   - Query: toLower(w.content) CONTAINS toLower('Kim Đồng')
   - Limit: 20 chunks
3. For each chunk:
   - extractor.enrich_text(content, link_to_person=TARGET_NAME)
   - Pass target_person to LLM prompt
4. LLM instruction: "Chỉ trích xuất thông tin TRỰC TIẾP liên quan đến '{target_person}'"
5. Build Achievement/Event/Era/Field nodes, link to Person
6. Query Neo4j for complete profile
```

### fast_api_ingestion.py v2.0.0 (API)
```
1. Upload file with target_person="Kim Đồng"
2. Background task:
   - Extract clean text from HTML/MD
   - Create Person node if missing
   - Call extractor.enrich_text(text, link_to_person="Kim Đồng")
   - LLM gets same filtering instruction
3. Build complete profile from Neo4j:
   - achievements, events, eras, fields, relationships
4. Return full profile in JSON response
```

## Key Integration Points

### 1. CustomGraphExtractor.enrich_text()
Located: `pipeline/custom_graph_extractor.py` line 259

```python
def enrich_text(self, text: str, source_chunk_id: Optional[str] = None, 
                link_to_person: Optional[str] = None):
    """
    BOTH test_person_extraction.py and fast_api_ingestion.py use this!
    
    Key parameter: link_to_person
    - test_person_extraction: Passes TARGET_NAME
    - fast_api_ingestion: Passes target_person from upload
    
    Inside: Calls extract_from_text(text, target_person=link_to_person)
    """
    extracted = self.extract_from_text(text, source_chunk_id, 
                                      target_person=link_to_person)
    # ... build nodes and relationships ...
    return nodes_count, relationships_count
```

### 2. LLM Prompt Filtering
Located: `pipeline/custom_graph_extractor.py` line 90

```python
if target_person:
    additional_instruction = f"""
    ⚠️ QUAN TRỌNG: Chỉ trích xuất thông tin TRỰC TIẾP liên quan đến '{target_person}'.
    Không trích xuất thông tin về những người khác.
    """
    prompt = EXTRACTION_PROMPT + additional_instruction
```

This instruction:
- Prevents data contamination (like Kim Đồng getting Einstein's theories)
- Works at LLM level (highest quality filtering)
- Used by BOTH CLI and API

### 3. Person Node Creation
Both implementations create Person node if it doesn't exist:

**test_person_extraction.py** (line ~30):
```python
db.create_or_get_person(TARGET_NAME)
```

**fast_api_ingestion.py** (line ~170):
```python
session.run("CREATE (p:Person {name: $name}) RETURN p", name=target_person)
```

### 4. Graph Building
Both use GraphBuilder to create nodes and relationships:
- Achievement nodes with descriptions
- Event nodes with event_type
- Era nodes with historical periods
- Field nodes for domains
- Person relationships with semantic types

---

# ============================================================================
# DATA FLOW IN API
# ============================================================================

## HTTP Request → Database Update

### Step 1: File Upload
```
POST /upload
├─ file: binary (.html/.md)
├─ target_person: "Kim Đồng" (optional, defaults to filename)
└─ Returns: job_id for tracking
```

### Step 2: Background Processing (async)
```
process_ingestion(job_id, file_content, target_person, file_type, filename)
│
├─ Extract text from HTML/Markdown
│  └─ extract_text_from_file(content, "html"|"md")
│
├─ Create Person node if missing
│  ├─ Query: MATCH (p:Person {name: $target_person})
│  └─ Create: CREATE (p:Person {name: $target_person})
│
├─ Extract with target_person filtering ⭐
│  └─ extractor.enrich_text(text, link_to_person=target_person)
│
├─ LLM receives prompt with instruction
│  └─ "Chỉ trích xuất thông tin TRỰC TIẾP liên quan đến '{target_person}'"
│
├─ Build nodes and relationships in Neo4j
│  ├─ Achievement nodes (ACHIEVED relationships)
│  ├─ Event nodes (PARTICIPATED_IN relationships)
│  ├─ Era nodes (ACTIVE_IN relationships)
│  ├─ Field nodes (BELONGS_TO_FIELD relationships)
│  └─ Person relationships (mutual relationships with other people)
│
└─ Query complete profile and return
   ├─ Count total nodes
   ├─ Get achievements
   ├─ Get events
   ├─ Get eras
   ├─ Get fields
   └─ Get relationships to other people
```

### Step 3: Status Query
```
GET /status/{job_id}
└─ Returns: Complete JobResult including full profile
```

---

# ============================================================================
# PROFILE RESPONSE STRUCTURE
# ============================================================================

When extraction is complete, profile contains:

```json
{
  "name": "Kim Đồng",
  "total_nodes": 45,
  "achievements": [
    {
      "name": "Thành lập Tây Sơn",
      "description": "Founding of Tây Sơn movement"
    },
    {
      "name": "Đánh bại quân Thanh",
      "description": "Victory against Qing army"
    }
  ],
  "events": [
    {
      "name": "Khởi nghĩa Tây Sơn",
      "type": "rebellion",
      "description": "Famous uprising"
    }
  ],
  "eras": [
    {
      "name": "Thời kỳ Tây Sơn",
      "period": "1778-1802"
    }
  ],
  "fields": [
    "Quân sự",
    "Chính trị",
    "Lãnh đạo"
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
```

This mirrors what `test_person_extraction.py` displays:
```python
# From test_person_extraction.py inspect_person()
profile["achievements"]     # → achievements list
profile["events"]           # → events list
profile["eras"]            # → eras list
profile["fields"]          # → fields list
profile["relationships"]   # → relationships to other people
```

---

# ============================================================================
# KEY DIFFERENCES FROM v1.0
# ============================================================================

| Aspect | v1.0 | v2.0 |
|--------|------|------|
| **Target Filtering** | ❌ No | ✅ Yes (link_to_person parameter) |
| **LLM Instruction** | Generic | ✅ Person-specific Vietnamese |
| **Profile Response** | Counts only | ✅ Full detailed profile |
| **Achievements** | All dumped | ✅ Only target person's |
| **Events** | Mixed types | ✅ Separate with event_type |
| **Thread Safety** | ❌ No | ✅ Yes (jobs_lock) |
| **Job Persistence** | Simple dict | ✅ Comprehensive tracking |
| **Relationships** | Basic | ✅ All 10 semantic types |
| **Error Handling** | Basic | ✅ Detailed with timestamps |

---

# ============================================================================
# INTEGRATION WITH EXISTING CODE
# ============================================================================

### Files Used

1. **pipeline/custom_graph_extractor.py**
   - `extract_from_text(text, target_person=None)` - Core extraction with filtering
   - `enrich_text(text, link_to_person=None)` - Wrapper that passes target_person
   - Line 90: Vietnamese instruction when target_person provided
   - Creates all node types: Achievement, Event, Era, Field, Person, Relationship

2. **graph/storage.py**
   - `GraphDB()` class for Neo4j connection
   - Used for Person node creation and profile queries

3. **graph/builder.py**
   - `GraphBuilder` for flexible node/relationship creation
   - Used internally by CustomGraphExtractor

### Environment Variables (from .env)
- `YESCALE_API_KEY` - Gemini 2.0 Flash API key
- `YESCALE_BASE_URL` - API endpoint
- `NEO4J_URI` - Database connection
- `NEO4J_USER` - Database credentials
- `NEO4J_PASSWORD` - Database credentials
- `NEO4J_DB` - Database name (default: "demo")

---

# ============================================================================
# TESTING & VALIDATION
# ============================================================================

### Test Script: test_api_v2.py

Run full test suite:
```powershell
python test_api_v2.py
```

Tests performed:
1. API health check (GET /health)
2. File upload if kim_dong.html exists
3. Direct extraction with sample Vietnamese text
4. List all jobs
5. Profile display for each result

### Manual Testing

```bash
# 1. Start API
python fast_api_ingestion.py

# 2. In another terminal, upload file
curl -F "file=@kim_dong.html" -F "target_person=Kim Đồng" \
  http://localhost:8000/upload

# 3. Check status
curl http://localhost:8000/status/{job_id}

# 4. View full profile (when status="completed")
curl http://localhost:8000/status/{job_id} | jq '.profile'
```

---

# ============================================================================
# TROUBLESHOOTING
# ============================================================================

### Issue: Data contamination (unrelated achievements)
**Cause:** LLM not respecting target_person filtering
**Fix:** Ensure `link_to_person` parameter is passed to `enrich_text()`
**Check:** In fast_api_ingestion.py line 179-182:
```python
extractor.enrich_text(
    text,
    source_chunk_id=filename,
    link_to_person=target_person  # ← Must be passed!
)
```

### Issue: Empty or wrong achievements
**Cause:** Text doesn't contain enough information about person
**Fix:** Provide richer source material (larger HTML/MD file)
**Check:** Test with `POST /extract-direct` endpoint with longer sample text

### Issue: No relationships returned
**Cause:** Person not mentioned with relationship verbs in text
**Fix:** Ensure source text mentions relationships with other people
**Examples:** "học trò của", "thầy của", "quân địch của", etc.

### Issue: Job not appearing in profile
**Cause:** Extraction still in progress
**Fix:** Wait and retry GET /status/{job_id}
**Details:** Background processing takes 5-30 seconds depending on text size

---

# ============================================================================
# FUTURE ENHANCEMENTS
# ============================================================================

Ideas for improvements:

1. **Batch Processing**
   - `/upload-batch` for multiple files
   - Process multiple people simultaneously

2. **Search Integration**
   - `GET /search/{person_name}` - Search existing profiles
   - `GET /related/{person_name}` - Get related people

3. **Export Formats**
   - `/export/{job_id}?format=json|csv|graphml`
   - Export extracted data in various formats

4. **Update Mode**
   - POST /update/{person_name} to add more data to existing person
   - Merge new discoveries without overwriting

5. **Validation Endpoint**
   - `/validate/{job_id}` - Check data quality
   - Detect anomalies like relationship conflicts

---

**Version:** 2.0.0
**Integration Date:** 2026-03-12
**Status:** ✅ Production Ready
**CLI Companion:** test_person_extraction.py
