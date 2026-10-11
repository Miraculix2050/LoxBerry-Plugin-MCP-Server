"""Address-set observations against imported metadata, without project inference."""

from __future__ import annotations

import json
from collections.abc import Mapping
from time import monotonic
from typing import Any

from .model import KnxError
from .project_metadata import ProjectMetadata

MAX_COMPARISON_FINDINGS = 10_000


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
                    {
                        "address_id": number,
                        "relation": "observed_project_only",
                        "names_differ": False,
                        "ambiguous_names": len(set(names[number])) > 1,
                        "name_comparison": "not_applicable",
                    }
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
            db.execute(
                "CREATE TEMP TABLE compared_names(address INTEGER NOT NULL,name TEXT NOT NULL, "
                "PRIMARY KEY(address,name)) WITHOUT ROWID"
            )
            db.executemany(
                "INSERT INTO compared_project VALUES(?)", ((number,) for number in names)
            )
            db.executemany(
                "INSERT INTO compared_names VALUES(?,?)",
                ((number, value) for number, values in names.items() for value in set(values)),
            )
            # Imported names are additional information. Overrides do not turn a
            # naming deviation into a correction of either source.
            query = (
                "WITH imported AS (SELECT address FROM addresses WHERE target=? "
                "AND imported!='{}'), observed AS ("
                "SELECT i.address,'common' AS relation,"
                "EXISTS(SELECT 1 FROM compared_names n WHERE n.address=i.address "
                "AND json_type(i.imported,'$.name')='text' "
                "AND n.name!=json_extract(i.imported,'$.name')) AS names_differ, "
                "(json_type(i.imported,'$.name')='text' AND EXISTS(SELECT 1 FROM compared_names n "
                "WHERE n.address=i.address)) AS name_assessed "
                "FROM addresses i JOIN compared_project p ON p.address=i.address "
                "WHERE i.target=? AND i.imported!='{}' "
                "UNION ALL SELECT i.address,'import_only',0,0 FROM imported i "
                "WHERE NOT EXISTS(SELECT 1 FROM compared_project p WHERE p.address=i.address) "
                "UNION ALL SELECT p.address,'observed_project_only',0,0 FROM compared_project p "
                "WHERE NOT EXISTS(SELECT 1 FROM imported i WHERE i.address=p.address)) "
                "SELECT address,relation,names_differ,"
                "(SELECT count(*) FROM compared_names n WHERE n.address=o.address)>1 "
                "AS ambiguous_names,CASE WHEN relation!='common' THEN 'not_applicable' "
                "WHEN name_assessed THEN 'compared' ELSE 'unknown' END AS name_comparison "
                "FROM observed o"
            )
            # Materialize numeric observations once. Counting and paging share
            # this indexed result instead of re-reading source JSON/name joins.
            db.execute(
                "CREATE TEMP TABLE compared_observations(address INTEGER PRIMARY KEY, "
                "relation TEXT NOT NULL,names_differ INTEGER NOT NULL, "
                "ambiguous_names INTEGER NOT NULL,name_comparison TEXT NOT NULL)"
            )
            db.execute("INSERT INTO compared_observations " + query, (target, target))
            counts = {
                "common": 0,
                "import_only": 0,
                "observed_project_only": 0,
                "name_deviations": 0,
                "name_comparisons_unknown": 0,
                "ambiguous_project_names": 0,
            }
            for relation, count, different, ambiguous, unknown in db.execute(
                "SELECT relation,count(*),sum(names_differ),sum(ambiguous_names),"
                "sum(name_comparison='unknown') FROM compared_observations GROUP BY relation",
            ):
                counts[relation] = count
                counts["name_deviations"] += different
                counts["name_comparisons_unknown"] += unknown
                counts["ambiguous_project_names"] += ambiguous
            rows = [
                {
                    "address_id": number,
                    "relation": relation,
                    "names_differ": bool(different),
                    "ambiguous_names": bool(ambiguous),
                    "name_comparison": name_comparison,
                }
                for number, relation, different, ambiguous, name_comparison in db.execute(
                    "SELECT address,relation,names_differ,ambiguous_names,name_comparison "
                    "FROM compared_observations ORDER BY address LIMIT ?",
                    (MAX_COMPARISON_FINDINGS,),
                )
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
