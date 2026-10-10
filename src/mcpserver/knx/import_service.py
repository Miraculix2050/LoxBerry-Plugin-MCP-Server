"""Import identity and conflict rules shared by XML and CSV adapters."""

from __future__ import annotations

import json

from .import_model import ImportAddress, ImportDocument, ImportGroup, ImportSelection
from .model import KnxError


def select_candidates(document: ImportDocument, choices: object = None) -> ImportSelection:
    """Never resolve contradicting candidates by their order in the input file."""
    if choices is None:
        choices = {}
    if not isinstance(choices, dict) or len(choices) > 66_560:
        raise KnxError("knx_choices_invalid")
    candidates: dict[str, list[ImportAddress | ImportGroup]] = {}
    duplicate_count = 0
    signatures: dict[str, set[str]] = {}
    all_items: list[ImportAddress | ImportGroup] = [*document.addresses, *document.groups]
    for item in all_items:
        identity = (
            f"address:{item.number}"
            if isinstance(item, ImportAddress)
            else f"group:{item.address_format}:{item.prefix}"
        )
        source = dict(item.source)
        if isinstance(item, ImportAddress) and "attributes" in source:
            source["attributes"] = {
                key: value
                for key, value in source["attributes"].items()
                if key
                not in {
                    "Name",
                    "Description",
                    "DPTs",
                    "Central",
                    "Unfiltered",
                    "Address",
                    "Security",
                }
            }
        elif isinstance(item, ImportGroup):
            source = {
                key: value for key, value in source.items() if key not in {"Name", "Description"}
            }
            for key in ("RangeStart", "RangeEnd"):
                if key in source:
                    source[key] = int(source[key])
        signature = json.dumps(
            {
                "fields": item.fields,
                "source": source,
                "format": item.address_format,
                "address": item.original if isinstance(item, ImportAddress) else item.prefix,
            },
            sort_keys=True,
        )
        if signature in signatures.setdefault(identity, set()):
            duplicate_count += 1
            continue
        signatures[identity].add(signature)
        candidates.setdefault(identity, []).append(item)
        if len(candidates[identity]) > 16:
            raise KnxError("knx_duplicate_limit")
    if not choices.keys() <= candidates.keys():
        raise KnxError("knx_choices_invalid")
    selected_addresses = []
    selected_groups = []
    conflicts = []
    for identity, values in candidates.items():
        index = choices.get(identity)
        if index is not None and (type(index) is not int or not 0 <= index < len(values)):
            raise KnxError("knx_choices_invalid")
        if len(values) > 1 and index is None:
            conflicts.append(
                {
                    "identity": identity,
                    "candidates": [
                        {
                            "index": number,
                            "address": value.original
                            if isinstance(value, ImportAddress)
                            else value.prefix,
                            "address_format": value.address_format,
                            "fields": value.fields,
                            "source": value.source,
                        }
                        for number, value in enumerate(values)
                    ],
                }
            )
            continue
        item = values[0 if index is None else index]
        if isinstance(item, ImportAddress):
            selected_addresses.append(item)
        else:
            selected_groups.append(item)
    return ImportSelection(
        tuple(sorted(selected_addresses, key=lambda row: row.number)),
        tuple(sorted(selected_groups, key=lambda row: (row.address_format, row.prefix))),
        tuple(conflicts),
        duplicate_count,
    )
