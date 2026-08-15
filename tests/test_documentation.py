"""Structural checks for maintained Markdown documentation."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
PAIR_DIRECTORIES = (DOCS / "user", DOCS / "clients")
LINK = re.compile(r"(?<!!)\[[^]]*\]\(([^)]+)\)")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)


def _slug(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^\w\- ]", "", value, flags=re.UNICODE)
    return re.sub(r"[ -]+", "-", value)


def _anchors(path: Path) -> set[str]:
    return {_slug(match.group(1)) for match in HEADING.finditer(path.read_text(encoding="utf-8"))}


def test_maintained_documentation_directories_have_readmes() -> None:
    directories = {DOCS, *(path.parent for path in DOCS.rglob("*.md"))}
    for directory in directories:
        assert (directory / "README.md").is_file(), directory


def test_user_and_client_language_pairs_are_complete() -> None:
    for directory in PAIR_DIRECTORIES:
        names = {path.name for path in directory.glob("*.md")}
        for name in names:
            if name.endswith(".de.md"):
                assert name.replace(".de.md", ".en.md") in names
            if name.endswith(".en.md"):
                assert name.replace(".en.md", ".de.md") in names


def test_user_and_client_language_pairs_have_matching_heading_structure() -> None:
    for directory in PAIR_DIRECTORIES:
        for german in directory.glob("*.de.md"):
            english = directory / german.name.replace(".de.md", ".en.md")
            german_levels = [
                len(match.group(0)) - len(match.group(0).lstrip("#"))
                for match in HEADING.finditer(german.read_text(encoding="utf-8"))
            ]
            english_levels = [
                len(match.group(0)) - len(match.group(0).lstrip("#"))
                for match in HEADING.finditer(english.read_text(encoding="utf-8"))
            ]
            assert german_levels == english_levels, german.name


def test_relative_document_links_and_anchors_resolve_with_exact_case() -> None:
    for source in (ROOT / "README.md", *DOCS.rglob("*.md")):
        content = source.read_text(encoding="utf-8")
        for raw_target in LINK.findall(content):
            if "://" in raw_target or raw_target.startswith("mailto:"):
                continue
            target, _, anchor = raw_target.partition("#")
            if target:
                path = source.parent
                for component in Path(target).parts:
                    if component == ".":
                        continue
                    if component == "..":
                        path = path.parent
                        continue
                    entries = {entry.name: entry for entry in path.iterdir()}
                    assert component in entries, f"{source}: {raw_target}"
                    path = entries[component]
                assert path.is_file(), f"{source}: {raw_target}"
            else:
                path = source
            if anchor:
                assert anchor in _anchors(path), f"{source}: {raw_target}"
