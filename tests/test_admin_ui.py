from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_initial_page_uses_one_aggregated_admin_call() -> None:
    cgi = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")

    assert "admin_call('page_state', {})" in cgi
    assert "my $config_result =" not in cgi
    assert "my $status_result =" not in cgi
    assert "my $sessions_result =" not in cgi


def test_common_actions_update_the_page_without_a_reload() -> None:
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")

    assert 'data-ajax="save_config"' in template
    assert "Array.isArray(result.data.sessions)" in template
    assert "updateSessions(result.data.sessions)" in template
    assert "window.location.reload" not in template
    assert "window.setTimeout(() => { element.hidden = true; }, 4000)" in template
    assert "window.clearTimeout(hideStatusTimers.get(status))" in template
    assert "url.searchParams.delete('notice')" in template
    assert "postAjax(body, actionTimeout(form.dataset.ajax))" in template
    assert "save_config: 90000" in template
    assert "revoke_all: 75000" in template
    assert "postAjax(body, 5000)" in template
    assert "if (result.data.certificate) updateCertificate" in template
    assert 'id="session-table-template"' in template
    assert "row.dataset.fingerprint !== sessionFingerprint(session)" in template
    assert "for (const row of existing.values()) row.remove()" in template


def test_admin_cards_use_consistent_vertical_spacing() -> None:
    template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")

    assert ".mcp-page { display: grid; gap: 1rem;" in template
    assert ".mcp-field-stack { display: grid; gap: .85rem; }" in template
    assert '<div class="mcp-field-stack">' in template


def test_service_status_is_first_and_uses_a_lightweight_ajax_contract() -> None:
    cgi = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")

    assert template.index('id="status"') < template.index('id="setup"')
    assert 'data-ajax="service_status"' not in template
    assert 'data-service-command="start"' in template
    assert 'data-service-command="stop"' in template
    assert 'data-service-command="restart"' in template
    assert "body.set('action', 'service_status')" in template
    assert "window.setTimeout(pollServiceStatus, delay)" in template
    assert "document.hidden || serviceActionRunning || servicePollInFlight" in template
    assert "document.addEventListener('visibilitychange'" in template
    assert "admin_call('service_status', {})" in cgi
    assert "admin_call('service_action', {command => $command})" in cgi
    assert "$command =~ /\\A(?:start|stop|restart)\\z/" in cgi
    assert "service.log&header=html&format=template" in cgi


def test_sessions_poll_only_while_visible_and_open_and_patch_changed_rows() -> None:
    cgi = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")

    assert "admin_call('list_sessions', {})" in cgi
    assert "body.set('action', 'list_sessions')" in template
    assert "window.setTimeout(pollSessions, delay)" in template
    assert (
        "document.hidden || !sessionsSection.open || sessionActionRunning || sessionPollInFlight"
        in template
    )
    assert "sessionsSection.addEventListener('toggle'" in template
    assert "row.dataset.fingerprint !== sessionFingerprint(session)" in template
    assert "sessionList.replaceChildren(fragment)" in template


def test_read_only_ajax_polling_does_not_create_admin_log_files() -> None:
    cgi = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")

    assert "sub admin_log" in cgi
    assert cgi.index("sub admin_log") < cgi.index("LoxBerry::Log->new")
    assert "$admin_log->close() if $admin_log;" in cgi
    assert "LOGSTART('index.cgi called')" not in cgi
    assert "loglevel => 7" not in cgi
    assert "filename => $filename" in cgi
    assert "append => 1" in cgi
    assert "nosession => 1" in cgi
    assert "LoxBerry::System::pluginloglevel($lbpplugindir)" in cgi
    assert "flock($lock, LOCK_EX)" in cgi
    assert "ADMIN_LOG_MAX_BYTES => 512 * 1024" in cgi
    assert "ADMIN_LOG_BACKUP_COUNT => 2" in cgi
    assert "ADMIN_LOG_MESSAGE_BYTES => 8 * 1024" in cgi
    assert "LOGSTART('Administrative action')" not in cgi
    assert "LOGEND('Administrative action finished')" not in cgi
    assert "action=service_$command outcome=completed" in cgi
    assert "component=admin_helper outcome=failed" in cgi
    assert "component=miniserver_config outcome=invalid" in cgi


def test_diagnostics_offer_dedicated_persistent_service_logging_controls() -> None:
    cgi = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")

    assert "admin_call('set_logging', {mode => ($q->{mode} // '')})" in cgi
    assert 'data-ajax="set_logging"' in template
    for level in ("off", "error", "warning", "info", "debug"):
        assert f'value="{level}"' in template
    assert 'value="debug_15"' not in template
    assert 'value="debug_60"' not in template
    assert 'value="stop_debug"' not in template
    assert "debug_until" not in template + cgi
    assert "DIAGNOSTICS.SERVICE_LEVEL" in template
    assert "DIAGNOSTICS.LOGMANAGER_HELP" in template
    assert "DIAGNOSTICS.SERVICE_SECTION" in template
    assert "DIAGNOSTICS.PLUGIN_SECTION" in template
    assert template.count('class="mcp-log-section"') == 2
    assert template.index('id="service-log-heading"') < template.index('id="plugin-log-heading"')
    assert "set_logging: 75000" in template
    assert "renderLogging(result.data.configuration)" in template
    assert "window.location.reload" not in template


def test_admin_log_message_and_rotation_are_bounded(tmp_path: Path) -> None:
    cgi = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")
    implementation = re.search(
        r"(use constant ADMIN_LOG_MAX_BYTES.*?)(?=sub admin_log \{)",
        cgi,
        re.DOTALL,
    )
    assert implementation is not None
    perl = shutil.which("perl")
    assert perl is not None, "Perl is required for the complete deterministic gate"
    log_file = tmp_path / "admin-ui.log"
    log_file.write_bytes(b"x" * (512 * 1024 - 100))
    for suffix, content in ((".1", b"one"), (".2", b"two"), (".3", b"stale")):
        log_file.with_name(log_file.name + suffix).write_bytes(content)
    script = f"""
use strict;
use warnings;
use Encode qw(decode encode FB_DEFAULT);
{implementation.group(1)}
my $message = bounded_admin_message(chr(0xE4) x 8000);
print length(encode('UTF-8', $message)), "\n";
print rotate_admin_log_locked($ARGV[0], 300), "\n";
"""

    result = subprocess.run(
        [perl, "-e", script, str(log_file)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines() == [str(8 * 1024), "1"]
    assert log_file.with_name(log_file.name + ".1").stat().st_size == 512 * 1024 - 100
    assert log_file.with_name(log_file.name + ".2").read_bytes() == b"one"
    assert not log_file.with_name(log_file.name + ".3").exists()


def test_service_actions_use_an_accessible_confirmation_and_dynamic_controls() -> None:
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")

    assert '<dialog id="service-confirm"' in template
    assert 'aria-labelledby="service-confirm-title"' in template
    assert "serviceConfirmMessages[serviceCommand]" in template
    assert "form.dataset.confirmed = 'true'" in template
    assert "form.requestSubmit()" in template
    assert "command === 'start'" in template
    assert "installed && active" in template
    assert "serviceState.dataset.kind = kind" in template
    assert "serviceActionRunning = true" in template
    assert "service_action: 75000" in template


def test_admin_sections_are_native_persistent_collapsibles() -> None:
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")

    for section in ("status", "setup", "help", "certificate", "sessions", "diagnostics"):
        assert f'<details id="{section}" class="mcp-card" data-persist-collapse' in template
    assert '<details id="status" class="mcp-card" data-persist-collapse open' in template
    assert '<details id="setup" class="mcp-card" data-persist-collapse open' in template
    assert "mcpserver.admin.sections.v1" in template
    assert "window.localStorage.getItem(collapseStorageKey)" in template
    assert "window.localStorage.setItem(collapseStorageKey" in template
    assert "element.addEventListener('toggle', persistCollapsibles)" in template
    assert "window.addEventListener('hashchange', openHashSection)" in template
    assert "target instanceof HTMLDetailsElement" in template


def test_miniserver_access_mode_is_an_explicit_read_or_switch_selection() -> None:
    cgi = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")

    assert '<select name="loxone_control_enabled">' in template
    assert '<option value="0" <TMPL_UNLESS LOXONE_CONTROL_ENABLED>selected' in template
    assert '<option value="1" <TMPL_IF LOXONE_CONTROL_ENABLED>selected' in template
    assert 'name="loxone_control_enabled" type="checkbox"' not in template
    assert "($q->{loxone_control_enabled} // '') eq '1'" in cgi


def test_miniserver_selection_uses_local_sanitized_loxberry_metadata() -> None:
    cgi = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")

    assert '"$lbhomedir/config/system/general.json"' in cgi
    assert "LoxBerry::System::get_miniservers()" not in cgi
    assert "next if enabled_value($stored->{Useclouddns})" in cgi
    assert "IPAddress => $stored->{Ipaddress}" in cgi
    assert "PortHttps => $stored->{Porthttps}" in cgi
    assert "miniserver_endpoint($server)" in cgi
    assert "FullURI" not in cgi + template
    assert "Credentials" not in cgi + template
    assert 'id="miniserver-select"' in template
    assert "<TMPL_LOOP MINISERVERS>" in template
    assert 'id="manual-endpoint-fields"' in template
    assert "<TMPL_UNLESS MANUAL_ENDPOINT>hidden</TMPL_UNLESS>" in template
    assert 'id="miniserver-endpoint"' in template
    assert "<TMPL_IF MANUAL_ENDPOINT>required<TMPL_ELSE>readonly</TMPL_IF>" in template
    assert "miniserverEndpoint.readOnly = Boolean(selectedEndpoint)" in template
    assert "miniserverEndpoint.required = !selectedEndpoint" in template
    assert "manualEndpointFields.hidden = Boolean(selectedEndpoint)" in template
    assert "miniserverEndpoint.addEventListener('input', syncTestEndpoint)" in template


def test_miniserver_endpoint_builder_rejects_unsafe_metadata() -> None:
    cgi = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")
    builder = re.search(r"sub miniserver_endpoint \{.*?^\}", cgi, re.MULTILINE | re.DOTALL)

    assert builder is not None
    perl = shutil.which("perl")
    assert perl is not None, "Perl is required for the complete deterministic gate"
    script = f"""
use Socket qw(AF_INET AF_INET6 inet_ntop inet_pton);
{builder.group(0)}
my @cases = (
    {{Transport => 'http', IPAddress => '192.168.1.20', Port => 80}},
    {{Transport => 'http', IPAddress => '192.168.1.20', Port => 8080}},
    {{Transport => 'https', IPAddress => 'miniserver.example', PortHttps => 443}},
    {{Transport => 'https', IPAddress => '2001:db8::1', PortHttps => 8443}},
    {{Transport => 'http', IPAddress => 'fc00:0:0:0:0:0:0:1', Port => 80}},
    {{Transport => 'http', IPAddress => '8.8.8.8', Port => 80}},
    {{Transport => 'http', IPAddress => '999.999.999.999', Port => 80}},
    {{Transport => 'http', IPAddress => '2001:db8::1', Port => 80}},
    {{Transport => 'http', IPAddress => 'host.example', Port => 80}},
    {{Transport => 'https', IPAddress => 'user@host.example', PortHttps => 443}},
    {{Transport => 'https', IPAddress => 'host.example/path', PortHttps => 443}},
    {{Transport => 'https', IPAddress => '2001:::1', PortHttps => 443}},
    {{Transport => 'https', IPAddress => 'host.example', PortHttps => 0}},
);
for my $case (@cases) {{ print((miniserver_endpoint($case) // 'rejected') . "\\n"); }}
"""
    result = subprocess.run([perl, "-e", script], check=True, capture_output=True, text=True)

    assert result.stdout.splitlines() == [
        "http://192.168.1.20",
        "http://192.168.1.20:8080",
        "https://miniserver.example",
        "https://[2001:db8::1]:8443",
        "http://[fc00::1]",
        "rejected",
        "rejected",
        "rejected",
        "rejected",
        "rejected",
        "rejected",
        "rejected",
        "rejected",
    ]


def test_local_mcp_url_builder_handles_hostname_ip_port_and_unsafe_values() -> None:
    cgi = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")
    builder = re.search(r"sub local_mcp_url \{.*?^\}", cgi, re.MULTILINE | re.DOTALL)

    assert builder is not None
    perl = shutil.which("perl")
    assert perl is not None, "Perl is required for the complete deterministic gate"
    script = f"""
use Socket qw(AF_INET AF_INET6 inet_ntop inet_pton);
{builder.group(0)}
my @cases = (
    ['loxberry-test', 443],
    ['loxberry-test', 8443],
    ['192.0.2.10', 443],
    ['2001:db8::1', 8443],
    ['user@host', 443],
    ['host/path', 443],
    ['', 443],
);
for my $case (@cases) {{ print((local_mcp_url(@$case) // '') . "\n"); }}
"""
    result = subprocess.run([perl, "-e", script], check=True, capture_output=True, text=True)

    assert result.stdout.splitlines() == [
        "https://loxberry-test/plugins/mcpserver/mcp",
        "https://loxberry-test:8443/plugins/mcpserver/mcp",
        "https://192.0.2.10/plugins/mcpserver/mcp",
        "https://[2001:db8::1]:8443/plugins/mcpserver/mcp",
        "",
        "",
        "",
    ]


def test_session_expiry_is_rendered_as_a_local_date_and_time() -> None:
    cgi = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")

    assert "strftime('%Y-%m-%d %H:%M:%S %Z', localtime(0 + $raw))" in cgi
    assert "$session->{expires_display} = format_expiry($session->{expires_at})" in cgi
    assert 'class="mcp-expiry"' in template
    assert 'data-expires-at="<TMPL_VAR expires_at ESCAPE=HTML>"' in template
    assert "<TMPL_VAR expires_display ESCAPE=HTML>" in template
    assert "new Intl.DateTimeFormat(document.documentElement.lang || undefined" in template
    assert "element.textContent = expiryFormatter.format(date)" in template
    assert "<td><TMPL_VAR expires_at ESCAPE=HTML></td>" not in template


def test_sessions_show_client_name_before_the_stable_instance_identifier() -> None:
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    german = (ROOT / "templates/lang/language_de.ini").read_text(encoding="utf-8")
    english = (ROOT / "templates/lang/language_en.ini").read_text(encoding="utf-8")

    assert template.index("<TMPL_VAR SESSIONS.CLIENT>") < template.index(
        "<TMPL_VAR SESSIONS.INSTANCE>"
    )
    assert "<TMPL_IF client_name><TMPL_VAR client_name ESCAPE=HTML>" in template
    assert "<TMPL_ELSE><TMPL_VAR SESSIONS.UNNAMED>" in template
    assert "INSTANCE=Client-Instanz" in german
    assert "UNNAMED=Unbenannter OAuth-Client" in german
    assert "INSTANCE=Client instance" in english
    assert "UNNAMED=Unnamed OAuth client" in english


def test_perl_expiry_formatter_rejects_out_of_range_values_safely() -> None:
    cgi = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")
    constant = re.search(r"use constant MAX_EXPIRY_EPOCH => [^;]+;", cgi)
    formatter = re.search(r"sub format_expiry \{.*?^\}", cgi, re.MULTILINE | re.DOTALL)

    assert constant is not None
    assert formatter is not None
    perl = shutil.which("perl")
    assert perl is not None, "Perl is required for the complete deterministic gate"
    script = f"""
use POSIX qw(strftime);
{constant.group(0)}
{formatter.group(0)}
for my $value (@ARGV) {{ print format_expiry($value), "\\n"; }}
for my $value ("1" . chr(0x0662), "1" . chr(0xff12)) {{
    print format_expiry($value) eq $value ? "unicode-raw\\n" : "unicode-changed\\n";
}}
print format_expiry(undef), "\\n";
"""
    values = [
        "1900000000",
        "4102444799",
        "4102444800",
        "999999999999999999",
        "-1",
        "1.5",
        " 1",
        "01",
    ]
    result = subprocess.run(
        [perl, "-e", script, *values],
        check=True,
        capture_output=True,
        text=True,
    )
    output = result.stdout.splitlines()

    assert output[0] != values[0]
    assert output[1] != values[1]
    assert output[2:] == [*values[2:], "unicode-raw", "unicode-raw", ""]


def test_browser_expiry_parser_uses_the_same_bounds() -> None:
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    parser = re.search(
        r"const MAX_EXPIRY_EPOCH = .*?^  \};",
        template,
        re.MULTILINE | re.DOTALL,
    )

    assert parser is not None
    node = shutil.which("node")
    assert node is not None, "Node.js is required for the complete deterministic gate"
    values = [
        "1900000000",
        "4102444799",
        "4102444800",
        "999999999999999999",
        "-1",
        "1.5",
        " 1",
        "01",
        "1\u0662",
        "1\uff12",
        "",
    ]
    script = f"""
{parser.group(0)}
console.log(JSON.stringify(process.argv.slice(1).map(parseExpiry)));
"""
    result = subprocess.run(
        [node, "-e", script, *values],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == (
        "[1900000000,4102444799,null,null,null,null,null,null,null,null,null]"
    )
