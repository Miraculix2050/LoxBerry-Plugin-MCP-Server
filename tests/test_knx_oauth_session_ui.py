"""KNX uses the actual shared browser OAuth broker contract."""

import subprocess


def test_shared_logout_fresh_registration_and_visible_logout_failure():
    script = r"""
const assert=require('node:assert/strict'),fs=require('node:fs');
const {JSDOM}=require('jsdom'),{webcrypto}=require('node:crypto');
const html=fs.readFileSync('templates/knx.html','utf8').replace(/<TMPL_VAR[^>]*>/g,'label');
let cookie=true, logoutFails=false, registration, authorization;const actions=[];
const origin='https://localhost',issuer=origin+'/plugins/mcpserver/oauth';
const setup=()=>{
  const w=new JSDOM(html,{url:origin+'/admin/plugins/mcpserver/knx.cgi',
    runScripts:'outside-only'}).window;
  Object.defineProperty(w,'crypto',{value:webcrypto});
  Object.assign(w.document.getElementById('knx-project-section').dataset,
    {error:'Error',connected:'Connected',disconnected:'Disconnected'});
  w.MCPKnx={snapshot:()=>({target:'t',revision:1})};
  const metadata={issuer};
  for(const [key,path]of Object.entries({authorization_endpoint:'authorize',
    token_endpoint:'token',registration_endpoint:'register',revocation_endpoint:'revoke'}))
    metadata[key]=issuer+'/'+path;
  w.fetch=async(url,options={})=>{
    let value,ok=true,status=200;
    if(String(url).includes('oauth-protected-resource'))value={
      resource:origin+'/plugins/mcpserver/mcp',authorization_servers:[issuer],
      scopes_supported:w.McpExplorerCore.EXPLORER_SCOPE_ORDER};
    else if(String(url).includes('.well-known/oauth-authorization-server'))value=metadata;
    else if(String(url).endsWith('/register')){
      registration=JSON.parse(options.body);value={client_id:'client'};
    }else if(String(url).endsWith('/explorer-session')){
      const body=JSON.parse(options.body);actions.push(body.action);
      if(body.action==='logout'){
        if(logoutFails){ok=false;status=503;value={error:'logout_unavailable'};}
        else{cookie=false;status=204;value={};}
      }else if(body.action==='complete'){
        assert.equal(registration.client_name,'LoxBerry MCP Tool Explorer');
        cookie=true;value={access_token:'synthetic',scope:'loxone:read',
          expires_in:60,expires_at:Date.now()/1000+600};
      }else{
        assert.equal(body.action,'access');
        ok=cookie;status=cookie?200:401;
        value=cookie?{access_token:'synthetic',scope:'loxone:read',expires_in:60,
          expires_at:Date.now()/1000+600}:{error:'invalid_session'};
      }
    }else throw new Error('Unexpected endpoint');
    return{ok,status,json:async()=>value};
  };
  w.open=()=>({closed:false,close(){this.closed=true;},location:{replace(url){
    authorization=new URL(url);
    setImmediate(()=>w.dispatchEvent(new w.MessageEvent('message',{origin,
      data:{type:'mcp-explorer-oauth',state:authorization.searchParams.get('state'),
        code:'synthetic-code'}})));
  }}});
  for(const name of ['explorer-core.js','explorer-state.js','explorer-auth.js'])
    w.eval(fs.readFileSync('webfrontend/htmlauth/'+name,'utf8'));
  w.McpExplorerClient={create:()=>({initialize:async()=>[]})};
  w.eval(fs.readFileSync('webfrontend/htmlauth/knx-project.js','utf8'));
  return w;
};
const settle=async()=>{for(let i=0;i<12;i++)await new Promise(r=>setImmediate(r));};
const el=(w,id)=>w.document.getElementById('knx-project-'+id);
(async()=>{
  let w=setup();await settle();assert(!el(w,'disconnect').disabled);
  el(w,'disconnect').click();await settle();
  assert.equal(actions.at(-1),'logout');assert.equal(cookie,false);w.close();
  w=setup();await settle();assert(!el(w,'connect').disabled);
  assert.equal(el(w,'connection-badge').textContent,'Disconnected');
  el(w,'connect').click();
  for(let i=0;i<40 && el(w,'connect').disabled;i++)await settle();
  await settle();
  assert.equal(cookie,true);
  assert.equal(registration.scope,w.McpExplorerCore.EXPLORER_SCOPE_ORDER.join(' '));
  assert.equal(el(w,'connection-badge').textContent,'Connected');
  assert.equal(el(w,'scope-list').children[1].lastElementChild.textContent,
    w.document.getElementById('knx-project-section').dataset.scopeNotGranted);
  logoutFails=true;el(w,'disconnect').click();await settle();
  assert.equal(el(w,'status').dataset.kind,'error');
  assert.match(el(w,'status').textContent,/logout_unavailable/);assert.equal(cookie,true);
  w.close();
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
