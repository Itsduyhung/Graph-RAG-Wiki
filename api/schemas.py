# api/schemas.py
"""API request/response schemas for Graph RAG."""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    """Request schema for query endpoint."""
    question: str = Field(..., description="User question")
    context: Optional[Dict[str, Any]] = Field(None, description="Additional context")


class QueryResponse(BaseModel):
    """Response schema for query endpoint."""
    answer: str = Field(..., description="Generated answer")
    active_person: Optional[str] = Field(None, description="Active person being discussed")
    context_used: Optional[str] = Field(None, description="Context used for answer")
    intent: Optional[Dict[str, Any]] = Field(None, description="Extracted intent")


class EntityRequest(BaseModel):
    """Request schema for entity extraction."""
    text: str = Field(..., description="Text to extract entities from")


class EntityResponse(BaseModel):
    """Response schema for entity extraction."""
    entities: List[Dict[str, Any]] = Field(..., description="Extracted entities")


class IngestRequest(BaseModel):
    """Request schema for data ingestion."""
    file_path: Optional[str] = Field(None, description="Path to file")
    data: Optional[List[Dict[str, Any]]] = Field(None, description="Structured data")
    file_type: Optional[str] = Field("auto", description="File type (auto, pdf, txt, csv, json)")


class IngestResponse(BaseModel):
    """Response schema for data ingestion."""
    status: str = Field(..., description="Status of ingestion")
    entities_created: int = Field(0, description="Number of entities created")
    message: Optional[str] = Field(None, description="Additional message")


