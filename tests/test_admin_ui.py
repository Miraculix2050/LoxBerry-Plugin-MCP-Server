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
