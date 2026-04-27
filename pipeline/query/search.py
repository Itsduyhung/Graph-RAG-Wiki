"""Search-related helpers extracted from QueryPipeline."""

import re
from typing import Dict, List


def search_events(
    pipeline, entity: str, keywords: List[str], event_type: str = None, temporal_emperor: str = None
) -> List[Dict]:
    candidates = []
    if not pipeline.graph_db or not pipeline.graph_db.driver or not entity:
        return candidates

    try:
        with pipeline.graph_db.driver.session(database=pipeline.graph_db.database) as session:
            emperor_reign = None
            if temporal_emperor:
                emperor_reign = get_emperor_reign_dates(pipeline, session, temporal_emperor)
                if emperor_reign:
                    print(
                        f"  [Event] Filtering by emperor reign: {temporal_emperor} "
                        f"({emperor_reign.get('start')} - {emperor_reign.get('end')})"
                    )

            event_query = """
                MATCH (e:Event)
                WHERE toLower(e.name) CONTAINS toLower($entity)
                   OR toLower(e.description) CONTAINS toLower($entity)
                   OR toLower(e.location) CONTAINS toLower($entity)
                RETURN elementId(e) as id, e.name as name, e.date as date,
                       e.event_type as event_type, e.description as description,
                       e.location as location, e.participants as participants,
                       e.significance as significance
                LIMIT 30
            """

            results = session.run(event_query, entity=entity or "")
            for record in results:
                event_id = record.get("id")
                event_name = record.get("name") or ""
                event_date = record.get("date") or ""
                if not (event_id and event_name):
                    continue

                if emperor_reign and not event_during_reign(event_date, emperor_reign):
                    continue

                score = 0
                source = "event_search"
                entity_lower = entity.lower() if entity else ""
                if entity_lower and entity_lower in event_name.lower():
                    score = 3.0
                    source = "event_exact_match"
                elif any(kw and kw.lower() in event_name.lower() for kw in (keywords or [])):
                    score = 2.5
                    source = "event_keyword_match"
                else:
                    score = 1.5
                    source = "event_fulltext"

                evt_type_str = record.get("event_type") or ""
                evt_type = evt_type_str.upper() if evt_type_str else ""
                if event_type and evt_type and event_type.lower() == evt_type.lower():
                    score += 1.0
                if emperor_reign and event_during_reign(event_date, emperor_reign):
                    score += 0.5

                candidates.append(
                    {
                        "id": event_id,
                        "type": "Event",
                        "name": event_name,
                        "date": event_date,
                        "event_type": record.get("event_type"),
                        "description": record.get("description", ""),
                        "location": record.get("location", ""),
                        "participants": record.get("participants", ""),
                        "significance": record.get("significance", ""),
                        "score": score,
                        "source": source,
                        "all_names": [],
                        "related": [],
                        "properties": {},
                    }
                )

            if not candidates and event_type:
                fallback_query = """
                    MATCH (e:Event)
                    WHERE toLower(e.event_type) = toLower($event_type)
                    RETURN elementId(e) as id, e.name as name, e.date as date,
                           e.event_type as event_type, e.description as description,
                           e.location as location, e.participants as participants,
                           e.significance as significance
                    LIMIT 20
                """
                print(f"  [Event] Fallback: searching for all events of type {event_type}")
                fallback_results = session.run(fallback_query, event_type=event_type)
                for record in fallback_results:
                    event_id = record.get("id")
                    event_name = record.get("name") or ""
                    event_date = record.get("date") or ""
                    if not (event_id and event_name):
                        continue
                    if emperor_reign and not event_during_reign(event_date, emperor_reign):
                        continue
                    candidates.append(
                        {
                            "id": event_id,
                            "type": "Event",
                            "name": event_name,
                            "date": event_date,
                            "event_type": record.get("event_type"),
                            "description": record.get("description", ""),
                            "location": record.get("location", ""),
                            "participants": record.get("participants", ""),
                            "significance": record.get("significance", ""),
                            "score": 1.0,
                            "source": "event_type_fallback",
                            "all_names": [],
                            "related": [],
                            "properties": {},
                        }
                    )

            print(f"  [Event Search] Found {len(candidates)} events")
    except Exception as e:
        print(f"  [Event Search] Error: {e}")
    return candidates


def extract_emperor_from_query(keywords: List[str]) -> str:
    emperor_names = [
        "Kiến Phúc", "Dục Đức", "Đồng Khánh", "Thành Thái", "Khải Định",
        "Bảo Đại", "Cảnh Hùng", "Bình Việt", "Ưng Đăng", "Minh Mạng",
        "Tự Đức", "Tùn Thiện", "Hàm Nghi", "Gia Long", "Minh Huỳền",
    ]
    for keyword in keywords:
        for emperor in emperor_names:
            if emperor.lower() in keyword.lower() or keyword.lower() in emperor.lower():
                return emperor
    return None


def get_emperor_reign_dates(pipeline, session, emperor_name: str) -> dict:
    try:
        result = session.run(
            """
            MATCH (p:Person)
            WHERE toLower(p.name) CONTAINS toLower($emperor)
               OR toLower(p.main_name) CONTAINS toLower($emperor)
            RETURN p.reign_start as start, p.reign_end as end
            LIMIT 1
            """,
            emperor=emperor_name,
        )
        record = result.single()
        if record:
            return {"start": record.get("start"), "end": record.get("end")}
    except Exception as e:
        print(f"  [Event] Error getting reign dates: {e}")
    return None


def event_during_reign(event_date: str, emperor_reign: dict) -> bool:
    if not event_date or not emperor_reign:
        return False
    try:
        event_year = None
        if isinstance(event_date, str):
            year_match = re.search(r"(\d{4})", event_date)
            if year_match:
                event_year = int(year_match.group(1))
        if not event_year:
            return False

        start_year = None
        end_year = None
        if emperor_reign.get("start"):
            year_match = re.search(r"(\d{4})", str(emperor_reign.get("start")))
            if year_match:
                start_year = int(year_match.group(1))
        if emperor_reign.get("end"):
            year_match = re.search(r"(\d{4})", str(emperor_reign.get("end")))
            if year_match:
                end_year = int(year_match.group(1))

        if start_year and end_year:
            return start_year <= event_year <= end_year
        if start_year:
            return event_year >= start_year
        if end_year:
            return event_year <= end_year
    except Exception as e:
        print(f"  [Event] Error checking event date: {e}")
    return False


def search_people_with_titles(pipeline) -> List[Dict]:
    candidates = []
    if not pipeline.graph_db or not pipeline.graph_db.driver:
        return candidates
    try:
        with pipeline.graph_db.driver.session(database=pipeline.graph_db.database) as session:
            result = session.run(
                """
                MATCH (p:Person)
                WHERE p.title IS NOT NULL
                  AND (toLower(p.title) CONTAINS 'đế'
                       OR toLower(p.title) CONTAINS 'vua'
                       OR toLower(p.title) CONTAINS 'phó'
                       OR toLower(p.title) CONTAINS 'quốc'
                       OR toLower(p.title) CONTAINS 'công'
                       OR toLower(p.title) CONTAINS 'vương')
                RETURN elementId(p) as id, p.name as name, p.title as title,
                       p.birth_year as birth_year, p.death_year as death_year,
                       p.description as description
                LIMIT 30
                """
            )
            for record in result:
                person_id = record.get("id")
                person_name = record.get("name") or ""
                if person_id and person_name:
                    candidates.append(
                        {
                            "id": person_id,
                            "type": "Person",
                            "name": person_name,
                            "title": record.get("title", ""),
                            "birth_year": record.get("birth_year", ""),
                            "death_year": record.get("death_year", ""),
                            "description": record.get("description", ""),
                            "score": 1.5,
                            "source": "title_search",
                            "all_names": [],
                            "related": [],
                            "properties": {},
                        }
                    )

            print(f"  [Title Search] Found {len(candidates)} people with titles")
            specific_names = ["Trần Cảo", "Mạc Đăng Dung", "Mac Dang Dung"]
            for target_name in specific_names:
                specific_result = session.run(
                    """
                    MATCH (p:Person)
                    WHERE toLower(p.name) CONTAINS toLower($name)
                    RETURN elementId(p) as id, p.name as name, p.title as title,
                           p.description as description
                    LIMIT 1
                    """,
                    name=target_name,
                )
                for record in specific_result:
                    person_id = record.get("id")
                    if any(c.get("id") == person_id for c in candidates):
                        continue
                    person_name = record.get("name") or ""
                    if person_id and person_name:
                        candidates.append(
                            {
                                "id": person_id,
                                "type": "Person",
                                "name": person_name,
                                "title": record.get("title", ""),
                                "description": record.get("description", ""),
                                "score": 2.0,
                                "source": "specific_search",
                                "all_names": [],
                                "related": [],
                                "properties": {},
                            }
                        )
                        print(f"    + Added specific match: {person_name}")
    except Exception as e:
        print(f"  [Title Search] Error: {e}")
    return candidates


def search_by_name_alias(pipeline, entity: str, keywords: List[str]) -> List[Dict]:
    with pipeline.graph_db.driver.session(database=pipeline.graph_db.database) as session:
        candidates = []
        search_terms = [entity] + [k for k in keywords if len(k) > 2][:5]
        for term in search_terms:
            result = session.run(
                """
                MATCH (n:Name)
                WHERE n.value = $term OR n.name_type = $term
                RETURN n, labels(n)[0] as type
                LIMIT 5
                """,
                term=term,
            )
            for r in result:
                n = r["n"]
                nid = n.element_id
                if nid in [c.get("id") for c in candidates]:
                    continue
                person_result = session.run(
                    """
                    MATCH (n:Name)-[]-(p:Person)
                    WHERE elementId(n) = $nid
                    RETURN elementId(p) as person_eid, p.name as person_name
                    LIMIT 1
                    """,
                    nid=nid,
                )
                for pr in person_result:
                    candidates.append(
                        {
                            "id": pr["person_eid"],
                            "type": "Person",
                            "name": pr["person_name"],
                            "via_name": n.get("value", ""),
                            "properties": dict(n),
                            "score": 1.5,
                            "source": "name_alias",
                        }
                    )
        return candidates


def search_name_alias_for_entity(pipeline, entity: str, intent: str) -> List[Dict]:
    with pipeline.graph_db.driver.session(database=pipeline.graph_db.database) as session:
        candidates = []
        intent_to_nametype = {
            "birth_name": ["birth_name", "birthname", "tên khai sinh"],
            "real_name": ["real_name", "birth_name"],
            "temple_name": ["temple_name", "tên húy"],
            "original_name": ["original_name", "tên gốc"],
            "regnal_name": ["regnal_name", "niên hiệu"],
        }
        person_result = session.run(
            """
            MATCH (p:Person)
            WHERE toLower(coalesce(toStringOrNull(p.name), "")) CONTAINS toLower($entity)
               OR toLower(coalesce(toStringOrNull(p.full_name), "")) CONTAINS toLower($entity)
               OR toLower(coalesce(toStringOrNull(p.alias), "")) CONTAINS toLower($entity)
            RETURN elementId(p) as peid, p.name as pname
            LIMIT 3
            """,
            entity=entity,
        )
        for pr in person_result:
            pid = pr["peid"]
            pname = pr["pname"]
            all_names_result = session.run(
                """
                MATCH (p:Person)-[r]-(n:Name)
                WHERE elementId(p) = $peid
                RETURN n.value as name_value, n.name_type as name_type, type(r) as rel_type
                LIMIT 10
                """,
                peid=pid,
            )
            names = []
            for nr in all_names_result:
                nv = nr.get("name_value", "")
                if nv:
                    names.append({"value": nv, "type": nr.get("name_type", ""), "rel": nr.get("rel_type", "")})
            if names:
                candidates.append(
                    {
                        "id": pid,
                        "type": "Person",
                        "name": pname,
                        "score": 2.0,
                        "source": f"name_alias:{intent}",
                        "all_names": names,
                    }
                )
        return candidates


def search_relationship_for_entity(pipeline, entity: str, intent: str) -> List[Dict]:
    from retriever.graph_retriever import GraphRetriever

    retriever = GraphRetriever(pipeline.graph_db)
    try:
        rel_result = retriever.retrieve_by_relationship_type(entity, intent)
        candidates = []
        targets_with_year = []
        for target in rel_result.get("targets", []):
            target_props = target.get("target", {})
            rel_props = target.get("relationship_properties", {})
            tid = target_props.get("id") or target_props.get("name", "")
            if intent.upper() == "SPOUSE_OF":
                if rel_props.get("start_year"):
                    targets_with_year.append(
                        {
                            "target": target_props,
                            "rel_props": rel_props,
                            "tid": tid,
                            "direction": target.get("direction", "outgoing"),
                            "start_year": rel_props.get("start_year", 0),
                        }
                    )
                continue
            if tid:
                candidates.append(
                    {
                        "id": tid,
                        "type": "Person",
                        "name": target_props.get("name", ""),
                        "properties": target_props,
                        "score": 2.5,
                        "source": f"relationship:{intent}",
                        "relationship": intent,
                        "direction": target.get("direction", "outgoing"),
                        "relationship_properties": rel_props,
                    }
                )
        if intent.upper() == "SPOUSE_OF" and targets_with_year:
            targets_with_year.sort(key=lambda x: x["start_year"], reverse=True)
            most_recent = targets_with_year[0]
            candidates.append(
                {
                    "id": most_recent["tid"],
                    "type": "Person",
                    "name": most_recent["target"].get("name", ""),
                    "properties": most_recent["target"],
                    "score": 2.5,
                    "source": "relationship:SPOUSE_OF",
                    "relationship": "SPOUSE_OF",
                    "direction": most_recent["direction"],
                    "relationship_properties": most_recent["rel_props"],
                }
            )
        return candidates
    except Exception as e:
        print(f"  [Relationship] Error searching {intent} for {entity}: {e}")
        return []


def fulltext_search(pipeline, entity: str, keywords: List[str], include_events: bool = False) -> List[Dict]:
    with pipeline.graph_db.driver.session(database=pipeline.graph_db.database) as session:
        candidates = []
        search_terms = [entity] + [k for k in keywords if len(k) > 2][:3]
        print(f"  [Fulltext] Searching with terms: {search_terms}")

        for term in search_terms:
            exact_result = session.run(
                """
                MATCH (p:Person)
                WHERE toLower(p.name) = toLower($term)
                   OR toLower(p.full_name) = toLower($term)
                RETURN p, 'exact' as match_type
                LIMIT 5
                """,
                term=term,
            )
            exact_count = 0
            for r in exact_result:
                exact_count += 1
                node = r["p"]
                nid = node.element_id
                if nid not in [c.get("id") for c in candidates]:
                    all_names = get_all_names_for_node(session, nid)
                    candidates.append(
                        {
                            "id": nid,
                            "type": "Person",
                            "name": node.get("name", ""),
                            "properties": dict(node),
                            "score": 3.0,
                            "source": "exact_match",
                            "all_names": all_names,
                        }
                    )
            if exact_count > 0:
                print(f"  [Fulltext] EXACT match: found {exact_count} Person(s)")

        if not any(c.get("source") == "exact_match" for c in candidates):
            try:
                ft_query = f"{entity}~"
                result = session.run(
                    """
                    CALL db.index.fulltext.queryNodes("entityIndex", $search_query)
                    YIELD node, score
                    RETURN node, score
                    ORDER BY score DESC
                    LIMIT 10
                    """,
                    search_query=ft_query,
                )
                ft_count = 0
                for r in result:
                    ft_count += 1
                    node = r["node"]
                    nid = node.element_id
                    if nid not in [c.get("id") for c in candidates]:
                        candidates.append(
                            {
                                "id": nid,
                                "type": list(node.labels)[0] if node.labels else "Unknown",
                                "name": node.get("name", ""),
                                "properties": dict(node),
                                "score": r["score"] * 1.5,
                                "source": "fulltext",
                                "all_names": get_all_names_for_node(session, nid),
                            }
                        )
                if ft_count > 0:
                    print(f"  [Fulltext] Index found: {ft_count} results")
            except Exception as e:
                print(f"  [Fulltext] Index error: {e}")

        for term in search_terms:
            result = session.run(
                """
                MATCH (n)
                WHERE n.name = $term
                   OR n.value = $term
                   OR n.title = $term
                   OR n.full_name = $term
                RETURN n, labels(n)[0] as type
                LIMIT 10
                """,
                term=term,
            )
            for r in result:
                n = r["n"]
                nid = n.element_id
                ntype = r["type"]
                if nid in [c.get("id") for c in candidates]:
                    continue
                base_score = 1.5 if ntype == "Person" else 1.0
                candidates.append(
                    {
                        "id": nid,
                        "type": ntype,
                        "name": n.get("name", "") or n.get("value", ""),
                        "properties": dict(n),
                        "score": base_score,
                        "source": "fulltext_fallback",
                        "all_names": get_all_names_for_node(session, nid),
                    }
                )

        print(f"  [Fulltext] Total candidates: {len(candidates)}")

        if include_events:
            for term in search_terms:
                result = session.run(
                    """
                    MATCH (e:Event)
                    WHERE toLower(e.name) CONTAINS toLower($term)
                       OR toLower(e.description) CONTAINS toLower($term)
                       OR toLower(e.location) CONTAINS toLower($term)
                    RETURN e
                    LIMIT 10
                    """,
                    term=term,
                )
                for r in result:
                    e = r["e"]
                    eid = e.element_id
                    if eid not in [c.get("id") for c in candidates]:
                        candidates.append(
                            {
                                "id": eid,
                                "type": "Event",
                                "name": e.get("name", ""),
                                "date": e.get("date", ""),
                                "event_type": e.get("event_type", ""),
                                "description": e.get("description", ""),
                                "location": e.get("location", ""),
                                "participants": e.get("participants", ""),
                                "significance": e.get("significance", ""),
                                "properties": dict(e),
                                "score": 1.2,
                                "source": "fulltext_event",
                                "all_names": [],
                            }
                        )
        return candidates


def get_all_names_for_node(session, node_eid: str) -> List[Dict]:
    all_names = []
    try:
        result = session.run(
            """
            MATCH (n:Name)-[r]-(p)
            WHERE elementId(p) = $peid
            RETURN n.value as name_value, n.name_type as name_type, type(r) as rel_type
            """,
            peid=node_eid,
        )
        for r in result:
            nv = r.get("name_value", "")
            if nv:
                all_names.append({"value": nv, "type": r.get("name_type", ""), "rel": r.get("rel_type", "")})
    except Exception:
        pass
    return all_names


def soft_matching_search(pipeline, entity: str, keywords: List[str]) -> List[Dict]:
    with pipeline.graph_db.driver.session(database=pipeline.graph_db.database) as session:
        candidates = []
        search_texts = [entity.lower()] + [k.lower() for k in keywords if len(k) > 2]
        result = session.run(
            """
            MATCH (n)
            WHERE ANY(prop IN keys(n)
                WHERE prop IN ['biography', 'description', 'bio', 'content', 'text']
                  AND n[prop] IS NOT NULL
                  AND toLower(coalesce(toStringOrNull(n[prop]), "")) CONTAINS $search)
            RETURN n, labels(n)[0] as type
            LIMIT 10
            """,
            search=search_texts[0] if search_texts else entity,
        )
        for r in result:
            n = r["n"]
            nid = n.element_id
            candidates.append(
                {
                    "id": nid,
                    "type": r["type"],
                    "name": n.get("name", "") or n.get("value", ""),
                    "properties": dict(n),
                    "score": 0.7,
                    "source": "soft_match",
                    "all_names": get_all_names_for_node(session, nid),
                }
            )
        return candidates


def vector_search(pipeline, query: str) -> List[Dict]:
    model = pipeline._get_semantic_model()
    if not model:
        print("  [Vector] Model not available (sentence-transformers not installed)")
        return []
    try:
        query_embedding = model.encode(query).tolist()
        with pipeline.graph_db.driver.session(database=pipeline.graph_db.database) as session:
            candidates = []
            vector_indexes = ["PersonVectorIndex", "NameVectorIndex", "DynastyVectorIndex"]
            for idx_name in vector_indexes:
                try:
                    result = session.run(
                        f"""
                        CALL db.index.vector.queryNodes("{idx_name}", 10, $embedding)
                        YIELD node, score
                        RETURN node, score
                        ORDER BY score DESC
                        LIMIT 5
                        """,
                        embedding=query_embedding,
                    )
                    for r in result:
                        node = r["node"]
                        candidates.append(
                            {
                                "id": node.element_id,
                                "type": list(node.labels)[0] if node.labels else "Unknown",
                                "name": node.get("name", "") or node.get("value", ""),
                                "properties": dict(node),
                                "score": r["score"],
                                "source": "vector",
                            }
                        )
                except Exception:
                    pass
            if candidates:
                print(f"  [Vector] Found {len(candidates)} results")
            candidates.sort(key=lambda x: x["score"], reverse=True)
            return candidates[:10]
    except Exception as e:
        print(f"  [Vector] Error: {e}")
        return []

