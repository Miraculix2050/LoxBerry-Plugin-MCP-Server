"""Version-bound State table evidence; no raw table data is publicly projected."""

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from .parser import ParsedProject

# Provenance: #335 comments 5972160124 and 5972202746 confirm exact project
# encoding and owner simulation. Extended operators and original table: #335
# comments 5973151293, 5973582354, 5973686935. Primary behavior:
# loxone.com/dede/kb/status-baustein/.
STATE_RULE_ID = "state_table_aq_v2"
MAX_STATE_ROWS = 100


@dataclass(frozen=True, slots=True)
class StateCondition:
    input_key: str
    operator: str
    numeric: Decimal | None = field(repr=False)
    text: str | None = field(repr=False)
    encoding: tuple[tuple[str, str], ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class StateRow:
    conditions: tuple[StateCondition, ...] = field(repr=False)
    numeric: Decimal = field(repr=False)
    source_index: int

    @property
    def conditional(self) -> bool:
        return bool(self.conditions)


_OPERATORS = {
    "1": ">",
    "2": ">=",
    "3": "<",
    "4": "<=",
    "5": "!=",
    "6": "*=",
    "7": "!*",
    "8": ":=",
    "9": "!:",
}
_MAX_TEXT_OPERAND = 256


def _number(raw: str) -> Decimal | None:
    if len(raw) > 64 or not re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", raw):
        return None
    try:
        value = Decimal(raw)
        return value if value.is_finite() else None
    except InvalidOperation:
        return None


def _condition(attrs: dict[str, str], position: int) -> StateCondition | None:
    selector = attrs.get(f"Input{position}")
    if selector not in {str(i) for i in range(1, 9)}:
        return None
    code = attrs.get(f"Cond{position}")
    operator = "==" if code is None else _OPERATORS.get(code)
    if operator is None:
        return None
    raw_numeric = attrs.get(f"CondV{position}")
    text = attrs.get(f"CondT{position}")
    if text is not None and (
        len(text) > _MAX_TEXT_OPERAND
        or "<" in text
        or ">" in text
        or any(ord(c) < 32 for c in text)
    ):
        return None  # Unverified references, formatting and control characters.
    numeric = _number(raw_numeric) if raw_numeric is not None else None
    if raw_numeric is not None and numeric is None:
        return None
    if operator in {"*=", "!*", ":=", "!:"}:
        if text is None:
            return None
    elif operator in {">", ">=", "<", "<="}:
        # Omitted zero is independently observed for the original I2 > 0 row.
        if raw_numeric is None:
            if operator != ">" or text is not None:
                return None
            numeric = Decimal(0)
        if text is not None:
            return None  # No ordering/coercion contract for a text operand.
    elif raw_numeric is None and text is None:
        if operator != "==":
            return None
        numeric = Decimal(0)  # Original equality-to-zero encoding.
    elif numeric is not None and text is not None and _number(text) != numeric:
        return None  # No demonstrated mixed-operand conversion contract.
    encoding = tuple(
        (k, attrs[k])
        for k in (f"Input{position}", f"Cond{position}", f"CondV{position}", f"CondT{position}")
        if k in attrs
    )
    # Preserve presence and exact operand spelling; only exact predicates shadow.
    return StateCondition(f"I{selector}", operator, numeric, text, encoding)


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
    """Recognize version-bound fixed operands; derive possible AQ influences only."""
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
        allowed = {"Valid", "ValidV", "Text", "TextV", "Icon", "IcC"}
        allowed.update(
            f"{prefix}{n}" for n in range(4) for prefix in ("Input", "Cond", "CondV", "CondT")
        )
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
        positions = [n for n in range(4) if f"Input{n}" in attrs]
        if positions != list(range(len(positions))):
            return gap("state_table_unsupported")
        if any(
            f"Input{n}" not in attrs
            and any(f"{prefix}{n}" in attrs for prefix in ("Cond", "CondV", "CondT"))
            for n in range(4)
        ):
            return gap("state_table_unsupported")
        conditions: list[StateCondition] = []
        for position in positions:
            condition = _condition(attrs, position)
            if condition is None:
                return gap("state_table_unsupported")
            conditions.append(condition)
        numeric = _number(attrs.get("TextV", ""))
        if numeric is None:
            return gap("state_table_unsupported")
        rows.append(StateRow(tuple(conditions), numeric, row_index))
    # The entire table must be known, even if an earlier default shadows a row.
    reachable: list[StateRow] = []
    for decoded_row in rows:
        if decoded_row.conditional and any(
            r.conditions == decoded_row.conditions for r in reachable
        ):
            continue  # Exactly identical conjunction: the earlier match always wins.
        reachable.append(decoded_row)
        if not decoded_row.conditional:
            break
    if not reachable or reachable[-1].conditional:
        return gap("state_table_unsupported")
    used = {c.input_key for r in reachable for c in r.conditions}
    dependencies = (
        tuple(f"I{i}" for i in range(1, 9) if f"I{i}" in used)
        if len({r.numeric for r in reachable}) > 1
        else ()
    )
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
