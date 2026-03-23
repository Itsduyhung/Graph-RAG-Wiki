"""LangChain LLMGraphTransformer-based graph enrichment.

Mục tiêu:
- Enrich graph Neo4j từ WikiChunk/SummaryDocument bằng LLMGraphTransformer.
- LLM được "khóa" không gian sáng tạo bằng allowed node/relationship types.
- Ghi vào Neo4j thông qua GraphBuilder (MERGE) để không phá dữ liệu cũ.

Yêu cầu env:
- NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, NEO4J_DB
- YESCALE_API_KEY
- YESCALE_BASE_URL (khuyến nghị: https://api.yescale.io/v1/chat/completions)
- YESCALE_MODEL (vd: gemini-2.0-flash)
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from langchain_openai import ChatOpenAI
from langchain_experimental.graph_transformers import LLMGraphTransformer

from graph.builder import GraphBuilder
from graph.storage import GraphDB


ALLOWED_NODES: List[str] = [
    "Person",
    "Country",
    "Field",
    "Era",
    "Dynasty",
    "Role",
    "Achievement",
    "Event",
    "TimePoint",
]

ALLOWED_RELATIONSHIPS: List[str] = [
    "BORN_IN",
    "BORN_AT",
    "DIED_AT",
    "WORKED_IN",
    "ACTIVE_IN",
    "BELONGS_TO_DYNASTY",
    "HAS_ROLE",
    "ACHIEVED",
    "INFLUENCED_BY",
    "CHILD_OF",
    "PARTICIPATED_IN",
    "HAPPENED_AT",
    "DESCRIBED_IN",
]


NODE_PROPERTIES: Dict[str, List[str]] = {
    "Person": [
        "name",
        "biography",
        "birth_date",
        "birth_year",
        "death_date",
        "death_year",
        "reign_start_year",
        "reign_end_year",
        "aliases",
        "role",
    ],
    "Country": ["name", "code", "region"],
    "Field": ["name", "category", "description"],
    "Era": ["name", "start_year", "end_year", "description"],
    "Dynasty": ["name", "start_year", "end_year", "description"],
    "Role": ["name", "category", "description"],
    "Achievement": ["name", "year", "description", "award"],
    "Event": ["name", "year", "description", "significance"],
    "TimePoint": ["label", "year", "month", "day"],
}


def _normalize_base_url(url: str) -> str:
    """
    YEScale thường cung cấp endpoint full như /v1/chat/completions.
    langchain-openai cần base_url dạng .../v1.
    """
    u = (url or "").strip()
    if not u:
        return ""
    if u.endswith("/chat/completions"):
        return u[: -len("/chat/completions")]
    return u


class LangChainGraphEnricher:
    """Enrich Neo4j graph bằng LLMGraphTransformer."""

    def __init__(
        self,
        graph_db: Optional[GraphDB] = None,
        model: Optional[str] = None,
        temperature: float = 0.2,
    ) -> None:
        self.graph_db = graph_db or GraphDB()
        self.builder = GraphBuilder(graph_db=self.graph_db)

        api_key = os.getenv("YESCALE_API_KEY")
        base_url = _normalize_base_url(os.getenv("YESCALE_BASE_URL", ""))
        if not api_key:
            raise RuntimeError("YESCALE_API_KEY chưa được cấu hình trong env.")
        if not base_url:
            raise RuntimeError("YESCALE_BASE_URL chưa được cấu hình trong env.")

        self.llm = ChatOpenAI(
            api_key=api_key,
            base_url=base_url,
            model=model or os.getenv("YESCALE_MODEL", "gemini-2.0-flash"),
            temperature=temperature,
        )

        self.transformer = LLMGraphTransformer(
            llm=self.llm,
            allowed_nodes=ALLOWED_NODES,
            allowed_relationships=ALLOWED_RELATIONSHIPS,
            node_properties=NODE_PROPERTIES,
        )

    def _node_identifier(self, node_type: str, props: Dict[str, Any]) -> Dict[str, Any]:
        # TimePoint định danh bằng label, còn lại dùng name
        if node_type == "TimePoint":
            label = props.get("label")
            if label:
                return {"label": label}
            # fallback theo year/month/day
            if props.get("year") is not None:
                y = props.get("year")
                m = props.get("month")
                d = props.get("day")
                if m is None:
                    return {"label": str(y)}
                if d is None:
                    return {"label": f"{int(y):04d}-{int(m):02d}"}
                return {"label": f"{int(y):04d}-{int(m):02d}-{int(d):02d}"}
            return {"label": "unknown"}

        name = props.get("name")
        if name:
            return {"name": name}
        # fallback id if present
        if "id" in props and props["id"] is not None:
            return {"id": props["id"]}
        return {"name": "unknown"}

    def enrich_text(
        self,
        text: str,
        source_chunk_id: Optional[str] = None,
        source: str = "WikiChunk",
    ) -> Tuple[int, int]:
        """
        Enrich 1 đoạn text.
        Trả về (nodes_created, relationships_created) (xấp xỉ, do GraphBuilder).
        """
        docs = self.transformer.convert_to_graph_documents([text])

        nodes: List[Dict[str, Any]] = []
        rels: List[Dict[str, Any]] = []

        for doc in docs:
            for n in getattr(doc, "nodes", []) or []:
                n_type = getattr(n, "type", None) or getattr(n, "label", None) or "Unknown"
                n_props = dict(getattr(n, "properties", {}) or {})
                # ensure name if id is the name
                n_id = getattr(n, "id", None)
                if "name" not in n_props and n_id and n_type != "TimePoint":
                    n_props["name"] = n_id

                nodes.append(
                    {
                        "type": n_type,
                        "identifier": self._node_identifier(n_type, n_props),
                        "properties": n_props,
                    }
                )

            for r in getattr(doc, "relationships", []) or []:
                r_type = getattr(r, "type", None) or "RELATED_TO"
                src = getattr(r, "source", None)
                tgt = getattr(r, "target", None)
                if not src or not tgt:
                    continue

                src_type = getattr(src, "type", None) or "Unknown"
                tgt_type = getattr(tgt, "type", None) or "Unknown"

                src_props = dict(getattr(src, "properties", {}) or {})
                tgt_props = dict(getattr(tgt, "properties", {}) or {})

                src_id = getattr(src, "id", None)
                tgt_id = getattr(tgt, "id", None)
                if "name" not in src_props and src_id and src_type != "TimePoint":
                    src_props["name"] = src_id
                if "name" not in tgt_props and tgt_id and tgt_type != "TimePoint":
                    tgt_props["name"] = tgt_id

                rel_props = dict(getattr(r, "properties", {}) or {})

                rels.append(
                    {
                        "from_type": src_type,
                        "from_id": self._node_identifier(src_type, src_props),
                        "rel_type": r_type,
                        "to_type": tgt_type,
                        "to_id": self._node_identifier(tgt_type, tgt_props),
                        "properties": rel_props,
                    }
                )

        # Optional: link back to source chunk for traceability
        if source_chunk_id:
            # Ensure source node exists (it should) and create DESCRIBED_IN
            for n in nodes:
                if n.get("type") == "Person":
                    rels.append(
                        {
                            "from_type": "Person",
                            "from_id": n.get("identifier"),
                            "rel_type": "DESCRIBED_IN",
                            "to_type": source,
                            "to_id": {"chunk_id": source_chunk_id}
                            if source == "WikiChunk"
                            else {"id": source_chunk_id},
                            "properties": {"relevance_score": 1.0},
                        }
                    )

        res = self.builder.build_from_data({"nodes": nodes, "relationships": rels})
        return res.get("nodes_created", 0), res.get("relationships_created", 0)

    def enrich_from_wikichunks(self, limit: int = 100) -> Dict[str, int]:
        with self.graph_db.driver.session(database=self.graph_db.database) as session:
            result = session.run(
                """
                MATCH (w:WikiChunk)
                WHERE w.content IS NOT NULL
                RETURN coalesce(w.chunk_id, toString(w.id)) AS cid, w.content AS content
                LIMIT $limit
                """,
                limit=limit,
            )
            chunks = [(r["cid"], r["content"]) for r in result]

        nodes_created = 0
        rels_created = 0
        for cid, content in chunks:
            n, r = self.enrich_text(content, source_chunk_id=cid, source="WikiChunk")
            nodes_created += n
            rels_created += r

        return {
            "chunks_processed": len(chunks),
            "nodes_created": nodes_created,
            "relationships_created": rels_created,
            "total": nodes_created + rels_created,
        }

