"""Presentation selection over bounded cached ETS observations, without catalog hydration."""

from __future__ import annotations

from collections import Counter
from typing import Any

from mcpserver.knx.model import address_number


def selection(
    view: str,
    relation: str | None,
    names_differ: bool | None,
    ambiguous_names: bool | None,
    address: str | None,
    source_details: bool,
) -> tuple[Any, ...]:
    """Normalize numeric identity; retain all presentation arguments for cursor binding."""
    if view not in {"full", "summary", "findings", "detail"}:
        raise ValueError("Unknown project analysis view")
    if relation not in {None, "common", "import_only", "observed_project_only"}:
        raise ValueError("Unknown address relation")
    if any(
        value is not None and type(value) is not bool for value in (names_differ, ambiguous_names)
    ):
        raise ValueError("Name filters must be booleans")
    if type(source_details) is not bool:
        raise ValueError("source_details must be boolean")
    number = address_number(address) if address is not None else None
    if address is not None and (number is None or address.endswith((":0", ":1"))):
        raise ValueError("address must be a two-/three-level address without a variant suffix")
    if view == "detail" and number is None:
        raise ValueError("detail requires an exact address")
    return view, relation, names_differ, ambiguous_names, number, source_details


def filter_observations(rows: list[Any], selected: tuple[Any, ...]) -> list[int]:
    """Select only numeric observations; false never turns unknown comparisons into matches."""
    _, relation, different, ambiguous, number, _ = selected
    relation_flag = {"import_only": 0, "common": 1, "observed_project_only": 2}.get(relation)
    result = []
    for value in rows:
        if type(value) is not int:
            raise ValueError("Compact selection requires ETS-only observations")
        flags = value >> 16
        if relation_flag is not None and flags & 3 != relation_flag:
            continue
        if number is not None and value & 65535 != number:
            continue
        if different is not None and (
            flags & 3 != 1
            or flags & 16
            or bool(flags & 4) != different
            or (different is False and flags & 32)
        ):
            continue
        if ambiguous is not None and bool(flags & 8) != ambiguous:
            continue
        result.append(value)
    return result


def compact_context(result: dict[str, Any], source_details: bool) -> dict[str, Any]:
    """Keep count scope and omitted evidence explicit; source groups are opt-in."""
    diagnostics = result["source_diagnostics"]
    counts: Counter[str] = Counter()
    for item in diagnostics["entries"]:
        counts[item["code"]] += item["count"]
    coverage = result["coverage_by_source_type"]
    return {
        "source_diagnostics": {
            "entries": [{"code": code, "count": count} for code, count in sorted(counts.items())],
            "complete": diagnostics["complete"],
            "groups_omitted": diagnostics["groups_omitted"],
            "labels_truncated": diagnostics["labels_truncated"],
        },
        "source_coverage": {
            "complete": coverage["complete"],
            "groups_omitted": coverage["groups_omitted"],
            "ambiguous_source_objects": coverage["ambiguous_source_objects"],
            "reported_groups": len(coverage["entries"]),
        },
        "source_diagnostics_details": diagnostics if source_details else None,
        "source_coverage_details": coverage if source_details else None,
    }


def selected_counts(rows: list[int]) -> dict[str, int]:
    counts = {
        "common": 0,
        "import_only": 0,
        "observed_project_only": 0,
        "name_deviations": 0,
        "name_comparisons_unknown": 0,
        "ambiguous_project_names": 0,
    }
    relations = ("import_only", "common", "observed_project_only")
    for value in rows:
        flags = value >> 16
        counts[relations[flags & 3]] += 1
        counts["name_deviations"] += int(bool(flags & 4))
        counts["name_comparisons_unknown"] += int(bool(flags & 16))
        counts["ambiguous_project_names"] += int(bool(flags & 8))
    return counts
