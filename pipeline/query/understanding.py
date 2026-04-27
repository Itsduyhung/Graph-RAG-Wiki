"""Query understanding and synonym helpers extracted from QueryPipeline."""

import json
import os
import re
from typing import Any, Dict, List, Optional

from llm.llm_client import call_llm

try:
    import underthesea

    WORD_SEG_AVAILABLE = True
except ImportError:
    WORD_SEG_AVAILABLE = False


def understand_query(pipeline, question: str) -> Dict[str, Any]:
    question_lower = question.lower()
    db_names = find_person_names_in_question(pipeline, question)
    if db_names:
        entity = db_names[0]
    else:
        entity = extract_entity(pipeline, question)
        caps = re.findall(r"\b[A-ZÀ-Ỹ][a-zà-ỹ]+\s+[A-ZÀ-Ỹ][a-zà-ỹ]+\b", question)
        if caps and str(entity).lower() in {"nêu", "kể", "cho biết", "trình bày", "liệt kê"}:
            entity = caps[0].strip()

    keywords = extract_keywords(question)

    intent = "identity"
    if ("ở đâu" in question_lower or "lưu vong ở" in question_lower or "sống ở" in question_lower) and any(
        w in question_lower for w in ["sống", "lưu vong", "lưu lạc"]
    ):
        intent = "location"

    high_priority_intents = ["location", "notable_works", "achievements"]
    for keyword, mapped_intent in pipeline.INTENT_MAPPING.items():
        if keyword in question_lower and mapped_intent in high_priority_intents:
            intent = mapped_intent
            break

    if intent == "identity":
        sorted_mappings = sorted(pipeline.INTENT_MAPPING.items(), key=lambda x: len(x[0]), reverse=True)
        for keyword, mapped_intent in sorted_mappings:
            if keyword in question_lower:
                intent = mapped_intent
                break

    target_type = infer_target_type(question_lower, intent)
    aggregation = llm_cypher_detection(pipeline, question_lower, entity, intent)
    return {
        "entity": entity,
        "intent": intent,
        "target_type": target_type,
        "keywords": keywords,
        "aggregation": aggregation,
        "original_question": question,
    }


def load_synonyms_from_db(pipeline) -> Dict[str, List[str]]:
    if pipeline._synonym_cache:
        return pipeline._synonym_cache
    if not pipeline.graph_db or not pipeline.graph_db.driver:
        return build_synonym_cache_from_groups(pipeline)
    try:
        with pipeline.graph_db.driver.session(database=pipeline.graph_db.database) as session:
            result = session.run(
                """
                MATCH (w1:Word)-[:SYNONYM]-(w2:Word)
                RETURN w1.name as word1, w2.name as word2
                """
            )
            synonym_map: Dict[str, set] = {}
            count = 0
            for r in result:
                w1 = r.get("word1", "")
                w2 = r.get("word2", "")
                if w1 and w2:
                    count += 1
                    synonym_map.setdefault(w1, set()).add(w2)
                    synonym_map.setdefault(w2, set()).add(w1)
            for word, synonyms in synonym_map.items():
                pipeline._synonym_cache[word] = list(synonyms)
            print(f"  [Synonyms] Loaded {count} synonym pairs from DB")
            if count == 0:
                print("  [Synonyms] DB has no synonyms, using fallback groups")
                return build_synonym_cache_from_groups(pipeline)
            return pipeline._synonym_cache
    except Exception as e:
        print(f"  [Synonyms] DB load failed: {e}, using fallback")
        return build_synonym_cache_from_groups(pipeline)


def build_synonym_cache_from_groups(pipeline) -> Dict[str, List[str]]:
    synonym_groups = getattr(pipeline, "EVENT_SYNONYM_GROUPS", [])
    for group in synonym_groups:
        for word in group:
            pipeline._synonym_cache.setdefault(word, [])
            for other in group:
                if other != word and other not in pipeline._synonym_cache[word]:
                    pipeline._synonym_cache[word].append(other)
    print(f"  [Synonyms] Built {len(pipeline._synonym_cache)} synonyms from groups")
    return pipeline._synonym_cache


def get_synonyms(pipeline, word: str) -> List[str]:
    if not pipeline._synonym_cache:
        load_synonyms_from_db(pipeline)
    return pipeline._synonym_cache.get(word, [])


def expand_query_with_synonyms(pipeline, keywords: List[str]) -> List[str]:
    expanded = list(keywords)
    for kw in keywords:
        for syn in get_synonyms(pipeline, kw):
            if syn not in expanded:
                expanded.append(syn)
    return expanded


def extract_entity(pipeline, question: str) -> str:
    question_clean = question
    particles = ["thứ mấy", "bao lâu", "bao lâu?", "mấy năm", "bao năm", "bao giờ"]
    for particle in particles:
        question_clean = question_clean.replace(particle, "")

    patterns = [
        (r"Sau khi\s+.+?(?:,|\s+)\s*(.+?)(?:\s+tự\s+xưng|\s+chiếm|\s+có|\s+được|\s+là|$|\?)", 1),
        (r"(?:lần\s+\d+|lần\s+thứ\s+\w+)\s*,?\s*(.+?)(?:\s+chiếm|\s+tự\s+xưng|\s+là|$|\?)", 1),
        (r"(?:vua|hoàng\s+đế|thái\s+tử|vương|công|tước)\s+([A-ZÀ-ỹ][a-zà-ỹ\s]+?)(?:\s+(?:tại|trị|sinh|mất|là|của|bao)|\?|$)", 1),
        (r"việc\s+([A-ZÀ-ỹ][a-zà-ỹ\s]+?)(?:\s+(?:bị|được|lên|đổi|phế|thoái|qua|tịch))", 1),
        (r"(?:Sau khi|khi|Khi)\s+([A-ZÀ-ỹ][a-zà-ỹ\s]+?)(?:\s+(?:thoái|đăng|lên|xuống|bị|được))", 1),
        (r"người\s+(kế\s+nhiệm|tiền\s+nhiệm)\s+([A-ZÀ-ỹ][a-zà-ỹ\s]+?)(?:\s+là\s+ai)", 2),
        (r"^([A-ZÀ-ỹ][a-zà-ỹ\s]+?)(?:\s+là\s+.+?phải\s+không)", 1),
        (r"^([A-ZÀ-ỹ][a-zà-ỹ\s]+?)(?:\s+là\s+ai|\s+là\s+gì|\s+ở\s+đâu)", 1),
        (r"\b([A-ZÀ-ỹ][a-zà-ỹ\s]*[A-ZÀ-ỹ])\s+(?:được|là|gọi|mệnh|đoạt)", 1),
        (r"^([A-ZÀ-ỹ][a-zà-ỹ]{2,})(?:\s+|$|\?)", 1),
        (r"(?:tên|của|ai là|gì là)\s+([A-ZÀ-ỹ][a-zà-ỹ\s]+?)(?:\?|$)", 1),
        (r",?\s*([A-ZÀ-ỹ][a-zà-ỹ\s]+?)(?:\s+(?:giữ|làm|được|đóng|là|có|ở|sống|mất|năm|nơi|được\s+tổ))", 1),
        (r"(?:trong|cho|với)\s+([A-ZÀ-ỹ][a-zà-ỹ\s]+?)(?:\s|$|\?)", 1),
        (r",\s*([A-ZÀ-ỹ][a-zà-ỹ\s]+?)(?:\s+(?:giữ|làm|được|đóng|là|có))", 1),
    ]

    for pattern, group in patterns:
        match = re.search(pattern, question, re.IGNORECASE)
        if match:
            extracted = match.group(group).strip()
            temporal_suffixes = [
                "sinh năm",
                "mất năm",
                "đăng quang",
                "lên ngôi",
                "thoái vị",
                "năm nào",
                "lúc nào",
                "ra sao",
                "tự xưng",
                "tự xưng là",
                "tử nạn",
                "bị phế truất",
            ]
            for suffix in temporal_suffixes:
                if extracted.lower().endswith(suffix):
                    extracted = extracted[: -len(suffix)].strip()
                if " " + suffix in " " + extracted.lower():
                    extracted = extracted[: extracted.lower().rfind(" " + suffix)].strip()
            stopwords = {
                "ai", "gì", "ở", "đâu", "nào", "chính", "phủ", "việt", "nam", "dân", "chủ", "cộng", "hòa",
                "vai", "trò", "sau", "khi", "trong", "cho", "với", "năm", "tháng", "ngày", "lời", "bài",
                "vua", "hoàng", "đế", "thái", "tử", "vương", "công", "tước", "được", "là", "tự", "xưng", "hiệu",
            }
            cleaned = " ".join(w for w in extracted.split() if w.lower() not in stopwords)
            if cleaned and len(cleaned) > 2:
                return cleaned

    try:
        all_names = find_person_names_in_question(pipeline, question)
        if all_names:
            return all_names[0]
    except Exception:
        pass

    if WORD_SEG_AVAILABLE:
        words = underthesea.word_tokenize(question)
        entity_words = []
        stopwords = {
            "sinh", "mất", "năm", "lên", "đăng", "ngày", "tháng", "lúc", "thôi", "là", "ai", "gì", "ở", "đâu",
            "của", "sau", "khi", "trong", "vai", "trò", "giữ", "được", "chính", "phủ", "việt", "nam", "dân",
            "chủ", "cộng", "hòa", "?", "vua", "hoàng", "đế", "thái", "tử",
        }
        for w in words:
            if w.lower() in stopwords:
                continue
            if w and w[0].isupper():
                entity_words.append(w)
        if entity_words:
            return " ".join(entity_words[:2])

    for w in question.split():
        if w and w[0].isupper():
            return w
    return question.strip().rstrip("?").strip()


def find_person_names_in_question(pipeline, question: str) -> List[str]:
    if not pipeline.graph_db or not pipeline.graph_db.driver:
        return []
    try:
        question_lower = question.lower()
        words = re.findall(r"[\wÀ-ỹ]+", question)
        potential_names = []
        for i in range(len(words)):
            for length in [3, 2]:
                if i + length <= len(words):
                    phrase = " ".join(words[i : i + length])
                    if phrase.lower() not in ["sinh năm", "mất năm", "là ai", "ai là", "tên của"]:
                        potential_names.append(phrase)
        for word in words:
            if len(word) >= 2 and word.lower() not in ["sinh", "mất", "năm", "bao", "nhiêu", "nào", "là", "ai", "gì", "đâu", "của", "tại"]:
                potential_names.append(word)
        if not potential_names:
            return []

        found_names = []
        with pipeline.graph_db.driver.session(database=pipeline.graph_db.database) as session:
            for candidate in potential_names:
                candidate_lower = re.sub(r"[^\wÀ-ỹ\s]", "", candidate.lower()).strip()
                if len(candidate_lower) <= 2:
                    continue
                result = session.run(
                    """
                    MATCH (p:Person)
                    WHERE toLower(coalesce(toStringOrNull(p.name), "")) CONTAINS $search_term
                       OR toLower(coalesce(toStringOrNull(p.full_name), "")) CONTAINS $search_term
                       OR toLower(coalesce(toStringOrNull(p.other_name), "")) CONTAINS $search_term
                       OR toLower(coalesce(toStringOrNull(p.real_name), "")) CONTAINS $search_term
                       OR toLower(coalesce(toStringOrNull(p.birth_name), "")) CONTAINS $search_term
                    RETURN p.name as name
                    LIMIT 100
                    """,
                    {"search_term": candidate_lower},
                )
                for record in result:
                    name = (record.get("name") or "").strip()
                    if name and len(name) > 2 and name.lower() in question_lower:
                        found_names.append((name, 5000 + len(name.split())))
        found_names_dict = {}
        for name, score in found_names:
            if name not in found_names_dict or score > found_names_dict[name]:
                found_names_dict[name] = score
        sorted_names = sorted(found_names_dict.items(), key=lambda x: (x[1], len(x[0])), reverse=True)
        return [name for name, _ in sorted_names]
    except Exception as e:
        print(f"  [ERROR] _find_person_names_in_question failed: {str(e)[:100]}")
        return []


def extract_keywords(question: str) -> List[str]:
    stopwords = {
        "là",
        "ai",
        "gì",
        "đâu",
        "khi",
        "nào",
        "ông",
        "bà",
        "của",
        "trong",
        "với",
        "vì",
        "cho",
        "hay",
        "có",
        "không",
        "và",
        "hoặc",
        "được",
        "để",
        "ra",
        "vào",
        "lên",
        "xuống",
        "ở",
        "bởi",
        "thứ",
        "một",
        "hai",
        "ba",
        "bốn",
        "năm",
        "sáu",
        "bảy",
        "tám",
        "chín",
        "mười",
        "cho",
        "nào",
        "những",
        "các",
        "với",
    }
    if WORD_SEG_AVAILABLE:
        words = underthesea.word_tokenize(question.lower())
    else:
        words = re.findall(r"\b[\wÀ-ỹ]+\b", question.lower())
    return [w for w in words if w not in stopwords and len(w) > 1]


def get_query_variants(pipeline, question: str, entity: str = None) -> List[str]:
    variants = [question]
    question_lower = question.lower()
    try:
        llm_variants = generate_variants_with_llm(pipeline, question, entity)
        if llm_variants:
            variants.extend(llm_variants)
            print(f"  [Variants] LLM generated: {len(llm_variants)} variants")
    except Exception as e:
        print(f"  [Variants] LLM generation failed: {e}, using rule-based")

    for key, synonyms in pipeline.QUERY_VARIANTS.items():
        if key in question_lower:
            for syn in synonyms:
                variant = question_lower.replace(key, syn)
                if variant != question_lower:
                    variants.append(variant)
            if entity:
                for syn in synonyms[:2]:
                    variants.append(f"{entity} {syn}")
    return list(set(variants))[:8]


def generate_variants_with_llm(pipeline, question: str, entity: str = None) -> List[str]:
    entity_part = f" (entity: {entity})" if entity else ""
    prompt = f"""Bạn là chuyên gia tạo biến thể câu hỏi tiếng Việt.
Tạo 3-5 biến thể KHÁC NHAU của câu hỏi sau, giữ nguyên ý nghĩa nhưng dùng từ ngữ khác.{entity_part}

Câu hỏi gốc: "{question}"

YÊU CẦU:
- Mỗi biến thể phải KHÁC với câu gốc và với nhau
- Dùng từ đồng nghĩa, cách diễn đạt khác
- Giữ nguyên entity (tên người/sự kiện)
- Không thay đổi ý nghĩa câu hỏi

Trả về MỖI câu hỏi trên 1 dòng, không đánh số, không có giải thích."""
    try:
        response = call_llm(prompt, model=pipeline.model, temperature=0.8)
        lines = [line.strip() for line in response.strip().split("\n") if line.strip()]
        return [v for v in lines if v and v.lower() != question.lower()][:5]
    except Exception as e:
        print(f"  [Variants] LLM call failed: {e}")
        return []


def infer_target_type(question_lower: str, intent: str) -> str:
    if any(w in question_lower for w in ["triều", "đại"]):
        return "Dynasty"
    if any(w in question_lower for w in ["sự kiện", "chiến tranh", "trận"]):
        return "Event"
    if any(w in question_lower for w in ["vua", "hoàng đế", "nhà", "thái tử"]):
        return "Person"
    return "Person"


def llm_cypher_detection(pipeline, question_lower: str, entity: str, intent: str) -> Optional[Dict[str, Any]]:
    if entity and len(entity.split()) >= 2 and not any(word in entity.lower() for word in ["triều", "nhà", "đại"]):
        print(f"  [Cypher] Skipping LLM detection for specific entity: {entity}")
        return None

    from prompts import CYPHER_DETECTION_PROMPT

    prompt = CYPHER_DETECTION_PROMPT.format(question=question_lower)
    try:
        default_temp = float(os.getenv("LLM_TEMPERATURE", "0.1"))
        response = call_llm(prompt, model="gemini-2.5-flash-lite", temperature=default_temp)
        result = json.loads(response.strip())
        if result.get("needs_cypher", False):
            cypher_query = result.get("cypher_query", "")
            if cypher_query:
                return {"type": "cypher", "cypher_query": cypher_query, "explanation": result.get("explanation", "")}
    except Exception as e:
        print(f"[WARNING] LLM Cypher detection failed: {e}")
        return fallback_pattern_detection(question_lower, entity, intent)
    return None


def fallback_pattern_detection(question_lower: str, entity: str, intent: str) -> Optional[Dict[str, Any]]:
    if "vua" not in question_lower and "hoàng đế" not in question_lower:
        return None
    min_duration_patterns = [
        "trị vì ngắn nhất",
        "cai trị ngắn nhất",
        "trị vì ít nhất",
        "cai trị ít nhất",
        "thời gian trị vì ít nhất",
        "thời gian cai trị ít nhất",
        "thời gian trị vì ngắn nhất",
        "thời gian cai trị ngắn nhất",
        "thống trị ngắn nhất",
    ]
    max_duration_patterns = [
        "trị vì lâu nhất",
        "cai trị lâu nhất",
        "thời gian trị vì lâu nhất",
        "thời gian cai trị lâu nhất",
        "thống trị lâu nhất",
        "thời gian cai trị dài nhất",
    ]
    first_patterns = ["vua đầu tiên", "ai là vua đầu tiên", "vua đầu tiên của", "vua đầu tiên trong", "vua đầu tiên ở"]
    last_patterns = ["vua cuối cùng", "ai là vua cuối cùng", "vua cuối cùng của", "vua cuối cùng trong", "vua cuối cùng ở"]
    if any(p in question_lower for p in min_duration_patterns):
        return {"type": "aggregation", "operation": "min", "metric": "reign_duration", "scope": "Dynasty", "target": "Person"}
    if any(p in question_lower for p in max_duration_patterns):
        return {"type": "aggregation", "operation": "max", "metric": "reign_duration", "scope": "Dynasty", "target": "Person"}
    if any(p in question_lower for p in first_patterns):
        return {"type": "aggregation", "operation": "min", "metric": "reign_start_year", "scope": "Dynasty", "target": "Person"}
    if any(p in question_lower for p in last_patterns):
        if entity and len(entity.split()) >= 2 and not any(word in entity.lower() for word in ["triều", "nhà"]):
            return None
        return {"type": "aggregation", "operation": "max", "metric": "reign_end_year", "scope": "Dynasty", "target": "Person"}
    emperor_position_pattern = r"([A-ZÀ-ỹ][a-zà-ỹ\s]*[A-ZÀ-ỹ])\s+là\s+vua\s+thứ\s+(\w+)\s+(?:của\s+)?(?:triều|nhà)\s+([A-ZÀ-ỹ][a-zà-ỹ\s]*[A-ZÀ-ỹ])"
    match = re.search(emperor_position_pattern, question_lower)
    if match:
        return {
            "type": "emperor_position",
            "person": match.group(1).strip(),
            "position_word": match.group(2).strip(),
            "dynasty": match.group(3).strip(),
        }
    if "ngắn nhất" in question_lower and "trị vì" in question_lower:
        return {"type": "aggregation", "operation": "min", "metric": "reign_duration", "scope": "Dynasty", "target": "Person"}
    return None


def is_compound_question(question: str) -> bool:
    q = (question or "").lower()
    if not q:
        return False
    has_connector = any(token in q for token in [" và ", " đồng thời ", " cũng như ", ", và "])
    temporal_markers = ["sinh năm", "ngày sinh", "năm sinh", "mất năm", "ngày mất", "qua đời"]
    location_markers = ["ở đâu", "quê ở đâu", "quê quán", "sinh ở đâu", "quê"]
    asks_temporal = any(k in q for k in temporal_markers)
    asks_location = any(k in q for k in location_markers)
    return has_connector and (asks_temporal and asks_location)


def should_use_direct_notable_works(question: str) -> bool:
    q = (question or "").lower()
    if not q:
        return False
    simple_patterns = [
        "tác phẩm tiêu biểu nào",
        "những tác phẩm tiêu biểu",
        "các tác phẩm tiêu biểu",
        "có những tác phẩm",
        "nổi tiếng với tác phẩm nào",
        "tác phẩm nào",
    ]
    contextual_patterns = ["trong hoàn cảnh", "hoàn cảnh nào", "vì sao", "như thế nào", "khi nào", "ở đâu", "ý nghĩa", "nội dung", "phân tích"]
    if any(k in q for k in contextual_patterns):
        return False
    return any(k in q for k in simple_patterns)


def is_birth_and_location_question(question: str) -> bool:
    q = (question or "").lower()
    birth_markers = ["sinh năm", "ngày sinh", "năm sinh", "sinh khi nào"]
    location_markers = ["quê ở đâu", "quê quán", "quê", "sinh ở đâu", "ở đâu"]
    return any(k in q for k in birth_markers) and any(k in q for k in location_markers)

