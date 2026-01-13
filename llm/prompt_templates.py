# llm/prompt_templates.py
"""Prompt templates for Graph RAG tasks."""

INTENT_PROMPT = """
You are an AI agent that extracts structured intent.
Return ONLY valid JSON.

User question:
"{question}"

Schema:
- Person
- Company
Relationship:
- (Person)-[:FOUNDED]->(Company)

JSON format:
{{
  "intent": "FIND_FOUNDER",
  "company": "<company name>"
}}
"""

ANSWER_PROMPT = """
You are an AI assistant.
Use ONLY the context below to answer.

Context:
{context}

Question:
{question}
"""

GRAPH_QUERY_PROMPT = """
Based on the user question, extract entities and relationships to query the knowledge graph.

User question: {question}

Extract:
1. Entity types (Person, Company, etc.)
2. Entity names
3. Relationship types (FOUNDED, WORKS_AT, etc.)
4. Query intent

Return JSON:
{{
  "entities": [
    {{"type": "Person|Company", "name": "..."}}
  ],
  "relationships": ["FOUNDED"],
  "intent": "FIND_FOUNDER"
}}
"""

ENTITY_EXTRACTION_PROMPT = """
Extract entities from the following text.

Text: {text}

Return JSON array of entities:
[
  {{"type": "Person", "name": "...", "confidence": 0.9}},
  {{"type": "Company", "name": "...", "confidence": 0.8}}
]
"""

CONTEXT_SYNTHESIS_PROMPT = """
Given the retrieved graph context, synthesize a clear and concise answer.

Graph Context:
{graph_context}

Question: {question}

Provide a clear answer based solely on the context above.
"""


