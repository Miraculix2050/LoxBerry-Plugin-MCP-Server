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


def test_explorer_requires_and_links_to_the_canonical_https_origin() -> None:
    resource = "https://loxberry.example/plugins/mcpserver/mcp"

    assert (
        run_core(f"core.canonicalExplorerUrl({json.dumps(resource)},'https://loxberry.example')")
        == ""
    )
    assert (
        run_core(f"core.canonicalExplorerUrl({json.dumps(resource)},'http://loxberry.example')")
        == "https://loxberry.example/admin/plugins/mcpserver/explorer.cgi"
    )
    assert (
        run_core(f"core.canonicalExplorerUrl({json.dumps(resource)},'https://loxberry-alias',true)")
        == ""
    )
    assert (
        run_core(
            "core.canonicalExplorerUrl('http://loxberry.example/plugins/mcpserver/mcp',"
            "'http://loxberry.example')"
        )
        is None
    )
    assert (
        run_core(
            "core.httpsExplorerUrl('http://192.0.2.10/admin/plugins/mcpserver/explorer.cgi?lang=de')"
        )
        == "https://192.0.2.10/admin/plugins/mcpserver/explorer.cgi?lang=de"
    )
    assert (
        run_core(
            "core.httpsExplorerUrl('https://loxberry.example/admin/plugins/mcpserver/explorer.cgi')"
        )
        is None
    )


def test_explorer_uses_current_https_origin_for_validated_oauth_endpoints() -> None:
    metadata = {
        "issuer": "https://192.0.2.10/plugins/mcpserver/oauth",
        "authorization_endpoint": "https://192.0.2.10/plugins/mcpserver/oauth/authorize",
        "token_endpoint": "https://192.0.2.10/plugins/mcpserver/oauth/token",
        "registration_endpoint": "https://192.0.2.10/plugins/mcpserver/oauth/register",
        "revocation_endpoint": "https://192.0.2.10/plugins/mcpserver/oauth/revoke",
    }

    assert run_core(
        f"core.localAuthorizationMetadata({json.dumps(metadata)},'https://loxberry-test')"
    ) == {
        "authorization_endpoint": "https://loxberry-test/plugins/mcpserver/oauth/authorize",
        "token_endpoint": "https://loxberry-test/plugins/mcpserver/oauth/token",
        "registration_endpoint": "https://loxberry-test/plugins/mcpserver/oauth/register",
        "revocation_endpoint": "https://loxberry-test/plugins/mcpserver/oauth/revoke",
    }
    tampered = dict(metadata)
    tampered["token_endpoint"] = "https://other.example/token"
    assert (
        run_core(f"core.localAuthorizationMetadata({json.dumps(tampered)},'https://loxberry-test')")
        is None
    )
    assert (
        run_core(f"core.localAuthorizationMetadata({json.dumps(metadata)},'http://loxberry-test')")
        is None
    )
    assert (
        run_core(
            "core.canonicalExplorerUrl('https://loxberry.example/another-path',"
            "'https://loxberry.example')"
        )
        is None
    )


def test_explorer_blocks_insecure_origins_before_oauth_discovery() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    discover_start = source.index("async function discover()")
    discover = source[
        discover_start : source.index("async function registerClient", discover_start)
    ]

    assert "if (window.location.protocol !== 'https:')" in discover
    assert "error.canonicalUrl = core.httpsExplorerUrl(window.location.href);" in discover
    assert discover.index("window.location.protocol") < discover.index("fetchJson(")


def test_explorer_opens_oauth_popup_synchronously_only_for_https() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    handler_start = source.index("elements.connect.addEventListener('click'")
    handler = source[
        handler_start : source.index("elements.disconnect.addEventListener", handler_start)
    ]

    assert "const insecureOrigin = window.location.protocol !== 'https:';" in handler
    assert "const authorizationPopup = insecureOrigin ? null : openAuthorizationPopup();" in handler
    assert handler.index("openAuthorizationPopup()") < handler.index("setBusy(true)")
    assert "state.oauth = await authorize(authorizationPopup);" in handler
    assert "authorizationPopup?.close()" in handler


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


def test_explorer_prioritizes_next_cursor_for_the_same_tool() -> None:
    tools = [
        {
            "name": "other",
            "inputSchema": {
                "type": "object",
                "properties": {"query": {"type": "string"}, "cursor": {"type": "string"}},
            },
        },
        {
            "name": "paged",
            "inputSchema": {
                "type": "object",
                "properties": {"query": {"type": "string"}, "cursor": {"type": "string"}},
            },
        },
    ]

    targets = run_core(
        f"core.compatibleTargets({json.dumps(tools)},'opaque',"
        "{sourcePath:['data','next_cursor'],sourceTool:'paged'})"
    )

    assert targets[0] == {"tool": "paged", "field": "cursor"}
    assert targets[1] == {"tool": "other", "field": "cursor"}


def test_explorer_cursor_transfer_and_next_page_preserve_previous_filters() -> None:
    tool = {
        "name": "paged",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": ["string", "null"], "default": None},
                "cursor": {"type": ["string", "null"], "default": None},
                "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 100},
            },
            "additionalProperties": False,
        },
    }
    context = {"tool": "paged", "arguments": {"query": "light", "limit": 25}}
    encoded_tool = json.dumps(tool)
    encoded_context = json.dumps(context)

    assert run_core(
        f"core.transferArguments({encoded_tool},'cursor','opaque','direct',{encoded_context})"
    ) == {"query": "light", "limit": 25, "cursor": "opaque"}
    context_with_cursor = {
        "tool": "paged",
        "arguments": {"query": "light", "limit": 25, "cursor": "old"},
    }
    assert run_core(
        f"core.transferArguments({encoded_tool},'query','new','direct',"
        f"{json.dumps(context_with_cursor)})"
    ) == {"query": "new", "limit": 25}
    assert run_core(
        f"core.nextPageArguments({encoded_tool},{json.dumps(context['arguments'])},"
        "{data:{next_cursor:'opaque'}})"
    ) == {"query": "light", "limit": 25, "cursor": "opaque"}
    assert (
        run_core(
            f"core.nextPageArguments({encoded_tool},{json.dumps(context['arguments'])},"
            "{data:{next_cursor:null}})"
        )
        is None
    )


def test_explorer_transfer_uses_the_target_tool_draft_and_invalidates_cursor() -> None:
    tool = {
        "name": "statistics",
        "inputSchema": {
            "type": "object",
            "properties": {"control_uuid": {"type": "string"}, "cursor": {"type": "string"}},
        },
    }
    assert run_core(
        f"core.transferArguments({json.dumps(tool)},'control_uuid','new','direct',null,"
        "{series_id:'series',cursor:'old'})"
    ) == {"control_uuid": "new", "series_id": "series"}


def test_explorer_sorts_tools_and_prepares_statistics_transfer() -> None:
    tools = [
        {
            "name": "loxberry_clear_statistics_cache",
            "annotations": {"readOnlyHint": False, "destructiveHint": False},
        },
        {
            "name": "loxone_operate_control",
            "annotations": {"readOnlyHint": False, "destructiveHint": False},
        },
        {
            "name": "loxone_get_statistics",
            "annotations": {"readOnlyHint": True, "destructiveHint": False},
        },
        {
            "name": "loxone_describe_control",
            "annotations": {"readOnlyHint": True, "destructiveHint": False},
        },
        {
            "name": "loxberry_get_system_status",
            "annotations": {"readOnlyHint": True, "destructiveHint": False},
        },
    ]
    groups = run_core(f"core.sortedToolGroups({json.dumps(tools)})")
    assert [group["id"] for group in groups] == [
        "loxoneRead",
        "loxoneHistory",
        "loxoneControl",
        "loxberryRead",
        "loxberryOperate",
    ]
    assert [tool["name"] for tool in groups[0]["tools"]] == [
        "loxone_describe_control",
    ]
    assert [tool["name"] for tool in groups[1]["tools"]] == ["loxone_get_statistics"]
    assert [tool["name"] for tool in groups[3]["tools"]] == ["loxberry_get_system_status"]
    assert [tool["name"] for tool in groups[4]["tools"]] == ["loxberry_clear_statistics_cache"]

    result = {
        "data": {"uuid": "control", "capabilities": {"statistics": [{"series_id": "series"}]}}
    }
    assert run_core(
        "core.statisticsTransfer('loxone_describe_control',"
        f"{json.dumps(result)},['data','capabilities','statistics',0],{{series_id:'series'}},0)"
    ) == {
        "tool": "loxone_get_statistics",
        "arguments": {
            "control_uuid": "control",
            "series_id": "series",
            "start": "1969-12-31T00:00:00.000Z",
            "end": "1970-01-01T00:00:00.000Z",
            "granularity": "raw",
        },
    }


def test_explorer_converts_datetime_local_values_to_rfc3339() -> None:
    converted = run_core("core.dateTimeLocalToRfc3339('2026-08-12T12:34')")
    assert isinstance(converted, str) and converted.endswith("Z")
    assert run_core(f"core.rfc3339ToDateTimeLocal({json.dumps(converted)})") == "2026-08-12T12:34"


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
        "lastResultContext": None,
        "nextPageRequest": None,
        "transferPath": "",
        "transferRecipe": None,
        "drafts": {},
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


def test_session_clear_prevents_call_artifacts_from_being_recreated() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "error.sessionCleared = true" in source
    assert "!(error && error.sessionCleared === true)" in source
    assert "sessionCleared = Boolean(error && error.sessionCleared === true)" in source
    assert source.count("if (!sessionCleared) {") >= 2


def test_explorer_resume_record_contains_only_valid_tab_scoped_refresh_data() -> None:
    token = "a" * 43
    resource = "https://local/plugins/mcpserver/mcp"
    oauth = {
        "metadata": {"token_endpoint": "https://local/token"},
        "clientId": token,
        "sessionId": token,
        "scope": "loxone:read",
        "accessToken": "must-not-be-stored",
        "refreshToken": token,
        "resource": resource,
        "expiresAt": 123,
        "resumeUntil": 1_000_000,
    }
    record = run_core(f"core.resumableSession({json.dumps(oauth)})")

    assert record == {
        "version": 1,
        "sessionId": token,
        "clientId": token,
        "scope": "loxone:read",
        "refreshToken": token,
        "resource": resource,
        "resumeUntil": 1_000_000,
    }
    encoded = json.dumps(record)
    assert (
        run_core(f"core.validateResumableSession({encoded},{json.dumps(resource)},999999)")
        == record
    )
    assert (
        run_core(f"core.validateResumableSession({encoded},{json.dumps(resource)},1000000)") is None
    )
    assert (
        run_core(
            f"core.validateResumableSession({encoded},'https://other/plugins/mcpserver/mcp',999999)"
        )
        is None
    )


def test_explorer_client_registration_is_tab_scoped_and_expires_before_server_cleanup() -> None:
    client_id = "a" * 43
    registered_at = 1_000_000
    record = run_core(f"core.clientRegistration('{client_id}',{registered_at})")

    assert record == {"version": 2, "clientId": client_id, "registeredAt": registered_at}
    encoded = json.dumps(record)
    assert run_core(f"core.validateClientRegistration({encoded},{registered_at})") == record
    assert (
        run_core(
            f"core.validateClientRegistration({encoded},"
            f"{registered_at}+core.EXPLORER_CLIENT_REGISTRATION_MS-1)"
        )
        == record
    )
    assert (
        run_core(
            f"core.validateClientRegistration({encoded},"
            f"{registered_at}+core.EXPLORER_CLIENT_REGISTRATION_MS)"
        )
        is None
    )
    assert (
        run_core(
            f"core.validateClientRegistration("
            f"{json.dumps({'version': 2, 'clientId': 'invalid', 'registeredAt': registered_at})},"
            f"{registered_at})"
        )
        is None
    )
    assert (
        run_core(
            f"core.validateClientRegistration("
            f"{json.dumps({'version': 1, 'clientId': client_id, 'registeredAt': registered_at})},"
            f"{registered_at})"
        )
        is None
    )


@pytest.mark.parametrize("exchange_fails", [False, True])
def test_explorer_refresh_removes_replayable_state_before_rotation(
    exchange_fails: bool,
) -> None:
    exchange = (
        "async()=>{events.push('exchange');throw new Error('offline')}"
        if exchange_fails
        else "async()=>{events.push('exchange');return {access_token:'new-access',"
        "refresh_token:'new-refresh',expires_in:600,scope:'loxone:read'}}"
    )
    expression = f"""(async()=>{{
      const events=[];
      const oauth={{resumeEnabled:true,clientId:'client',refreshToken:'old-refresh',
        resource:'https://local/mcp',scope:'loxone:read'}};
      try {{
        const saved=await core.rotateRefreshToken(oauth,{exchange},
          ()=>events.push('clear'),()=>{{events.push('save');return true}},1000);
        return {{events,saved,refreshToken:oauth.refreshToken}};
      }} catch (_error) {{ return {{events,refreshToken:oauth.refreshToken}}; }}
    }})()"""

    actual = run_core_async(expression)
    if exchange_fails:
        assert actual == {"events": ["clear", "exchange"], "refreshToken": "old-refresh"}
    else:
        assert actual == {
            "events": ["clear", "exchange", "save"],
            "saved": True,
            "refreshToken": "new-refresh",
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


def test_explorer_transcript_is_incremental_and_details_are_lazy() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    add_transcript = source[
        source.index("function addTranscript") : source.index("function safeMcpResponse")
    ]
    transcript_entry = source[
        source.index("function transcriptEntry") : source.index("function renderTranscript")
    ]

    assert "renderTranscript()" not in add_transcript
    assert "elements.transcript.append(transcriptEntry(entry))" in add_transcript
    assert "firstElementChild?.remove()" in add_transcript
    assert "details.addEventListener('toggle'" in transcript_entry
    assert "{once: true}" in transcript_entry


def test_explorer_tabs_support_roving_focus_and_arrow_keys() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "elements.formTab.tabIndex = jsonMode ? -1 : 0" in source
    assert "elements.jsonTab.tabIndex = jsonMode ? 0 : -1" in source
    assert "if (event.key === 'ArrowLeft')" in source
    assert "if (event.key === 'ArrowRight')" in source
    assert "if (event.key === 'Home')" in source
    assert "if (event.key === 'End')" in source
    assert "elements.formTab.addEventListener('keydown', handleTabKey)" in source
    assert "elements.jsonTab.addEventListener('keydown', handleTabKey)" in source


def test_explorer_scope_validation_accepts_independent_canonical_choices() -> None:
    assert run_core("core.validExplorerScope('loxone:read')") is True
    assert run_core("core.validExplorerScope('loxone:read loxone:control loxberry:read')") is True
    assert (
        run_core("core.validExplorerScope('loxone:read loxone:history loxberry:operate')") is True
    )
    assert run_core("core.validExplorerScope('loxone:read loxberry:operate')") is False
    assert run_core("core.validExplorerScope('loxone:read loxberry:read loxone:control')") is False


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
    assert "core.localAuthorizationMetadata(" in source
    assert "trustedLocalAlias && pageOrigin.protocol === 'https:'" in source
    assert "issuerUrl.origin !== resourceUrl.origin" in source
    assert "code_challenge_method: 'S256'" in source
    assert "width=680,height=900,resizable=yes,scrollbars=yes" in source
    assert "core.rotateRefreshToken(" in source
    assert "if (state.oauth) await revokeAndClear()" in source
    assert "core.toolIsMutating(state.selectedTool)" in source
    assert "state.history.length > core.MAX_CALL_HISTORY" in source
    assert "fetchWithTimeout('/plugins/mcpserver/mcp'" in source
    assert "}, 70000)" in source
    assert "localStorage.setItem" not in source
    assert "window.localStorage.removeItem(key)" in source
    assert "core.validateClientRegistration" in source
    assert "JSON.stringify(core.clientRegistration(clientId, Date.now()))" in source
    assert "sessionStorage.setItem" in source
    assert "core.validateResumableSession" in source
    assert "readStoredSession(discovered.resourceMetadata.resource)" in source
    assert "navigator.locks.request" in source
    assert "ifAvailable: true" in source
    assert "await refreshAccessToken();" in source
    assert "window.addEventListener('pagehide'" not in source
    assert "navigator.sendBeacon" not in source
    assert 'target="_blank"' in (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    index_template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    index_cgi = (ROOT / "webfrontend" / "htmlauth" / "index.cgi").read_text(encoding="utf-8")
    assert 'id="explorer-link"' in index_template
    assert 'href="<TMPL_VAR EXPLORER_URL ESCAPE=HTML>"' in index_template
    assert "explorerLink.href = `${window.location.origin}${explorerPath}`" in index_template
    assert "EXPLORER_URL => 'explorer.cgi'" in index_cgi
    assert "savedOrigin" not in index_template
    assert "@media (max-width: 52rem)" in template
    assert ":focus-visible" in template
    assert "<dialog" in template
    assert 'id="explorer-confirm-tool"' in template
    assert 'id="explorer-next-page"' in template
    assert 'id="explorer-history-arguments"' in template
    assert "data-tool-group-loxone-history=" in template
    assert 'data-help-control-type="<TMPL_VAR EXPLORER.HELP_CONTROL_TYPE ESCAPE=HTML>"' in template
    assert "const description = helpKey ? label(helpKey) : effective.description" in source
    assert 'id="explorer-access-scopes"' not in template
    assert 'id="explorer-scope-' not in template
    assert "<TMPL_VAR EXPLORER.PERMISSIONS_AFTER_LOGIN>" in template
    assert 'id="explorer-origin-warning"' in template
    assert 'id="explorer-origin-link"' in template
    assert "const canonicalUrl = core.canonicalExplorerUrl(" in source
    assert "showConnectionError(_error, label('error'))" in source
    assert "if (canonicalOriginMismatch && stored) clearStoredSession()" in source
    assert 'id="explorer-session-expiry" hidden' in template
    assert "const scope = core.EXPLORER_SCOPE_ORDER.filter" in source
    assert "const registrationScope = scope" in source
    assert "supported.delete('loxberry:operate')" in source
    assert "state.selectedTool.name === 'loxberry_clear_statistics_cache'" in source
    assert "elements.historyArguments.hidden = !historySource" in source
    assert "function clientStorageKey()" in source
    assert "Cache_Control => 'no-store'" in callback
    assert "frame-ancestors 'none'" in callback
    assert "window.history.replaceState" in callback


def test_explorer_initial_discovery_has_no_pre_login_permission_choice() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    initial_discovery = source[
        source.index("(async () => {", source.index("selectTab(false, false);")) : source.index(
            "stored = readStoredSession"
        )
    ]

    assert "setScopeAvailability" not in initial_discovery
    assert "scopeHistory" not in initial_discovery


def test_session_refresh_preserves_pending_loxberry_approval_action() -> None:
    source = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")

    assert "session.loxberry_read_eligible && !session.loxberry_read_approved" in source
    assert "allowForm.dataset.ajax = 'allow_loxberry_read'" in source
    assert "Boolean(session.loxberry_read_eligible)" in source


def test_session_refresh_updates_related_loxberry_bindings() -> None:
    source = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")

    assert 'id="loxberry-binding-list"' in source
    assert "const updateLoxberryBindings = (bindings) =>" in source
    assert "const updateLoxberryBindingTable = (bindings, section, body, actionName) =>" in source
    assert "result.data.loxberry_bindings" in source
    assert "bindingRow.client_name" in source
    assert "bindingRow.identity" in source
    assert "bindingRow.fingerprint" in source


def test_session_refresh_updates_separate_loxberry_operate_bindings() -> None:
    source = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")

    assert 'id="loxberry-operate-binding-list"' in source
    assert "const updateLoxberryOperateBindings = (bindings) =>" in source
    assert "result.data.loxberry_operate_bindings" in source
    assert "bindingRow.inactive" in source
    assert "session.loxberry_operate_eligible && !session.loxberry_operate_approved" in source


def test_explorer_uses_csp_compatible_panel_free_loxberry_header() -> None:
    cgi = (ROOT / "webfrontend" / "htmlauth" / "explorer.cgi").read_text(encoding="utf-8")
    template = (ROOT / "templates" / "explorer.html").read_text(encoding="utf-8")

    assert "lbheader($L{'EXPLORER.TITLE'} . \" V$version\", 'nopanels'" in cgi
    assert "'unsafe-eval'" not in cgi
    assert '<a class="lb-button" href="index.cgi"><TMPL_VAR EXPLORER.BACK></a>' in template


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
