"""Executable boundaries for the static Tool Explorer modules."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "webfrontend" / "htmlauth"


def _run_node(body: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for Explorer module tests")
    paths = {
        name: json.dumps(str(SCRIPTS / f"explorer-{name}.js"))
        for name in ("core", "state", "auth", "client", "views")
    }
    program = (
        "\n".join(f"const {name} = require({path});" for name, path in paths.items()) + "\n" + body
    )
    result = subprocess.run(
        [node, "-e", program], check=True, capture_output=True, text=True, encoding="utf-8"
    )
    return json.loads(result.stdout)


def test_explorer_static_scripts_load_in_dependency_order() -> None:
    template = (ROOT / "templates" / "explorer.html").read_text(encoding="utf-8")
    scripts = re.findall(r'<script defer src="(explorer(?:-[^"?]+)?\.js)\?v=', template)
    assert scripts == [
        "explorer-adapters.js",
        "explorer-core.js",
        "explorer-state.js",
        "explorer-auth.js",
        "explorer-client.js",
        "explorer-views.js",
        "explorer.js",
    ]
    assert all((SCRIPTS / name).is_file() for name in scripts)
    source = (SCRIPTS / "explorer-core.js").read_text(encoding="utf-8")
    assert "document." not in source
    assert "createResultInspector" not in source


def test_explorer_state_keeps_drafts_bounded_history_and_clears_secrets() -> None:
    result = _run_node(
        """console.log(JSON.stringify((() => {
          const model = state.create(core);
          const one = {name:'one',inputSchema:{type:'object',properties:{x:{type:'string'}}}};
          const two = {name:'two',inputSchema:{type:'object',properties:{y:{type:'string'}}}};
          model.setTools([one,two]);
          model.selectTool('one',undefined,'{}');
          model.setField('x',true,'kept');
          model.selectTool('two',undefined,'{"x":"kept"}');
          model.selectTool('one',undefined,'{}');
          const draft = model.data.arguments.x;
          for(let i=0;i<core.MAX_CALL_HISTORY+3;i++) model.appendHistory({i});
          for(let i=0;i<core.MAX_TRANSCRIPT+3;i++) model.appendTranscript({i});
          model.setSession({accessToken:'synthetic-token'});
          const historyBefore=model.data.history.length;
          const transcriptBefore=model.data.transcript.length;
          model.clear();
          return {draft,historyBefore,transcriptBefore,oauth:model.data.oauth,
            drafts:model.data.drafts,history:model.data.history,
            transcript:model.data.transcript,arguments:model.data.arguments};
        })()))"""
    )
    assert result == {
        "draft": "kept",
        "historyBefore": 50,
        "transcriptBefore": 100,
        "oauth": None,
        "drafts": {},
        "history": [],
        "transcript": [],
        "arguments": {},
    }


def test_mcp_client_keeps_wire_calls_and_transcript_separate() -> None:
    result = _run_node(
        """(async () => {
          global.performance = {now: () => 100};
          const model = state.create(core);
          model.setSession({accessToken:'synthetic-token',resumeUntil:Date.now()+60000});
          const tool = {name:'future_tool',inputSchema:{type:'object',
            properties:{password:{type:'string'}}}};
          const wire = [], transcript = [];
          const fetchWithTimeout = async (url, options, timeout) => {
            const request = JSON.parse(options.body);
            wire.push({url,method:request.method,headers:options.headers,
              args:request.params.arguments,timeout});
            const result = request.method === 'initialize'
              ? {protocolVersion:core.PROTOCOL_VERSION}
              : request.method === 'tools/list' ? {tools:[tool]} : {ok:true};
            return {status:200,ok:true,headers:{get:()=> 'application/json'},
              text:async()=>JSON.stringify({jsonrpc:'2.0',id:request.id,result})};
          };
          const mcp = client.create({core,state:model.data,explorerState:model,
            label:(x)=>x,accessToken:async()=> 'synthetic-token',fetchWithTimeout,
            addTranscript:(...items)=>transcript.push(items)});
          model.setTools(await mcp.initialize());
          await mcp.callTool('future_tool',{password:'synthetic-secret'});
          return {methods:wire.map(item=>item.method),
            endpoints:wire.map(item=>item.url),
            timeout:wire.at(-1).timeout,protocol:wire.at(-1).headers['MCP-Protocol-Version'],
            authorized:wire.at(-1).headers.Authorization === 'Bearer synthetic-token',
            wireSecret:wire.at(-1).args.password,
            safeTranscript:JSON.stringify(transcript).includes('synthetic-secret'),
            tokenLeaked:JSON.stringify(transcript).includes('synthetic-token'),
            transcriptCount:transcript.length,toolCount:model.data.tools.length};
        })().then(value=>console.log(JSON.stringify(value)))
          .catch(error=>{console.error(error);process.exit(1)});"""
    )
    assert result == {
        "methods": ["initialize", "notifications/initialized", "tools/list", "tools/call"],
        "endpoints": ["/plugins/mcpserver/mcp"] * 4,
        "timeout": 70000,
        "protocol": "2025-11-25",
        "authorized": True,
        "wireSecret": "synthetic-secret",
        "safeTranscript": False,
        "tokenLeaked": False,
        "transcriptCount": 4,
        "toolCount": 1,
    }


def test_mcp_client_drops_inflight_response_after_session_clear() -> None:
    assert _run_node(
        """(async () => {
          global.performance = {now: () => 100};
          const model = state.create(core);
          model.setSession({accessToken:'synthetic-token',resumeUntil:Date.now()+60000});
          const entries=[];
          const mcp=client.create({core,state:model.data,explorerState:model,label:x=>x,
            accessToken:async()=> 'synthetic-token',
            fetchWithTimeout:async()=>{
              model.clear();
              return {status:200,ok:true,headers:{get:()=> 'application/json'},
                text:async()=>'{"jsonrpc":"2.0","result":{}}'};
            },addTranscript:(...items)=>entries.push(items)});
          try { await mcp.callTool('future_tool',{}); }
          catch(error) { return {cleared:error.sessionCleared,entries:entries.length,
            history:model.data.history.length}; }
          throw new Error('Expected session clear');
        })().then(value=>console.log(JSON.stringify(value)))
          .catch(error=>{console.error(error);process.exit(1)});"""
    ) == {"cleared": True, "entries": 0, "history": 0}


def test_auth_refresh_updates_scopes_through_same_origin_session() -> None:
    assert _run_node(
        """(async () => {
          global.window={setTimeout,clearTimeout};
          const model=state.create(core);
          model.setSession({metadata:{explorer_session_endpoint:'/oauth/explorer-session'},
            accessToken:'old',expiresAt:0,resumeUntil:Date.now()+60000});
          const requests=[];
          global.fetch=async (url,options)=>{
            requests.push({url,credentials:options.credentials,body:JSON.parse(options.body)});
            return {ok:true,json:async()=>({access_token:'fresh',scope:'loxone:read',
              expires_in:60,expires_at:Math.floor(Date.now()/1000)+60})};
          };
          let renders=0;
          const session=auth.create({core,state:model.data,explorerState:model,label:x=>x,
            clearOriginWarning:()=>{},renderConnection:()=>renders++,revokeAndClear:()=>{}});
          const token=await session.accessToken();
          return {token,scope:model.data.oauth.scope,requests,renders};
        })().then(value=>console.log(JSON.stringify(value)))
          .catch(error=>{console.error(error);process.exit(1)});"""
    ) == {
        "token": "fresh",
        "scope": "loxone:read",
        "requests": [
            {
                "url": "/oauth/explorer-session",
                "credentials": "same-origin",
                "body": {"action": "access"},
            }
        ],
        "renders": 1,
    }


def test_auth_does_not_restore_a_session_cleared_during_refresh() -> None:
    assert _run_node(
        """(async () => {
          global.window={setTimeout,clearTimeout};
          const model=state.create(core);
          model.setSession({metadata:{explorer_session_endpoint:'/oauth/explorer-session'},
            accessToken:'old',expiresAt:0,resumeUntil:Date.now()+60000});
          global.fetch=async()=>{
            model.clear();
            return {ok:true,json:async()=>({access_token:'late',scope:'loxone:read',
              expires_in:60,expires_at:Math.floor(Date.now()/1000)+60})};
          };
          let clears=0;
          const session=auth.create({core,state:model.data,explorerState:model,label:x=>x,
            clearOriginWarning:()=>{},renderConnection:()=>{},
            revokeAndClear:()=>{clears++;model.clear()}});
          try { await session.accessToken(); }
          catch(error) { return {cleared:error.sessionCleared,oauth:model.data.oauth,clears}; }
          throw new Error('Expected expired session');
        })().then(value=>console.log(JSON.stringify(value)))
          .catch(error=>{console.error(error);process.exit(1)});"""
    ) == {"cleared": True, "oauth": None, "clears": 1}


def test_connection_view_does_not_replace_an_oauth_error() -> None:
    assert _run_node(
        """console.log(JSON.stringify((() => {
          global.window={clearTimeout:()=>{}};
          const model=state.create(core);
          const status={textContent:'OAuth failed',dataset:{kind:'error'}};
          const el={status,connect:{},disconnect:{},run:{},connectionBadge:{dataset:{}},
            sessionExpiry:{},accessScopes:{},scopeList:{replaceChildren(){}},
            scopeUnavailable:{},sessionExpiryTime:{textContent:'',removeAttribute(){}}};
          const ui=views.create({core,state:model.data,adapters:{},elements:el,
            label:x=>x,narrowViewport:{matches:false},element:()=>{},actions:{}});
          ui.renderConnection();
          return {text:status.textContent,kind:status.dataset.kind,
            connectDisabled:el.connect.disabled};
        })()))"""
    ) == {"text": "OAuth failed", "kind": "error", "connectDisabled": False}
