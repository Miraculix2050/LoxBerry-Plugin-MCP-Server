"""Versioned KNX main-type evidence paired against Config and Miniserver objects."""

from dataclasses import dataclass

from .parser import ParsedProject, ProjectElement

# Only pairs observed unchanged on both sides of the 2026-10-17 comparison.
_PAIRS: dict[str, dict[str, tuple[int, tuple[int, ...]]]] = {
    "EIBsensor": {"4": (5, (9,)), "5": (6, (5,)), "8": (9, (14,)), "9": (10, (7, 8))},
    "EIBactor": {
        "1": (2, (3,)),
        "2": (3, (10,)),
        "3": (4, (11,)),
        "4": (5, (9,)),
        "5": (6, (5,)),
        "6": (7, (1,)),
    },
}


@dataclass(frozen=True, slots=True)
class KnxDptEvidence:
    source_format: str = "miniserver_loxcc"
    mapping_version: str = "miniserver-knx-v1"
    format_version: str = "274"
    config_version: str = "17020828"
    status: str = "mapped_explicit_code"
    eis: int | None = None
    dpt_main_types: tuple[int, ...] = ()
    subtype: None = None
    compatibility: str = "not_established"


def verified_knx_format(project: ParsedProject) -> bool:
    """Require exactly the evidenced, unambiguous part-local format boundary."""
    root = project.elements[0]
    documents = [e for e in project.elements if e.value("Type") == "Document"]
    versions = [e for e in project.elements if any(k == "ConfigVersion" for k, _ in e.attributes)]
    return (
        root.tag == "ControlList"
        and [v for k, v in root.attributes if k == "Version"] == ["274"]
        and len(documents) == 1
        and versions == documents
        and documents[0].tag == "C"
        and [v for k, v in documents[0].attributes if k == "Type"] == ["Document"]
        and [v for k, v in documents[0].attributes if k == "ConfigVersion"] == ["17020828"]
    )


def knx_dpt_evidence(element: ProjectElement, *, verified: bool) -> KnxDptEvidence | None:
    if not verified or element.tag != "C":
        return None
    types = [v for k, v in element.attributes if k == "Type"]
    if len(types) != 1:
        return None
    source_type = types[0]
    codes = [v for k, v in element.attributes if k == "EIBType"]
    if not codes:
        if source_type in {"EIBsensor", "EIBactor"}:
            return KnxDptEvidence(status="mapped_implicit_config_default", dpt_main_types=(1,))
        if source_type in {"EIBtextsensor", "EIBtextactor"}:
            return KnxDptEvidence(status="mapped_object_type", eis=15, dpt_main_types=(16,))
    if len(codes) == 1:
        pair = _PAIRS.get(source_type, {}).get(codes[0])
        if pair is not None:
            return KnxDptEvidence(eis=pair[0], dpt_main_types=pair[1])
    return None
