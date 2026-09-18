"""Small bounded XML tokenizer preserving duplicate attributes and mixed content."""

import re
from dataclasses import dataclass, field

from .models import DEFAULT_LIMITS, ProjectError, ProjectLimits

_NAME = re.compile(r"[A-Za-z_][\w.:-]*")
_ATTRIBUTE = re.compile(r"""\s+([A-Za-z_][\w.:-]*)\s*=\s*(["'])(.*?)\2""", re.DOTALL)
_ENTITY = re.compile(r"&([^;\s<&]+);")


@dataclass(frozen=True, slots=True)
class ProjectElement:
    tag: str
    attributes: tuple[tuple[str, str], ...] = field(repr=False)
    parent: int | None
    content: tuple[str | int, ...] = field(repr=False)

    def value(self, name: str) -> str | None:
        values = {value for key, value in self.attributes if key == name}
        return next(iter(values)) if len(values) == 1 else None


@dataclass(frozen=True, slots=True)
class ParsedProject:
    elements: tuple[ProjectElement, ...] = field(repr=False)
    anomalies: tuple[tuple[int, str], ...]


def _entities(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match[1]
        builtin = {"lt": "<", "gt": ">", "amp": "&", "quot": '"', "apos": "'"}
        if name in builtin:
            return builtin[name]
        if name.startswith("#"):
            try:
                code = int(name[2:], 16) if name.startswith("#x") else int(name[1:])
                if code in {9, 10, 13} or (32 <= code <= 0x10FFFF and not 0xD800 <= code <= 0xDFFF):
                    return chr(code)
            except ValueError:
                pass
        raise ProjectError("project_entity_invalid")

    # Reject unrecognized ampersands rather than retaining an external entity.
    if "&" in _ENTITY.sub("", text):
        raise ProjectError("project_entity_invalid")
    return _ENTITY.sub(replace, text)


def parse_project(data: bytes, limits: ProjectLimits = DEFAULT_LIMITS) -> ParsedProject:
    if len(data) > limits.decoded_bytes:
        raise ProjectError("project_parse_limit")
    try:
        text = data.decode("utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")
    except UnicodeError:
        raise ProjectError("project_encoding_invalid") from None
    if any(ord(ch) < 32 and ch not in "\t\r\n" for ch in text):
        raise ProjectError("project_character_invalid")
    tags: list[str] = []
    attributes: list[tuple[tuple[str, str], ...]] = []
    parents: list[int | None] = []
    contents: list[list[str | int]] = []
    stack: list[int] = []
    anomalies: list[tuple[int, str]] = []
    cursor = 0
    attribute_count = 0
    root_count = 0
    while cursor < len(text):
        if text[cursor] != "<":
            end = text.find("<", cursor)
            end = len(text) if end < 0 else end
            value = _entities(text[cursor:end])
            if stack:
                contents[stack[-1]].append(value)
            elif value.strip():
                raise ProjectError("project_xml_invalid")
            cursor = end
            continue
        if text.startswith("<!--", cursor) or text.startswith("<![CDATA[", cursor):
            comment = text.startswith("<!--", cursor)
            start, terminator = (cursor + 4, "-->") if comment else (cursor + 9, "]]>")
            end = text.find(terminator, start)
            if end < 0 or (not comment and not stack):
                raise ProjectError("project_xml_invalid")
            if not comment:
                contents[stack[-1]].append(text[start:end])
            cursor = end + len(terminator)
            continue
        if text.startswith("<?xml ", cursor) and not tags:
            end = text.find("?>", cursor)
            if end < 0:
                raise ProjectError("project_xml_invalid")
            cursor = end + 2
            continue
        if text.startswith(("<!", "<?"), cursor):
            raise ProjectError("project_xml_declaration_unsupported")
        # Locate the tag boundary without crossing a quoted attribute value.
        end = cursor + 1
        quote = ""
        while end < len(text):
            char = text[end]
            if quote:
                if char == quote:
                    quote = ""
            elif char in "\"'":
                quote = char
            elif char == ">":
                break
            end += 1
        if end == len(text):
            raise ProjectError("project_xml_invalid")
        body = text[cursor + 1 : end]
        cursor = end + 1
        if body.startswith("/"):
            if not stack or body[1:].strip() != tags[stack.pop()]:
                raise ProjectError("project_xml_invalid")
            continue
        empty = body.endswith("/")
        body = body[:-1] if empty else body
        match = _NAME.match(body)
        if match is None:
            raise ProjectError("project_xml_invalid")
        tag = match[0]
        position = match.end()
        pairs: list[tuple[str, str]] = []
        seen: set[str] = set()
        index = len(tags)
        while position < len(body) and body[position:].strip():
            attribute = _ATTRIBUTE.match(body, position)
            if attribute is None:
                raise ProjectError("project_xml_invalid")
            name, _, raw = attribute.groups()
            value = _entities(raw)
            if name in seen:
                anomalies.append((index, "duplicate_attribute"))
            if "\n" in raw or "\r" in raw:
                anomalies.append((index, "attribute_newline"))
            seen.add(name)
            pairs.append((name, value))
            attribute_count += 1
            if attribute_count > limits.attributes:
                raise ProjectError("project_parse_limit")
            position = attribute.end()
        if index >= limits.elements or len(stack) >= limits.depth:
            raise ProjectError("project_parse_limit")
        parent = stack[-1] if stack else None
        if parent is None:
            root_count += 1
        else:
            contents[parent].append(index)
        tags.append(tag)
        attributes.append(tuple(pairs))
        parents.append(parent)
        contents.append([])
        if not empty:
            stack.append(index)
    if stack or root_count != 1:
        raise ProjectError("project_xml_invalid")
    return ParsedProject(
        tuple(
            ProjectElement(tag, attributes[i], parents[i], tuple(contents[i]))
            for i, tag in enumerate(tags)
        ),
        tuple(anomalies),
    )
