"""Direct-answer and response handlers extracted from QueryPipeline."""

import os
import re
from typing import Any, Dict, Optional


def handle_birth_and_location_query(pipeline, query_info: Dict[str, Any]) -> Optional[str]:
    """Answer compound questions asking both birth time and birthplace."""
    entity = query_info.get("entity", "")
    if not entity:
        return None

    cypher = """
    MATCH (p:Person)
    WHERE toLower(coalesce(toStringOrNull(p.name), "")) CONTAINS toLower($entity)
       OR toLower(coalesce(toStringOrNull(p.full_name), "")) CONTAINS toLower($entity)
       OR toLower(coalesce(toStringOrNull(p.real_name), "")) CONTAINS toLower($entity)
       OR toLower(coalesce(toStringOrNull(p.birth_name), "")) CONTAINS toLower($entity)
    RETURN p.name as name,
           p.birth_year as birth_year,
           p.birth_date as birth_date,
           p.birth_place as birth_place,
           p.hometown as hometown
    LIMIT 3
    """
    try:
        with pipeline.graph_db.driver.session(database=pipeline.graph_db.database) as session:
            records = list(session.run(cypher, entity=entity))
            if not records:
                return None

            r = records[0]
            name = r.get("name") or entity
            birth_date = r.get("birth_date")
            birth_year = r.get("birth_year")
            birth_place = r.get("birth_place") or r.get("hometown")
            if birth_place:
                cleaned_place = re.sub(r"<[^>]+>", " ", str(birth_place))
                cleaned_place = re.sub(r"\s+", " ", cleaned_place).strip()
                lower_clean = cleaned_place.lower()
                if (
                    len(cleaned_place) > 120
                    or "http" in lower_clean
                    or "<" in cleaned_place
                    or "href" in lower_clean
                    or "</" in cleaned_place
                ):
                    cleaned_place = ""
                birth_place = cleaned_place

            if birth_date:
                birth_text = f"sinh ngày {birth_date}"
            elif birth_year:
                birth_text = f"sinh năm {birth_year}"
            else:
                birth_text = "chưa có dữ liệu rõ về năm sinh"

            place_text = f"quê ở {birth_place}" if birth_place else "chưa có dữ liệu rõ về quê quán"
            return f"{name} {birth_text} và {place_text}."
    except Exception as e:
        print(f"[Birth+Location Query] Error: {e}")
        return None


def generate_answer(pipeline, query_info: Dict[str, Any], context: str) -> str:
    """Generate answer from filtered context with streaming."""
    if not context:
        return no_data_answer()

    answer_text = ""
    print("  📡 Streaming response from LLM...\n")
    default_temp = float(os.getenv("LLM_TEMPERATURE", "0.1"))
    entity = query_info.get("entity")
    for chunk in pipeline.answer_generator.generate_answer_stream(
        question=query_info["original_question"],
        context=context,
        temperature=default_temp,
        entity=entity,
    ):
        print(chunk, end="", flush=True)
        answer_text += chunk

    print()
    return answer_text


def no_data_answer() -> str:
    """Fallback when no data found."""
    return """Không tìm thấy thông tin trong dữ liệu.

Gợi ý:
- Kiểm tra lại chính tả tên nhân vật
- Thử hỏi theo cách khác: "X là ai?" thay vì "tên thật của X"
- Nhân vật có thể chưa được thêm vào database"""

