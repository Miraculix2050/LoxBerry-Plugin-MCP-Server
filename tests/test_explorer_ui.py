from __future__ import annotations

import json
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from mcpserver.schema_reference import tool_schema_catalog

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "webfrontend" / "htmlauth" / "explorer.js"
ADAPTERS = ROOT / "webfrontend" / "htmlauth" / "explorer-adapters.js"
ADMIN_SCRIPTS = ROOT / "webfrontend" / "htmlauth" / "admin"


def test_help_and_explorer_link_to_static_schema_reference() -> None:
    index = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    explorer = (ROOT / "templates" / "explorer.html").read_text(encoding="utf-8")
    cgi = (ROOT / "webfrontend" / "htmlauth" / "index.cgi").read_text(encoding="utf-8")

    assert "SCHEMA_REFERENCE_URL => 'tool-schema-reference.html'" in cgi
    assert 'href="<TMPL_VAR SCHEMA_REFERENCE_URL ESCAPE=HTML>"' in index
    assert 'href="tool-schema-reference.html"' in explorer
    assert "ACTION.SCHEMA_REFERENCE" in index
    assert "ACTION.SCHEMA_REFERENCE" in explorer


def test_schema_reference_link_label_is_concise_in_both_languages() -> None:
    german = (ROOT / "templates" / "lang" / "language_de.ini").read_text(encoding="utf-8")
    english = (ROOT / "templates" / "lang" / "language_en.ini").read_text(encoding="utf-8")

    assert "SCHEMA_REFERENCE=Schema-Referenz öffnen" in german
    assert "SCHEMA_REFERENCE=Open schema reference" in english


def test_explorer_uses_one_compact_mobile_tool_panel_and_adaptive_workspace() -> None:
    template = (ROOT / "templates" / "explorer.html").read_text(encoding="utf-8")
    stylesheet = (ROOT / "webfrontend" / "htmlauth" / "mcp-ui.css").read_text(encoding="utf-8")
    source = SCRIPT.read_text(encoding="utf-8")
    responsive_panels = source[
        source.index("function syncResponsivePanels") : source.index("function showError")
    ]

    assert template.count('id="explorer-tools"') == 1
    assert template.count('id="explorer-history"') == 1
    assert '<details id="explorer-tools-panel" class="mcp-explorer-card" open>' in template
    assert '<details id="explorer-history-panel" class="mcp-explorer-card" open>' in template
    assert (
        '<details id="explorer-request" class="mcp-explorer-card" tabindex="-1" open>' in template
    )
    assert '<details id="explorer-result" class="mcp-explorer-card" tabindex="-1" open>' in template
    assert '<summary><h2 id="request-title"><TMPL_VAR EXPLORER.SELECTED_TOOL></h2>' in template
    assert '<summary><h2 id="result-title"><TMPL_VAR EXPLORER.RESULT></h2></summary>' in template
    assert '<details id="explorer-history-arguments" hidden>' in template
    assert 'class="mcp-explorer-panel-label"' in template
    assert 'id="explorer-request"' in template
    assert 'id="explorer-result"' in template
    assert "@media (min-width: 80rem)" in stylesheet
    assert "@media (max-width: 52rem)" in stylesheet
    assert "grid-template-columns: minmax(18rem, 22rem) minmax(0, 1fr)" in stylesheet
    assert "grid-template-columns: minmax(20rem, 24rem) minmax(0, 1fr)" in stylesheet
    assert "grid-template-columns: minmax(22rem, .9fr) minmax(24rem, 1.1fr)" in stylesheet
    assert "details.mcp-explorer-card > summary { padding:" in stylesheet
    assert "details.mcp-explorer-card > summary { display: flex" not in stylesheet
    assert ".mcp-explorer-panel-label { display: inline-flex" in stylesheet
    assert "const narrowViewport = window.matchMedia('(max-width: 52rem)')" in source
    assert "elements.toolsPanel.open = false" in responsive_panels
    assert "elements.historyPanel.open = false" in responsive_panels
    assert "initializeMcp" not in responsive_panels
    assert "mcpRequest" not in responsive_panels
    assert "revealRequest(true, false)" in source
    assert "revealResult();" in source


def test_tool_badges_are_localized_through_the_explorer_template() -> None:
    german = (ROOT / "templates" / "lang" / "language_de.ini").read_text(encoding="utf-8")
    english = (ROOT / "templates" / "lang" / "language_en.ini").read_text(encoding="utf-8")
    template = (ROOT / "templates" / "explorer.html").read_text(encoding="utf-8")
    source = SCRIPT.read_text(encoding="utf-8")
    render_tools = source[
        source.index("function renderTools()") : source.index("function draftFor(")
    ]

    assert "TOOL_BADGE_READ_ONLY=Nur lesen" in german
    assert "TOOL_BADGE_WRITE=Schreibzugriff" in german
    assert "TOOL_BADGE_READ_ONLY=Read only" in english
    assert "TOOL_BADGE_WRITE=Write" in english
    assert (
        'data-tool-badge-read-only="<TMPL_VAR EXPLORER.TOOL_BADGE_READ_ONLY ESCAPE=HTML>"'
        in template
    )
    assert 'data-tool-badge-write="<TMPL_VAR EXPLORER.TOOL_BADGE_WRITE ESCAPE=HTML>"' in template
    assert "core.toolMetadataLabels(tool)[0]" in render_tools
    assert "core.toolIsMutating(tool)" in render_tools
    assert "text: 'read-only'" not in render_tools
    assert "text: 'write'" not in render_tools


def test_request_result_and_history_arguments_reopen_on_relevant_actions() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    template = (ROOT / "templates" / "explorer.html").read_text(encoding="utf-8")
    german = (ROOT / "templates/lang/language_de.ini").read_text(encoding="utf-8")
    english = (ROOT / "templates/lang/language_en.ini").read_text(encoding="utf-8")
    select_tool = source[
        source.index("function selectTool(") : source.index("function setDraftField(")
    ]
    render_result = source[
        source.index("function renderResult(") : source.index("function transcriptEntry(")
    ]

    assert "SELECTED_TOOL=Ausgewähltes Tool" in german
    assert "SELECTED_TOOL=Selected tool" in english
    assert 'id="explorer-request-selection"' in template
    assert 'id="explorer-history-arguments-value"' in template
    assert "if (state.selectedTool) elements.request.open = true" in select_tool
    assert "elements.result.open = true" in render_result
    assert "elements.historyArguments.open = false" in render_result
    assert "elements.historyArgumentsValue.textContent = ''" in render_result
    assert (
        "elements.result.open = true"
        in source[
            source.index("function revealResult()") : source.index("function syncResponsivePanels")
        ]
    )


def test_tool_metadata_labels_are_localized_and_inspectable() -> None:
    german = (ROOT / "templates" / "lang" / "language_de.ini").read_text(encoding="utf-8")
    english = (ROOT / "templates" / "lang" / "language_en.ini").read_text(encoding="utf-8")
    template = (ROOT / "templates" / "explorer.html").read_text(encoding="utf-8")
    source = SCRIPT.read_text(encoding="utf-8")
    keys = [
        "TOOL_BADGE_WRITE_POSSIBLE",
        "TOOL_HINT_DESTRUCTIVE",
        "TOOL_HINT_ADDITIVE",
        "TOOL_HINT_IDEMPOTENT",
        "TOOL_HINT_REPEAT_EFFECT",
        "TOOL_HINT_OPEN_WORLD",
        "TOOL_HINT_CLOSED_WORLD",
        "TOOL_HINTS_NOTICE",
        "TOOL_DESCRIPTION",
        "TOOL_REQUIRED_SCOPES",
        "TOOL_SCOPES_UNKNOWN",
        "TOOL_TECHNICAL_METADATA",
    ]
    for key in keys:
        attribute = key.lower().replace("_", "-")
        assert f"{key}=" in german
        assert f"{key}=" in english
        assert f'data-{attribute}="<TMPL_VAR EXPLORER.{key} ESCAPE=HTML>"' in template
    assert "core.toolMetadataLabels(state.selectedTool)" in source
    assert "core.toolRequiredScopes(state.selectedTool)" in source
    assert "JSON.stringify(state.selectedTool.annotations || {}, null, 2)" in source
    assert "element('details', {className: 'mcp-explorer-technical'})" in source


def run_core(expression: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for explorer JavaScript tests")
    program = (
        f"const core=require({json.dumps(str(SCRIPT))}); console.log(JSON.stringify({expression}));"
    )
    result = subprocess.run([node, "-e", program], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def run_adapters(expression: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for explorer JavaScript tests")
    program = (
        f"const adapters=require({json.dumps(str(ADAPTERS))}); "
        f"console.log(JSON.stringify({expression}));"
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


def run_inspector(scenario: str) -> object:
    dom = """(() => {
      class Node {
        constructor(tag) {
          this.tag = tag; this.children = []; this.attrs = {}; this.handlers = {};
          this.textContent = ''; this.hidden = false; this.className = '';
        }
        append(...nodes) { this.children.push(...nodes); }
        replaceChildren(...nodes) { this.children = nodes; }
        remove() {
          if (this.parent) this.parent.children = this.parent.children.filter(n => n !== this);
        }
        setAttribute(key, value) { this.attrs[key] = value; }
        getAttribute(key) { return this.attrs[key]; }
        addEventListener(key, handler) { this.handlers[key] = handler; }
        click() { this.handlers.click(); }
      }
      const document = {createElement: tag => new Node(tag)};
      const originalAppend = Node.prototype.append;
      Node.prototype.append = function (...nodes) {
        nodes.forEach(child => { child.parent = this; }); originalAppend.apply(this, nodes);
      };
      const walk = root => [root, ...root.children.flatMap(walk)];
      const labels = {selectValue:'Select',expandResult:'Expand',
        collapseResult:'Collapse',moreResults:'Show more'};
      const transfers = [];
      const inspect = value => core.createResultInspector(document, value, labels,
        (selected, path) => transfers.push({selected, path}));
    """
    return run_core(dom + scenario + "})()")


def test_result_inspector_bounds_initial_dom_and_reaches_all_array_items() -> None:
    result = run_inspector("""
      const tree = inspect(Array.from({length:1000}, (_, i) => ({value:i})));
      const count = () => walk(tree).filter(node =>
        node.className === 'mcp-explorer-tree-entry').length;
      const initial = count();
      for (let i = 0; i < 9; i++) {
        walk(tree).find(node => node.className === 'mcp-explorer-tree-more').click();
      }
      return {initial, final:count(), more:walk(tree).filter(node =>
        node.className === 'mcp-explorer-tree-more').length,
        last:walk(tree).some(node => node.tag === 'button' &&
          node.textContent.endsWith('999 {1}'))};
    """)
    assert result == {"initial": 100, "final": 1000, "more": 0, "last": True}


def test_result_inspector_shallow_budget_disclosure_and_exact_transfer_path() -> None:
    result = run_inspector("""
      const many = Object.fromEntries(Array.from({length:150}, (_, i) =>
        [`field${i}`, {value:i, other:true}]));
      const budgetTree = inspect(many);
      const budget = walk(budgetTree).filter(node =>
        node.className === 'mcp-explorer-tree-entry').length;
      const tree = inspect({metadata:{cursor:'next'},items:[{id:'exact'}]});
      const before = walk(tree).filter(node =>
        node.className === 'mcp-explorer-tree-entry').length;
      const toggle = walk(tree).find(node => node.className === 'mcp-explorer-tree-toggle'
        && node.textContent.includes('items'));
      const collapsed = toggle.getAttribute('aria-expanded');
      toggle.click();
      const expanded = toggle.getAttribute('aria-expanded');
      const index = walk(tree).find(node => node.className === 'mcp-explorer-tree-toggle'
        && node.textContent.includes('0 {1}'));
      index.click();
      walk(tree).find(node => node.tag === 'button' && node.textContent === 'id: "exact"').click();
      toggle.click();
      return {budget, before, collapsed, expanded, closed:toggle.getAttribute('aria-expanded'),
        after:walk(tree).filter(node =>
          node.className === 'mcp-explorer-tree-entry').length, transfers};
    """)
    assert result == {
        "budget": 200,
        "before": 3,
        "collapsed": "false",
        "expanded": "true",
        "closed": "false",
        "after": 5,
        "transfers": [{"selected": "exact", "path": ["items", 0, "id"]}],
    }


def test_result_inspector_empty_scalar_and_error_values() -> None:
    result = run_inspector("""
      const values = [inspect(null),inspect([]),inspect({}),inspect({isError:true,
        content:[{type:'text',text:'failed'}]})];
      return values.map(tree => ({text:walk(tree).map(node => node.textContent).filter(Boolean),
        items:walk(tree).filter(node =>
          node.className === 'mcp-explorer-tree-entry').length}));
    """)
    assert result[0]["items"] == 1
    assert result[1]["text"] == ["[0]"]
    assert result[2]["text"] == ["{0}"]
    assert result[3]["items"] >= 2


def test_result_inspector_array_object_preview_and_null_display() -> None:
    result = run_inspector("""
      const tree = inspect({items:[
        {name:'  Kitchen  ',type:'Switch',uuid:'a'},
        {name:' ',title:'Overview',type:'Page'},
        {label:'Etage'}, {type:'Light'}, {id:0}, {uuid:'abc'},
        {name:null,other:1}, null, 'plain',
        {name:'X'.repeat(90)}
      ], ordinary:{name:'No preview'}, missing:null});
      const items = walk(tree).find(node => node.tag === 'button' &&
        node.textContent.includes('items [10]'));
      items.click();
      const captions = walk(tree).filter(node => node.className ===
        'mcp-explorer-tree-toggle').map(node => node.textContent);
      const values = walk(tree).filter(node => node.className ===
        'mcp-explorer-value').map(node => node.textContent);
      walk(tree).find(node => node.className === 'mcp-explorer-value' &&
        node.textContent === '7: -').click();
      return {captions,values,transfers};
    """)
    assert any(text.endswith('0 {3} "Kitchen"') for text in result["captions"])
    assert any(text.endswith('1 {3} "Overview"') for text in result["captions"])
    assert any(text.endswith('2 {1} "Etage"') for text in result["captions"])
    assert any(text.endswith('3 {1} "Light"') for text in result["captions"])
    assert any(text.endswith("4 {1} 0") for text in result["captions"])
    assert any(text.endswith('5 {1} "abc"') for text in result["captions"])
    assert any(text.endswith("6 {2}") for text in result["captions"])
    assert any(text.endswith("ordinary {1}") for text in result["captions"])
    assert any('9 {1} "' + "X" * 80 in text for text in result["captions"])
    assert "7: -" in result["values"]
    assert '8: "plain"' in result["values"]
    assert "missing: -" in result["values"]
    assert result["transfers"] == [{"selected": None, "path": ["items", 7]}]


def test_result_inspector_uses_the_same_history_path_and_lazy_complete_json() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    template = (ROOT / "templates" / "explorer.html").read_text(encoding="utf-8")
    german = (ROOT / "templates" / "lang" / "language_de.ini").read_text(encoding="utf-8")
    english = (ROOT / "templates" / "lang" / "language_en.ini").read_text(encoding="utf-8")
    render_result = source[
        source.index("function renderResult(") : source.index("function transcriptEntry(")
    ]
    render_history = source[
        source.index("function renderHistory(") : source.index("async function runSelectedTool(")
    ]

    assert "core.createResultInspector(document, displayed" in render_result
    assert (
        "renderResult(entry.result, {tool: entry.tool, arguments: entry.arguments, history: true})"
        in render_history
    )
    assert "elements.resultRaw.textContent = JSON.stringify(result" not in render_result
    assert "elements.resultRaw.textContent = JSON.stringify(state.lastResult, null, 2)" in source
    assert "navigator.clipboard.writeText(JSON.stringify(state.lastResult, null, 2))" in source
    for key in ("EXPAND_RESULT", "COLLAPSE_RESULT", "MORE_RESULTS", "SELECT_VALUE"):
        assert f"EXPLORER.{key} ESCAPE=HTML" in template
        assert f"{key}=" in german
        assert f"{key}=" in english


def test_explorer_preserves_structured_mcp_error_details() -> None:
    response = {
        "jsonrpc": "2.0",
        "id": 7,
        "error": {
            "code": -32000,
            "message": "emergency_stop_active",
            "data": {
                "status": "disabled",
                "observed_at": "2026-08-16T21:41:03Z",
                "blocked_since": "2026-08-16T21:40:51Z",
            },
        },
    }

    assert run_core(f"core.mcpFailure({json.dumps(response)},'fallback')") == {
        "message": "emergency_stop_active",
        "result": {"error": response["error"]},
    }
    source = SCRIPT.read_text(encoding="utf-8")
    assert "error.mcpResult = failure.result" in source
    assert "core.clone(error.mcpResult)" in source


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
        "explorer_session_endpoint": "https://loxberry-test/plugins/mcpserver/oauth/explorer-session",
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
    authorize_start = source.index("async function authorize(popup)")
    authorize = source[
        authorize_start : source.index("async function refreshAccessToken", authorize_start)
    ]
    assert authorize.index("const discovered = await discover();") < authorize.index(
        "if (!popup) throw new Error(label('popupBlocked'));"
    )


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


def test_explorer_filters_tools_locally_by_name_description_and_group() -> None:
    tools = [
        {
            "name": "loxone_find_controls",
            "description": "Find visible controls",
            "annotations": {"readOnlyHint": True, "destructiveHint": False},
        },
        {
            "name": "loxone_get_control_history",
            "description": "Read archived events",
            "annotations": {"readOnlyHint": True, "destructiveHint": False},
        },
        {
            "name": "loxone_operate_control",
            "description": "Set a control",
            "annotations": {"readOnlyHint": False, "destructiveHint": False},
        },
        {
            "name": "loxberry_get_system_status",
            "description": "Read host health",
            "annotations": {"readOnlyHint": True, "destructiveHint": False},
        },
    ]
    encoded = json.dumps(tools)

    def filtered(search: str, groups: list[str]) -> list[dict[str, object]]:
        return run_core(
            f"core.filteredToolGroups({encoded},{json.dumps(search)},{json.dumps(groups)})"
        )

    assert [group["id"] for group in filtered("", [])] == [
        "loxoneRead",
        "loxoneHistory",
        "loxoneControl",
        "loxberryRead",
    ]
    assert [tool["name"] for group in filtered("FIND_CONTROLS", []) for tool in group["tools"]] == [
        "loxone_find_controls"
    ]
    assert [tool["name"] for group in filtered("  ARCHIVED  ", []) for tool in group["tools"]] == [
        "loxone_get_control_history"
    ]
    assert [
        tool["name"] for group in filtered("control", ["loxoneHistory"]) for tool in group["tools"]
    ] == ["loxone_get_control_history"]
    assert filtered("host", ["loxoneRead"]) == []
    assert filtered("", ["loxberryRead"])[0]["tools"][0]["name"] == "loxberry_get_system_status"
    assert [group["id"] for group in filtered("", ["loxoneHistory", "loxberryRead"])] == [
        "loxoneHistory",
        "loxberryRead",
    ]
    assert filtered("host", ["loxoneHistory", "loxberryRead"])[0]["id"] == "loxberryRead"


def test_explorer_scope_filters_include_all_published_history_and_operate_tools() -> None:
    history_names = [
        "loxone_get_statistics",
        "loxone_get_control_history",
        "loxone_get_state_history",
        "loxone_analyze_observability",
    ]
    operate_names = [
        "loxberry_clear_statistics_cache",
        "loxberry_list_event_history_sources",
        "loxberry_add_event_history_source",
        "loxberry_remove_event_history_source",
        "loxberry_purge_event_history_source",
    ]
    tools = [
        {"name": name, "annotations": {"readOnlyHint": True, "destructiveHint": False}}
        for name in history_names + operate_names
    ]
    encoded = json.dumps(tools)

    def names_for(group: str) -> list[str]:
        groups = run_core(f"core.filteredToolGroups({encoded},'',{json.dumps([group])})")
        return [tool["name"] for entry in groups for tool in entry["tools"]]

    assert set(names_for("loxoneHistory")) == set(history_names)
    assert set(names_for("loxberryOperate")) == set(operate_names)
    assert names_for("loxoneRead") == []
    assert names_for("loxberryRead") == []


def test_explorer_discovery_controls_preserve_selection_and_drafts() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    template = (ROOT / "templates" / "explorer.html").read_text(encoding="utf-8")
    stylesheet = (ROOT / "webfrontend" / "htmlauth" / "mcp-ui.css").read_text(encoding="utf-8")
    german = (ROOT / "templates" / "lang" / "language_de.ini").read_text(encoding="utf-8")
    english = (ROOT / "templates" / "lang" / "language_en.ini").read_text(encoding="utf-8")
    handlers = source[
        source.index("elements.toolSearch.addEventListener('input'") : source.index(
            "elements.run.addEventListener('click'"
        )
    ]

    assert '<input id="explorer-tool-search" type="search"' in template
    assert '<details id="explorer-tool-filters"' in template
    assert template.count('data-tool-group="') == 7
    assert template.count('type="checkbox" data-tool-group="') == 7
    assert 'id="explorer-tool-filter-count"' in template
    assert "core.filteredToolGroups(state.tools, state.toolSearch, state.toolGroups)" in source
    assert 'src="explorer-adapters.js?v=<TMPL_VAR VERSION ESCAPE=HTML>-registry-v1"' in template
    assert 'src="explorer.js?v=<TMPL_VAR VERSION ESCAPE=HTML>-collapsible-v1"' in template
    assert "label('noMatchingTools')" in source
    assert "label('noTools')" in source
    assert "state.toolSearch = elements.toolSearch.value" in handlers
    assert "state.toolGroups = [...state.toolGroups, group]" in handlers
    assert "state.toolGroups = state.toolGroups.filter(" in handlers
    assert "if (group === 'all') state.toolGroups = []" in handlers
    assert "renderTools();" in handlers
    assert "mcpRequest(" not in handlers
    assert "selectTool(" not in handlers
    assert "state.drafts" not in handlers
    assert "state.toolSearch = '';" in source
    assert "state.toolGroups = [];" in source
    assert ".mcp-explorer-tool-filter-options" in stylesheet
    for language in (german, english):
        for key in ("SEARCH_TOOLS=", "FILTER_TOOLS=", "FILTER_ALL=", "NO_MATCHING_TOOLS="):
            assert key in language
    assert "FILTER_TOOLS=Gruppen filtern" in german
    assert "FILTER_TOOLS=Filter groups" in english


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
    assert run_adapters(
        "adapters.transferRecipe('loxone_describe_control',"
        f"{json.dumps(result)},['data','capabilities','statistics',0],{{series_id:'series'}},"
        "[{name:'loxone_get_statistics'}],0)"
    ) == {
        "tool": "loxone_get_statistics",
        "contextLabel": "statisticsTransferContext",
        "arguments": {
            "control_uuid": "control",
            "series_id": "series",
            "start": "1969-12-31T00:00:00.000Z",
            "end": "1970-01-01T00:00:00.000Z",
            "granularity": "raw",
        },
    }


def test_unknown_tool_uses_generic_explorer_path() -> None:
    tool = {
        "name": "future_custom_tool",
        "description": "Search future data",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    }
    encoded = json.dumps(tool)
    assert run_adapters(f"adapters.forTool({encoded})") is None
    assert run_core(f"core.toolGroup({encoded})") == "other"
    assert run_core(f"core.toolRequiredScopes({encoded})") is None
    assert run_core(f"core.filteredToolGroups([{encoded}],'future',['other'])")[0]["tools"] == [
        tool
    ]
    assert run_core(f"core.validateArguments({{query:'text'}},{encoded}.inputSchema)") == []
    assert run_core(f"core.validateArguments({{}},{encoded}.inputSchema)")
    assert run_core(f"core.toolIsMutating({encoded})") is False
    source = SCRIPT.read_text(encoding="utf-8")
    assert "mcpRequest('tools/call', {name: tool.name, arguments: args}, false)" in source
    assert "adapters.fieldVisible(state.selectedTool, name, state.arguments)" in source


def test_registry_keeps_tool_hints_out_of_authorization_and_defaults_unknown_safely() -> None:
    assert run_adapters("adapters.toolGroup({name:'future_loxone_tool'})") == "other"
    assert run_adapters("adapters.requiredMutationScope({name:'future_write'})") is None
    assert run_core("core.toolIsMutating({name:'future_write'})") is True
    assert (
        run_adapters("adapters.requiredMutationScope({name:'loxone_operate_control'})")
        == "loxone:control"
    )
    assert (
        run_adapters("adapters.requiredMutationScope({name:'loxberry_add_event_history_source'})")
        == "loxberry:operate"
    )
    assert run_adapters(
        "adapters.requiredScopes({name:'loxberry_list_event_history_sources'})"
    ) == ["loxone:read", "loxone:history", "loxberry:operate"]
    source = SCRIPT.read_text(encoding="utf-8")
    assert "core.toolIsMutating(state.selectedTool)" in source
    assert "if (!(await confirmMutation(state.selectedTool, state.arguments))) return;" in source
    assert "requiredMutationScope &&" in source
    assert "loxone_operate_control" not in source
    assert "loxberry_clear_statistics_cache" not in source


def test_explorer_ui_binds_static_registry_in_its_own_scope() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    ui = source[source.index("(function () {\n  'use strict';\n  if (typeof window") :]
    assert "const adapters = window.McpExplorerAdapters;" in ui
    assert "adapters.requiredMutationScope(state.selectedTool)" in ui


def test_operation_adapter_changes_only_action_parameters() -> None:
    assert run_adapters(
        "adapters.changeAction({control_uuid:'id',action:'set_value',value:4,cursor:'keep'},'on')"
    ) == {"control_uuid": "id", "action": "on", "cursor": "keep"}
    assert (
        run_adapters("adapters.fieldVisible({name:'loxone_operate_control'},'value',{action:'on'})")
        is False
    )
    assert run_adapters("adapters.fieldVisible({name:'future_tool'},'value',{action:'on'})") is True
    assert (
        run_adapters(
            "adapters.fieldVisible({name:'loxone_operate_control'},'brightness',"
            "{action:'set_color_temperature'})"
        )
        is True
    )


def test_statistics_recipe_requires_source_shape_and_available_target() -> None:
    result = {"data": {"uuid": "control"}}
    source = json.dumps(result)
    path = "['data','capabilities','statistics',0]"
    assert (
        run_adapters(
            f"adapters.transferRecipe('loxone_describe_control',{source},{path},"
            "{series_id:'series'},[])"
        )
        is None
    )
    assert (
        run_adapters(
            f"adapters.transferRecipe('other_tool',{source},{path},"
            "{series_id:'series'},[{name:'loxone_get_statistics'}])"
        )
        is None
    )
    assert (
        run_adapters(
            f"adapters.transferRecipe('loxone_describe_control',{source},['data'],"
            "{series_id:'series'},[{name:'loxone_get_statistics'}])"
        )
        is None
    )


def test_explorer_converts_datetime_local_values_to_rfc3339() -> None:
    converted = run_core("core.dateTimeLocalToRfc3339('2026-08-12T12:34')")
    assert isinstance(converted, str) and converted.endswith("Z")
    assert run_core(f"core.rfc3339ToDateTimeLocal({json.dumps(converted)})") == "2026-08-12T12:34"


def test_explorer_time_ranges_and_action_fields_are_bounded() -> None:
    assert run_core("core.timeRange('hour',0)") == {
        "start": "1969-12-31T23:00:00.000Z",
        "end": "1970-01-01T00:00:00.000Z",
    }
    assert run_core("core.timeRange('today',0).start <= core.timeRange('today',0).end") is True
    assert (
        run_core("new Date(core.timeRange('day',0).end) - new Date(core.timeRange('day',0).start)")
        == 86_400_000
    )
    assert (
        run_core(
            "new Date(core.timeRange('week',0).end) - new Date(core.timeRange('week',0).start)"
        )
        == 604_800_000
    )
    assert run_core("core.timeRange('unknown',0)") is None
    assert run_core("core.actionFields('set_color_hsv')") == ["hue", "saturation", "brightness"]
    assert run_core("core.actionFields('set_color_temperature')") == ["brightness", "kelvin"]
    assert run_core("core.actionFields('on')") == []
    assert run_core("core.isAdvancedField('cursor')") is True
    assert run_core("core.isAdvancedField('control_uuid')") is False
    assert run_core("core.isReferenceField('control_uuid')") is True


def test_explorer_reference_candidates_use_matching_tab_history_only() -> None:
    history = [
        {
            "tool": "loxone_list_rooms",
            "result": {
                "structuredContent": {
                    "data": {
                        "items": [
                            {
                                "uuid": "room-1",
                                "name": "Office",
                                "room_group": {"uuid": "group-1", "name": "Ground floor"},
                            },
                        ]
                    }
                }
            },
        },
        {
            "tool": "loxone_find_controls",
            "result": {
                "content": {
                    "data": {
                        "items": [
                            {"uuid": "control-1", "name": "Ceiling light"},
                        ]
                    }
                }
            },
        },
    ]
    encoded = json.dumps(history)

    assert run_core(f"core.referenceCandidates('control_uuid',{encoded})") == [
        {"value": "control-1", "label": "Ceiling light (control-1)"}
    ]
    assert run_core(f"core.referenceCandidates('room_group_uuid',{encoded})") == [
        {"value": "group-1", "label": "Ground floor (group-1)"}
    ]
    assert run_core(f"core.referenceCandidates('state_uuids',{encoded})") == []


def test_explorer_preserves_datetime_format_for_optional_string_fields() -> None:
    schema = {
        "anyOf": [{"type": "string"}, {"type": "null"}],
        "format": "date-time",
        "default": None,
    }
    encoded = json.dumps(schema)

    assert run_core(f"core.effectiveSchema({encoded},{encoded}).format") == "date-time"
    assert run_core(f"core.schemaSupportedForReuse({encoded},{encoded})") is True


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


def test_tool_metadata_labels_follow_explicit_hints_without_inventing_safety() -> None:
    cases = [
        (
            {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
            ["toolBadgeReadOnly", "toolHintClosedWorld"],
        ),
        (
            {
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": False,
                "openWorldHint": True,
            },
            ["toolBadgeWrite", "toolHintDestructive", "toolHintRepeatEffect", "toolHintOpenWorld"],
        ),
        (
            {
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
            ["toolBadgeWrite", "toolHintAdditive", "toolHintIdempotent", "toolHintClosedWorld"],
        ),
        (
            {"readOnlyHint": True, "destructiveHint": True, "openWorldHint": False},
            ["toolBadgeWritePossible"],
        ),
        ({"readOnlyHint": True}, ["toolBadgeWritePossible"]),
        ({}, ["toolBadgeWritePossible"]),
    ]
    for hints, expected in cases:
        tool = {"annotations": hints}
        assert run_core(f"core.toolMetadataLabels({json.dumps(tool)})") == expected


def test_required_scopes_cover_current_tools_and_leave_unknown_tools_unmapped() -> None:
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    names = [tool["name"] for tool in tool_schema_catalog(version)["tools"]]
    mapped = run_core(
        f"Object.fromEntries({json.dumps(names)}.map(name => "
        "[name,core.toolRequiredScopes({name})]))"
    )
    assert set(mapped) == set(names)
    assert all(scopes and scopes[0] == "loxone:read" for scopes in mapped.values())
    assert mapped["loxone_get_system_status"] == ["loxone:read"]
    assert mapped["loxone_get_statistics"] == ["loxone:read", "loxone:history"]
    assert mapped["loxone_operate_control"] == ["loxone:read", "loxone:control"]
    assert mapped["loxberry_get_service_health"] == ["loxone:read", "loxberry:read"]
    assert mapped["loxberry_add_event_history_source"] == [
        "loxone:read",
        "loxone:history",
        "loxberry:operate",
    ]
    assert mapped["loxberry_purge_event_history_source"] == [
        "loxone:read",
        "loxone:history",
        "loxberry:operate",
    ]
    assert run_core("core.toolRequiredScopes({name:'future_tool'})") is None


def test_explorer_oauth_guards_and_resource_binding() -> None:
    assert (
        run_core(
            "core.acceptOAuthMessage('https://local','https://local',"
            "{type:'mcp-explorer-oauth',state:'expected',code:'code'},'expected')"
        )
        is True
    )
    assert (
        run_core(
            "core.acceptOAuthMessage('https://other','https://local',"
            "{type:'mcp-explorer-oauth',state:'expected',code:'code'},'expected')"
        )
        is False
    )
    assert (
        run_core(
            "core.acceptOAuthMessage('https://local','https://local',"
            "{type:'mcp-explorer-oauth',state:'wrong',code:'code'},'expected')"
        )
        is False
    )
    assert (
        run_core(
            "core.acceptOAuthPayload({type:'mcp-explorer-oauth',state:'expected',code:'code'},'expected')"
        )
        is True
    )
    assert (
        run_core("core.acceptOAuthPayload({type:'mcp-explorer-oauth',state:'expected'},'expected')")
        is False
    )


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
        "toolSearch": "",
        "toolGroups": [],
        "arguments": {},
        "history": [],
        "transcript": [],
        "lastResult": None,
        "hasResult": False,
        "lastResultContext": None,
        "nextPageRequest": None,
        "transferPath": "",
        "transferRecipe": None,
        "drafts": {},
    }


def test_explorer_session_clear_removes_sensitive_dom_content() -> None:
    expression = """(() => {
      const text = () => ({textContent:'secret',hidden:false});
      const list = () => ({children:['secret'],hidden:false,
        replaceChildren(){this.children=[];}});
      const dialog = () => ({open:true,returnValue:'',close(value){
        this.open=false; this.returnValue=value || '';
      }});
      const elements={json:{value:'{"token":"secret"}'},confirmTool:text(),
        confirmArguments:text(),confirm:dialog(),transferSource:text(),
        transferContext:text(),transferTool:list(),transferField:list(),
        transferEmpty:{hidden:true},transferApply:{disabled:false},transfer:dialog(),
        resultContext:text(),historyArguments:{hidden:false,open:true},
        historyArgumentsValue:text(),restoreHistory:{hidden:false},
        resultTree:list(),resultRaw:text(),rawDetails:{open:true},
        validation:text(),callFeedback:text()};
      core.clearSensitiveDom(elements);
      return {
        json:elements.json.value,confirmTool:elements.confirmTool.textContent,
        confirmArguments:elements.confirmArguments.textContent,
        confirmOpen:elements.confirm.open,confirmReturn:elements.confirm.returnValue,
        transferSource:elements.transferSource.textContent,
        transferContext:elements.transferContext.textContent,
        transferTool:elements.transferTool.children,
        transferField:elements.transferField.children,
        transferEmpty:elements.transferEmpty.hidden,
        transferApply:elements.transferApply.disabled,transferOpen:elements.transfer.open,
        resultContext:elements.resultContext.textContent,
        resultContextHidden:elements.resultContext.hidden,
        historyArguments:elements.historyArgumentsValue.textContent,
        historyArgumentsHidden:elements.historyArguments.hidden,
        historyArgumentsOpen:elements.historyArguments.open,
        restoreHistory:elements.restoreHistory.hidden,
        resultTree:elements.resultTree.children,
        resultRaw:elements.resultRaw.textContent,
        rawOpen:elements.rawDetails.open,
        validation:elements.validation.textContent,
        validationHidden:elements.validation.hidden,
        callFeedback:elements.callFeedback.textContent,
        callFeedbackHidden:elements.callFeedback.hidden,
      };
    })()"""
    assert run_core(expression) == {
        "json": "{}",
        "confirmTool": "",
        "confirmArguments": "",
        "confirmOpen": False,
        "confirmReturn": "cancel",
        "transferSource": "",
        "transferContext": "",
        "transferTool": [],
        "transferField": [],
        "transferEmpty": False,
        "transferApply": True,
        "transferOpen": False,
        "resultContext": "",
        "resultContextHidden": True,
        "historyArguments": "",
        "historyArgumentsHidden": True,
        "historyArgumentsOpen": False,
        "restoreHistory": True,
        "resultTree": [],
        "resultRaw": "",
        "rawOpen": False,
        "validation": "",
        "validationHidden": True,
        "callFeedback": "",
        "callFeedbackHidden": True,
    }


def test_explorer_granted_scopes_are_exact_and_fail_closed() -> None:
    expression = """(() => {
      const scopes = core.EXPLORER_SCOPE_ORDER;
      const all = core.grantedScopes(scopes.join(' '));
      const partial = core.grantedScopes('loxone:read loxone:history loxberry:read');
      return {
        all: scopes.map(scope => all.has(scope)),
        partial: scopes.map(scope => partial.has(scope)),
        absent: core.grantedScopes(undefined),
        empty: core.grantedScopes('  '),
        unknown: core.grantedScopes('loxone:read unrelated:admin'),
        duplicate: core.grantedScopes('loxone:read loxone:read'),
      };
    })()"""
    assert run_core(expression) == {
        "all": [True] * 5,
        "partial": [True, True, False, True, False],
        "absent": None,
        "empty": None,
        "unknown": None,
        "duplicate": None,
    }


def test_explorer_scope_display_tracks_session_lifecycle() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    template = (ROOT / "templates" / "explorer.html").read_text(encoding="utf-8")
    german = (ROOT / "templates" / "lang" / "language_de.ini").read_text(encoding="utf-8")
    english = (ROOT / "templates" / "lang" / "language_en.ini").read_text(encoding="utf-8")

    assert 'id="explorer-access-scopes" hidden' in template
    assert 'id="explorer-scope-list"' in template
    assert "core.grantedScopes(state.oauth.scope)" in source
    assert "core.EXPLORER_SCOPE_ORDER" in source
    assert "token.scope || scope" not in source
    assert "token.scope || state.oauth.scope" not in source
    refresh = source[
        source.index("async function refreshAccessToken") : source.index(
            "async function accessToken"
        )
    ]
    assert "state.oauth.scope = typeof token.scope === 'string' ? token.scope : '';" in refresh
    assert "renderConnection();" in refresh
    logout = source[
        source.index("async function revokeAndClear") : source.index("function renderConnection")
    ]
    assert logout.index("clearExplorerState()") < logout.index("action: 'logout'")
    assert logout.index("renderAll()") < logout.index("action: 'logout'")
    assert "core.clearSensitiveDom(elements);" in logout
    assert source.count("clearExplorerState();") >= 6
    assert "sessionExpiryTimer = window.setTimeout" in source
    assert "if (logoutChannel) logoutChannel.postMessage('logout');" in source
    for text in (german, english):
        assert "GRANTED_OAUTH_SCOPES=" in text
        assert "SCOPE_GRANTED=" in text
        assert "SCOPE_NOT_GRANTED=" in text
        assert "SCOPE_UNAVAILABLE=" in text


def test_session_clear_prevents_call_artifacts_from_being_recreated() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "error.sessionCleared = true" in source
    assert "!(error && error.sessionCleared === true)" in source
    assert (
        "sessionCleared = Boolean(error && error.sessionCleared === true) || state.oauth !== oauth"
        in source
    )
    assert source.count("if (!sessionCleared) {") >= 2
    assert "if (elements.confirm.open) elements.confirm.close('cancel');" in source
    request = source[
        source.index("async function mcpRequest") : source.index("async function initializeMcp")
    ]
    assert request.count("state.oauth !== oauth || Date.now() >= oauth.resumeUntil") == 2
    run = source[
        source.index("async function runSelectedTool") : source.index("function openTransfer")
    ]
    assert run.index("if (state.oauth !== oauth || Date.now() >= oauth.resumeUntil)") < run.index(
        "const tool = state.selectedTool"
    )
    assert "if (!sessionCleared) setCallFeedback(" in run


def test_explorer_keeps_refresh_credentials_out_of_browser_storage() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "explorer-session" in source
    assert "credentials: 'same-origin'" in source
    assert "BroadcastChannel" in source
    assert "sessionStorage" not in source
    assert source.count("window.localStorage.getItem(key)") == 1
    assert source.count("window.localStorage.setItem(key, String(element.open))") == 1
    assert "mcp-explorer-connection-open-v1" in source
    assert "mcp-explorer-scopes-open-v1" in source
    assert "refreshToken" not in source


def test_explorer_connection_and_scopes_are_independent_persistent_disclosures() -> None:
    template = (ROOT / "templates" / "explorer.html").read_text(encoding="utf-8")
    source = SCRIPT.read_text(encoding="utf-8")

    links = template.index('href="index.cgi"')
    panel = template.index('id="explorer-connection-panel"')
    scopes = template.index('id="explorer-access-scopes"')
    assert links < panel < scopes
    assert '<details id="explorer-connection-panel" class="mcp-explorer-card" open>' in template
    assert '<details id="explorer-access-scopes" hidden>' in template
    assert '<summary><h1 id="explorer-title">' in template
    assert "<summary><TMPL_VAR EXPLORER.GRANTED_OAUTH_SCOPES></summary>" in template
    assert (
        "persistDisclosure(elements.connectionPanel, 'mcp-explorer-connection-open-v1')" in source
    )
    assert "persistDisclosure(elements.accessScopes, 'mcp-explorer-scopes-open-v1')" in source


def test_explorer_connection_summary_shows_live_status_badge() -> None:
    template = (ROOT / "templates" / "explorer.html").read_text(encoding="utf-8")
    stylesheet = (ROOT / "webfrontend" / "htmlauth" / "mcp-ui.css").read_text(encoding="utf-8")
    source = SCRIPT.read_text(encoding="utf-8")
    summary = template[
        template.index('<details id="explorer-connection-panel"') : template.index(
            '<div class="mcp-explorer-panel-content',
        )
    ]

    assert 'id="explorer-title"' in summary
    assert 'id="explorer-connection-badge" class="mcp-service-badge"' in summary
    assert 'data-kind="inactive"><TMPL_VAR EXPLORER.DISCONNECTED>' in summary
    assert "#explorer-connection-badge { margin-inline-start:" in stylesheet
    assert "connectionBadge: document.getElementById('explorer-connection-badge')" in source
    render_connection = source[
        source.index("function renderConnection") : source.index("function element")
    ]
    assert "label(connected ? 'connected' : 'disconnected')" in render_connection
    assert "connected ? 'success' : 'inactive'" in render_connection


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
    assert "new Date(entry.at).toLocaleString()" in transcript_entry
    assert "className: 'mcp-explorer-protocol-meta'" in transcript_entry
    assert transcript_entry.index("label('dateTime')") < transcript_entry.index("label('status')")
    template = (ROOT / "templates/explorer.html").read_text(encoding="utf-8")
    assert 'data-date-time="<TMPL_VAR EXPLORER.DATE_TIME ESCAPE=HTML>"' in template
    assert "DATE_TIME=Datum/Uhrzeit" in (ROOT / "templates/lang/language_de.ini").read_text(
        encoding="utf-8"
    )
    assert "DATE_TIME=Date/time" in (ROOT / "templates/lang/language_en.ini").read_text(
        encoding="utf-8"
    )
    stylesheet = (ROOT / "webfrontend/htmlauth/mcp-ui.css").read_text(encoding="utf-8")
    assert ".mcp-explorer-protocol-meta p { margin: 0; }" in stylesheet


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


def test_explorer_history_summary_is_schema_bound_redacted_and_short() -> None:
    schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer"},
            "options": {
                "type": "object",
                "properties": {
                    "region": {"type": "string"},
                    "credential": {"type": "string", "writeOnly": True},
                },
            },
            "password": {"type": "string"},
        },
    }
    value = {
        "query": "Rollladen" * 30,
        "limit": 20,
        "options": {"region": "north", "credential": "nested-secret", "unknown": "hidden"},
        "password": "top-secret",
        "unknown": "hidden-too",
    }
    summary = run_core(f"core.summarizeArguments({json.dumps(value)},{json.dumps(schema)})")
    assert isinstance(summary, str)
    assert summary.startswith('query="Rollladen')
    assert "limit=20" in summary
    assert "[redacted]" in summary
    assert len(summary) <= 120
    for secret in ("nested-secret", "top-secret", "hidden", "hidden-too"):
        assert secret not in summary
    assert run_core(f"core.summarizeArguments({json.dumps(value)},null)") == ""


def test_explorer_history_summary_prioritizes_non_default_arguments() -> None:
    schema = {
        "type": "object",
        "properties": {
            "has_statistics": {"type": "boolean", "default": False},
            "has_history": {"type": "boolean", "default": False},
            "has_notes": {"type": "boolean", "default": False},
            "query": {"type": "string"},
        },
    }
    value = {
        "has_statistics": False,
        "has_history": False,
        "has_notes": False,
        "query": "MCP-Test",
    }
    summary = run_core(f"core.summarizeArguments({json.dumps(value)},{json.dumps(schema)})")
    assert summary.startswith('query="MCP-Test"')
    assert summary.count("=") <= 3


def test_explorer_history_and_call_feedback_are_separate_from_connection() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    template = (ROOT / "templates" / "explorer.html").read_text(encoding="utf-8")
    run = source[
        source.index("async function runSelectedTool") : source.index("function openTransfer")
    ]
    history = source[
        source.index("function renderHistory") : source.index("async function runSelectedTool")
    ]

    assert "at: Date.now()" in run
    assert "new Date(entry.at).toLocaleTimeString()" in history
    assert "core.summarizeArguments(entry.arguments" in history
    assert "setCallFeedback(label('working'), 'working')" in run
    assert "setCallFeedback(`${label(ok ? 'callCompleted' : 'error')}" in run
    assert "setStatus(" not in run
    assert 'id="explorer-call-feedback"' in template
    assert 'role="status" aria-live="polite" hidden' in template
    assert template.index('id="explorer-result"') < template.index(
        'id="explorer-transcript-details"'
    )
    assert template.index(
        "</details>", template.index('id="explorer-raw-details"')
    ) < template.index('id="explorer-transcript-details"')
    assert "TRANSCRIPT=MCP protocol / debug" in (ROOT / "templates/lang/language_en.ini").read_text(
        encoding="utf-8"
    )
    assert "TRANSCRIPT=MCP-Protokoll / Debug" in (
        ROOT / "templates/lang/language_de.ini"
    ).read_text(encoding="utf-8")


def test_explorer_ui_is_local_scoped_and_progressively_safe() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    template = (ROOT / "templates" / "explorer.html").read_text(encoding="utf-8")
    stylesheet = (ROOT / "webfrontend" / "htmlauth" / "mcp-ui.css").read_text(encoding="utf-8")
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
    assert "action: 'access'" in source
    assert "if (state.oauth) await revokeAndClear()" in source
    assert "core.toolIsMutating(state.selectedTool)" in source
    assert "state.history.length > core.MAX_CALL_HISTORY" in source
    assert "fetchWithTimeout('/plugins/mcpserver/mcp'" in source
    assert "}, 70000)" in source
    assert "sessionStorage" not in source
    assert "window.localStorage.setItem(key, String(element.open))" in source
    assert "navigator.locks.request" not in source
    assert "await refreshAccessToken();" in source
    assert "window.addEventListener('pagehide'" not in source
    assert "navigator.sendBeacon" not in source
    assert 'target="_blank"' in (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    index_template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    configuration = (ADMIN_SCRIPTS / "configuration.js").read_text(encoding="utf-8")
    index_cgi = (ROOT / "webfrontend" / "htmlauth" / "index.cgi").read_text(encoding="utf-8")
    assert 'id="explorer-link"' in index_template
    assert 'href="<TMPL_VAR EXPLORER_URL ESCAPE=HTML>"' in index_template
    assert "explorerLink.href = `${window.location.origin}${explorerPath}`" in configuration
    assert "EXPLORER_URL => 'explorer.cgi'" in index_cgi
    assert "savedOrigin" not in index_template
    assert "@media (max-width: 52rem)" in stylesheet
    assert ":focus-visible" in stylesheet
    assert "<dialog" in template
    assert 'id="explorer-confirm-tool"' in template
    assert 'id="explorer-next-page"' in template
    assert 'id="explorer-history-arguments"' in template
    assert "data-tool-group-loxone-history=" in template
    assert 'data-help-control-type="<TMPL_VAR EXPLORER.HELP_CONTROL_TYPE ESCAPE=HTML>"' in template
    assert "const description = helpKey ? label(helpKey) : effective.description" in source
    assert 'id="explorer-access-scopes" hidden' in template
    assert 'id="explorer-scope-list"' in template
    assert "<TMPL_VAR EXPLORER.PERMISSIONS_AFTER_LOGIN>" in template
    assert 'id="explorer-origin-warning"' in template
    assert 'id="explorer-origin-link"' in template
    assert "const canonicalUrl = core.canonicalExplorerUrl(" in source
    assert "showConnectionError(_error, label('error'))" in source
    assert 'id="explorer-session-expiry" hidden' in template
    assert "const scope = core.EXPLORER_SCOPE_ORDER.filter" in source
    assert "const registrationScope = scope" in source
    assert "supported.delete('loxberry:operate')" in source
    assert "return fetchJson(metadata.explorer_session_endpoint" in source
    assert "adapters.requiredMutationScope(state.selectedTool)" in source
    assert "elements.historyArguments.hidden = !historySource" in source
    assert "Cache_Control => 'no-store'" in callback
    assert "frame-ancestors 'none'" in callback
    assert "window.history.replaceState" in callback
    assert "new BroadcastChannel('mcp-explorer-oauth')" in callback
    assert "window.setTimeout(() => window.close(), 100)" in callback
    assert "new BroadcastChannel('mcp-explorer-oauth')" in source
    assert "authorizationChannel.onmessage = onChannelMessage" in source


def test_explorer_initial_discovery_has_no_pre_login_permission_choice() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    initial_discovery = source[
        source.index("(async () => {", source.index("selectTab(false, false);")) :
    ]

    assert "setScopeAvailability" not in initial_discovery
    assert "scopeHistory" not in initial_discovery


def test_explorer_login_failure_remains_visible_after_connection_render() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    login_handler = source[
        source.index("elements.connect.addEventListener('click'") : source.index(
            "elements.disconnect.addEventListener('click'"
        )
    ]
    failure_handler = login_handler[
        login_handler.index("} catch (error) {") : login_handler.index(
            "} finally { setBusy(false); }"
        )
    ]

    assert failure_handler.index("renderAll();") < failure_handler.index(
        "showConnectionError(error, label('error'));"
    )


def test_session_refresh_preserves_pending_loxberry_approval_action() -> None:
    source = (ADMIN_SCRIPTS / "sessions.js").read_text(encoding="utf-8")

    assert "session.loxberry_read_eligible && !session.loxberry_read_approved" in source
    assert "allowForm.dataset.ajax = 'allow_loxberry_read'" in source
    assert "Boolean(session.loxberry_read_eligible)" in source


def test_session_refresh_updates_related_loxberry_bindings() -> None:
    markup = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    source = (ADMIN_SCRIPTS / "sessions.js").read_text(encoding="utf-8")

    assert 'id="loxberry-binding-list"' in markup
    assert "const updateLoxberryBindings = (bindings) =>" in source
    assert "const updateLoxberryBindingTable = (bindings, section, body, actionName) =>" in source
    assert "result.data.loxberry_bindings" in source
    assert "bindingRow.client_name" in source
    assert "bindingRow.identity" in source
    assert "bindingRow.fingerprint" in source


def test_session_refresh_updates_separate_loxberry_operate_bindings() -> None:
    markup = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    source = (ADMIN_SCRIPTS / "sessions.js").read_text(encoding="utf-8")

    assert 'id="loxberry-operate-binding-list"' in markup
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
