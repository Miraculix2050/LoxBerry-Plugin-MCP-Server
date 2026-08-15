from __future__ import annotations

import configparser
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from mcpserver.skill_delivery import SKILL_REVISION
from tools.build_plugin import (
    _EXECUTABLES,
    _add,
    _locked_requirements,
)
from tools.build_plugin import (
    _verify_project_wheel as verify_project_wheel_input,
)
from tools.build_release_candidate import _copy_runtime_wheels, _publish, _source_ignore
from tools.build_release_candidate import main as build_release_candidate
from tools.prepare_wheelhouse import main as prepare_wheelhouse
from tools.validate_release_metadata import validate as validate_release_metadata
from tools.verify_plugin import (
    PackageVerificationError,
    _expected_project_version,
    verify_archive,
)
from tools.verify_plugin import (
    _verify_project_wheel as verify_project_wheel_archive,
)

ROOT = Path(__file__).resolve().parents[1]


def _write_project_wheel(
    path: Path,
    *,
    include_openai_metadata: bool = True,
    stale_file: str | None = None,
    extra_file: str | None = None,
    duplicate_file: str | None = None,
    missing_file: str | None = None,
) -> None:
    with zipfile.ZipFile(path, "w") as wheel:
        for source in (ROOT / "src" / "mcpserver").rglob("*.py"):
            name = source.relative_to(ROOT / "src").as_posix()
            if name == missing_file:
                continue
            source_bytes = source.read_bytes().replace(b"\r\n", b"\n")
            wheel.writestr(name, b"stale" if name == stale_file else source_bytes)
            if name == duplicate_file:
                wheel.writestr(name, source_bytes)
        if extra_file:
            wheel.writestr(extra_file, b"stale deleted module")
        wheel.writestr("mcpserver/skills/using-loxberry-mcp/SKILL.md", b"skill")
        if include_openai_metadata:
            wheel.writestr(
                "mcpserver/skills/using-loxberry-mcp/agents/openai.yaml",
                b"interface: {}\n",
            )


def test_agent_skill_is_declared_as_wheel_package_data() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    skill = ROOT / "src" / "mcpserver" / "skills" / "using-loxberry-mcp"

    assert (skill / "SKILL.md").is_file()
    assert (skill / "agents" / "openai.yaml").is_file()
    assert '"skills/using-loxberry-mcp/SKILL.md"' in pyproject
    assert '"skills/using-loxberry-mcp/agents/openai.yaml"' in pyproject


def test_mcp_client_smoke_covers_skill_delivery_surfaces() -> None:
    script = (ROOT / "tools" / "test_mcp_client.ps1").read_text(encoding="utf-8")

    assert "skill://using-loxberry-mcp/SKILL.md" in script
    assert "loxone_get_skill_guide" in script
    assert "method = 'resources/list'" in script
    assert "method = 'resources/read'" in script
    assert "mcp_skill_delivery=pass" in script
    assert f"$skillGuide.data.revision -ne {SKILL_REVISION}" in script
    assert "[int]$CallbackPort" in script
    assert "if ($proxyArguments[$index] -match '^https?://')" in script
    assert "$callbackIndex = $serverUrlIndex + 1" in script
    assert "$proxyArguments.Insert($callbackIndex, [string]$CallbackPort)" in script
    assert "$controlAdvertised = $actual -contains 'loxone_operate_control'" in script
    assert "if ($ControlFixturePath -and -not $controlAdvertised)" in script
    assert "'loxberry_get_system_status', 'loxberry_list_service_events'," in script
    assert "Temporary override control is outside the approved test intersection." in script
    assert "Temporary override starts must use the fixed 60-second test duration." in script
    assert "Read-only tool $Name returned error code $($envelope.data.error)." in script
    assert "[switch]$ReadFeatureAcceptance" in script
    assert "mcp_room_snapshot_acceptance=pass" in script
    assert "mcp_weather_acceptance=pass" in script
    assert "mcp_readonly_controller_models_acceptance=pass" in script


@pytest.mark.parametrize("variant", ["extra", "duplicate", "missing"])
def test_project_wheel_source_set_must_match_exactly(tmp_path: Path, variant: str) -> None:
    wheel = tmp_path / "project.whl"
    arguments = {
        "extra_file": "mcpserver/deleted.py" if variant == "extra" else None,
        "duplicate_file": "mcpserver/server.py" if variant == "duplicate" else None,
        "missing_file": "mcpserver/server.py" if variant == "missing" else None,
    }
    if variant == "duplicate":
        with pytest.warns(UserWarning, match="Duplicate name"):
            _write_project_wheel(wheel, **arguments)
    else:
        _write_project_wheel(wheel, **arguments)

    with pytest.raises(SystemExit, match="Python source set differs"):
        verify_project_wheel_input(wheel, ROOT / "src")
    with pytest.raises(PackageVerificationError, match="Python source set differs"):
        verify_project_wheel_archive(wheel.read_bytes(), ROOT / "src")


def test_project_wheel_source_verification_ignores_line_endings(tmp_path: Path) -> None:
    source_root = tmp_path / "src"
    source = source_root / "mcpserver" / "module.py"
    source.parent.mkdir(parents=True)
    source.write_bytes(b'"""Module."""\r\n')
    wheel = tmp_path / "project.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("mcpserver/module.py", b'"""Module."""\n')
        archive.writestr("mcpserver/skills/using-loxberry-mcp/SKILL.md", b"skill\n")
        archive.writestr(
            "mcpserver/skills/using-loxberry-mcp/agents/openai.yaml", b"interface: {}\n"
        )

    verify_project_wheel_input(wheel, source_root)
    verify_project_wheel_archive(wheel.read_bytes(), source_root)


def test_plugin_identity_and_platform_contract() -> None:
    parser = configparser.ConfigParser()
    parser.read(ROOT / "plugin.cfg", encoding="utf-8")

    assert parser["PLUGIN"]["NAME"] == "mcpserver"
    assert parser["PLUGIN"]["FOLDER"] == "mcpserver"
    assert parser["PLUGIN"]["TITLE"] == "LoxBerry MCP Server"
    assert parser["PLUGIN"]["VERSION"] == "0.4.0-beta.2"
    assert parser["AUTOUPDATE"]["AUTOMATIC_UPDATES"] == "true"
    assert parser["AUTOUPDATE"]["RELEASECFG"].startswith("https://")
    assert parser["AUTOUPDATE"]["PRERELEASECFG"].startswith("https://")
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
        "bin/renew-web-certificate",
        "icons/icon.svg",
        "webfrontend/htmlauth/index.cgi",
        "webfrontend/htmlauth/explorer.cgi",
        "webfrontend/htmlauth/explorer_callback.cgi",
        "webfrontend/htmlauth/explorer.js",
        "templates/index.html",
        "templates/explorer.html",
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


def test_healthcheck_uses_loxberry_plugin_protocol() -> None:
    healthcheck = (ROOT / "bin/healthcheck").read_text(encoding="utf-8")

    assert 'case "${1:-check}" in' in healthcheck
    assert "title)" in healthcheck
    assert "printf '%s\\n' \"$description\"" in healthcheck
    assert "printf '%s\\n%s\\n%s\\n' \"$description\" 3" in healthcheck
    assert "printf '%s\\n%s\\n%s\\n' \"$description\" 5" in healthcheck
    assert 'check "Plugin configuration" test -r "$plugin_config/mcpserver.json"' in healthcheck
    assert "curl --fail --silent --max-time 3 --output /dev/null" in healthcheck
    assert "No repair action was taken." in healthcheck


def test_upgrade_preserves_configuration_in_plugin_data() -> None:
    preupgrade = (ROOT / "preupgrade.sh").read_text(encoding="utf-8")
    postinstall = (ROOT / "postinstall.sh").read_text(encoding="utf-8")

    assert "installer_root=${6:-}" in preupgrade
    assert "if ! sudo -n /bin/systemctl stop loxberry-mcpserver.service; then" in preupgrade
    assert (
        "main_pid=$(systemctl show --property=MainPID --value --no-pager "
        "loxberry-mcpserver.service || true)"
    ) in preupgrade
    assert 'kill -TERM "$main_pid" || exit 2' in preupgrade
    assert "for _ in {1..20}" in preupgrade
    assert "MCP service did not stop before upgrade migration." in preupgrade
    assert preupgrade.index(
        "if ! sudo -n /bin/systemctl stop loxberry-mcpserver.service; then"
    ) < preupgrade.index('config_file="$LBPCONFIG/$actual_folder/mcpserver.json"')
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


def test_postupgrade_removes_legacy_per_request_admin_logs() -> None:
    postupgrade = (ROOT / "postupgrade.sh").read_text(encoding="utf-8")

    assert "${LBHOMEDIR:-/opt/loxberry}/log/plugins/$actual_folder" in postupgrade
    assert "-name '*_admin-ui.log' -delete" in postupgrade


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


def test_upgrade_removes_the_obsolete_debug_window_atomically() -> None:
    hook = (ROOT / "postupgrade.sh").read_text(encoding="utf-8")

    assert 'python3 - "$plugin_config/mcpserver.json"' in hook
    assert 'logging_config.pop("debug_until")' in hook
    assert "os.fsync(handle.fileno())" in hook
    assert "os.replace(temporary, path)" in hook


def test_phase_four_upgrade_migrates_configuration_and_private_cache() -> None:
    hook = (ROOT / "postupgrade.sh").read_text(encoding="utf-8")
    postroot = (ROOT / "postroot.sh").read_text(encoding="utf-8")

    assert 'document.get("schema_version") == 1' in hook
    assert 'document["schema_version"] = 2' in hook
    for script in (hook, postroot):
        assert 'prepare_private_directory "$plugin_data/statistics-cache" || exit 2' in script
        assert "os.O_NOFOLLOW" in script
        assert "os.fchown(fd" in script
        assert "os.fchmod(fd, 0o700)" in script
        assert "os.lstat(path)" in script


def test_postroot_keeps_installer_alive_during_apache_activation() -> None:
    hook = (ROOT / "postroot.sh").read_text(encoding="utf-8")

    assert "systemctl restart apache2" not in hook
    assert "systemctl reload apache2" in hook
    assert hook.index("systemctl restart loxberry-mcpserver.service") < hook.index(
        "systemctl reload apache2"
    )
    assert "systemctl restart loxberry-mcpserver.service || exit 2" in hook
    assert "for _ in {1..30}" in hook
    assert "curl --fail --silent --max-time 2 http://127.0.0.1:8765/healthz" in hook
    assert 'if [ "$service_ready" -ne 1 ]' in hook
    assert '(umask 0137 && openssl rand 32 > "$key")' in hook
    assert 'chmod 644 "$unit" "$apache"' in hook
    assert 'loxberry_home=$(realpath -e -- "$LBHOMEDIR")' in hook
    assert 'sed "s|@LBHOMEDIR@|$loxberry_home|g"' in hook
    assert 'chmod 755 "$certificate_helper_tmp"' in hook
    assert 'mv -f "$certificate_helper_tmp" "$certificate_helper"' in hook
    assert "/usr/local/sbin/loxberry-mcpserver-renew-web-certificate" in hook
    assert 'NOPASSWD: /usr/local/sbin/loxberry-mcpserver-renew-web-certificate ""' in hook
    assert "renew-web-certificate *" not in hook
    for action in ("start", "stop", "restart"):
        assert f"NOPASSWD: /bin/systemctl {action} loxberry-mcpserver.service" in hook
    assert "NOPASSWD: /bin/systemctl * loxberry-mcpserver.service" not in hook
    assert "NOPASSWD: /bin/systemctl start *" not in hook
    assert "NOPASSWD: /bin/systemctl stop *" not in hook
    assert 'service_log="$plugin_log/service.log"' in hook
    assert "systemctl stop loxberry-mcpserver.service || exit 2" in hook
    assert hook.index("systemctl stop loxberry-mcpserver.service || exit 2") < hook.index(
        'python3 - "$service_log"'
    )
    assert "os.O_NOFOLLOW" in hook
    assert "os.fchown(fd" in hook
    assert "os.fchmod(fd, 0o640)" in hook
    assert "os.lstat(path)" in hook
    assert 'chown loxberry:loxberry "$service_log"' not in hook
    assert 'chmod 640 "$service_log"' not in hook
    assert "LoxBerry::System::get_localip()" in hook
    unit = (ROOT / "config/systemd/loxberry-mcpserver.service.in").read_text(encoding="utf-8")
    assert "@LOCAL_IP_HOST@" in unit
    assert "https://@LOCAL_IP_HOST@" in unit
    assert "Environment=MCPSERVER_LOG_FILE=@LOG_DIR@/service.log" in unit
    assert "StandardOutput=journal" in unit
    assert "StandardError=journal" in unit
    assert "StandardOutput=append:@LOG_DIR@/service.log" not in unit


def test_native_loxberry_log_levels_are_enabled() -> None:
    plugin = (ROOT / "plugin.cfg").read_text(encoding="utf-8")

    assert "CUSTOM_LOGLEVELS=true" in plugin
    assert "CUSTOM_LOGLEVELS=false" not in plugin


def test_postinstall_rewrites_moved_venv_entrypoints() -> None:
    hook = (ROOT / "postinstall.sh").read_text(encoding="utf-8")

    assert '"#!$new_venv/bin/python"' in hook
    assert 'sed -i "1c\\\\#!$venv/bin/python"' in hook
    assert 'rm -rf -- "$venv"' in hook
    assert 'mv "$old_venv" "$venv"' in hook


def test_postinstall_project_pin_matches_plugin_version() -> None:
    parser = configparser.ConfigParser()
    parser.read(ROOT / "plugin.cfg", encoding="utf-8")
    project_version = _expected_project_version(parser["PLUGIN"]["VERSION"])
    hook = (ROOT / "postinstall.sh").read_text(encoding="utf-8")

    assert f"loxberry-mcpserver=={project_version}" in hook


def test_package_builder_includes_plugin_icon() -> None:
    source = (ROOT / "tools" / "build_plugin.py").read_text(encoding="utf-8")

    assert '"icons"' in source
    assert (ROOT / "icons" / "icon.svg").is_file()


def test_perl_admin_cgi_has_valid_syntax() -> None:
    perl = shutil.which("perl")
    if perl is None:
        pytest.skip("perl is unavailable")
    for name in ("index.cgi", "explorer.cgi", "explorer_callback.cgi"):
        subprocess.run(
            [
                perl,
                f"-I{ROOT / 'tests' / 'perl_stubs'}",
                "-c",
                str(ROOT / "webfrontend/htmlauth" / name),
            ],
            check=True,
        )
    subprocess.run(
        [
            perl,
            f"-I{ROOT / 'tests' / 'perl_stubs'}",
            "-c",
            str(ROOT / "bin" / "renew-web-certificate"),
        ],
        check=True,
    )


def test_certificate_helper_keeps_pin_off_argv_and_uses_fixed_core_actions() -> None:
    helper = (ROOT / "bin" / "renew-web-certificate").read_text(encoding="utf-8")

    assert "my $securepin = <STDIN>;" in helper
    assert "check_securepin($securepin)" in helper
    assert "revokewwwcert.sh" in helper
    assert "makewwwcert.sh" in helper
    assert "@LBHOMEDIR@" in helper
    assert '$ENV{PERL5LIB} = "$loxberry_home/libs/perllib";' in helper
    assert "/opt/loxberry" not in helper
    assert "systemd-run" in helper
    assert "--unit=$unit" in helper
    assert "@ARGV == 1 && $ARGV[0] eq '--worker'" in helper
    assert "checksecurepin '$securepin'" not in helper


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
    assert "/\\A(?:de|en)\\z/" in cgi
    assert "$LoxBerry::System::lang = $q->{lang}" in cgi
    assert "$LoxBerry::Web::lang = $q->{lang}" in cgi
    assert "ajax-generic.php" not in cgi + template
    assert 'method="post"' in template
    assert "fetch('index.cgi'" in template
    assert "overflow-x: auto" in template
    assert "@media (max-width: 30rem)" in template
    assert "#diagnostics .lb-table-scroll { overflow-x: visible; }" in template
    assert ":focus-visible" in template
    assert 'type="password"' in template
    assert 'name="renew_confirmation"' in template
    assert 'data-ajax="renew_certificate"' in template
    assert 'data-copy-target="mcp-url-hostname"' in template
    assert 'data-copy-target="mcp-url-ip"' in template
    assert "LoxBerry::System::check_securepin" not in cgi
    assert "MCPSERVER_CERT_HELPER" in cgi


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
    project_wheel = wheelhouse / "loxberry_mcpserver-0.4.0b2-py3-none-any.whl"
    _write_project_wheel(project_wheel)
    hash_lock = tmp_path / "runtime-arm64.sha256"
    hash_lock.write_text(
        "".join(
            f"{hashlib.sha256(wheel.read_bytes()).hexdigest()}  {wheel.name}\n"
            for wheel in sorted(wheelhouse.glob("*.whl"))
            if not wheel.name.startswith("loxberry_mcpserver-")
        ),
        encoding="ascii",
    )
    output = tmp_path / "plugin.zip"

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "build_plugin.py"),
            "--wheelhouse",
            str(wheelhouse),
            "--output",
            str(output),
            "--runtime-hash-lock",
            str(hash_lock),
        ],
        check=True,
        cwd=ROOT,
    )

    assert verify_archive(output) == hashlib.sha256(output.read_bytes()).hexdigest()

    _write_project_wheel(project_wheel, include_openai_metadata=False)
    missing_skill_metadata = tmp_path / "missing-skill-metadata.zip"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "build_plugin.py"),
            "--wheelhouse",
            str(wheelhouse),
            "--output",
            str(missing_skill_metadata),
            "--runtime-hash-lock",
            str(hash_lock),
        ],
        check=True,
        cwd=ROOT,
    )
    with pytest.raises(PackageVerificationError, match="project wheel entry is missing"):
        verify_archive(missing_skill_metadata)

    _write_project_wheel(project_wheel, stale_file="mcpserver/server.py")
    stale_source = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "build_plugin.py"),
            "--wheelhouse",
            str(wheelhouse),
            "--output",
            str(tmp_path / "stale-source.zip"),
            "--runtime-hash-lock",
            str(hash_lock),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert stale_source.returncode != 0
    assert "project wheel contains stale source: mcpserver/server.py" in stale_source.stderr
    stale_archive = tmp_path / "stale-project-source.zip"
    with zipfile.ZipFile(output) as source, zipfile.ZipFile(stale_archive, "w") as destination:
        for entry in source.infolist():
            content = (
                project_wheel.read_bytes()
                if entry.filename.startswith("bin/wheelhouse/loxberry_mcpserver-")
                else source.read(entry)
            )
            destination.writestr(entry, content)
    stale_digest = hashlib.sha256(stale_archive.read_bytes()).hexdigest()
    stale_archive.with_suffix(".zip.sha256").write_text(
        f"{stale_digest}  {stale_archive.name}\n", encoding="ascii"
    )
    with pytest.raises(PackageVerificationError, match="contains stale source"):
        verify_archive(stale_archive)
    _write_project_wheel(project_wheel)

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
            "--runtime-hash-lock",
            str(hash_lock),
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
            "--runtime-hash-lock",
            str(hash_lock),
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

    dependency = source / "dependency-1.0-py3-none-any.whl"
    _copy_runtime_wheels(
        source,
        destination,
        {"dependency": "1.0"},
        {dependency.name: hashlib.sha256(dependency.read_bytes()).hexdigest()},
    )

    assert [item.name for item in destination.iterdir()] == ["dependency-1.0-py3-none-any.whl"]
    candidate = tmp_path / "candidate.zip"
    output = tmp_path / "published.zip"
    candidate.write_bytes(b"new")
    output.write_bytes(b"old")
    with pytest.raises(RuntimeError, match="different content"):
        _publish(candidate, output, hashlib.sha256(candidate.read_bytes()).hexdigest())


def test_release_source_copy_ignores_untracked_build_and_temporary_directories() -> None:
    ignored = _source_ignore(
        "source",
        ["src", "tmp", "dist", "build", ".pytest_cache", "note.txt", "bytecode.pyc"],
    )

    assert ignored == {"tmp", "dist", "build", ".pytest_cache", "bytecode.pyc"}


def test_release_candidate_builds_plugin_archive_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    build_calls: list[tuple[str, ...]] = []
    test_environments: list[dict[str, str]] = []

    def run(*arguments: str, root: Path, environment: dict[str, str] | None = None) -> None:
        del root
        if "tools/test.py" in arguments:
            assert environment is not None
            test_environments.append(environment)
        if "tools/build_plugin.py" in arguments:
            build_calls.append(arguments)
            output = Path(arguments[arguments.index("--output") + 1])
            output.write_bytes(b"candidate")

    monkeypatch.setattr("tools.build_release_candidate._run", run)
    monkeypatch.setattr(
        sys,
        "argv",
        ["build_release_candidate.py", "--output-dir", str(tmp_path)],
    )
    monkeypatch.setenv("PYTEST_ADDOPTS", "--maxfail=1")

    assert build_release_candidate() == 0
    assert len(build_calls) == 1
    assert len(test_environments) == 1
    pytest_options = test_environments[0]["PYTEST_ADDOPTS"]
    parsed_options = shlex.split(pytest_options)
    assert parsed_options[-2:] == ["-p", "no:cacheprovider"]
    basetemp = Path(parsed_options[0].removeprefix("--basetemp="))
    assert basetemp.is_absolute()
    assert not basetemp.exists()


def test_prepare_runtime_wheelhouse_skips_project_wheel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[list[str]] = []

    def run(arguments: list[str], **_kwargs: object) -> None:
        commands.append(arguments)

    monkeypatch.setattr("tools.prepare_wheelhouse.subprocess.run", run)
    monkeypatch.setattr(
        "tools.prepare_wheelhouse._verify_runtime_wheels",
        lambda *_arguments: None,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["prepare_wheelhouse.py", "--runtime-only", str(tmp_path)],
    )

    assert prepare_wheelhouse() == 0
    assert len(commands) == 1
    assert commands[0][2:4] == ["pip", "download"]
    assert (tmp_path / "runtime-arm64.lock").is_file()
    assert (tmp_path / "runtime-arm64.sha256").is_file()


@pytest.mark.parametrize(
    "script",
    [
        "tools/verify_plugin.py",
        "tools/build_release_candidate.py",
        "tools/prepare_wheelhouse.py",
    ],
)
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


def test_mcp_client_probe_resolves_windows_application_aliases() -> None:
    script = (ROOT / "tools" / "test_mcp_client.ps1").read_text(encoding="utf-8")

    assert "function Resolve-ProcessCommand" in script
    assert "Select-Object -First 1" in script
    assert "$startInfo.FileName = Resolve-ProcessCommand ([string]$server.command)" in script
    assert "'loxone_list_global_metadata'" in script
    assert "'loxone_get_room_snapshot'" in script
    assert "'loxone_get_weather'" in script
    assert "$optional = @(" in script
    assert "$tool.annotations.idempotentHint -ne $false" in script
    assert "$tool.name -eq 'loxberry_clear_statistics_cache'" in script


def _write_claude_config(path: Path, *, configured: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = (
        {"mcpServers": {"loxberry-mcp": {"command": "node", "args": []}}}
        if configured
        else {"preferences": {}}
    )
    path.write_text(json.dumps(document), encoding="utf-8")


def _run_claude_config_check(tmp_path: Path, *extra_args: str) -> subprocess.CompletedProcess[str]:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell is unavailable")
    app_data = tmp_path / "Roaming"
    local_app_data = tmp_path / "Local"
    return subprocess.run(
        [
            pwsh,
            "-NoProfile",
            "-File",
            str(ROOT / "tools" / "test_mcp_client.ps1"),
            "-CheckConfigurationOnly",
            *extra_args,
        ],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "APPDATA": str(app_data),
            "LOCALAPPDATA": str(local_app_data),
        },
    )


def test_mcp_client_probe_prefers_active_store_profile(tmp_path: Path) -> None:
    store_config = (
        tmp_path
        / "Local"
        / "Packages"
        / "Claude_test"
        / "LocalCache"
        / "Roaming"
        / "Claude"
        / "claude_desktop_config.json"
    )
    classic_config = tmp_path / "Roaming" / "Claude" / "claude_desktop_config.json"
    _write_claude_config(store_config, configured=False)
    _write_claude_config(classic_config, configured=True)

    result = _run_claude_config_check(tmp_path)

    assert result.returncode != 0
    assert "claude_mcp_configuration=pass" not in result.stdout


def test_mcp_client_probe_accepts_configured_store_profile(tmp_path: Path) -> None:
    store_config = (
        tmp_path
        / "Local"
        / "Packages"
        / "Claude_test"
        / "LocalCache"
        / "Roaming"
        / "Claude"
        / "claude_desktop_config.json"
    )
    _write_claude_config(store_config, configured=True)

    result = _run_claude_config_check(tmp_path)

    assert result.returncode == 0
    assert result.stdout.strip() == "claude_mcp_configuration=pass"


def test_mcp_client_probe_falls_back_to_classic_profile(tmp_path: Path) -> None:
    classic_config = tmp_path / "Roaming" / "Claude" / "claude_desktop_config.json"
    _write_claude_config(classic_config, configured=True)

    result = _run_claude_config_check(tmp_path)

    assert result.returncode == 0
    assert result.stdout.strip() == "claude_mcp_configuration=pass"


def test_mcp_client_probe_respects_explicit_config_path(tmp_path: Path) -> None:
    explicit_config = tmp_path / "explicit" / "claude.json"
    _write_claude_config(explicit_config, configured=True)

    result = _run_claude_config_check(
        tmp_path,
        "-ClaudeConfigPath",
        str(explicit_config),
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "claude_mcp_configuration=pass"


def test_plugin_archive_verifier_rejects_checksum_mismatch(tmp_path: Path) -> None:
    archive = tmp_path / "plugin.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("plugin.cfg", b"invalid")
    archive.with_suffix(".zip.sha256").write_text(f"{'0' * 64}  {archive.name}\n", encoding="ascii")

    with pytest.raises(PackageVerificationError, match="checksum"):
        verify_archive(archive)


def test_release_metadata_and_changelog_match_current_prerelease() -> None:
    notes = validate_release_metadata(ROOT, "0.4.0-beta.2", "prerelease")
    parser = configparser.ConfigParser()
    parser.read(ROOT / "plugin.cfg", encoding="utf-8")
    source_fallback = (ROOT / "src" / "mcpserver" / "__init__.py").read_text(encoding="utf-8")

    assert "Enable bounded history/statistics" in notes
    assert f'__version__ = "{parser["PLUGIN"]["VERSION"]}"' in source_fallback
    with pytest.raises(ValueError, match="stable releases"):
        validate_release_metadata(ROOT, "0.4.0-beta.2", "stable")
    with pytest.raises(ValueError, match="prerelease releases"):
        validate_release_metadata(ROOT, "0.4.0", "prerelease")
    with pytest.raises(ValueError, match="channel must"):
        validate_release_metadata(ROOT, "0.4.0-beta.2", "preview")
    with pytest.raises(ValueError, match="versions do not match"):
        validate_release_metadata(ROOT, "0.3.0-alpha.2", "prerelease")


@pytest.mark.parametrize(
    ("version", "expected"),
    (
        ("0.4.0-alpha.15", "0.4.0a15"),
        ("0.4.0-beta.1", "0.4.0b1"),
        ("0.4.0", "0.4.0"),
    ),
)
def test_project_version_normalization_supports_alpha_beta_and_stable(
    version: str, expected: str
) -> None:
    assert _expected_project_version(version) == expected


@pytest.mark.parametrize("version", ("0.4.0-alpha.01", "0.4.0-beta.01", "0.4.0-BETA.1"))
def test_project_version_normalization_rejects_leading_zero_prerelease_counter(
    version: str,
) -> None:
    with pytest.raises(ValueError, match="version must use"):
        _expected_project_version(version)


def test_release_workflow_is_manual_owner_only_and_separates_permissions() -> None:
    workflow = (ROOT / ".github/workflows/publish-plugin-release.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "github.actor" in workflow
    assert "github.triggering_actor" in workflow
    assert "github.repository_owner" in workflow
    assert "REF_NAME: ${{ github.ref_name }}" in workflow
    assert "CHANNEL: ${{ inputs.channel }}" in workflow
    assert "ref: ${{ github.sha }}" in workflow
    assert "confirm_release:" in workflow
    assert "contents: read" in workflow
    assert "contents: write" in workflow
    assert "pull_request_target" not in workflow
    assert "release.published" not in workflow
    assert "\n  push:" not in workflow
    for action in (
        "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
        "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
        "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093",
    ):
        assert action in workflow

    publisher = (ROOT / "tools/publish_github_release.sh").read_text(encoding="utf-8")
    assert 'git config user.name "github-actions[bot]"' in publisher
    assert "actual_title=" in publisher
    assert "actual_body=" in publisher
    assert "title or notes do not match" in publisher
    assert 'gh release view "$TAG" --repo "$REPOSITORY"' in publisher
    assert "releases/tags/$TAG" not in publisher
    assert "draft: .isDraft" in publisher
    assert 'apiUrl | split("/") | last' in publisher


def test_package_contract_excludes_update_and_development_files() -> None:
    source = (ROOT / "tools/build_plugin.py").read_text(encoding="utf-8")
    root_manifest = source.split("_ROOT_FILES", 1)[1].split(")", 1)[0]

    for forbidden in (
        '".gitattributes"',
        '"release.cfg"',
        '"prerelease.cfg"',
        '"AGENTS.md"',
        '"tests"',
        '"tools"',
    ):
        assert forbidden not in root_manifest
