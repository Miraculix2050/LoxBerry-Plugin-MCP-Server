from __future__ import annotations

import configparser
import hashlib
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from tools.build_plugin import _EXECUTABLES, _add, _locked_requirements
from tools.build_release_candidate import _copy_runtime_wheels, _publish
from tools.verify_plugin import PackageVerificationError, verify_archive

ROOT = Path(__file__).resolve().parents[1]


def test_plugin_identity_and_platform_contract() -> None:
    parser = configparser.ConfigParser()
    parser.read(ROOT / "plugin.cfg", encoding="utf-8")

    assert parser["PLUGIN"]["NAME"] == "mcpserver"
    assert parser["PLUGIN"]["FOLDER"] == "mcpserver"
    assert parser["PLUGIN"]["TITLE"] == "LoxBerry MCP Server"
    assert parser["PLUGIN"]["VERSION"] == "0.1.0-alpha.1"
    assert parser["SYSTEM"]["LB_MINIMUM"] == "4.0.0"
    assert parser["SYSTEM"]["INTERFACE"] == "2.0"
    for name in ("release.cfg", "prerelease.cfg"):
        update = configparser.ConfigParser()
        update.read(ROOT / name, encoding="utf-8")
        assert "AUTOUPDATE" in update


def test_v4_package_manifest_is_present() -> None:
    required = [
        "preinstall.sh",
        "preupgrade.sh",
        "postinstall.sh",
        "postroot.sh",
        "postupgrade.sh",
        "uninstall/uninstall.sh",
        "bin/healthcheck",
        "icons/icon.svg",
        "webfrontend/htmlauth/index.cgi",
        "templates/index.html",
        "templates/lang/language_de.ini",
        "templates/lang/language_en.ini",
    ]
    assert all((ROOT / item).is_file() for item in required)
    hooks = "\n".join(
        (ROOT / item).read_text(encoding="utf-8")
        for item in ("postinstall.sh", "postupgrade.sh", "postroot.sh")
    )
    assert "actual_folder=$3" in hooks
    assert "LBPCONFIG/$actual_folder" in hooks
    assert "LBPDATA/$actual_folder" in hooks


def test_upgrade_preserves_configuration_in_plugin_data() -> None:
    preupgrade = (ROOT / "preupgrade.sh").read_text(encoding="utf-8")
    postinstall = (ROOT / "postinstall.sh").read_text(encoding="utf-8")

    assert "installer_root=${6:-}" in preupgrade
    assert 'backup_dir="$installer_root/.mcpserver-upgrade"' in preupgrade
    assert 'install -m 600 "$config_file" "$backup_dir/mcpserver.json"' in preupgrade
    assert "sessions.json loxone-tokens.json.enc install.key" in preupgrade
    assert "installer_root=${6:-}" in postinstall
    assert 'upgrade_backup="$upgrade_backup_dir/mcpserver.json"' in postinstall
    assert 'install -m 600 "$upgrade_backup" "$config_file"' in postinstall
    assert "sessions.json loxone-tokens.json.enc install.key" in postinstall
    assert postinstall.index('install -m 600 "$upgrade_backup" "$config_file"') < postinstall.index(
        'cp "$plugin_config/default-config.json" "$config_file"'
    )


def test_shell_hooks_have_valid_syntax() -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is unavailable")
    scripts = [
        "preinstall.sh",
        "preupgrade.sh",
        "postinstall.sh",
        "postroot.sh",
        "postupgrade.sh",
        "uninstall/uninstall.sh",
        "bin/healthcheck",
        "bin/mcpserver-admin",
    ]
    subprocess.run([bash, "-n", *(str(ROOT / item) for item in scripts)], check=True)


def test_postroot_keeps_installer_alive_during_apache_activation() -> None:
    hook = (ROOT / "postroot.sh").read_text(encoding="utf-8")

    assert "systemctl restart apache2" not in hook
    assert "systemctl reload apache2" in hook
    assert hook.index("systemctl restart loxberry-mcpserver.service") < hook.index(
        "systemctl reload apache2"
    )
    assert '(umask 0137 && openssl rand 32 > "$key")' in hook
    assert 'chmod 644 "$unit" "$apache"' in hook


def test_postinstall_rewrites_moved_venv_entrypoints() -> None:
    hook = (ROOT / "postinstall.sh").read_text(encoding="utf-8")

    assert '"#!$new_venv/bin/python"' in hook
    assert 'sed -i "1c\\\\#!$venv/bin/python"' in hook
    assert 'rm -rf -- "$venv"' in hook
    assert 'mv "$old_venv" "$venv"' in hook


def test_package_builder_includes_plugin_icon() -> None:
    source = (ROOT / "tools" / "build_plugin.py").read_text(encoding="utf-8")

    assert '"icons"' in source
    assert (ROOT / "icons" / "icon.svg").is_file()


def test_perl_admin_cgi_has_valid_syntax() -> None:
    perl = shutil.which("perl")
    if perl is None:
        pytest.skip("perl is unavailable")
    subprocess.run(
        [
            perl,
            f"-I{ROOT / 'tests' / 'perl_stubs'}",
            "-c",
            str(ROOT / "webfrontend/htmlauth/index.cgi"),
        ],
        check=True,
    )


def test_language_files_have_matching_contracts() -> None:
    def keys(path: Path) -> set[tuple[str, str]]:
        parser = configparser.ConfigParser()
        parser.optionxform = str  # type: ignore[assignment]
        parser.read(path, encoding="utf-8")
        return {(section, key) for section in parser.sections() for key in parser[section]}

    assert keys(ROOT / "templates/lang/language_de.ini") == keys(
        ROOT / "templates/lang/language_en.ini"
    )


def test_ui_is_nojqm_responsive_and_progressively_enhanced() -> None:
    cgi = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")

    assert "'nojqm'" in cgi
    assert "ajax-generic.php" not in cgi + template
    assert 'method="post"' in template
    assert "fetch('index.cgi'" in template
    assert "overflow-x: auto" in template
    assert "@media (max-width: 30rem)" in template
    assert "#diagnostics .lb-table-scroll { overflow-x: visible; }" in template
    assert ":focus-visible" in template


def test_installed_text_files_use_lf_only() -> None:
    paths = [
        *(ROOT / name for name in ("plugin.cfg", "release.cfg", "prerelease.cfg")),
        *(ROOT / name for name in ("preinstall.sh", "postinstall.sh", "postroot.sh")),
        *(
            item
            for folder in ("bin", "config", "templates", "uninstall", "webfrontend")
            for item in (ROOT / folder).rglob("*")
            if item.is_file()
        ),
    ]
    for path in paths:
        assert b"\r\n" not in path.read_bytes(), path


def test_package_builder_emits_unix_executable_modes(tmp_path: Path) -> None:
    output = tmp_path / "test.zip"
    source = ROOT / "bin" / "healthcheck"
    with zipfile.ZipFile(output, "w") as archive:
        _add(archive, source, "bin/healthcheck")
        _add(archive, ROOT / "plugin.cfg", "plugin.cfg")

    with zipfile.ZipFile(output) as archive:
        executable = archive.getinfo("bin/healthcheck")
        regular = archive.getinfo("plugin.cfg")
        assert executable.create_system == 3
        assert executable.external_attr >> 16 & 0o777 == 0o755
        assert regular.external_attr >> 16 & 0o777 == 0o644
        assert "bin/healthcheck" in _EXECUTABLES


def test_package_builder_normalizes_installed_text_to_lf(tmp_path: Path) -> None:
    source = tmp_path / "runtime.lock"
    source.write_bytes(b"first\r\nsecond\r\n")
    output = tmp_path / "test.zip"

    with zipfile.ZipFile(output, "w") as archive:
        _add(archive, source, "bin/runtime-arm64.lock")

    with zipfile.ZipFile(output) as archive:
        assert archive.read("bin/runtime-arm64.lock") == b"first\nsecond\n"


def test_plugin_archive_verifier_accepts_builder_output(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    for name, version in _locked_requirements(ROOT / "requirements" / "runtime-arm64.lock").items():
        wheel_name = name.replace("-", "_")
        (wheelhouse / f"{wheel_name}-{version}-py3-none-any.whl").write_bytes(b"wheel")
    (wheelhouse / "loxberry_mcpserver-0.1.0a1-py3-none-any.whl").write_bytes(b"project")
    output = tmp_path / "plugin.zip"

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "build_plugin.py"),
            "--wheelhouse",
            str(wheelhouse),
            "--output",
            str(output),
        ],
        check=True,
        cwd=ROOT,
    )

    assert verify_archive(output) == hashlib.sha256(output.read_bytes()).hexdigest()

    with zipfile.ZipFile(output) as source:
        omitted = next(
            name
            for name in source.namelist()
            if name.startswith("bin/wheelhouse/")
            and not name.startswith("bin/wheelhouse/loxberry_mcpserver-")
        )
        tampered = tmp_path / "tampered.zip"
        with zipfile.ZipFile(tampered, "w") as destination:
            for entry in source.infolist():
                if entry.filename != omitted:
                    destination.writestr(entry, source.read(entry))
    tampered_digest = hashlib.sha256(tampered.read_bytes()).hexdigest()
    tampered.with_suffix(".zip.sha256").write_text(
        f"{tampered_digest}  {tampered.name}\n", encoding="ascii"
    )
    with pytest.raises(PackageVerificationError, match="does not match its lock"):
        verify_archive(tampered)

    (wheelhouse / "foreign_package-9.9-py3-none-any.whl").write_bytes(b"foreign")
    rejected = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "build_plugin.py"),
            "--wheelhouse",
            str(wheelhouse),
            "--output",
            str(tmp_path / "rejected.zip"),
        ],
        check=False,
        cwd=ROOT,
    )
    assert rejected.returncode != 0
    (wheelhouse / "foreign_package-9.9-py3-none-any.whl").unlink()
    (wheelhouse / "loxberry_mcpserver-0.0.9-py3-none-any.whl").write_bytes(b"stale project")
    stale_project = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "build_plugin.py"),
            "--wheelhouse",
            str(wheelhouse),
            "--output",
            str(tmp_path / "stale-project.zip"),
        ],
        check=False,
        cwd=ROOT,
    )
    assert stale_project.returncode != 0

    placeholder = tmp_path / "placeholder.zip"
    with zipfile.ZipFile(output) as source, zipfile.ZipFile(placeholder, "w") as destination:
        for entry in source.infolist():
            if entry.filename.startswith("bin/wheelhouse/loxberry_mcpserver-"):
                replacement = zipfile.ZipInfo(
                    "bin/wheelhouse/loxberry_mcpserver-0.1.0a1-placeholder.txt",
                    entry.date_time,
                )
                replacement.create_system = entry.create_system
                replacement.external_attr = entry.external_attr
                replacement.compress_type = entry.compress_type
                destination.writestr(replacement, b"not a wheel")
            else:
                destination.writestr(entry, source.read(entry))
    placeholder_digest = hashlib.sha256(placeholder.read_bytes()).hexdigest()
    placeholder.with_suffix(".zip.sha256").write_text(
        f"{placeholder_digest}  {placeholder.name}\n", encoding="ascii"
    )
    with pytest.raises(PackageVerificationError, match="invalid entry"):
        verify_archive(placeholder)


def test_release_helpers_exclude_stale_project_wheel_and_refuse_overwrite(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    (source / "dependency-1.0-py3-none-any.whl").write_bytes(b"dependency")
    (source / "dependency-0.9-py3-none-any.whl").write_bytes(b"stale dependency")
    (source / "foreign-1.0-py3-none-any.whl").write_bytes(b"foreign")
    (source / "loxberry_mcpserver-0.1.0a1-py3-none-any.whl").write_bytes(b"stale")

    _copy_runtime_wheels(source, destination, {"dependency": "1.0"})

    assert [item.name for item in destination.iterdir()] == ["dependency-1.0-py3-none-any.whl"]
    candidate = tmp_path / "candidate.zip"
    output = tmp_path / "published.zip"
    candidate.write_bytes(b"new")
    output.write_bytes(b"old")
    with pytest.raises(RuntimeError, match="different content"):
        _publish(candidate, output, hashlib.sha256(candidate.read_bytes()).hexdigest())


@pytest.mark.parametrize("script", ["tools/verify_plugin.py", "tools/build_release_candidate.py"])
def test_documented_python_automation_clis_start_without_pythonpath(script: str) -> None:
    result = subprocess.run(
        [sys.executable, script, "--help"],
        check=False,
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    assert result.returncode == 0


def test_mcp_client_probe_has_valid_powershell_syntax() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell is unavailable")
    script = ROOT / "tools" / "test_mcp_client.ps1"
    command = (
        "$errors=$null; [void][System.Management.Automation.Language.Parser]::"
        "ParseFile($env:MCPSERVER_POWERSHELL_TEST_SCRIPT,[ref]$null,[ref]$errors); "
        "if($errors.Count){exit 1}"
    )
    subprocess.run(
        [pwsh, "-NoProfile", "-Command", command],
        check=True,
        env={**os.environ, "MCPSERVER_POWERSHELL_TEST_SCRIPT": str(script)},
    )


def test_plugin_archive_verifier_rejects_checksum_mismatch(tmp_path: Path) -> None:
    archive = tmp_path / "plugin.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("plugin.cfg", b"invalid")
    archive.with_suffix(".zip.sha256").write_text(f"{'0' * 64}  {archive.name}\n", encoding="ascii")

    with pytest.raises(PackageVerificationError, match="checksum"):
        verify_archive(archive)
