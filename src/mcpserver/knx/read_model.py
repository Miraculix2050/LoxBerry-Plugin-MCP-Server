"""Bounded local metadata queries and source projections, without project access."""

from __future__ import annotations

import json
import re
from typing import Any

from .model import KnxError, address, text


def datapoint(raw: str) -> dict[str, Any]:
    """Recognize identifiers without claiming membership in a KNX type registry."""
    subtype = re.fullmatch(r"DPST-([0-9]{1,5})-([0-9]{1,5})", raw)
    dotted = re.fullmatch(r"([0-9]{1,5})\.([0-9]{1,5})", raw)
    main_only = re.fullmatch(r"DPT-([0-9]{1,5})", raw)
    match = subtype or dotted or main_only
    if match is None or int(match[1]) == 0:
        return {"raw": raw, "status": "invalid_format", "normalized": None}
    main = int(match[1])
    sub = int(match[2]) if subtype or dotted else None
    return {
        "raw": raw,
        "status": "format_valid_type_unverified",
        "main": main,
        "subtype": sub,
        "normalized": f"{main}.{sub:03d}" if sub is not None else str(main),
    }


def deviations(imported: dict[str, Any], overrides: dict[str, Any]) -> list[str]:
    result = []
    for key in sorted(imported.keys() & overrides.keys()):
        left, right = imported[key], overrides[key]
        if key == "dpts":
            left = [datapoint(value)["normalized"] or value for value in left]
            right = [datapoint(value)["normalized"] or value for value in right]
        if left != right:
            result.append(key)
    return result


def query_filters(value: object) -> dict[str, Any]:
    if value is None:
        return {"query": "", "source": "all", "deviations_only": False}
    if not isinstance(value, dict) or not value.keys() <= {"query", "source", "deviations_only"}:
        raise KnxError("knx_query_invalid")
    try:
        query = text(value.get("query", ""), 128).strip()
    except KnxError:
        raise KnxError("knx_query_invalid") from None
    source = value.get("source", "all")
    different = value.get("deviations_only", False)
    if source not in ("all", "imported", "manual", "both") or type(different) is not bool:
        raise KnxError("knx_query_invalid")
    return {"query": query, "source": source, "deviations_only": different}


def query_sql(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    clauses = []
    parameters: list[Any] = []
    query = filters["query"]
    if query:
        text_columns = [
            "a.original",
            "printf('%d/%d',a.address >> 11,a.address & 2047)",
            "printf('%d/%d/%d',a.address >> 11,(a.address >> 8) & 7,a.address & 255)",
            "json_extract(a.imported,'$.name')",
            "json_extract(a.overrides,'$.name')",
            "json_extract(a.imported,'$.description')",
            "json_extract(a.overrides,'$.description')",
        ]
        terms = [f"instr(knx_casefold({column}),?)>0" for column in text_columns]
        parameters.extend([query.casefold()] * len(terms))
        for fmt in ("three_level", "two_level"):
            try:
                number, _ = address(query, fmt)
            except KnxError:
                continue
            terms.append("a.address=?")
            parameters.append(number)
            break
        clauses.append("(" + " OR ".join(terms) + ")")
    if filters["source"] in ("imported", "both"):
        clauses.append("a.imported!='{}'")
    if filters["source"] in ("manual", "both"):
        clauses.append("a.overrides!='{}'")
    if filters["deviations_only"]:
        clauses.append("knx_deviates(a.imported,a.overrides)=1")
    return "".join(" AND " + clause for clause in clauses), parameters


def sql_deviates(imported: str, overrides: str) -> bool:
    return bool(deviations(json.loads(imported), json.loads(overrides)))


def details(imported: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    return {
        "deviations": deviations(imported, overrides),
        "dpt_details": {
            source: {
                "state": "unknown"
                if "dpts" not in fields
                else ("empty" if not fields["dpts"] else "declared"),
                "items": [datapoint(value) for value in fields.get("dpts", [])],
                "association": "not_established",
            }
            for source, fields in (("imported", imported), ("manual", overrides))
        },
    }
