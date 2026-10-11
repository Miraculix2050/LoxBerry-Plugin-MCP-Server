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
            db.execute("CREATE TEMP TABLE compared_project(address INTEGER PRIMARY KEY)")
            db.executemany(
                "INSERT INTO compared_project VALUES(?)", ((number,) for number in names)
            )
            # Count imported keys directly. Per-import correlated membership and
            # full-union grouping are unnecessary: only common keys need JSON.
            imported_count = db.execute(
                "SELECT count(*) FROM addresses INDEXED BY addresses_imported "
                "WHERE target=? AND imported!='{}'",
                (target,),
            ).fetchone()[0]
            counts = {
                "common": 0,
                "import_only": imported_count,
                "observed_project_only": 0,
                "name_deviations": 0,
                "name_comparisons_unknown": 0,
                "ambiguous_project_names": sum(len(set(value)) > 1 for value in names.values()),
            }
            flags = {}
            for number, imported_name, name_type in db.execute(
                "SELECT i.address,json_extract(i.imported,'$.name'),json_type(i.imported,'$.name') "
                "FROM compared_project p CROSS JOIN addresses i "
                "WHERE i.target=? AND i.address=p.address AND i.imported!='{}'",
                (target,),
            ):
                values = set(names[number])
                assessed = name_type == "text" and bool(values)
                different = assessed and any(value != imported_name for value in values)
                flags[number] = (
                    1
                    | (4 if different else 0)
                    | (8 if len(values) > 1 else 0)
                    | (0 if assessed else 16)
                )
                counts["common"] += 1
                counts["name_deviations"] += int(different)
                counts["name_comparisons_unknown"] += int(not assessed)
            counts["import_only"] -= counts["common"]
            project_only = sorted(number for number in names if number not in flags)
            counts["observed_project_only"] = len(project_only)
            flags.update(
                (number, 2 | (8 if len(set(names[number])) > 1 else 0)) for number in project_only
            )
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
                for number in sorted(imported_keys + project_only)[:MAX_COMPARISON_FINDINGS]
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
