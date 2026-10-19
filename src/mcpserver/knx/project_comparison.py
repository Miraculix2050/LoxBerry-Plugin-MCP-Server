"""Address-set observations against imported metadata, without project inference."""

from __future__ import annotations

import json
from collections.abc import Mapping
from time import monotonic
from typing import Any

from .model import KnxError
from .project_metadata import ProjectMetadata

MAX_COMPARISON_FINDINGS = 10_000


def unpack_observation(value: int) -> dict[str, Any]:
    """Decode an internal numeric observation only when projecting a page."""
    flags = value >> 16
    relation = ("import_only", "common", "observed_project_only")[flags & 3]
    return {
        "address_id": value & 65535,
        "relation": relation,
        "names_differ": bool(flags & 4),
        "ambiguous_names": bool(flags & 8),
        "name_comparison": "unknown"
        if flags & 16
        else "compared"
        if relation == "common"
        else "not_applicable",
    }


class ProjectComparison:
    """Borrow authorized project keys/names; never load the metadata catalog."""

    def __init__(self, metadata: ProjectMetadata) -> None:
        self.metadata = metadata

    def observe(
        self,
        target: str,
        revision: int,
        names: Mapping[int, tuple[str, ...]],
        *,
        deadline: float | None = None,
    ) -> dict[str, Any]:
        if any(type(number) is not int or not 0 <= number <= 65535 for number in names):
            raise KnxError("knx_address_invalid")
        if not self.metadata._exists():
            if revision:
                raise KnxError("knx_revision_conflict")
            keys = sorted(names)
            return {
                "revision": revision,
                "import_info": {},
                "counts": {
                    "common": 0,
                    "import_only": 0,
                    "observed_project_only": len(keys),
                    "name_deviations": 0,
                    "name_comparisons_unknown": 0,
                    "ambiguous_project_names": sum(len(set(value)) > 1 for value in names.values()),
                },
                "rows": [
                    number | ((2 | (8 if len(set(names[number])) > 1 else 0)) << 16)
                    for number in keys[:MAX_COMPARISON_FINDINGS]
                ],
                "truncated": len(keys) > MAX_COMPARISON_FINDINGS,
            }
        with self.metadata._connection() as db:
            if deadline is not None:
                db.set_progress_handler(lambda: int(monotonic() >= deadline), 1000)
            db.execute("BEGIN")
            self.metadata.store.check(db, target, revision)
            # Count all imported keys, but project names only for common keys.
            # One JSON aggregate avoids temporary membership tables and a Python
            # row conversion per address. Never hydrate other catalog fields.
            imported_count = db.execute(
                "SELECT count(*) FROM addresses INDEXED BY addresses_imported "
                "WHERE target=? AND imported!='{}'",
                (target,),
            ).fetchone()[0]
            imported = dict(
                json.loads(
                    db.execute(
                        "SELECT json_group_array(json_array(i.address, "
                        "CASE WHEN json_type(i.imported,'$.name')='text' "
                        "THEN json_extract(i.imported,'$.name') ELSE NULL END)) "
                        "FROM json_each(?) p CROSS JOIN addresses i "
                        "WHERE i.target=? AND i.address=p.value AND i.imported!='{}'",
                        (json.dumps(list(names), separators=(",", ":")), target),
                    ).fetchone()[0]
                )
            )
            counts = {
                "common": 0,
                "import_only": imported_count,
                "observed_project_only": 0,
                "name_deviations": 0,
                "name_comparisons_unknown": 0,
                "ambiguous_project_names": 0,
            }
            flags = {}
            for position, (number, values) in enumerate(names.items()):
                if position % 1000 == 0 and deadline is not None and monotonic() >= deadline:
                    raise KnxError("knx_storage_failed")
                # Most addresses have one name. Deduplicate only multiple source
                # names; repeated identical object names are not ambiguity.
                if len(values) > 1:
                    values = tuple(set(values))
                ambiguous = len(values) > 1
                counts["ambiguous_project_names"] += int(ambiguous)
                if number not in imported:
                    flags[number] = 2 | (8 if ambiguous else 0)
                    continue
                imported_name = imported[number]
                assessed = imported_name is not None and bool(values)
                # Distinct names cannot all equal one imported source name.
                different = assessed and (values[0] != imported_name or ambiguous)
                flags[number] = (
                    1 | (4 if different else 0) | (8 if ambiguous else 0) | (0 if assessed else 16)
                )
                counts["common"] += 1
                counts["name_deviations"] += int(different)
                counts["name_comparisons_unknown"] += int(not assessed)
            counts["import_only"] -= counts["common"]
            counts["observed_project_only"] = len(names) - counts["common"]
            # SQLite returns one bounded numeric array. Avoid 10,000 Python row
            # callbacks and DTO allocations; only a delivered page is decoded.
            imported_keys = json.loads(
                db.execute(
                    "SELECT json_group_array(address) FROM "
                    "(SELECT address FROM addresses INDEXED BY addresses_imported "
                    "WHERE target=? AND imported!='{}' ORDER BY address LIMIT ?)",
                    (target, MAX_COMPARISON_FINDINGS),
                ).fetchone()[0]
            )
            rows = [
                number | (flags.get(number, 0) << 16)
                for number in sorted(set(imported_keys) | names.keys())[:MAX_COMPARISON_FINDINGS]
            ]
            raw_info = db.execute(
                "SELECT information FROM import_state WHERE target=?", (target,)
            ).fetchone()
            try:
                info = json.loads(raw_info[0]) if raw_info else {}
                if not isinstance(info, dict):
                    raise ValueError
            except ValueError:
                raise KnxError("knx_storage_failed") from None
            return {
                "revision": revision,
                "import_info": {
                    key: info[key]
                    for key in (
                        "complete_export",
                        "imported_at",
                        "document_digest",
                        "mode",
                        "file_format",
                        "encoding",
                    )
                    if key in info
                },
                "counts": counts,
                "rows": rows,
                "truncated": sum(
                    counts[key] for key in ("common", "import_only", "observed_project_only")
                )
                > len(rows),
            }
