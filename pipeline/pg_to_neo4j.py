"""Postgres → Neo4j migration pipeline.

Ý tưởng:
- Đọc data từ Postgres (PgAdmin4 chỉ là UI, bản chất là Postgres DB).
- Map từng dòng (row) sang nodes / relationships theo schema của graph.
- Sử dụng GraphBuilder (đã dùng MERGE) nên:
  - Nếu node Person đã tồn tại (theo khóa định danh), nó sẽ được cập nhật, không tạo bản sao.
  - Nếu chưa tồn tại, nó sẽ được tạo mới.
"""

from typing import Dict, Any, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

from graph.builder import GraphBuilder
from graph.storage import GraphDB


class PostgresToNeo4jMigrator:
    """Migration data từ Postgres sang Neo4j theo mapping rõ ràng."""

    def __init__(
        self,
        pg_dsn: str,
        graph_db: Optional[GraphDB] = None,
    ) -> None:
        """
        Args:
            pg_dsn: DSN kết nối Postgres, ví dụ:
                "dbname=mydb user=myuser password=mypass host=localhost port=5432"
            graph_db: Kết nối Neo4j (nếu None sẽ dùng GraphDB() mặc định)
        """
        self.pg_dsn = pg_dsn
        self.graph_db = graph_db or GraphDB()
        self.graph_builder = GraphBuilder(graph_db=self.graph_db)

    def _query_pg(self, sql: str) -> List[Dict[str, Any]]:
        """Chạy query Postgres và trả về list dict."""
        with psycopg2.connect(self.pg_dsn) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql)
                rows = cur.fetchall()
        return [dict(r) for r in rows]

    # --------- Ví dụ mapping cụ thể cho Person ----------
    def migrate_persons(
        self,
        person_table: str = "persons",
        limit: Optional[int] = None,
    ) -> Dict[str, int]:
        """
        Migrate bảng Person trong Postgres sang Neo4j.

        Giả sử bảng Postgres có schema (ví dụ):
            persons(
              id SERIAL PRIMARY KEY,
              full_name TEXT,
              birth_date DATE,
              email TEXT,
              biography TEXT,
              country_of_birth TEXT
            )

        Bạn có thể chỉnh sửa SQL/mapping cho khớp với schema thật của bạn.
        """
        sql = f"SELECT id, full_name, birth_date, email, biography, country_of_birth FROM {person_table}"
        if limit:
            sql += f" LIMIT {int(limit)}"

        rows = self._query_pg(sql)

        nodes: List[Dict[str, Any]] = []
        rels: List[Dict[str, Any]] = []

        for row in rows:
            person_id = row.get("id")
            name = row.get("full_name") or f"Person-{person_id}"
            birth_date = row.get("birth_date")
            email = row.get("email")
            biography = row.get("biography")
            country = row.get("country_of_birth")

            # Node Person (dùng id Postgres làm identifier để tránh trùng tên)
            nodes.append(
                {
                    "type": "Person",
                    "identifier": {"id": person_id},
                    "properties": {
                        "name": name,
                        "birth_date": str(birth_date) if birth_date else None,
                        "email": email,
                        "biography": biography,
                    },
                }
            )

            # Node Country + quan hệ BORN_IN nếu có
            if country:
                nodes.append(
                    {
                        "type": "Country",
                        "identifier": {"name": country},
                        "properties": {},
                    }
                )
                rels.append(
                    {
                        "from_type": "Person",
                        "from_id": {"id": person_id},
                        "rel_type": "BORN_IN",
                        "to_type": "Country",
                        "to_id": {"name": country},
                        "properties": {},
                    }
                )

        # Dùng build_from_data với format {"nodes": [...], "relationships": [...]}
        result = self.graph_builder.build_from_data(
            {"nodes": nodes, "relationships": rels}
        )
        return result

    # --------- Migration cho documents / chunks / summaries ----------

    def migrate_documents(
        self,
        document_table: str = "documents",
        limit: Optional[int] = None,
    ) -> Dict[str, int]:
        """
        Migrate bảng documents → nodes type Document.

        Giả sử bảng documents có các cột (dựa trên screenshot):
            id UUID PRIMARY KEY,
            file_path TEXT,
            file_name TEXT,
            source_type TEXT,
            status TEXT,
            metadata JSONB,
            content_hash TEXT,
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        """
        sql = (
            f"SELECT id, file_path, file_name, source_type, status, "
            f"metadata, content_hash, created_at, updated_at "
            f"FROM {document_table}"
        )
        if limit:
            sql += f" LIMIT {int(limit)}"

        rows = self._query_pg(sql)

        nodes: List[Dict[str, Any]] = []
        for row in rows:
            doc_id = row.get("id")
            if not doc_id:
                continue

            nodes.append(
                {
                    "type": "Document",
                    "identifier": {"id": str(doc_id)},
                    "properties": {
                        "file_path": row.get("file_path"),
                        "file_name": row.get("file_name"),
                        "source_type": row.get("source_type"),
                        "status": row.get("status"),
                        "content_hash": row.get("content_hash"),
                        "created_at": str(row.get("created_at"))
                        if row.get("created_at")
                        else None,
                        "updated_at": str(row.get("updated_at"))
                        if row.get("updated_at")
                        else None,
                    },
                }
            )

        return self.graph_builder.build_from_data({"nodes": nodes, "relationships": []})

    def migrate_parent_chunks(
        self,
        parent_table: str = "parent_chunks",
        limit: Optional[int] = None,
    ) -> Dict[str, int]:
        """
        Migrate bảng parent_chunks → WikiChunk nodes + HAS_PARENT_CHUNK relationships.

        Giả sử parent_chunks có:
            id BIGINT PRIMARY KEY,
            document_id UUID,
            content TEXT,
            h1 TEXT, h2 TEXT, h3 TEXT,
            metadata JSONB,
            created_at TIMESTAMP, ...
        """
        sql = (
            f"SELECT id, document_id, content, h1, h2, h3, metadata, created_at "
            f"FROM {parent_table}"
        )
        if limit:
            sql += f" LIMIT {int(limit)}"

        rows = self._query_pg(sql)

        nodes: List[Dict[str, Any]] = []
        rels: List[Dict[str, Any]] = []

        for row in rows:
            chunk_id = row.get("id")
            document_id = row.get("document_id")
            if chunk_id is None:
                continue

            nodes.append(
                {
                    "type": "WikiChunk",
                    "identifier": {"id": int(chunk_id)},
                    "properties": {
                        "content": row.get("content"),
                        "h1": row.get("h1"),
                        "h2": row.get("h2"),
                        "h3": row.get("h3"),
                        "chunk_type": "parent",
                        "document_id": str(document_id) if document_id else None,
                        "created_at": str(row.get("created_at"))
                        if row.get("created_at")
                        else None,
                    },
                }
            )

            if document_id:
                rels.append(
                    {
                        "from_type": "Document",
                        "from_id": {"id": str(document_id)},
                        "rel_type": "HAS_PARENT_CHUNK",
                        "to_type": "WikiChunk",
                        "to_id": {"id": int(chunk_id)},
                        "properties": {},
                    }
                )

        return self.graph_builder.build_from_data({"nodes": nodes, "relationships": rels})

    def migrate_child_chunks(
        self,
        child_table: str = "child_chunks",
        limit: Optional[int] = None,
    ) -> Dict[str, int]:
        """
        Migrate bảng child_chunks → WikiChunk nodes + HAS_CHILD_CHUNK relationships.

        Giả sử child_chunks có:
            id BIGINT PRIMARY KEY,
            document_id UUID,
            parent_id BIGINT,
            content TEXT,
            h1 TEXT, h2 TEXT, h3 TEXT,
            metadata JSONB,
            created_at TIMESTAMP, ...
        """
        sql = (
            f"SELECT id, document_id, parent_id, content, h1, h2, h3, metadata, created_at "
            f"FROM {child_table}"
        )
        if limit:
            sql += f" LIMIT {int(limit)}"

        rows = self._query_pg(sql)

        nodes: List[Dict[str, Any]] = []
        rels: List[Dict[str, Any]] = []

        for row in rows:
            chunk_id = row.get("id")
            document_id = row.get("document_id")
            parent_id = row.get("parent_id")
            if chunk_id is None:
                continue

            nodes.append(
                {
                    "type": "WikiChunk",
                    "identifier": {"id": int(chunk_id)},
                    "properties": {
                        "content": row.get("content"),
                        "h1": row.get("h1"),
                        "h2": row.get("h2"),
                        "h3": row.get("h3"),
                        "chunk_type": "child",
                        "document_id": str(document_id) if document_id else None,
                        "parent_id": int(parent_id) if parent_id is not None else None,
                        "created_at": str(row.get("created_at"))
                        if row.get("created_at")
                        else None,
                    },
                }
            )

            if document_id:
                rels.append(
                    {
                        "from_type": "Document",
                        "from_id": {"id": str(document_id)},
                        "rel_type": "HAS_CHILD_CHUNK",
                        "to_type": "WikiChunk",
                        "to_id": {"id": int(chunk_id)},
                        "properties": {},
                    }
                )

            if parent_id is not None:
                rels.append(
                    {
                        "from_type": "WikiChunk",
                        "from_id": {"id": int(parent_id)},
                        "rel_type": "HAS_CHILD_CHUNK",
                        "to_type": "WikiChunk",
                        "to_id": {"id": int(chunk_id)},
                        "properties": {},
                    }
                )

        return self.graph_builder.build_from_data({"nodes": nodes, "relationships": rels})

    def migrate_summaries(
        self,
        summary_table: str = "summary_documents",
        assoc_table: str = "document_summary_association",
        limit: Optional[int] = None,
    ) -> Dict[str, int]:
        """
        Migrate summary_documents + document_summary_association → SummaryDocument nodes
        và HAS_SUMMARY relationships.

        Giả sử:
            summary_documents(id, summary_content, status, metadata, created_at, ...)
            document_summary_association(document_id, summary_id, created_at, ...)
        """
        sql_summary = (
            f"SELECT id, summary_content, status, metadata, created_at "
            f"FROM {summary_table}"
        )
        if limit:
            sql_summary += f" LIMIT {int(limit)}"

        summaries = self._query_pg(sql_summary)

        # Lấy association riêng (không limit để đảm bảo đủ liên kết)
        sql_assoc = (
            f"SELECT document_id, summary_id, created_at "
            f"FROM {assoc_table}"
        )
        assoc_rows = self._query_pg(sql_assoc)

        nodes: List[Dict[str, Any]] = []
        rels: List[Dict[str, Any]] = []

        for row in summaries:
            sid = row.get("id")
            if not sid:
                continue

            nodes.append(
                {
                    "type": "SummaryDocument",
                    "identifier": {"id": str(sid)},
                    "properties": {
                        "summary_content": row.get("summary_content"),
                        "status": row.get("status"),
                        "created_at": str(row.get("created_at"))
                        if row.get("created_at")
                        else None,
                    },
                }
            )

        for assoc in assoc_rows:
            doc_id = assoc.get("document_id")
            sid = assoc.get("summary_id")
            if not doc_id or not sid:
                continue

            rels.append(
                {
                    "from_type": "Document",
                    "from_id": {"id": str(doc_id)},
                    "rel_type": "HAS_SUMMARY",
                    "to_type": "SummaryDocument",
                    "to_id": {"id": str(sid)},
                    "properties": {},
                }
            )

        return self.graph_builder.build_from_data({"nodes": nodes, "relationships": rels})

    def migrate_all_documents_and_chunks(
        self,
        document_table: str = "documents",
        parent_table: str = "parent_chunks",
        child_table: str = "child_chunks",
        summary_table: str = "summary_documents",
        assoc_table: str = "document_summary_association",
        limit_documents: Optional[int] = None,
        limit_chunks: Optional[int] = None,
    ) -> Dict[str, int]:
        """
        Chạy toàn bộ migration liên quan đến documents/chunks/summaries.

        Trả về tổng nodes/relationships đã tạo (xấp xỉ, do build_from_data chạy từng phần).
        """
        total_nodes = 0
        total_rels = 0

        res_docs = self.migrate_documents(document_table, limit_documents)
        total_nodes += res_docs.get("nodes_created", 0)
        total_rels += res_docs.get("relationships_created", 0)

        res_parent = self.migrate_parent_chunks(parent_table, limit_chunks)
        total_nodes += res_parent.get("nodes_created", 0)
        total_rels += res_parent.get("relationships_created", 0)

        res_child = self.migrate_child_chunks(child_table, limit_chunks)
        total_nodes += res_child.get("nodes_created", 0)
        total_rels += res_child.get("relationships_created", 0)

        res_sum = self.migrate_summaries(summary_table, assoc_table, limit_documents)
        total_nodes += res_sum.get("nodes_created", 0)
        total_rels += res_sum.get("relationships_created", 0)

        return {
            "nodes_created": total_nodes,
            "relationships_created": total_rels,
            "total": total_nodes + total_rels,
        }

