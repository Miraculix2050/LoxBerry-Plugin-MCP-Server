"""Browser-domain comparison regressions; native browser acceptance is separate."""

import subprocess
from pathlib import Path


def test_shared_read_only_session_sources_pagination_and_stale_results():
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {JSDOM} = require('jsdom');
const html = fs.readFileSync('templates/knx.html', 'utf8').replace(/<TMPL_VAR[^>]*>/g, 'label');
const w = new JSDOM(html, {url:'https://localhost/admin/plugins/mcpserver/knx.cgi',runScripts:'outside-only'}).window;
const page=w.document.getElementById('knx-page');
const ui=w.document.getElementById('knx-project-section');
Object.assign(page.dataset,{unknown:'Unknown',empty:'Empty',sources:'Sources',description:'Description',importSource:'ETS'});
Object.assign(ui.dataset,{error:'Error',connected:'Connected',disconnected:'Disconnected',targetChanged:'Stale',
  common:'Common',importOnly:'Import only',observedProjectOnly:'Project only',
  namesDiffer:'Naming deviation',
  namesSame:'No observed difference',namesUnknown:'Incomplete names',ambiguous:'Multiple names',
  limited:'Limited',
  latestDocument:'Last file',complete:'Complete',partial:'Partial',sourceLimits:'Source gaps'});
page.setAttribute('aria-busy','true');
let saved={target:'binding',revision:1};
w.MCPKnx={snapshot:()=>saved};
w.confirm=w.alert=w.prompt=()=>{throw new Error('Native dialog forbidden');};
for(const name of ['explorer-core.js','explorer-state.js'])
  w.eval(fs.readFileSync('webfrontend/htmlauth/'+name,'utf8'));
let authOptions, requests=[], mode='ok', pendingResolve;
w.McpExplorerAuth={create(options){authOptions=options;return{
  discover:async()=>({authorizationMetadata:{},resourceMetadata:{resource:'local'}}),
  refreshAccessToken:async()=>options.explorerState.updateToken({access_token:'synthetic',scope:'loxone:read',
    expires_in:60,expires_at:Date.now()/1000+60}),accessToken:async()=>'synthetic',fetchWithTimeout:async()=>{},
  explorerSession:async()=>{},openAuthorizationPopup:()=>null,authorize:async()=>{}
};}};
const item={group_address:'1/2/3',comparison:{address_id:2563,relation:'common',names_differ:true,
  name_comparison:'compared',project_names_complete:true,ambiguous_names:true,project_objects_omitted:0,
  project_objects:[{project_node_id:'p:1',loxone_name:'Loxone primary A',original_address:'1/2/3:0',
    project_description:'Project description',name_complete:true,truncated_fields:[]},
    {project_node_id:'p:2',loxone_name:'Loxone primary B',original_address:'1/515:1',
    project_description:null,name_complete:true,truncated_fields:[]}],
  local_metadata:{imported:{name:'<img src=x onerror=synthetic>',description:'ETS details'},
    manual:{name:''},
    import_info:{file_format:'csv',imported_at:1}}}};
const envelope=()=>({ok:true,stale:false,observed_at:'synthetic',
  data:{findings:[structuredClone(item)],
  next_cursor:requests.length===1?'cursor':null,summaries:{ets_project_comparison:{target_binding:'binding',
    knx_revision:1,import_info:{complete_export:false},counts:{common:1,import_only:1,observed_project_only:0,name_deviations:1},
    source_limits:{unsupported_source_objects:2,invalid_or_missing_address:3,ambiguous_source_objects:1,
      source_groups_omitted:0,diagnostic_groups_omitted:0,incomplete_project_names:4}}},
  project_fingerprint:'f',model_version:13,coverage_by_source_type:{},source_diagnostics:{},
  analysis_truncated:false,truncation_reasons:[],page_truncated:false}});
w.McpExplorerClient={create(){return{initialize:async()=>[],callTool:async(name,args)=>{
  requests.push({name,args});
  if(mode==='pending')return await new Promise(resolve=>{pendingResolve=resolve;});
  if(mode==='restricted')return{structuredContent:{ok:false,data:{error:'permission_denied'}}};
  if(mode==='denied')return{structuredContent:{ok:false,
    data:{error:'unauthenticated',message:'Fresh access denied'}}};
  return{structuredContent:envelope()};
}};}};
const el=id=>w.document.getElementById('knx-project-'+id);
const settle=async()=>{for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));};
const click=async(id)=>{el(id).click();await settle();};
(async()=>{
  w.eval(fs.readFileSync('webfrontend/htmlauth/knx-project.js','utf8'));
  assert.equal(authOptions.requestedScopes.join(' '),'loxone:read');
  page.removeAttribute('aria-busy');
  page.dispatchEvent(new w.CustomEvent('knx-idle'));await settle();
  assert.equal(el('run').disabled,false);assert.equal(el('status').textContent,'Connected');
  await click('run');
  assert.equal(requests[0].name,'loxone_analyze_project');
  assert.equal(requests[0].args.analyses.join(','),'ets_project_comparison');
  assert.equal(el('rows').children.length,1,el('status').textContent);
  assert.match(el('summary').textContent,/Source gaps: 2 \/ 3 \/ 1 \/ 0 \/ 0 \/ 4/);
  const cells=el('rows').querySelector('tr').children;
  assert.match(cells[2].textContent,/Loxone primary A/);
  assert.match(cells[2].textContent,/Loxone primary B/);
  assert.match(cells[3].textContent,/<img src=x/);
  assert.equal(el('rows').querySelector('img'),null);
  assert.equal(cells[4].textContent,'Empty');assert.match(cells[5].textContent,/Naming deviation/);
  assert.match(el('summary').textContent,/Last file: Partial/);
  assert.equal(el('next').disabled,false);
  await click('next');
  assert.equal(requests[1].args.cursor,'cursor');
  assert.equal(el('next').disabled,true);
  assert.match(el('count').textContent,/2\u20132 \/ 2/);
  const correction=w.MCPKnxProject.snapshot();
  await w.MCPKnxProject.validate(correction.binding);
  assert.equal(requests.at(-1).args.cursor,'cursor');
  item.comparison.project_objects[0].loxone_name='Changed since preview';
  await assert.rejects(()=>w.MCPKnxProject.validate(correction.binding),/knx_revision_conflict/);
  item.comparison.project_objects[0].loxone_name='Loxone primary A';
  mode='restricted';
  await assert.rejects(()=>w.MCPKnxProject.validate(correction.binding),/knx_revision_conflict/);
  mode='ok';
  saved={target:'binding',revision:2};page.dispatchEvent(new w.CustomEvent('knx-state'));
  assert.equal(el('rows').children.length,0);assert.equal(el('next').disabled,true);
  saved={target:'binding',revision:1};mode='pending';el('run').click();await settle();
  saved={target:'other',revision:1};page.dispatchEvent(new w.CustomEvent('knx-state'));
  pendingResolve({structuredContent:envelope()});await settle();
  assert.equal(el('rows').children.length,0);assert.match(el('status').textContent,/Stale/);
  saved={target:'binding',revision:1};mode='denied';await click('run');
  assert.equal(el('rows').children.length,0);assert.equal(el('run').disabled,true);
  assert.equal(el('connect').disabled,false);
  assert.match(el('status').textContent,/Fresh access denied/);
  w.close();
})().catch(error=>{w.close();console.error(error);process.exitCode=1;});
"""
    subprocess.run(
        ["node", "-e", script], cwd=Path(__file__).resolve().parents[1], check=True, timeout=30
    )


def test_real_transport_401_and_logout_during_session_restore_or_login():
    script = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),{JSDOM}=require('jsdom');
const html=fs.readFileSync('templates/knx.html','utf8').replace(/<TMPL_VAR[^>]*>/g,'label');
const w=new JSDOM(html,{url:'https://localhost/admin/plugins/mcpserver/knx.cgi',
  runScripts:'outside-only'}).window;
let channel,discoveryResolve,authorizeResolve;
w.BroadcastChannel=class{constructor(){channel=this;}postMessage(){}};
for(const file of ['explorer-core.js','explorer-state.js','explorer-client.js'])
  w.eval(fs.readFileSync('webfrontend/htmlauth/'+file,'utf8'));
const page=w.document.getElementById('knx-page');
page.removeAttribute('aria-busy');
w.MCPKnx={snapshot:()=>({target:'binding',revision:1})};
const session=()=>({metadata:{},scope:'loxone:read',accessToken:'synthetic',
  expiresAt:Date.now()+60000,resumeUntil:Date.now()+60000});
w.McpExplorerAuth={create:()=>({
  discover:()=>new Promise(resolve=>{discoveryResolve=resolve;}),
  authorize:()=>new Promise(resolve=>{authorizeResolve=resolve;}),
  openAuthorizationPopup:()=>({}),refreshAccessToken:async()=>{},accessToken:async()=>'synthetic',
  explorerSession:async()=>{},fetchWithTimeout:async(_url,options)=>{
    const request=JSON.parse(options.body),denied=request.method==='tools/call';
    const result=request.method==='initialize'?{protocolVersion:w.McpExplorerCore.PROTOCOL_VERSION}:
      request.method==='tools/list'?{tools:[]}:{};
    return{status:denied?401:200,statusText:denied?'Unauthorized':'OK',ok:!denied,
      headers:{get:()=>'application/json'},text:async()=>JSON.stringify({result})};
  }
})};
const el=id=>w.document.getElementById('knx-project-'+id);
const settle=async()=>{for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));};
const logout=()=>channel.onmessage({data:'logout'});
(async()=>{
  w.eval(fs.readFileSync('webfrontend/htmlauth/knx-project.js','utf8'));await settle();
  logout();discoveryResolve({authorizationMetadata:{},resourceMetadata:{resource:'local'}});
  await settle();assert.equal(el('connect').disabled,false);assert.equal(el('run').disabled,true);
  el('connect').click();await settle();logout();authorizeResolve(session());await settle();
  assert.equal(el('connect').disabled,false);assert.equal(el('run').disabled,true);
  el('connect').click();await settle();authorizeResolve(session());await settle();
  assert.equal(el('connect').disabled,true);assert.equal(el('run').disabled,false);
  el('run').click();await settle();
  assert.equal(el('connect').disabled,false);assert.equal(el('run').disabled,true);
  assert.equal(el('rows').children.length,0);assert.match(el('status').textContent,/401/);
  w.close();
})().catch(error=>{w.close();console.error(error);process.exitCode=1;});
"""
    subprocess.run(
        ["node", "-e", script], cwd=Path(__file__).resolve().parents[1], check=True, timeout=30
    )


def test_real_shared_oauth_requests_read_only_scope_and_preserves_explorer_default():
    script = r"""
const assert=require('node:assert/strict'),fs=require('node:fs');
const {webcrypto}=require('node:crypto'),{JSDOM}=require('jsdom');
const w=new JSDOM('',{url:'https://localhost/admin/plugins/mcpserver/knx.cgi',runScripts:'outside-only'}).window;
Object.defineProperty(w,'crypto',{value:webcrypto});
for(const name of ['explorer-core.js','explorer-state.js','explorer-auth.js'])
  w.eval(fs.readFileSync('webfrontend/htmlauth/'+name,'utf8'));
const core=w.McpExplorerCore, origin='https://localhost', issuer=origin+'/plugins/mcpserver/oauth';
const metadata={issuer};
for(const [field,path]of Object.entries({authorization_endpoint:'authorize',token_endpoint:'token',
  registration_endpoint:'register',revocation_endpoint:'revoke'}))metadata[field]=issuer+'/'+path;
let registration, authorization;
w.fetch=async(url,options={})=>{
  let value;
  if(String(url).includes('oauth-protected-resource'))value={resource:origin+'/plugins/mcpserver/mcp',
    authorization_servers:[issuer],scopes_supported:core.EXPLORER_SCOPE_ORDER};
  else if(String(url).includes('.well-known/oauth-authorization-server'))value=metadata;
  else if(String(url).endsWith('/register')){registration=JSON.parse(options.body);
    value={client_id:'synthetic-client'};}
  else if(String(url).endsWith('/explorer-session')){
    const body=JSON.parse(options.body);assert.equal(body.action,'complete');
    assert.equal(body.resource,origin+'/plugins/mcpserver/mcp');
    value={access_token:'synthetic-access',scope:authorization.searchParams.get('scope'),
      expires_in:60,expires_at:Date.now()/1000+60};
  }else throw new Error('Unexpected endpoint');
  return{ok:true,json:async()=>value};
};
const popup={closed:false,close(){this.closed=true;},location:{replace(url){
  authorization=new URL(url);
  setImmediate(()=>w.dispatchEvent(new w.MessageEvent('message',{origin,
    data:{type:'mcp-explorer-oauth',
    state:authorization.searchParams.get('state'),code:'synthetic-code'}})));
}}};
const create=options=>w.McpExplorerAuth.create({core,state:{},explorerState:{},label:key=>key,
  clearOriginWarning(){},renderConnection(){},revokeAndClear(){},...options});
(async()=>{
  const readOnly=await create({requestedScopes:['loxone:read'],clientName:'KNX comparison'})
    .authorize(popup);
  assert.equal(registration.scope,'loxone:read');
  assert.equal(registration.client_name,'KNX comparison');
  assert.equal(authorization.searchParams.get('scope'),'loxone:read');
  assert.equal(readOnly.scope,'loxone:read');
  assert.equal(authorization.searchParams.get('code_challenge_method'),'S256');
  await create({}).authorize(popup);
  assert.equal(registration.scope,core.EXPLORER_SCOPE_ORDER.join(' '));
  assert.equal(registration.client_name,'LoxBerry MCP Tool Explorer');
  assert.equal(authorization.searchParams.get('scope'),core.EXPLORER_SCOPE_ORDER.join(' '));
  await assert.rejects(create({requestedScopes:['unexpected']}).authorize(popup));
  w.close();
})().catch(error=>{w.close();console.error(error);process.exitCode=1;});
"""
    subprocess.run(
        ["node", "-e", script], cwd=Path(__file__).resolve().parents[1], check=True, timeout=30
    )
