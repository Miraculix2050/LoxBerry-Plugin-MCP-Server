from __future__ import annotations

import configparser
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from tools.build_plugin import _EXECUTABLES, _add

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
