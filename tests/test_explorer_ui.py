from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "webfrontend" / "htmlauth" / "explorer.js"


def run_core(expression: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for explorer JavaScript tests")
    program = (
        f"const core=require({json.dumps(str(SCRIPT))}); console.log(JSON.stringify({expression}));"
    )
    result = subprocess.run([node, "-e", program], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def run_core_async(expression: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for explorer JavaScript tests")
    program = (
        f"const core=require({json.dumps(str(SCRIPT))});"
        f"(async()=>console.log(JSON.stringify(await ({expression}))))()"
        ".catch(error=>{console.error(error);process.exit(1);});"
    )
    result = subprocess.run([node, "-e", program], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def test_explorer_defaults_and_validation_follow_tool_schema() -> None:
    schema = {
        "type": "object",
        "properties": {
            "query": {"type": ["string", "null"], "default": None},
            "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 100},
            "state_uuids": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 100,
            },
        },
        "required": ["state_uuids"],
        "additionalProperties": False,
    }
    encoded = json.dumps(schema)

    assert run_core(f"core.defaultArguments({encoded})") == {
        "limit": 50,
        "state_uuids": [],
    }
    errors = run_core(
        f"core.validateArguments({{query:null,limit:101,state_uuids:[],extra:true}},{encoded})"
    )
    assert any("above maximum" in error for error in errors)
    assert any("too few items" in error for error in errors)
    assert any("unknown" in error for error in errors)


def test_explorer_reuses_only_schema_compatible_values() -> None:
    tools = [
        {
            "name": "describe",
            "inputSchema": {
                "type": "object",
                "properties": {"control_uuid": {"type": "string"}},
            },
        },
        {
            "name": "states",
            "inputSchema": {
                "type": "object",
                "properties": {"state_uuids": {"type": "array", "items": {"type": "string"}}},
            },
        },
    ]

    assert run_core(f"core.compatibleTargets({json.dumps(tools)},'uuid-value')") == [
        {"tool": "describe", "field": "control_uuid"},
        {"tool": "states", "field": "state_uuids", "mode": "wrap-array"},
    ]
    assert run_core(f"core.compatibleTargets({json.dumps(tools)},['one','two'])") == [
        {"tool": "states", "field": "state_uuids"}
    ]
    assert run_core("core.valueForTransfer('uuid-value','wrap-array')") == ["uuid-value"]
    assert run_core("core.valueForTransfer(['one'],'direct')") == ["one"]


def test_explorer_reuse_honours_full_nested_schema() -> None:
    tools = [
        {
            "name": "strict",
            "inputSchema": {
                "type": "object",
                "$defs": {"code": {"type": "string", "pattern": "^[A-Z]{3}$"}},
                "properties": {
                    "code": {"$ref": "#/$defs/code"},
                    "items": {
                        "type": "array",
                        "minItems": 2,
                        "items": {"type": "integer", "minimum": 1},
                    },
                    "record": {
                        "type": "object",
                        "required": ["id"],
                        "properties": {"id": {"type": "string", "minLength": 2}},
                        "additionalProperties": False,
                    },
                },
            },
        }
    ]
    encoded = json.dumps(tools)

    assert run_core(f"core.compatibleTargets({encoded},'ABC')") == [
        {"tool": "strict", "field": "code"}
    ]
    assert run_core(f"core.compatibleTargets({encoded},'ab')") == []
    assert run_core(f"core.compatibleTargets({encoded},[1,2])") == [
        {"tool": "strict", "field": "items"}
    ]
    assert run_core(f"core.compatibleTargets({encoded},[0])") == []
    assert run_core(f"core.compatibleTargets({encoded},{{id:'ok'}})") == [
        {"tool": "strict", "field": "record"}
    ]
    assert run_core(f"core.compatibleTargets({encoded},{{}})") == []


def test_explorer_nullable_and_variant_validation() -> None:
    assert run_core("core.valueMatchesSchema(null,{type:['string','null']},{})") is True
    assert (
        run_core("core.valueMatchesSchema(null,{anyOf:[{type:'string'},{type:'null'}]},{})") is True
    )
    assert (
        run_core(
            "core.validateValue('AB',{anyOf:[{type:'string',pattern:'^[A-Z]{3}$'},{type:'integer'}]},{}).length"
        )
        == 1
    )
    assert (
        run_core(
            "core.validateValue('ABC',{anyOf:[{type:'string',pattern:'^[A-Z]{3}$'},{type:'integer'}]},{}).length"
        )
        == 0
    )


def test_explorer_reuse_fails_closed_for_unsupported_schemas() -> None:
    properties = {
        "anything": {},
        "fixed": {"type": ["string", "null"], "enum": ["allowed"]},
        "constant": {"const": 42},
        "combined": {"allOf": [{"type": "string"}]},
        "tuple": {"type": "array", "items": [{"type": "string"}]},
        "unknown": {"type": "mystery"},
        "missing_ref": {"$ref": "#/$defs/missing"},
        "formatted": {"type": "string", "format": "uuid"},
    }
    tools = [{"name": "strict", "inputSchema": {"properties": properties}}]
    encoded = json.dumps(tools)

    assert run_core(f"core.compatibleTargets({encoded},null)") == [
        {"tool": "strict", "field": "anything"}
    ]
    assert run_core(f"core.compatibleTargets({encoded},'allowed')") == [
        {"tool": "strict", "field": "anything"},
        {"tool": "strict", "field": "fixed"},
    ]
    assert run_core(f"core.compatibleTargets({encoded},42)") == [
        {"tool": "strict", "field": "anything"},
        {"tool": "strict", "field": "constant"},
    ]
    assert run_core(f"core.compatibleTargets({encoded},['value'])") == [
        {"tool": "strict", "field": "anything"}
    ]


def test_explorer_write_classification_fails_closed() -> None:
    safe = {"annotations": {"readOnlyHint": True, "destructiveHint": False}}
    cases = [
        {},
        {"annotations": {"readOnlyHint": True}},
        {"annotations": {"destructiveHint": False}},
        {"annotations": {"readOnlyHint": False, "destructiveHint": False}},
        {"annotations": {"readOnlyHint": True, "destructiveHint": True}},
    ]

    assert run_core(f"core.toolIsMutating({json.dumps(safe)})") is False
    for tool in cases:
        assert run_core(f"core.toolIsMutating({json.dumps(tool)})") is True


def test_explorer_oauth_guards_and_resource_binding() -> None:
    assert (
        run_core(
            "core.acceptOAuthMessage('https://local','https://local',"
            "{type:'mcp-explorer-oauth',state:'expected'},'expected')"
        )
        is True
    )
    assert (
        run_core(
            "core.acceptOAuthMessage('https://other','https://local',"
            "{type:'mcp-explorer-oauth',state:'expected'},'expected')"
        )
        is False
    )
    assert (
        run_core(
            "core.acceptOAuthMessage('https://local','https://local',"
            "{type:'mcp-explorer-oauth',state:'wrong'},'expected')"
        )
        is False
    )
    assert run_core(
        "core.authorizationCodeTokenFields('client','code','https://local/callback','verifier','https://local/mcp')"
    ) == {
        "grant_type": "authorization_code",
        "client_id": "client",
        "code": "code",
        "redirect_uri": "https://local/callback",
        "code_verifier": "verifier",
        "resource": "https://local/mcp",
    }
    assert run_core("core.refreshTokenFields('client','refresh','https://local/mcp')") == {
        "grant_type": "refresh_token",
        "client_id": "client",
        "refresh_token": "refresh",
        "resource": "https://local/mcp",
    }


def test_explorer_disconnect_clears_all_in_memory_session_data() -> None:
    expression = """(() => {
      const state={oauth:{accessToken:'secret'},tools:[{}],selectedTool:{},arguments:{value:1},
        history:[{}],transcript:[{}],lastResult:{},transferValue:'value',transferPath:'$.value'};
      core.clearSensitiveState(state);
      return state;
    })()"""

    assert run_core(expression) == {
        "oauth": None,
        "tools": [],
        "selectedTool": None,
        "arguments": {},
        "history": [],
        "transcript": [],
        "lastResult": None,
        "transferPath": "",
    }


@pytest.mark.parametrize("revocation_fails", [False, True])
def test_explorer_revocation_always_clears_session(revocation_fails: bool) -> None:
    revoke = (
        "async()=>{events.push('revoke-attempt');throw new Error('offline')}"
        if revocation_fails
        else "async()=>{events.push('revoke')}"
    )
    expression = f"""(() => {{
      const events=[];
      return core.revokeThenClear({{refreshToken:'refresh'}},{revoke},()=>events.push('cleared'))
        .then(()=>events);
    }})()"""

    expected = ["revoke-attempt", "cleared"] if revocation_fails else ["revoke", "cleared"]
    assert run_core_async(expression) == expected


def test_explorer_revocation_request_uses_bounded_timeout() -> None:
    expression = """(() => {
      const seen={};
      const fetcher=async(url,options,timeout)=>Object.assign(seen,
        {url,timeout,body:options.body.toString(),keepalive:options.keepalive});
      const oauth={metadata:{revocation_endpoint:'https://local/revoke'},
        refreshToken:'refresh',clientId:'client'};
      return core.revokeOAuthGrant(fetcher,oauth,core.REVOCATION_TIMEOUT_MS).then(()=>seen);
    })()"""

    assert run_core_async(expression) == {
        "url": "https://local/revoke",
        "timeout": 5000,
        "body": "token=refresh&token_type_hint=refresh_token&client_id=client",
        "keepalive": True,
    }


def test_explorer_generated_field_ids_are_unique_and_labelled() -> None:
    assert run_core("[core.fieldControlId(0),core.fieldControlId(1)]") == [
        "explorer-field-0",
        "explorer-field-1",
    ]
    expression = """(() => {
      const documentObject={createElement:(tag)=>({tag,attributes:{},children:[],
        setAttribute(name,value){this.attributes[name]=value},append(...children){this.children.push(...children)}}),
        createTextNode:(text)=>({textContent:text})};
      const input={};
      const label=core.createFieldLabel(documentObject,'state_uuid',input,3);
      const include={};
      const optional=core.createOptionalToggle(
        documentObject,'state_uuid',include,3,'Use optional parameter');
      return {tag:label.tag,forValue:label.attributes.for,inputId:input.id,
        text:label.children[0].textContent,optionalFor:optional.attributes.for,
        optionalId:include.id,optionalText:optional.children[1].textContent};
    })()"""
    assert run_core(expression) == {
        "tag": "label",
        "forValue": "explorer-field-3",
        "inputId": "explorer-field-3",
        "text": "state_uuid",
        "optionalFor": "explorer-include-3",
        "optionalId": "explorer-include-3",
        "optionalText": " Use optional parameter: state_uuid",
    }


def test_explorer_control_option_requires_positive_discovery() -> None:
    expression = """(() => {
      const state={controlAvailable:false};
      const control={value:'control'};
      const option={disabled:false};
      const note={hidden:true};
      core.applyControlAvailability(state,control,option,note,false);
      const unavailable={state:state.controlAvailable,value:control.value,
        disabled:option.disabled,noteHidden:note.hidden};
      core.applyControlAvailability(state,control,option,note,true);
      return {unavailable,available:{state:state.controlAvailable,
        disabled:option.disabled,noteHidden:note.hidden}};
    })()"""
    assert run_core(expression) == {
        "unavailable": {
            "state": False,
            "value": "read",
            "disabled": True,
            "noteHidden": False,
        },
        "available": {"state": True, "disabled": False, "noteHidden": True},
    }


def test_explorer_redacts_secret_shaped_arguments() -> None:
    schema = {
        "type": "object",
        "properties": {
            "visible": {"type": "string"},
            "credential": {"type": "string", "format": "password"},
        },
    }
    value = {"visible": "shown", "credential": "hidden", "access_token": "hidden-too"}

    assert run_core(f"core.redactArguments({json.dumps(value)},{json.dumps(schema)})") == {
        "visible": "shown",
        "credential": "[redacted]",
        "access_token": "[redacted]",
    }


def test_explorer_ui_is_local_scoped_and_progressively_safe() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    template = (ROOT / "templates" / "explorer.html").read_text(encoding="utf-8")
    callback = (ROOT / "webfrontend" / "htmlauth" / "explorer_callback.cgi").read_text(
        encoding="utf-8"
    )

    assert "fetchWithTimeout('/plugins/mcpserver/mcp'" in source
    assert "oauth-protected-resource/plugins/mcpserver/mcp" in source
    assert "issuerUrl.origin !== window.location.origin" in source
    assert "authorizationMetadata[name] !== value" in source
    assert "code_challenge_method: 'S256'" in source
    assert "core.refreshTokenFields(state.oauth.clientId" in source
    assert "if (state.oauth) await revokeAndClear()" in source
    assert "core.toolIsMutating(state.selectedTool)" in source
    assert "state.history.length > core.MAX_CALL_HISTORY" in source
    assert "fetchWithTimeout('/plugins/mcpserver/mcp'" in source
    assert "}, 70000)" in source
    assert "localStorage.setItem" in source
    assert "/^[A-Za-z0-9_-]{43}$/" in source
    assert (
        "accessToken"
        not in source[
            source.index("localStorage.setItem") - 100 : source.index("localStorage.setItem") + 200
        ]
    )
    assert 'target="_blank"' in (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    assert "@media (max-width: 52rem)" in template
    assert ":focus-visible" in template
    assert "<dialog" in template
    assert 'id="explorer-confirm-tool"' in template
    assert 'id="explorer-access-mode"' in template
    assert '<option value="read">' in template
    assert 'id="explorer-control-option" value="control" disabled' in template
    assert "elements.control.value === 'control'" in source
    assert "Cache_Control => 'no-store'" in callback
    assert "frame-ancestors 'none'" in callback
    assert "window.history.replaceState" in callback


def test_explorer_transcript_never_records_authorization_headers() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    add_transcript = source[
        source.index("function addTranscript") : source.index("async function mcpRequest")
    ]
    request_section = source[
        source.index("async function mcpRequest") : source.index("async function initializeMcp")
    ]

    assert "headers" not in add_transcript
    assert "safeRequest" in request_section
    assert "redactArguments" in request_section
    assert "safeMcpResponse" in request_section
    assert "[omitted; structuredContent shown]" in source


def test_oauth_callback_emits_no_store_and_frame_protection() -> None:
    perl = shutil.which("perl")
    if perl is None:
        pytest.skip("Perl is required for callback header verification")
    callback = ROOT / "webfrontend" / "htmlauth" / "explorer_callback.cgi"

    result = subprocess.run([perl, str(callback)], check=True, capture_output=True, text=True)
    headers = result.stdout.split("\n\n", 1)[0].lower()

    assert "cache-control: no-store" in headers
    assert "content-security-policy:" in headers
    assert "frame-ancestors 'none'" in headers
    assert "referrer-policy: no-referrer" in headers
    assert "x-content-type-options: nosniff" in headers


def test_explorer_page_emits_no_store_and_frame_protection() -> None:
    perl = shutil.which("perl")
    if perl is None:
        pytest.skip("Perl is required for explorer header verification")
    explorer = ROOT / "webfrontend" / "htmlauth" / "explorer.cgi"

    result = subprocess.run(
        [perl, f"-I{ROOT / 'tests' / 'perl_stubs'}", str(explorer)],
        check=True,
        capture_output=True,
        text=True,
    )
    headers = result.stdout.lower()

    assert "cache-control: no-store" in headers
    assert "content-security-policy:" in headers
    assert "frame-ancestors 'none'" in headers
    assert "referrer-policy: no-referrer" in headers
    assert "x-content-type-options: nosniff" in headers
    assert "x-frame-options: deny" in headers
