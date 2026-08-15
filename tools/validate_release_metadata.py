"""Validate release metadata and extract the exact changelog section."""

from __future__ import annotations

import argparse
import configparser
import re
from pathlib import Path

try:
    from tools.versioning import VERSION_PATTERN
except ModuleNotFoundError:  # Direct documented CLI execution from repository root.
    from versioning import VERSION_PATTERN


def _read(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")
    return parser


def validate(root: Path, version: str, channel: str) -> str:
    if channel not in {"prerelease", "stable"}:
        raise ValueError("channel must be prerelease or stable")
    prerelease = re.fullmatch(r"\d+\.\d+\.\d+-(?:alpha|beta)\.(?:0|[1-9]\d*)", version)
    stable = re.fullmatch(r"\d+\.\d+\.\d+", version)
    if VERSION_PATTERN.fullmatch(version) is None or (not prerelease and not stable):
        raise ValueError("version must use x.y.z, x.y.z-alpha.n or x.y.z-beta.n")
    if channel == "stable" and not stable:
        raise ValueError("stable releases must not use a prerelease version")
    if channel == "prerelease" and not prerelease:
        raise ValueError("prerelease releases must use an alpha or beta version")
    plugin = _read(root / "plugin.cfg")
    selected = _read(root / ("release.cfg" if channel == "stable" else "prerelease.cfg"))
    plugin_version = plugin["PLUGIN"]["VERSION"]
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'(?m)^version = "([^"]+)"$', pyproject)
    if plugin_version != version or match is None or match.group(1) != version:
        raise ValueError("plugin and Python project versions do not match the release version")
    base = "https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server"
    tag = f"v{version}"
    expected = {
        "VERSION": version,
        "ARCHIVEURL": f"{base}/releases/download/{tag}/LoxBerry-MCP-Server-{version}.zip",
        "INFOURL": f"{base}/releases/tag/{tag}",
    }
    for key, value in expected.items():
        if selected["AUTOUPDATE"].get(key, "") != value:
            raise ValueError(f"{channel} {key} does not match the release contract")
    if plugin["PLUGIN"].get("WEBSITE") != f"{base}/blob/{tag}/README.md":
        raise ValueError("plugin WEBSITE must be bound to the release tag")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    heading = re.compile(rf"(?m)^## {re.escape(version)}(?:\s+-\s+\d{{4}}-\d{{2}}-\d{{2}})?\s*$")
    found = heading.search(changelog)
    if found is None:
        raise ValueError(f"CHANGELOG.md has no section for {version}")
    following = re.search(r"(?m)^## ", changelog[found.end() :])
    end = found.end() + following.start() if following else len(changelog)
    notes = changelog[found.end() : end].strip()
    if not notes:
        raise ValueError(f"CHANGELOG.md section for {version} is empty")
    return notes + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--channel", required=True, choices=("stable", "prerelease"))
    parser.add_argument("--notes-output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    notes = validate(root, args.version, args.channel)
    if args.notes_output:
        args.notes_output.parent.mkdir(parents=True, exist_ok=True)
        args.notes_output.write_text(notes, encoding="utf-8", newline="\n")
    print(f"RELEASE_METADATA=pass version={args.version} channel={args.channel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
