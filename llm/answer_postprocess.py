"""Post-processing utilities for final LLM answers."""

import re


def clean_markdown_format(text: str) -> str:
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"\n\s*\*\s+", "\n", text)
    if text.startswith("* "):
        text = text[2:].lstrip()
    text = text.replace("*", "")
    return text


def clean_relationship_codes(text: str) -> str:
    relationship_map = {
        "FRIEND_OF": "bạn bè",
        "OPPONENT_OF_IDEOLOGY": "đối thủ về tư tưởng",
        "ALLY_OF": "đồng minh",
        "RIVAL_OF": "đối thủ",
        "CHILD_OF": "con của",
        "FATHER_OF": "cha của",
        "MOTHER_OF": "mẹ của",
        "PARENT_OF": "cha mẹ của",
        "SPOUSE_OF": "vợ/chồng của",
        "MARRIED_TO": "kết hôn với",
        "SIBLING_OF": "anh/chị/em của",
        "MENTOR_OF": "người cố vấn của",
        "STUDENT_OF": "học trò của",
        "SUCCESSOR_OF": "kế nhiệm",
        "PREDECESSOR_OF": "tiền nhiệm",
        "FOUNDED": "sáng lập",
        "WORKS_AT": "làm việc tại",
        "BORN_IN": "sinh tại",
        "BORN_AT": "sinh tại",
        "BORN_ON": "sinh ngày",
        "DIED_IN": "mất tại",
        "DIED_ON": "mất ngày",
        "PARTICIPATED_IN": "tham gia",
        "LED": "lãnh đạo",
        "COMMANDED": "chỉ huy",
        "INSTRUCTED": "chỉ thị",
        "RULED": "cai trị",
        "CROWNED_AS": "đăng quang làm",
        "CARED_BY": "được nuôi dạy bởi",
        "ADOPTED_CHILD_OF": "con nuôi của",
        "ADOPTED_BY": "được nhận làm con nuôi bởi",
        "MEMBER_OF": "thành viên của",
        "BELONGS_TO": "thuộc về",
    }
    for code, vi_text in relationship_map.items():
        text = re.sub(rf'["\']?\b{re.escape(code)}\b["\']?', vi_text, text)
    text = re.sub(r"\b(relationship|relationships|property|properties|node|nodes|edge|edges)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r'["\']?\b[A-Z]+(?:_[A-Z]+)+\b["\']?', "", text)
    text = re.sub(r'["\']\b[A-Z]{3,}\b["\']', "", text)
    text = re.sub(r"\(([^()]+)\)", r"\1", text)
    text = re.sub(r"\s+,", ",", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r" +([,.;:!?])", r"\1", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return text.strip()


def naturalize_vietnamese_response(text: str) -> str:
    active_person_match = re.search(r"\n\nActive person:.*$", text, flags=re.DOTALL)
    active_person_suffix = active_person_match.group(0) if active_person_match else ""
    body = text[:active_person_match.start()] if active_person_match else text
    cleanup_patterns = [
        (r"\bcó mối quan hệ\s*[:\-]?\s*(?=[,.;!?]|$)", ""),
        (r"\blà\s*(?=[,.;!?]|$)", ""),
        (r"\bvới\s*(?=[,.;!?]|$)", ""),
        (r"\bvà\s*(?=[,.;!?]|$)", ""),
        (r"\bbao gồm\s*[:\-]?\s*(?=[,.;!?]|$)", ""),
        (r"\bnhư\s+sau\s*[:\-]?\s*(?=[,.;!?]|$)", ""),
    ]
    for pattern, replacement in cleanup_patterns:
        body = re.sub(pattern, replacement, body, flags=re.IGNORECASE)
    body = re.sub(r"[,:;]\s*[,:;]+", ": ", body)
    body = re.sub(r"\.\s*\.", ".", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    body = re.sub(r"[ \t]{2,}", " ", body)
    body = re.sub(r" +([,.;:!?])", r"\1", body)
    body = re.sub(r"([,;:])\s*(\n|$)", r".\2", body)
    body = re.sub(r"^\s*[-*]\s*[.,;:!?]?\s*$", "", body, flags=re.MULTILINE)
    body = re.sub(r"^\s*\d+\.\s*[.,;:!?]?\s*$", "", body, flags=re.MULTILINE)
    lines = [line.strip() for line in body.splitlines()]
    lines = [line for line in lines if line]
    body = "\n".join(lines).strip()
    if not body:
        body = "Hiện tại mình chưa tìm thấy thông tin này trong dữ liệu."
    return f"{body}{active_person_suffix}".strip()


def enforce_vietnamese_only(text: str) -> str:
    active_person_match = re.search(r"\n\nActive person:.*$", text, flags=re.DOTALL)
    active_person_suffix = active_person_match.group(0) if active_person_match else ""
    body = text[:active_person_match.start()] if active_person_match else text
    english_to_vi = {
        "commanded": "chỉ huy",
        "instructed": "chỉ thị",
        "led": "lãnh đạo",
        "founded": "sáng lập",
        "participated_in": "tham gia",
        "works_at": "làm việc tại",
        "successor_of": "kế nhiệm",
        "predecessor_of": "tiền nhiệm",
        "spouse_of": "vợ/chồng của",
        "child_of": "con của",
        "father_of": "cha của",
        "mother_of": "mẹ của",
        "mentor_of": "người cố vấn của",
        "student_of": "học trò của",
    }
    for eng, vi in english_to_vi.items():
        body = re.sub(rf"\b{re.escape(eng)}\b", vi, body, flags=re.IGNORECASE)
    body = re.sub(r'["\']\b[A-Za-z_]{3,}\b["\']', "", body)
    body = re.sub(r"\b[A-Z]{3,}(?:_[A-Z]{2,})*\b", "", body)
    body = re.sub(r"\s+,", ",", body)
    body = re.sub(r"[ \t]{2,}", " ", body)
    body = re.sub(r" +([,.;:!?])", r"\1", body)
    body = re.sub(r"\n[ \t]+", "\n", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    body = body.strip()
    if not body:
        body = "Hiện tại mình chưa tìm thấy thông tin này trong dữ liệu."
    return f"{body}{active_person_suffix}".strip()


def postprocess_answer(text: str) -> str:
    """Apply post-processing in canonical order."""
    cleaned = clean_markdown_format(text)
    cleaned = clean_relationship_codes(cleaned)
    cleaned = naturalize_vietnamese_response(cleaned)
    cleaned = enforce_vietnamese_only(cleaned)
    return cleaned

