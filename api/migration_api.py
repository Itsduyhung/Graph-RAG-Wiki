"""FastAPI app cung cấp endpoint migrate Postgres → Neo4j."""

from typing import Optional, Dict, Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from pipeline.pg_to_neo4j import PostgresToNeo4jMigrator


class MigrationRequest(BaseModel):
    """Body cho request migrate."""

    pg_dsn: str = Field(
        ...,
        description=(
            "Postgres DSN, ví dụ: "
            '"dbname=mydb user=myuser password=mypass host=localhost port=5432"'
        ),
    )
    person_table: str = Field(
        "persons",
        description="Tên bảng chứa dữ liệu Person trong Postgres",
    )
    limit: Optional[int] = Field(
        None,
        description="Giới hạn số dòng migrate (nếu muốn test trước)",
    )


class MigrationResponse(BaseModel):
    """Kết quả migrate."""

    status: str
    details: Dict[str, Any]


app = FastAPI(title="PG → Neo4j Migration API")


@app.post("/migrate/persons", response_model=MigrationResponse)
def migrate_persons(body: MigrationRequest) -> MigrationResponse:
    """Trigger migrate persons từ Postgres sang Neo4j."""
    migrator = PostgresToNeo4jMigrator(pg_dsn=body.pg_dsn)
    result = migrator.migrate_persons(
        person_table=body.person_table,
        limit=body.limit,
    )
    return MigrationResponse(status="success", details=result)


