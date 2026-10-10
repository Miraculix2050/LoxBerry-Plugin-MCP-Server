"""Normalize explicit ETS source fields without selecting a preferred DPT."""

from typing import Any

from .model import KnxError, metadata


def source_fields(attributes: dict[str, str], *, group: bool = False) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for source, field in (("Name", "name"), ("Description", "description")):
        if source in attributes:
            fields[field] = attributes[source]
    if not group:
        if "DPTs" in attributes:
            fields["dpts"] = attributes["DPTs"].replace(",", " ").split()
        for source, field in (("Central", "central"), ("Unfiltered", "unfiltered")):
            if source in attributes:
                if attributes[source] not in {"true", "false"}:
                    raise KnxError("knx_flag_invalid")
                fields[field] = attributes[source] == "true"
        if "Security" in attributes:
            fields["security"] = attributes["Security"]
    return metadata(fields, require_name=True)
