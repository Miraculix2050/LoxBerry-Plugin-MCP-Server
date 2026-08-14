from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tools import test as test_runner
from tools.test import TestPlan as RunnerPlan
from tools.test import create_plan, discover_changed_files, main


def _pytest_targets(plan: RunnerPlan) -> set[str]:
    for command in plan.commands:
        if command[1:4] == ("-m", "pytest", "-q"):
            return set(command[4:])
    return set()


def test_changed_packaging_selects_package_contract_tests() -> None:
    plan = create_plan("changed", ("tools/build_release_candidate.py",))

    assert plan.effective_profile == "changed"
    assert _pytest_targets(plan) == {
        "tests/test_apache_config.py",
        "tests/test_plugin_package.py",
    }


def test_changed_ui_selects_only_affected_ui_groups() -> None:
    plan = create_plan("changed", ("webfrontend/htmlauth/explorer.js",))

    assert plan.effective_profile == "changed"
    assert _pytest_targets(plan) == {
        "tests/test_explorer_ui.py",
        "tests/test_oauth.py",
    }


def test_shared_language_files_select_both_ui_groups() -> None:
    plan = create_plan("changed", ("templates/lang/language_de.ini",))

    assert plan.effective_profile == "changed"
    assert _pytest_targets(plan) == {
        "tests/test_admin.py",
        "tests/test_admin_ui.py",
        "tests/test_apache_config.py",
        "tests/test_explorer_ui.py",
        "tests/test_oauth.py",
    }


def test_changed_documentation_uses_only_diff_check() -> None:
    plan = create_plan("changed", ("docs/development/automation.md",))

    assert plan.effective_profile == "changed"
    assert plan.commands == (("git", "diff", "--check"),)


def test_packaged_skill_markdown_selects_contract_tests() -> None:
    plan = create_plan("changed", ("src/mcpserver/skills/using-loxberry-mcp/SKILL.md",))

    assert plan.effective_profile == "changed"
    assert _pytest_targets(plan) == {
        "tests/test_plugin_package.py",
        "tests/test_tools.py",
    }


def test_unknown_runtime_path_falls_back_to_full() -> None:
    plan = create_plan("changed", ("src/mcpserver/future_module.py",))

    assert plan.effective_profile == "full"
    assert plan.reason == "unmapped or cross-cutting paths: src/mcpserver/future_module.py"
    assert any(command[1:4] == ("-m", "pytest", "-q") for command in plan.commands)


def test_changed_explicit_plan_cli_does_not_run_commands(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "test.py",
            "--profile",
            "changed",
            "--files",
            "tools/test.py",
            "--plan",
        ],
    )

    assert main() == 0
    output = capsys.readouterr().out
    assert "requested=changed effective=changed" in output
    assert "tests/test_test_runner.py" in output


def test_full_profile_keeps_ci_commands_quiet() -> None:
    plan = create_plan("full")

    assert plan.commands[-1][1:] == ("-m", "pytest", "-q")
    assert plan.commands[0] == ("git", "diff", "--check")


def test_runner_creates_a_unique_pytest_basetemp_before_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plan = RunnerPlan(
        "changed",
        "changed",
        (),
        ((sys.executable, "-m", "pytest", "-q"),),
    )
    monkeypatch.setattr(test_runner, "ROOT", tmp_path)
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)

    pytest_basetemps: list[Path] = []

    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert (tmp_path / "tmp").is_dir()
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        assert environment["PYTHONPATH"] == str(tmp_path / "src")
        pytest_basetemp = Path(environment["PYTEST_ADDOPTS"].removeprefix("--basetemp="))
        assert pytest_basetemp.parent == tmp_path / "tmp"
        assert pytest_basetemp.is_dir()
        pytest_basetemps.append(pytest_basetemp)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(test_runner.subprocess, "run", run)

    assert test_runner._run(plan) == 0
    assert test_runner._run(plan) == 0
    assert len(set(pytest_basetemps)) == 2
    assert not any(pytest_basetemp.exists() for pytest_basetemp in pytest_basetemps)


def test_runner_preserves_existing_pytest_basetemp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plan = RunnerPlan("changed", "changed", (), ((sys.executable, "-m", "pytest", "-q"),))
    monkeypatch.setattr(test_runner, "ROOT", tmp_path)
    monkeypatch.setenv("PYTEST_ADDOPTS", "--basetemp=/managed/pytest -p no:cacheprovider")

    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert not (tmp_path / "tmp").exists()
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        assert environment["PYTHONPATH"] == str(tmp_path / "src")
        assert environment["PYTEST_ADDOPTS"] == "--basetemp=/managed/pytest -p no:cacheprovider"
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(test_runner.subprocess, "run", run)

    assert test_runner._run(plan) == 0


def test_invalid_explicit_base_ref_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failed_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 1, "", "unknown revision")

    monkeypatch.setattr("tools.test.subprocess.run", failed_run)

    with pytest.raises(RuntimeError, match="invalid base ref"):
        discover_changed_files("missing-ref", explicit=True)


def test_documented_test_cli_starts_without_pythonpath() -> None:
    result = subprocess.run(
        [sys.executable, "tools/test.py", "--help"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    assert result.returncode == 0
