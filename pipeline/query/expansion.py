"""Graph expansion helpers extracted from QueryPipeline."""

from typing import Dict, List


def expand_graph(pipeline, candidates: List[Dict]) -> List[Dict]:
    if not candidates:
        return []

    max_total_nodes = 200
    candidate_ids = [c["id"] for c in candidates[:50]]

    with pipeline.graph_db.driver.session(database=pipeline.graph_db.database) as session:
        batch_query = """
        UNWIND $cids AS cid
        MATCH (center) WHERE elementId(center) = cid
        MATCH (center)-[r*1..1]-(neighbor)
        WHERE NOT elementId(neighbor) = cid
        WITH DISTINCT neighbor
        LIMIT $total_limit
        RETURN elementId(neighbor) AS nid, labels(neighbor)[0] AS ntype
        """

        nodes_to_fetch = session.run(batch_query, cids=candidate_ids, total_limit=max_total_nodes)
        expanded = {}
        person_ids = []

        for record in nodes_to_fetch:
            if record["ntype"] == "Person":
                person_ids.append(record["nid"])
            else:
                expanded[record["nid"]] = {"id": record["nid"], "type": record["ntype"]}

        if person_ids:
            for pid in person_ids:
                if len(expanded) >= max_total_nodes:
                    break
                person_data = get_person_context(pipeline, session, pid)
                if person_data:
                    expanded[pid] = person_data

        return list(expanded.values())


def get_person_context(pipeline, session, person_eid: str) -> Dict:
    mega_query = """
    MATCH (p:Person) WHERE elementId(p) = $peid
    RETURN p {
        .*,
        all_names_raw: [(p)-[r]-(n:Name) | { value: n.value, type: n.name_type, rel: type(r) }],
        related_nodes: [(p)-[r]-(rel) WHERE NOT rel:Person AND NOT rel:Name | {
            name: rel.name, type: labels(rel)[0], rel_type: type(r),
            is_outgoing: startNode(r) = p,
            year: rel.year, month: rel.month, age: rel.age,
            description: rel.description, date: rel.date,
            event_persons: [(rel)-[er]-(p2:Person) WHERE p2 <> p | p2.name][0..5]
        }][0..100],
        family: [(p)-[r]-(f:Person) | {
            name: f.name, rel_type: type(r),
            is_outgoing: startNode(r) = p, rel_props: properties(r)
        }][0..30]
    } AS full_data
    """
    result = session.run(mega_query, peid=person_eid)
    record = result.single()
    if not record:
        return {}

    data = record["full_data"]
    context = {"id": person_eid, "type": "Person", "all_names": [], "related": []}

    fields = [
        "name", "full_name", "other_name", "birth_name", "nickname", "alias",
        "description", "role", "title", "birth_date", "death_date",
        "birth_year", "death_year", "reign_start", "reign_end",
        "reign_duration", "personality", "adoptive_father", "father", "mother",
    ]
    for field in fields:
        context[field] = data.get(field, "") or ""

    for n in data.get("all_names_raw", []):
        context["all_names"].append({"value": n["value"], "type": n["type"], "rel": n["rel"]})

    for rr in data.get("related_nodes", []):
        rel_text = pipeline._format_relationship(rr["rel_type"], rr["is_outgoing"], rr["name"])
        parts = []
        if rr.get("date"):
            parts.append(f"ngày: {rr['date']}")
        if rr.get("month"):
            parts.append(f"tháng: {rr['month']}")
        if rr.get("year"):
            parts.append(f"năm: {rr['year']}")
        if rr.get("age"):
            parts.append(f"tuổi: {rr['age']}")
        rel_detail = f" [{', '.join(parts)}]" if parts else ""
        related_persons = ""
        if rr.get("event_persons"):
            related_persons = f" - Người liên quan: {', '.join(rr['event_persons'])}"

        context["related"].append(
            {
                "name": rr["name"],
                "type": rr["type"],
                "rel": rel_text,
                "detail": rel_detail,
                "related_persons": related_persons,
                "description": rr.get("description", "") or "",
                "year": rr.get("year", ""),
                "month": rr.get("month", ""),
                "date": rr.get("date", ""),
            }
        )

    for family in data.get("family", []):
        rel_text = pipeline._format_relationship(
            family["rel_type"], family["is_outgoing"], family["name"], family["rel_props"]
        )
        context["related"].append(
            {"name": family["name"], "type": "Person", "rel": rel_text, "rel_props": family["rel_props"]}
        )

    return context

