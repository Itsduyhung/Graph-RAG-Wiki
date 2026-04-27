"""Candidate retrieval helpers extracted from QueryPipeline."""

from typing import Any, Dict, List


def retrieve_candidates(pipeline, query_info: Dict[str, Any], semantic_available: bool) -> List[Dict]:
    """DB-driven candidate retrieval."""
    entity = query_info.get("entity", "")
    keywords = query_info.get("keywords", [])
    intent = query_info.get("intent", "")

    candidates: List[Dict] = []
    seen_ids = set()

    relationship_intents = [
        "SUCCESSOR_OF",
        "PREDECESSOR_OF",
        "ADOPTED_CHILD_OF",
        "ADOPTIVE_PARENT_OF",
        "FOSTER_CHILD_OF",
        "FOSTER_PARENT_OF",
    ]
    if intent in relationship_intents:
        rel_candidates = pipeline._search_relationship_for_entity(entity, intent)
        print(f"  [Relationship] Found {len(rel_candidates)} relationship candidates for {intent}")
        for c in rel_candidates:
            if c.get("id") not in seen_ids:
                c["score"] = 2.5
                candidates.append(c)
                seen_ids.add(c.get("id"))

    with pipeline.graph_db.driver.session(database=pipeline.graph_db.database) as session:
        debug_result = session.run(
            """
            MATCH (p:Person)
            WHERE toLower(coalesce(toStringOrNull(p.name), "")) CONTAINS toLower($entity)
            RETURN p.name as name, p.birth_date as birth_date, p.death_date as death_date
            LIMIT 3
            """,
            entity=entity,
        )
        debug_persons = list(debug_result)
        if debug_persons:
            print(f"  [DEBUG] DB has Person(s) matching '{entity}':")
            for p in debug_persons:
                print(f"    - {p['name']} (birth: {p.get('birth_date', 'N/A')}, death: {p.get('death_date', 'N/A')})")
        else:
            print(f"  [DEBUG] NO Person found in DB matching '{entity}'")

    expanded_keywords = pipeline._expand_query_with_synonyms(keywords)
    if expanded_keywords != keywords:
        print(f"  [Synonyms] Expanded: {keywords} → {expanded_keywords}")

    name_intents = ["birth_name", "real_name", "temple_name", "original_name", "regnal_name"]
    if intent in name_intents:
        for c in pipeline._search_name_alias_for_entity(entity, intent):
            if c.get("id") not in seen_ids:
                c["score"] = 2.0
                candidates.append(c)
                seen_ids.add(c.get("id"))

    event_intents = ["EVENT", "TREATY", "MILITARY", "REBELLION"]
    if intent in event_intents:
        temporal_emperor = pipeline._extract_emperor_from_query(keywords)
        event_candidates = pipeline._search_events(entity, expanded_keywords, intent, temporal_emperor)
        print(f"  [Event] Found {len(event_candidates)} event candidates for intent '{intent}'")
        for c in event_candidates:
            if c.get("id") not in seen_ids:
                candidates.append(c)
                seen_ids.add(c.get("id"))

    for c in pipeline._search_by_name_alias(entity, keywords):
        if c.get("id") not in seen_ids:
            candidates.append(c)
            seen_ids.add(c.get("id"))

    ft_candidates = pipeline._fulltext_search(entity, expanded_keywords, include_events=(intent not in event_intents))
    for c in ft_candidates:
        if c.get("id") not in seen_ids:
            candidates.append(c)
            seen_ids.add(c.get("id"))

    if len(candidates) < 5 and len(entity) > 30:
        print(f"  [Fallback] Entity too complex ({len(entity)} chars), searching with keywords instead")
        keyword_candidates = pipeline._fulltext_search("", expanded_keywords, include_events=True)
        for c in keyword_candidates:
            if c.get("id") not in seen_ids:
                c["score"] = c.get("score", 1.0) * 0.8
                candidates.append(c)
                seen_ids.add(c.get("id"))

        print("  [Fallback2] Searching for people with titles...")
        title_search_candidates = pipeline._search_people_with_titles()
        for c in title_search_candidates:
            if c.get("id") not in seen_ids:
                c["score"] = c.get("score", 1.0) * 0.7
                candidates.append(c)
                seen_ids.add(c.get("id"))

    if len(candidates) < 3:
        for c in pipeline._soft_matching_search(entity, expanded_keywords):
            if c.get("id") not in seen_ids:
                candidates.append(c)
                seen_ids.add(c.get("id"))

    if len(candidates) < 3 and semantic_available:
        for c in pipeline._vector_search(entity):
            if c.get("id") not in seen_ids:
                candidates.append(c)
                seen_ids.add(c.get("id"))

    def sort_key(candidate: Dict[str, Any]):
        source_priority = {
            "exact_match": 1.0,
            "name_alias:birth_name": 1.0,
            "name_alias": 0.9,
            "fulltext": 0.8,
            "fulltext_fallback": 0.7,
            "soft_match": 0.5,
            "vector": 0.3,
        }
        source = candidate.get("source", "")
        priority = 0.5
        for key, val in source_priority.items():
            if key in source:
                priority = val
                break
        return (1 - priority, -candidate.get("score", 0))

    candidates.sort(key=sort_key)
    return candidates[:20]

