# llm/__init__.py
"""LLM module for Graph RAG - sử dụng Ollama."""
from .llm_client import call_llm, call_ollama, call_llm_with_context
from .prompt_templates import (
    INTENT_PROMPT,
    ANSWER_PROMPT,
    GRAPH_QUERY_PROMPT,
    ENTITY_EXTRACTION_PROMPT,
    CONTEXT_SYNTHESIS_PROMPT
)
from .answer_generator import AnswerGenerator

__all__ = [
    "call_llm",
    "call_ollama",
    "call_llm_with_context",
    "INTENT_PROMPT",
    "ANSWER_PROMPT",
    "GRAPH_QUERY_PROMPT",
    "ENTITY_EXTRACTION_PROMPT",
    "CONTEXT_SYNTHESIS_PROMPT",
    "AnswerGenerator",
]

