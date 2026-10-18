import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(os.name != "posix", reason="native CGI pipe handling requires POSIX")
@pytest.mark.parametrize("stderr_bytes,expected", [(7000, "200000 7000"), (9000, "limited")])
def test_knx_helper_drains_both_pipes_and_bounds_diagnostics(stderr_bytes, expected):
    source = (ROOT / "webfrontend/htmlauth/knx.cgi").read_text(encoding="utf-8")
    reader = re.search(r"sub read_helper_pipes \{.*?^\}", source, re.MULTILINE | re.DOTALL)
    assert reader is not None
    perl = shutil.which("perl")
    assert perl is not None
    script = r"""
use strict;
use warnings;
use IO::Select;
use IPC::Open3;
use Symbol qw(gensym);
READER
my ($input, $output);
my $error = gensym;
my $pid = open3($input, $output, $error, $^X, '-e',
    'print STDERR "e" x COUNT; print STDOUT "o" x 200000;');
close $input;
alarm 5;
my @result = eval { read_helper_pipes($output, $error) };
if ($@) { kill 'KILL', $pid; print "limited"; }
else { print length($result[0]) . " " . length($result[1]); }
waitpid($pid, 0);
alarm 0;
""".replace("READER", reader[0]).replace("COUNT", str(stderr_bytes))
    result = subprocess.run(
        [perl, "-e", script], capture_output=True, text=True, timeout=10, check=True
    )
    assert result.stdout == expected


def test_knx_timing_is_numeric_allowlisted_and_separate_from_response_data():
    source = (ROOT / "webfrontend/htmlauth/knx.cgi").read_text(encoding="utf-8")
    assert source.index("BEGIN { $knx_compile_started") < source.index("use CGI;")
    assert "my %allowed = map" in source
    assert "-Server_Timing" in source
    assert "mcpserver_admin_timing=" in source
    assert "print $response_json" in source


@pytest.mark.parametrize("mode", ["fallback", "accelerated", "failed_accelerator", "unavailable"])
def test_helper_decoder_preserves_original_json_validation_and_values(mode):
    perl = shutil.which("perl")
    assert perl is not None
    if (
        mode == "accelerated"
        and subprocess.run([perl, "-MJSON::XS", "-e", "1"], capture_output=True).returncode
    ):
        pytest.skip("optional JSON::XS accelerator is not installed")
    source = (ROOT / "webfrontend/htmlauth/knx.cgi").read_text(encoding="utf-8")
    decoder = re.search(r"sub decode_helper_json \{.*?^\}", source, re.MULTILINE | re.DOTALL)[0]
    setup = {
        "fallback": "my $knx_fast_json;",
        "accelerated": "require JSON::XS; my $knx_fast_json = JSON::XS->new->utf8->max_depth(512);",
        "failed_accelerator": (
            "{package Broken; sub decode {die 'synthetic';}} "
            "my $knx_fast_json = bless {}, 'Broken';"
        ),
        "unavailable": (
            "my $knx_fast_json; "
            "unshift @INC, sub {die 'unavailable' if $_[1] eq 'JSON/XS.pm'; return;};"
        ),
    }[mode]
    setup += " my $knx_decoder_initialized = " + ("0;" if mode == "unavailable" else "1;")
    script = (
        "use JSON::PP qw(decode_json encode_json);\n"
        + setup
        + "\n"
        + decoder
        + r"""
local $/; my $inputs = decode_json(<STDIN>); my @results;
my $canonical = JSON::PP->new->canonical->allow_nonref;
for my $raw (@$inputs) {
    my ($old, $new, $old_ok, $new_ok);
    $old_ok = eval { $old = decode_json($raw); 1 } ? 1 : 0;
    $new_ok = eval { $new = decode_helper_json($raw); 1 } ? 1 : 0;
    my $same_value = !$old_ok || $canonical->encode($old) eq $canonical->encode($new);
    push @results, ($old_ok == $new_ok && $same_value) ? 1 : 0;
}
print encode_json(\@results);
"""
    )
    inputs = [
        json.dumps(
            {
                "ok": True,
                "data": {
                    "flag": False,
                    "none": None,
                    "values": [0, -1, 65535, 1.25],
                    "text": 'ä\n\t"\\',
                },
            }
        ),
        '{"text":"\\ud800"}',
        '{"x":1,"x":2}',
        "null",
        "42",
        '{"ok":true} trailing',
        '{"n":01}',
        '{"s":"\\uZZZZ"}',
        "",
        "{",
        '{"ok":true,"text":"ä"}',
        "[" * 520 + "0" + "]" * 520,
    ]
    result = subprocess.run(
        [perl, "-e", script],
        input=json.dumps(inputs),
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )
    assert json.loads(result.stdout) == [1] * len(inputs)


@pytest.mark.parametrize("fail", [False, True])
def test_helper_timing_never_includes_request_or_credentials(monkeypatch, fail):
    import io
    from types import SimpleNamespace

    from mcpserver import admin

    request = {"action": "knx_project_page", "payload": {"fixture": "private-request-fixture"}}
    stdout, stderr = io.StringIO(), io.StringIO()
    monkeypatch.setattr(
        admin.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(json.dumps(request).encode()))
    )
    monkeypatch.setattr(admin.sys, "stdout", stdout)
    monkeypatch.setattr(admin.sys, "stderr", stderr)
    monkeypatch.setenv("HTTP_X_LOXONE_AUTHORIZATION", "Bearer private-credential-fixture")
    monkeypatch.setenv(
        "MCPSERVER_ADMIN_STARTED_NS", str(admin._MODULE_IMPORT_STARTED_NS - 1_000_000)
    )

    def dispatch(value, *, timing):
        assert value == request
        timing["forward_config_ms"] = 1.25
        if fail:
            raise admin.AdminError("Synthetic rejection", code="synthetic_rejection")
        return {"fixture": "public-result"}

    monkeypatch.setattr(admin, "dispatch", dispatch)
    admin.main()
    response = json.loads(stdout.getvalue())
    assert response["ok"] is not fail
    assert "timing" not in response
    diagnostic = stderr.getvalue()
    assert len(diagnostic.encode()) < 4096
    assert "private-request-fixture" not in diagnostic
    assert "private-credential-fixture" not in diagnostic
    metrics = json.loads(diagnostic.removeprefix("mcpserver_admin_timing="))
    assert metrics["forward_config_ms"] == 1.25
    assert all(isinstance(value, int | float) and value >= 0 for value in metrics.values())
