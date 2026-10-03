"""Check origin tuples and exercise the shipped CGI guards before helper calls."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "bin/lib/MCPServer/RequestSecurity.pm"
BASE = {
    "REQUEST_METHOD": "POST",
    "HTTPS": "on",
    "REQUEST_SCHEME": "https",
    "HTTP_HOST": "loxberry.example",
    "HTTP_ORIGIN": "https://loxberry.example",
}
CASES = [
    pytest.param({}, True, id="https"),
    pytest.param(
        {"HTTPS": "off", "REQUEST_SCHEME": "http", "HTTP_ORIGIN": "http://loxberry.example"},
        True,
        id="http",
    ),
    pytest.param({"HTTP_ORIGIN": "http://loxberry.example"}, False, id="http-origin-over-https"),
    pytest.param({"HTTPS": "off", "REQUEST_SCHEME": "http"}, False, id="https-origin-over-http"),
    pytest.param(
        {"HTTP_ORIGIN": "https://loxberry.example:443"}, True, id="explicit-origin-default-port"
    ),
    pytest.param({"HTTP_HOST": "loxberry.example:443"}, True, id="explicit-host-default-port"),
    pytest.param(
        {"HTTP_HOST": "loxberry.example:8443", "HTTP_ORIGIN": "https://loxberry.example:8443"},
        True,
        id="custom-port",
    ),
    pytest.param({"HTTP_HOST": "loxberry.example:8443"}, False, id="port-mismatch"),
    pytest.param(
        {"HTTP_HOST": "LOXBERRY.EXAMPLE", "HTTP_ORIGIN": "HTTPS://LoxBerry.Example"},
        True,
        id="case-insensitive-dns",
    ),
    pytest.param({"HTTP_HOST": "127.0.0.1", "HTTP_ORIGIN": "https://127.0.0.1"}, True, id="ipv4"),
    pytest.param(
        {"HTTP_HOST": "[2001:db8::1]:8443", "HTTP_ORIGIN": "https://[2001:0db8:0:0:0:0:0:1]:8443"},
        True,
        id="ipv6-normalized",
    ),
    pytest.param({"HTTP_ORIGIN": "https://other.example"}, False, id="different-host"),
    pytest.param({"HTTP_ORIGIN": None}, False, id="missing-origin"),
    pytest.param({"HTTP_ORIGIN": "null"}, False, id="opaque-origin"),
    pytest.param({"HTTP_HOST": None}, False, id="missing-host"),
    pytest.param({"REQUEST_METHOD": "GET"}, False, id="get"),
    pytest.param({"REQUEST_METHOD": None}, False, id="missing-method"),
    pytest.param({"HTTPS": None}, True, id="scheme-only"),
    pytest.param({"REQUEST_SCHEME": None}, True, id="tls-only"),
    pytest.param({"HTTPS": "1", "REQUEST_SCHEME": None}, True, id="tls-one"),
    pytest.param({"HTTPS": "ON", "REQUEST_SCHEME": "HTTPS"}, True, id="metadata-case"),
    pytest.param(
        {"HTTPS": None, "REQUEST_SCHEME": None, "HTTP_ORIGIN": "http://loxberry.example"},
        True,
        id="native-http-default",
    ),
    pytest.param({"HTTPS": None, "REQUEST_SCHEME": None}, False, id="no-tls-inference"),
    pytest.param(
        {
            "HTTPS": "0",
            "REQUEST_SCHEME": "http",
            "HTTP_HOST": "loxberry.example:80",
            "HTTP_ORIGIN": "http://loxberry.example",
        },
        True,
        id="http-default-port",
    ),
    pytest.param({"HTTPS": "off"}, False, id="contradictory-http"),
    pytest.param({"REQUEST_SCHEME": "http"}, False, id="contradictory-https"),
    pytest.param({"HTTPS": "true"}, False, id="invalid-tls"),
    pytest.param({"HTTPS": ""}, False, id="empty-tls"),
    pytest.param({"REQUEST_SCHEME": "ftp"}, False, id="invalid-scheme"),
    pytest.param({"REQUEST_SCHEME": ""}, False, id="empty-scheme"),
    pytest.param(
        {
            "HTTP_FORWARDED": "proto=http;host=other.example",
            "HTTP_X_FORWARDED_PROTO": "http",
            "HTTP_X_FORWARDED_HOST": "other.example",
            "HTTP_X_FORWARDED_PORT": "80",
        },
        True,
        id="forwarded-ignored",
    ),
    pytest.param(
        {"HTTPS": None, "REQUEST_SCHEME": "http", "HTTP_X_FORWARDED_PROTO": "https"},
        False,
        id="forwarded-cannot-enable-tls",
    ),
    pytest.param(
        {
            "HTTP_HOST": "public.example:8443",
            "HTTP_ORIGIN": "https://public.example:8443",
            "SERVER_PORT": "80",
            "HTTP_X_FORWARDED_PROTO": "http",
        },
        True,
        id="trusted-proxy-cgi-metadata",
    ),
    pytest.param(
        {
            "HTTPS": "off",
            "REQUEST_SCHEME": "http",
            "HTTP_HOST": "loxberry.example:443",
            "HTTP_ORIGIN": "http://loxberry.example:443",
        },
        True,
        id="port-does-not-imply-tls",
    ),
]
for invalid in (
    "",
    "https://loxberry.example/",
    "https://loxberry.example/path",
    "https://loxberry.example?x=1",
    "https://loxberry.example#x",
    "https://user@loxberry.example",
    "https://loxberry.example https://other.example",
    "https://loxberry.example,https://other.example",
    "https://loxberry.example\n",
    "https://loxberry.example\r",
    "https://loxberry.example\t",
    " https://loxberry.example",
    "https://loxberry.example:0",
    "https://loxberry.example:65536",
    "https://loxberry.example:",
    "https://loxberry.example:+443",
    "https://[::1",
    "https://[fe80::1%eth0]",
    "https://2001:db8::1",
):
    CASES.append(pytest.param({"HTTP_ORIGIN": invalid}, False, id=f"invalid-origin-{invalid!r}"))
for invalid in (
    "",
    "loxberry.example\n",
    "loxberry.example/",
    "user@loxberry.example",
    "loxberry.example:0",
    "loxberry.example:65536",
    "loxberry.example:",
    "-loxberry.example",
    "loxberry..example",
    "loxberry_example",
    "999.1.1.1",
    "127.1",
    "[::gg]",
    "[fe80::1%eth0]",
    "2001:db8::1",
    "a" * 64 + ".example",
):
    CASES.append(
        pytest.param(
            {"HTTP_HOST": invalid, "HTTP_ORIGIN": f"https://{invalid}"},
            False,
            id=f"invalid-host-{invalid!r}",
        )
    )


def _request(overrides: dict[str, str | None]) -> dict[str, str]:
    return {key: value for key, value in (BASE | overrides).items() if value is not None}


def _environment() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("HTTP_")
        and key not in {"HTTPS", "REQUEST_SCHEME", "REQUEST_METHOD", "QUERY_STRING", "SERVER_PORT"}
    }


@pytest.mark.parametrize(("overrides", "allowed"), CASES)
def test_origin_tuple(overrides: dict[str, str | None], allowed: bool) -> None:
    perl = shutil.which("perl")
    if perl is None:
        pytest.skip("Perl is required")
    result = subprocess.run(
        [
            perl,
            f"-I{ROOT / 'bin/lib'}",
            "-MMCPServer::RequestSecurity",
            "-MJSON::PP",
            "-e",
            "local $/; my $request = decode_json(<STDIN>); "
            "print MCPServer::RequestSecurity::same_origin_post($request);",
        ],
        input=json.dumps(_request(overrides)),
        text=True,
        capture_output=True,
        check=True,
        env=_environment(),
    )
    assert result.stdout == ("1" if allowed else "0"), result.stderr


@pytest.mark.skipif(os.name == "nt", reason="CGI executable-helper integration requires Linux")
@pytest.mark.parametrize("endpoint", ("index.cgi", "event_history.cgi"))
@pytest.mark.parametrize(("overrides", "allowed"), CASES)
def test_cgi_guard_before_helper(
    tmp_path: Path, endpoint: str, overrides: dict[str, str | None], allowed: bool
) -> None:
    perl = shutil.which("perl")
    if perl is None:
        pytest.skip("Perl is required")
    module = tmp_path / "lib/MCPServer/RequestSecurity.pm"
    module.parent.mkdir(parents=True)
    shutil.copyfile(MODULE, module)
    helper = tmp_path / "mcpserver-admin"
    marker = tmp_path / "helper-called"
    helper.write_text(
        "#!/usr/bin/env perl\nuse strict; use warnings;\n"
        "my $request = <STDIN>;\n"
        "open my $marker, '>', $ENV{LB_TEST_HELPER_MARKER} or die 'Marker unavailable';\n"
        "print {$marker} 'called'; close $marker;\n"
        'print q({"ok":true,"data":{}});\n',
        encoding="utf-8",
    )
    helper.chmod(0o755)
    action = "get_config" if endpoint == "index.cgi" else "event_history_local_overview"
    body = f"action={action}&ajax=1"
    command = [
        perl,
        f"-I{ROOT / 'tests/perl_stubs'}",
        str(ROOT / "webfrontend/htmlauth" / endpoint),
    ]
    if "REQUEST_METHOD" not in _request(overrides):
        # CGI's offline mode reads command-line parameters instead of QUERY_STRING.
        # Keep the method absent while still exercising an actual action guard.
        command.extend((f"action={action}", "ajax=1"))
    result = subprocess.run(
        command,
        input=body,
        text=True,
        capture_output=True,
        check=True,
        env={
            **_environment(),
            **_request(overrides),
            "CONTENT_TYPE": "application/x-www-form-urlencoded",
            "CONTENT_LENGTH": str(len(body)),
            "LB_TEST_HOME": str(tmp_path),
            "LB_TEST_CONFIG_DIR": str(tmp_path),
            "LB_TEST_DATA_DIR": str(tmp_path),
            "LB_TEST_BIN_DIR": str(tmp_path),
            "LB_TEST_TEMPLATE_DIR": str(tmp_path),
            "LB_TEST_LOG_DIR": str(tmp_path),
            "LB_TEST_HELPER_MARKER": str(marker),
            # CGI reads query parameters for GET; retain the requested action so
            # the method guard is actually exercised instead of rendering a page.
            "QUERY_STRING": body if _request(overrides).get("REQUEST_METHOD") != "POST" else "",
        },
    )
    headers, payload = result.stdout.replace("\r\n", "\n").split("\n\n", 1)
    data = json.loads(payload)
    assert data["ok"] is allowed
    assert marker.exists() is allowed
    assert "cache-control: no-store" in headers.lower()
    assert "x-frame-options: deny" in headers.lower()
    assert "content-security-policy:" in headers.lower()
    if not allowed:
        assert "status: 403" in headers.lower()
        assert data["error"]["code"] == "forbidden"
