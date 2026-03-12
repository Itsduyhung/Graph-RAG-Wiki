"""LangChain helper cho Postgres → Neo4j.

Mục đích:
- Dùng LangChain SQLDatabase + LLM để:
  - Khám phá schema Postgres.
  - Sinh gợi ý SQL SELECT phù hợp với câu hỏi hoặc intent.
- Sau đó, SQL cụ thể vẫn được đưa vào PostgresToNeo4jMigrator để map sang graph.

Lưu ý:
- Phần này là optional / advanced. Migration chuẩn vẫn nên dùng mapping rõ ràng.
"""

from typing import Optional

from langchain_community.utilities import SQLDatabase
from langchain_community.llms import Ollama
from langchain.chains import SQLDatabaseChain


class LangChainSqlHelper:
    """Dùng LangChain để sinh SQL gợi ý từ natural language."""

    def __init__(
        self,
        pg_uri: str,
        ollama_model: str = "mistral",
    ) -> None:
        """
        Args:
            pg_uri: SQLAlchemy URI tới Postgres, ví dụ:
                postgresql+psycopg2://user:pass@localhost:5432/dbname
            ollama_model: tên model Ollama (đồng bộ với config hiện tại).
        """
        self.db = SQLDatabase.from_uri(pg_uri)
        self.llm = Ollama(model=ollama_model)
        self.chain = SQLDatabaseChain.from_llm(self.llm, self.db, verbose=False)

    def suggest_sql(self, question: str) -> str:
        """
        Từ một câu hỏi / mô tả, sinh ra SQL SELECT gợi ý.

        Bạn có thể log SQL này rồi chỉnh tay,
        sau đó đưa vào pipeline migration.
        """
        # SQLDatabaseChain mặc định sẽ chạy SQL, nhưng ở đây ta chủ yếu muốn SQL.
        # Một cách đơn giản là yêu cầu nó in / trả về SQL.
        prompt = (
            "Chỉ tạo truy vấn SQL SELECT (không chạy), "
            "phù hợp với câu hỏi sau. Trả về thuần SQL:\n\n"
            f"{question}"
        )
        sql = self.llm(prompt)
        return sql.strip()

