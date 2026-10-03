"""Version-bound State table evidence; no raw table data is publicly projected."""

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from .parser import ParsedProject

# Provenance: #335 comments 5972160124 and 5972202746 confirm exact project
# encoding and owner simulation; primary behavior: loxone.com/dede/kb/status-baustein/.
STATE_RULE_ID = "state_i2_eq1_aq_v1"
MAX_STATE_ROWS = 100


@dataclass(frozen=True, slots=True)
class StateRow:
    conditional: bool
    numeric: Decimal = field(repr=False)
    source_index: int


@dataclass(frozen=True, slots=True)
class StateFlow:
    block_key: str
    version: tuple[str | None, str | None, str | None]
    reason: str | None
    dependencies: tuple[str, ...] = ()
    rows: tuple[StateRow, ...] = field(default=(), repr=False)


def decode_state_flow(
    project: ParsedProject,
    index: int,
    key: str,
    children: dict[int, list[int]],
    config_version: str | None,
) -> StateFlow:
    """Recognize only the independently confirmed I2 == 1/default encoding."""
    elements = project.elements
    block = elements[index]
    raw_version = (config_version, elements[0].value("Version"), block.value("V"))

    def safe_version(value: str | None) -> str | None:
        return value if value and re.fullmatch(r"[0-9]{1,16}", value) else None

    version = (
        safe_version(raw_version[0]),
        safe_version(raw_version[1]),
        safe_version(raw_version[2]),
    )

    def gap(reason: str) -> StateFlow:
        return StateFlow(key, version, reason)

    if (
        version != ("17020828", "274", "178")
        or sum(k == "Version" for k, _ in elements[0].attributes) != 1
        or sum(k == "V" for k, _ in block.attributes) != 1
    ):
        return gap("state_version_unverified")
    tables = [i for i in children.get(index, []) if elements[i].tag == "StateTexts"]
    if len(tables) != 1:
        return gap("state_table_unsupported")
    table = tables[0]
    if any(isinstance(c, str) and c.strip() for c in elements[table].content):
        return gap("state_table_unsupported")
    row_indices = children.get(table, [])
    if len(row_indices) > MAX_STATE_ROWS:
        return gap("state_table_limit")
    if not row_indices or elements[table].attributes != (("Num", str(len(row_indices))),):
        return gap("state_table_unsupported")
    rows: list[StateRow] = []
    for row_index in row_indices:
        row = elements[row_index]
        attrs = dict(row.attributes)
        allowed = {"Valid", "ValidV", "Text", "TextV", "Icon", "IcC", "Input0", "CondV0", "CondT0"}
        if (
            row.tag != "StateText"
            or len(attrs) != len(row.attributes)
            or set(attrs) - allowed
            or attrs.get("Valid") != "true"
            or attrs.get("ValidV") != "true"
            or any(isinstance(c, str) and c.strip() for c in row.content)
            or children.get(row_index)
        ):
            return gap("state_table_unsupported")
        condition = {k: v for k, v in attrs.items() if k.startswith(("Input", "Cond"))}
        if condition and condition != {"Input0": "2", "CondV0": "1", "CondT0": "1"}:
            return gap("state_table_unsupported")
        try:
            raw = attrs.get("TextV", "")
            if len(raw) > 64:
                return gap("state_table_unsupported")
            if not re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", raw):
                return gap("state_table_unsupported")
            numeric = Decimal(raw)
            if not numeric.is_finite():
                return gap("state_table_unsupported")
        except InvalidOperation:
            return gap("state_table_unsupported")
        rows.append(StateRow(bool(condition), numeric, row_index))
    # The entire table must be known, even if an earlier default shadows a row.
    reachable: list[StateRow] = []
    for decoded_row in rows:
        if decoded_row.conditional and any(r.conditional for r in reachable):
            continue  # Identical tested predicate: the earlier match always wins.
        reachable.append(decoded_row)
        if not decoded_row.conditional:
            break
    if not reachable or reachable[-1].conditional:
        return gap("state_table_unsupported")
    dependencies = ("I2",) if len({r.numeric for r in reachable}) > 1 else ()
    return StateFlow(key, version, None, dependencies, tuple(reachable))


def state_connector_reason(flow: StateFlow, connector: str | None, direction: str) -> str | None:
    """AQ has an isolated verified contract; other outputs remain unknown."""
    if flow.reason:
        return flow.reason
    if connector == "AQ":
        return None
    if connector in {f"I{i}" for i in range(1, 9)} and direction == "upstream":
        return None  # External providers of an input do not traverse internal outputs.
    return "state_connector_unverified"
