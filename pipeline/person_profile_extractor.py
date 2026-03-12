"""Extract Person profiles from SummaryDocument text and write into Neo4j.

Sử dụng:
    python test_person_extraction.py

Ý tưởng:
- Đọc summary_content từ các node SummaryDocument (Neo4j).
- Gọi LLM (Gemini 2.0 Flash qua YEScale) để trích Person + fact quan trọng.
- Dùng GraphBuilder.create_person_with_profile() để sinh Person graph:
  Person, Country, Era, Field, Achievement, ...
"""

import json
from typing import Any, Dict, List, Optional

from graph.builder import GraphBuilder
from graph.storage import GraphDB
from llm.llm_client import call_llm


PERSON_EXTRACTION_PROMPT = """
Bạn là một trợ lý trích xuất tri thức từ văn bản tiếng Việt.

Đoạn văn sau mô tả về một hoặc nhiều nhân vật lịch sử / nhân vật quan trọng.
Nhiệm vụ của bạn:
- Trích xuất các thông tin có cấu trúc về Person.
- Ưu tiên điền birth_year, death_year (số) để trả lời "sinh năm nào?", "mất/qua đời năm nào?".
- Sự kiện "Qua đời" nên có year chính xác nếu văn bản nêu.
- Nếu có "Lên ngôi/Đăng quang/Thoái vị" và có năm thì điền year.
- Nếu văn bản gợi ý rõ (dù không ghi trực tiếp), bạn có thể SUY LUẬN năm sinh/năm mất/năm sự kiện.
- Điền vào các node Archievement như 1 thành tựu rằng họ đã làm gì đó sáng
- Điền các node field thì nên điền vào như là 1 lĩnh vực mà person đó hoạt động (ví dụ: quân sự)
- Điền các node Era biểu thị thời gian (Ví dụ: Triều đại..., Thế kỷ..., )
- Timepoint là các năm đặc biệt (Ví dụ:mất năm ..., sinh năm..., hoạt động sự kiện khoảng thời gian...,...)
- Chỉ dùng null khi thực sự không có đủ thông tin để suy luận hợp lý.

Nếu `focus_name` khác null: chỉ trả về thông tin cho đúng nhân vật đó; nếu văn bản không nói về người đó thì trả {"persons": []}.

focus_name: <<FOCUS_NAME_JSON>>

Văn bản:
\"\"\"<<TEXT>>\"\"\"

TRẢ VỀ DUY NHẤT JSON hợp lệ (không giải thích thêm), theo format mẫu:
{{
  "persons": [
    {{
      "name": null,
      "person_properties": {{
        "birth_date": null,
        "birth_year": null,
        "birth_month": null,
        "birth_day": null,
        "death_date": null,
        "death_year": null,
        "death_month": null,
        "death_day": null,
        "biography": null,
        "reign_start_year": null,
        "reign_end_year": null,
        "role": null,
        "aliases": null
      }},
      "roles": [],
      "dynasty": null,
      "born_in": {{
        "country": null,
        "city": null,
        "year": null
      }},
      "worked_in": [],
      "active_in": [],
      "achievements": [],
      "influenced_by": [],
      "parents": [],
      "events": [
        {{
          "name": null,
          "year": null,
          "month": null,
          "day": null,
          "description": null,
          "significance": null
        }}
      ]
    }}
  ]
}}
"""


class PersonProfileExtractor:
    """Trích xuất Person profile từ SummaryDocument trong Neo4j."""

    def __init__(self, graph_db: Optional[GraphDB] = None) -> None:
        self.graph_db = graph_db or GraphDB()
        self.builder = GraphBuilder(graph_db=self.graph_db)

    def _extract_from_text(
        self,
        text: str,
        temperature: float = 0.2,
        focus_name: Optional[str] = None,
        debug: bool = False,
    ) -> List[Dict[str, Any]]:
        """Gọi LLM để trích danh sách persons từ một đoạn text."""
        if not text or not text.strip():
            return []

        # Không dùng .format vì prompt có nhiều dấu { } của JSON mẫu
        prompt = (
            PERSON_EXTRACTION_PROMPT
            .replace("<<TEXT>>", text.strip())
            .replace("<<FOCUS_NAME_JSON>>", json.dumps(focus_name, ensure_ascii=False))
        )
        raw = call_llm(prompt, temperature=temperature, max_tokens=2048)
        if debug:
            print("\n--- DEBUG LLM RAW (first 800 chars) ---")
            print(raw[:800])

        # Cố gắng parse JSON, kể cả khi model trả thêm text
        def try_parse(s: str) -> Optional[Dict[str, Any]]:
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                # Thử cắt phần JSON giữa { ... }
                start = s.find("{")
                end = s.rfind("}") + 1
                if start >= 0 and end > start:
                    try:
                        return json.loads(s[start:end])
                    except json.JSONDecodeError:
                        return None
                return None

        data = try_parse(raw)
        if not data or "persons" not in data or not isinstance(data["persons"], list):
            if debug:
                print("DEBUG: JSON parse failed or missing 'persons'.")
            return []

        # Ensure list items are dicts
        normalized: List[Dict[str, Any]] = []
        for item in data["persons"]:
            if isinstance(item, dict):
                normalized.append(item)
            elif isinstance(item, str) and item.strip():
                normalized.append({"name": item.strip()})
        return normalized

    def _create_person_from_dict(self, person: Dict[str, Any]) -> None:
        """Map dict từ LLM sang create_person_with_profile()."""
        name = person.get("name")
        if not name:
            return

        person_props = person.get("person_properties") or {}
        # normalize aliases to list if it looks like a comma-separated string
        aliases = person_props.get("aliases")
        if isinstance(aliases, str) and "," in aliases:
            person_props["aliases"] = [a.strip() for a in aliases.split(",") if a.strip()]

        def ensure_list_of_dicts(value: Any) -> Optional[List[Dict[str, Any]]]:
            """Đảm bảo value là list[dict]; bỏ qua phần tử không hợp lệ."""
            if value is None:
                return None
            if not isinstance(value, list):
                return None
            out: List[Dict[str, Any]] = []
            for item in value:
                if isinstance(item, dict):
                    out.append(item)
                # Nếu LLM trả string, không đoán cấu trúc — bỏ qua để tránh lỗi
            return out or None

        born_in = person.get("born_in") or None
        worked_in = ensure_list_of_dicts(person.get("worked_in"))
        active_in = ensure_list_of_dicts(person.get("active_in"))
        achievements = ensure_list_of_dicts(person.get("achievements"))
        influenced_by = ensure_list_of_dicts(person.get("influenced_by"))
        parents = ensure_list_of_dicts(person.get("parents"))
        events = ensure_list_of_dicts(person.get("events"))
        roles = person.get("roles") or None
        dynasty = person.get("dynasty") or None

        # Gọi helper đã có sẵn
        self.builder.create_person_with_profile(
            person_name=name,
            person_properties=person_props,
            born_in=born_in,
            worked_in=worked_in,
            active_in=active_in,
            achievements=achievements,
            influenced_by=influenced_by,
            described_in=None,
            companies_founded=None,
            parents=parents,
            events=events,
            roles=roles,
            dynasty=dynasty,
        )

    def extract_from_summaries(self, limit: int = 10) -> Dict[str, int]:
        """
        Lấy một số SummaryDocument trong Neo4j và trích Person profile.

        Returns:
            {"summaries_processed": ..., "persons_created": ...}
        """
        summaries: List[Dict[str, Any]] = []

        with self.graph_db.driver.session(database=self.graph_db.database) as session:
            result = session.run(
                """
                MATCH (s:SummaryDocument)
                RETURN s.id AS id, s.summary_content AS summary
                ORDER BY s.created_at DESC
                LIMIT $limit
                """,
                limit=limit,
            )
            for record in result:
                summaries.append(
                    {"id": record["id"], "summary": record["summary"]},
                )

        persons_created = 0

        for item in summaries:
            persons = self._extract_from_text(item["summary"], focus_name=None, debug=False)
            for p in persons:
                try:
                    self._create_person_from_dict(p)
                    persons_created += 1
                except Exception as e:
                    # Đơn giản log ra console, tránh dừng cả batch
                    print(f"Error creating person from summary {item['id']}: {e}")

        return {
            "summaries_processed": len(summaries),
            "persons_created": persons_created,
        }

    def extract_from_chunks_for_name(self, name: str, limit: int = 50) -> Dict[str, int]:
        """
        Tìm các WikiChunk có nhắc tới `name` và trích Person từ đó.

        Hữu ích khi bạn muốn chắc chắn sinh node Person cho một nhân vật cụ thể
        (vd: 'Trần Nhân Tông') mà summary tổng quát chưa đủ rõ.
        """
        chunks: List[Dict[str, Any]] = []

        q = (name or "").strip().lower()
        tokens = [tok for tok in q.split() if len(tok) >= 2]
        if not tokens:
            return {"chunks_scanned": 0, "persons_created": 0}

        with self.graph_db.driver.session(database=self.graph_db.database) as session:
            result = session.run(
                """
                MATCH (w:WikiChunk)
                WHERE (
                       (
                         w.content IS NOT NULL AND
                         any(tok IN $tokens WHERE toLower(w.content) CONTAINS tok)
                       )
                    OR (
                         w.h1 IS NOT NULL AND
                         any(tok IN $tokens WHERE toLower(w.h1) CONTAINS tok)
                       )
                    OR (
                         w.h2 IS NOT NULL AND
                         any(tok IN $tokens WHERE toLower(w.h2) CONTAINS tok)
                       )
                    OR (
                         w.h3 IS NOT NULL AND
                         any(tok IN $tokens WHERE toLower(w.h3) CONTAINS tok)
                       )
                )
                RETURN w.id AS chunk_id,
                       w.content AS content,
                       w.h1 AS h1,
                       w.h2 AS h2,
                       w.h3 AS h3
                LIMIT $limit
                """,
                tokens=tokens,
                limit=limit,
            )
            for record in result:
                chunks.append(
                    {
                        "chunk_id": record["chunk_id"],
                        "content": record["content"],
                        "h1": record["h1"],
                        "h2": record["h2"],
                        "h3": record["h3"],
                    }
                )

        persons_created = 0

        def matches_target(extracted: str, target: str) -> bool:
            """
            Match mềm: target có thể là 'Lê Thái Tông' hoặc 'Thái Tông'.
            Điều kiện: tất cả token quan trọng của target phải xuất hiện trong extracted.
            """
            e = (extracted or "").strip().lower()
            t = (target or "").strip().lower()
            if not e or not t:
                return False
            # token hoá đơn giản theo khoảng trắng, bỏ token quá ngắn
            tokens = [tok for tok in t.split() if len(tok) >= 2]
            return all(tok in e for tok in tokens)

        for item in chunks:
            # Ghép tiêu đề + nội dung để LLM có đủ ngữ cảnh
            parts = [
                p for p in [item.get("h1"), item.get("h2"), item.get("h3"), item.get("content")] if p
            ]
            text = "\n".join(parts)
            persons = self._extract_from_text(text, focus_name=name, debug=False)

            for p in persons:
                # Chỉ tạo Person nếu tên khớp (hoặc chứa) name đang focus
                extracted_name = (p.get("name") or "").strip()
                if not extracted_name:
                    continue
                if not matches_target(extracted_name, name):
                    # Bỏ qua các nhân vật khác (vd: đoạn có cả Nguyễn Du và Trần Nhân Tông)
                    continue

                try:
                    self._create_person_from_dict(p)
                    persons_created += 1
                    # (Tuỳ chọn) có thể thêm DESCRIBED_IN tới chunk này nếu cần sau
                except Exception as e:
                    print(f"Error creating person from chunk {item['chunk_id']}: {e}")

        return {
            "chunks_scanned": len(chunks),
            "persons_created": persons_created,
        }

