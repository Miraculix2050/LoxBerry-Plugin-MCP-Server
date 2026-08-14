"""Run change-driven checks locally and the complete deterministic CI gate."""

from __future__ import annotations

import argparse
import fnmatch
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

ROOT: Final = Path(__file__).resolve().parents[1]
Command = tuple[str, ...]
_PYTEST_BASETEMP: Final = "tmp/pytest"

_DOCUMENTATION_PATTERNS: Final = (
    "AGENTS.md",
    "CONTRIBUTING.md",
    "docs/**",
    "LICENSE",
    "README.md",
)
_FULL_PATTERNS: Final = (
    ".github/**",
    "pyproject.toml",
    "requirements/**",
    "src/mcpserver/__init__.py",
)
_TEST_GROUPS: Final = (
    (
        (
            ".gitattributes",
            "bin/**",
            "config/apache/**",
            "config/systemd/**",
            "icons/**",
            "plugin.cfg",
            "preinstall.sh",
            "preupgrade.sh",
            "postinstall.sh",
            "postroot.sh",
            "postupgrade.sh",
            "prerelease.cfg",
            "release.cfg",
            "tools/build_plugin.py",
            "tools/build_release_candidate.py",
            "tools/prepare_wheelhouse.py",
            "tools/verify_plugin.py",
            "uninstall/**",
        ),
        ("tests/test_plugin_package.py", "tests/test_apache_config.py"),
    ),
    (
        (
            "src/mcpserver/admin.py",
            "templates/index.html",
            "tools/benchmark_admin_page_state.py",
            "templates/lang/**",
            "webfrontend/htmlauth/index.cgi",
        ),
        (
            "tests/test_admin.py",
            "tests/test_admin_ui.py",
            "tests/test_apache_config.py",
        ),
    ),
    (
        (
            "templates/explorer.html",
            "templates/lang/**",
            "webfrontend/htmlauth/explorer.cgi",
            "webfrontend/htmlauth/explorer_callback.cgi",
            "webfrontend/htmlauth/explorer.js",
        ),
        ("tests/test_explorer_ui.py", "tests/test_oauth.py"),
    ),
    (
        ("config/default-config.json", "src/mcpserver/config.py"),
        (
            "tests/test_admin.py",
            "tests/test_config.py",
            "tests/test_settings.py",
        ),
    ),
    (
        ("src/mcpserver/certificates.py", "bin/renew-web-certificate"),
        ("tests/test_admin.py", "tests/test_certificates.py"),
    ),
    (
        ("src/mcpserver/auth/**",),
        (
            "tests/test_auth_store.py",
            "tests/test_explorer_ui.py",
            "tests/test_loxone_store.py",
            "tests/test_oauth.py",
            "tests/test_server.py",
        ),
    ),
    (
        ("src/mcpserver/loxone/**", "tools/test_loxone_target.py"),
        (
            "tests/test_control.py",
            "tests/test_control_commands.py",
            "tests/test_loxone_cache.py",
            "tests/test_loxone_client.py",
            "tests/test_loxone_events.py",
            "tests/test_loxone_security.py",
            "tests/test_loxone_structure.py",
            "tests/test_loxone_target.py",
            "tests/test_tools.py",
        ),
    ),
    (
        ("src/mcpserver/server.py",),
        ("tests/test_oauth.py", "tests/test_server.py", "tests/test_tools.py"),
    ),
    (
        ("src/mcpserver/settings.py",),
        ("tests/test_config.py", "tests/test_server.py", "tests/test_settings.py"),
    ),
    (
        ("src/mcpserver/skill_delivery.py", "src/mcpserver/skills/**"),
        ("tests/test_plugin_package.py", "tests/test_tools.py"),
    ),
    (
        ("src/mcpserver/tools.py",),
        (
            "tests/test_control.py",
            "tests/test_control_commands.py",
            "tests/test_server.py",
            "tests/test_tools.py",
        ),
    ),
    (
        ("tools/test.py",),
        ("tests/test_test_runner.py",),
    ),
)


@dataclass(frozen=True)
class TestPlan:
    requested_profile: str
    effective_profile: str
    files: tuple[str, ...]
    commands: tuple[Command, ...]
    reason: str | None = None


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def _normalize_file(value: str) -> str:
    path = Path(value)
    if path.is_absolute():
        try:
            path = path.resolve().relative_to(ROOT)
        except ValueError as exc:
            raise ValueError(f"changed path is outside the repository: {value}") from exc
    normalized = path.as_posix().removeprefix("./")
    if normalized == ".." or normalized.startswith("../"):
        raise ValueError(f"changed path is outside the repository: {value}")
    return normalized


def _full_commands() -> tuple[Command, ...]:
    return (
        ("git", "diff", "--check"),
        (sys.executable, "-m", "ruff", "format", "--check", "."),
        (sys.executable, "-m", "ruff", "check", "."),
        (sys.executable, "-m", "mypy"),
        (sys.executable, "-m", "pytest", "-q"),
    )


def _is_pytest_command(command: Command) -> bool:
    return command[1:4] == ("-m", "pytest", "-q")


def create_plan(profile: str, files: tuple[str, ...] = ()) -> TestPlan:
    normalized = tuple(sorted({_normalize_file(path) for path in files}))
    if profile == "full":
        return TestPlan("full", "full", normalized, _full_commands())
    if profile != "changed":
        raise ValueError(f"unsupported test profile: {profile}")

    selected_tests: set[str] = set()
    python_files: set[str] = set()
    needs_mypy = False
    fallback_reasons: list[str] = []

    for path in normalized:
        repository_path = ROOT / path
        if path.endswith(".py") and repository_path.is_file():
            python_files.add(path)
        if path.startswith("tests/test_") and path.endswith(".py"):
            if repository_path.is_file():
                selected_tests.add(path)
            else:
                fallback_reasons.append(path)
            continue
        if _matches(path, _DOCUMENTATION_PATTERNS):
            continue
        if _matches(path, _FULL_PATTERNS):
            fallback_reasons.append(path)
            continue

        matched = False
        for patterns, tests in _TEST_GROUPS:
            if _matches(path, patterns):
                matched = True
                selected_tests.update(tests)
        if path.startswith("src/"):
            needs_mypy = True
        if not matched:
            fallback_reasons.append(path)

    if fallback_reasons:
        reason = "unmapped or cross-cutting paths: " + ", ".join(sorted(fallback_reasons))
        return TestPlan("changed", "full", normalized, _full_commands(), reason)

    commands: list[Command] = [("git", "diff", "--check")]
    if python_files:
        ordered_python = tuple(sorted(python_files))
        commands.append((sys.executable, "-m", "ruff", "format", "--check", *ordered_python))
        commands.append((sys.executable, "-m", "ruff", "check", *ordered_python))
    if needs_mypy:
        commands.append((sys.executable, "-m", "mypy"))
    if selected_tests:
        commands.append((sys.executable, "-m", "pytest", "-q", *tuple(sorted(selected_tests))))
    return TestPlan("changed", "changed", normalized, tuple(commands))


def _git_lines(*arguments: str) -> tuple[str, ...]:
    completed = subprocess.run(
        ("git", *arguments),
        check=False,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        detail = completed.stderr.strip() or "git command failed"
        raise RuntimeError(detail)
    return tuple(line for line in completed.stdout.splitlines() if line)


def _resolve_base_ref(base_ref: str, *, explicit: bool) -> bool:
    completed = subprocess.run(
        ("git", "rev-parse", "--verify", f"{base_ref}^{{commit}}"),
        check=False,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if completed.returncode and explicit:
        raise RuntimeError(f"invalid base ref: {base_ref}")
    return completed.returncode == 0


def discover_changed_files(base_ref: str, *, explicit: bool) -> tuple[str, ...] | None:
    if not _resolve_base_ref(base_ref, explicit=explicit):
        return None
    files: set[str] = set()
    files.update(_git_lines("diff", "--name-only", "--diff-filter=ACDMRT", f"{base_ref}...HEAD"))
    files.update(_git_lines("diff", "--name-only", "--diff-filter=ACDMRT"))
    files.update(_git_lines("diff", "--cached", "--name-only", "--diff-filter=ACDMRT"))
    files.update(_git_lines("ls-files", "--others", "--exclude-standard"))
    return tuple(sorted({_normalize_file(path) for path in files}))


def _runtime_issues() -> tuple[str, ...]:
    issues: list[str] = []
    if sys.version_info[:2] != (3, 13):
        issues.append(
            f"Python 3.13 required, found {sys.version_info.major}.{sys.version_info.minor}"
        )
    for runtime in ("perl", "node"):
        if shutil.which(runtime) is None:
            issues.append(f"{runtime} is required")
    return tuple(issues)


def _format_command(command: Command) -> str:
    return subprocess.list2cmdline(command)


def _print_plan(plan: TestPlan) -> None:
    print(
        f"TEST_PLAN requested={plan.requested_profile} effective={plan.effective_profile} "
        f"files={len(plan.files)}",
        flush=True,
    )
    if plan.reason:
        print(f"TEST_PLAN_REASON={plan.reason}", flush=True)
    for command in plan.commands:
        print(f"TEST_COMMAND={_format_command(command)}", flush=True)
    if plan.effective_profile == "full":
        for issue in _runtime_issues():
            print(f"TEST_ENVIRONMENT={issue}", flush=True)


def _run(plan: TestPlan) -> int:
    if plan.effective_profile == "full":
        issues = _runtime_issues()
        if issues:
            for issue in issues:
                print(f"INCOMPLETE={issue}", file=sys.stderr)
            return 2

    environment = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    existing_pytest_options = environment.get("PYTEST_ADDOPTS", "")
    uses_default_pytest_basetemp = "--basetemp" not in existing_pytest_options
    if uses_default_pytest_basetemp:
        environment["PYTEST_ADDOPTS"] = (
            f"{existing_pytest_options} --basetemp={_PYTEST_BASETEMP}"
        ).strip()
    for command in plan.commands:
        if _is_pytest_command(command) and uses_default_pytest_basetemp:
            (ROOT / _PYTEST_BASETEMP).parent.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(command, check=False, cwd=ROOT, env=environment)
        if completed.returncode:
            return completed.returncode
    print(
        f"TEST_RESULT=pass profile={plan.effective_profile} "
        f"commands={len(plan.commands)} files={len(plan.files)}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("changed", "full"), default="full")
    parser.add_argument(
        "--files", nargs="+", help="Explicit changed paths for the Changed profile."
    )
    parser.add_argument("--base-ref", help="Git base ref for automatic Changed selection.")
    parser.add_argument(
        "--plan", action="store_true", help="Print selected checks without running them."
    )
    args = parser.parse_args()
    profile = cast(str, args.profile)
    explicit_files = tuple(cast(list[str] | None, args.files) or ())
    base_ref = cast(str | None, args.base_ref)

    if profile == "full" and (explicit_files or base_ref):
        parser.error("--files and --base-ref require --profile changed")

    try:
        if profile == "changed" and not explicit_files:
            changed = discover_changed_files(
                base_ref or "origin/master", explicit=base_ref is not None
            )
            if changed is None:
                plan = TestPlan(
                    "changed",
                    "full",
                    (),
                    _full_commands(),
                    "default base ref origin/master is unavailable",
                )
            else:
                plan = create_plan("changed", changed)
        else:
            plan = create_plan(profile, explicit_files)
    except (RuntimeError, ValueError) as exc:
        print(f"TEST_SELECTION_ERROR={exc}", file=sys.stderr)
        return 2

    _print_plan(plan)
    return 0 if args.plan else _run(plan)


if __name__ == "__main__":
    raise SystemExit(main())
