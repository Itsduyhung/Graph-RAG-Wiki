"""Shared types for query pipeline modules."""

from typing import Any, Dict, List, TypedDict


class QueryInfo(TypedDict, total=False):
    entity: str
    intent: str
    target_type: str
    keywords: List[str]
    aggregation: Dict[str, Any]
    original_question: str


Candidate = Dict[str, Any]

