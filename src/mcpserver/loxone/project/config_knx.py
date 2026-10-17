"""Offline KNX datatype evidence for explicitly supplied Loxone Config XML only.

This module is deliberately separate from the Miniserver snapshot pipeline.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .models import DEFAULT_LIMITS, ProjectError
from .parser import parse_project

MAPPING_VERSION = "config-knx-v1"
_CODES = {
    "1": (2, (3,)),
    "2": (3, (10,)),
    "3": (4, (11,)),
    "4": (5, (9,)),
    "5": (6, (5,)),
    "6": (7, (1,)),
    "8": (9, (14,)),
    "9": (10, (7, 8)),
    "10": (11, (12, 13)),
    "13": (14, (5, 6)),
}
_SUPPORTED = {
    "EIBsensor": frozenset({"2", "3", "4", "5", "8", "9", "10", "13"}),
    "EIBactor": frozenset({"1", "2", "3", "4", "5", "6", "8", "9", "10"}),
    "EIBtextsensor": frozenset[str](),
    "EIBtextactor": frozenset[str](),
}


@dataclass(frozen=True, slots=True)
class ConfigKnxDatatype:
    """Source evidence and candidate DPT main types, never a chosen subtype."""

    element_index: int
    source_type: str
    source_value: str | None
    status: str
    eis: int | None = None
    dpt_main_types: tuple[int, ...] = ()


def inspect_config_knx(data: bytes) -> dict[str, object]:
    """Inspect a local .Loxone XML file, not decoded or packed Miniserver data.

    Only the observed format/configuration version pair enables the mapping.
    Missing scalar codes and conflicting attributes remain unresolved.
    """
    project = parse_project(data)
    root = project.elements[0]
    if root.tag != "ControlList":
        raise ProjectError("config_knx_format_unsupported")
    versions = {
        element.value("ConfigVersion")
        for element in project.elements
        if element.tag == "C" and element.value("Type") == "Document"
    }
    verified = root.value("Version") == "274" and versions == {"17020828"}
    records: list[ConfigKnxDatatype] = []
    for index, element in enumerate(project.elements):
        source_type = element.value("Type")
        if element.tag != "C" or source_type not in _SUPPORTED:
            continue
        code = element.value("EIBType")
        if any(len(value) > 200 for key, value in element.attributes if key == "EIBType"):
            raise ProjectError("config_knx_datatype_limit")
        present = any(key == "EIBType" for key, _ in element.attributes)
        status = "unsupported_version" if not verified else "unresolved"
        eis: int | None = None
        dpts: tuple[int, ...] = ()
        if verified:
            if not present and source_type in {"EIBtextsensor", "EIBtextactor"}:
                status, eis, dpts = "mapped_object_type", 15, (16,)
            elif code in _SUPPORTED[source_type]:
                status = "mapped_explicit_code"
                eis, dpts = _CODES[code]
            elif not present:
                status = "missing_code"
        records.append(ConfigKnxDatatype(index, source_type, code, status, eis, dpts))
    return {
        "source_format": "loxone_config_xml",
        "mapping_version": MAPPING_VERSION,
        "version_verified": verified,
        "records": [asdict(record) for record in records],
    }


def main() -> int:
    """Print only datatype evidence; omit project names, IDs and other attributes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path, help="Local Loxone Config .Loxone XML file")
    args = parser.parse_args()
    try:
        with args.project.open("rb") as source:
            data = source.read(DEFAULT_LIMITS.decoded_bytes + 1)
        result = inspect_config_knx(data)
    except (OSError, ProjectError):
        print(json.dumps({"error": "config_knx_inspection_failed"}))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
