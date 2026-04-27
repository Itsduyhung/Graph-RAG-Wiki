"""Context formatting/filtering extracted from QueryPipeline."""

from typing import Any, Dict, List


def filter_context(pipeline, query_info: Dict[str, Any], candidates: List[Dict[str, Any]]) -> str:
    """LLM filter context - send full context."""
    if not candidates:
        return ""

    entity = query_info.get("entity", "")
    intent = query_info.get("intent", "")

    context_text = format_candidates(candidates, main_entity_name=entity)

    print("\n  [DEBUG] === CONTEXT FILTERING DEBUG ===")
    print(f"  Entity: {entity}")
    print(f"  Intent: {intent}")
    print(f"  Total candidates: {len(candidates)}")
    print(f"  [DEBUG] Raw context length: {len(context_text)} chars")
    print("  [DEBUG] Sending FULL context to answer generation (no LLM filter)")
    return context_text


def format_candidates(candidates: List[Dict[str, Any]], main_entity_name: str = None) -> str:
    """Format candidates thành text readable - ưu tiên main entity."""
    main_entity_lines: List[str] = []
    other_lines: List[str] = []

    main_entity_id = None
    if main_entity_name:
        for c in candidates:
            cname = c.get("name", "").lower()
            all_names = c.get("all_names", [])
            if (cname and main_entity_name.lower() in cname) or any(
                main_entity_name.lower() in n.get("value", "").lower() for n in all_names
            ):
                main_entity_id = c.get("id")
                break

    for c in candidates:
        node_type = c.get("type", "Unknown")
        name = c.get("name", "N/A")
        line = f"\n[{node_type}] {name}"

        for key in [
            "role",
            "description",
            "birth_place",
            "organization",
            "action",
            "phong_vuong_year",
            "title",
            "alias",
            "other_name",
            "birth_name",
            "birth_date",
            "birth_year",
            "death_date",
            "death_year",
            "reign_start",
            "reign_end",
            "reign_duration",
            "reign_duration_days",
            "reign_length_days",
            "duration_days",
            "personality",
            "adoptive_father",
            "father",
            "mother",
        ]:
            val = c.get(key, "") or c.get("properties", {}).get(key, "")
            if val:
                line += f"\n  {key}: {val}"

        all_names = c.get("all_names", [])
        if all_names:
            line += "\n  All Names:"
            for an in all_names:
                if an.get("value"):
                    line += f"\n    - {an['value']} [{an.get('type', '')}]"

        reign_duration = c.get("reign_duration") or c.get("properties", {}).get("reign_duration")
        if reign_duration and "reign_duration" not in line:
            line += f"\n  reign_duration: {reign_duration}"

        all_props = c.get("properties", {})
        if all_props:
            line += "\n  Properties:"
            excluded_props = {
                "role",
                "description",
                "birth_place",
                "organization",
                "action",
                "phong_vuong_year",
                "title",
                "alias",
                "other_name",
                "birth_name",
                "birth_date",
                "birth_year",
                "death_date",
                "death_year",
                "reign_start",
                "reign_end",
                "reign_duration",
                "reign_duration_days",
                "reign_length_days",
                "duration_days",
                "personality",
                "adoptive_father",
                "father",
                "mother",
            }
            for prop, val in all_props.items():
                if val and prop not in excluded_props:
                    line += f"\n    - {prop}: {val}"

        related = c.get("related", [])
        if related:
            line += "\n  Related:"
            for r in related[:50]:
                rel_name = r.get("name", "N/A")
                rel_text = r.get("rel", "")
                detail_parts = []
                if r.get("year"):
                    detail_parts.append(f"năm {r['year']}")
                if r.get("month"):
                    detail_parts.append(f"{r['month']}")
                if r.get("age"):
                    detail_parts.append(f"tuổi {r['age']}")
                if r.get("date"):
                    detail_parts.append(f"ngày {r['date']}")
                if r.get("description"):
                    detail_parts.append(f"{r['description']}")
                detail_str = f" - {', '.join(detail_parts)}" if detail_parts else ""
                related_persons_str = r.get("related_persons", "")

                if rel_text:
                    line += f"\n    - {rel_name}: {rel_text}{detail_str}{related_persons_str}"
                else:
                    rel_node_type = r.get("type", "")
                    if rel_node_type:
                        line += f"\n    - {rel_name} ({rel_node_type}){detail_str}{related_persons_str}"
                    else:
                        line += f"\n    - {rel_name}{detail_str}{related_persons_str}"

        if c.get("id") == main_entity_id:
            main_entity_lines.append(line)
        else:
            other_lines.append(line)

    return "\n".join(main_entity_lines + other_lines)

