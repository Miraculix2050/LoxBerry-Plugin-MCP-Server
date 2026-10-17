"""Saved KNX policy state must remain distinct from local form edits."""

import subprocess

import pytest


@pytest.mark.parametrize("prefix", ["knx-read", "knx-drafts", "knx-write"])
def test_saved_badge_polling_preserves_edits_revision_and_visible_tab_boundaries(prefix):
    script = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),{JSDOM}=require('jsdom');
const html=fs.readFileSync('templates/knx.html','utf8').replace(/<TMPL_VAR[^>]*>/g,'label');
const dom=new JSDOM(html,
  {url:'https://local.example/knx.cgi',runScripts:'outside-only'}), w=dom.window;
const prefix=process.argv[1];
for(const other of ['knx-read','knx-drafts','knx-write'])
  if(other!==prefix)w.document.getElementById(other+'-delegation').remove();
const section=w.document.getElementById(prefix+'-delegation');
const el=id=>w.document.getElementById(prefix+'-'+id);
Object.assign(section.dataset,{enabled:'Enabled',disabled:'Disabled',unknown:'Unknown',failed:'Failed'});
let hidden=false, pause=false, resume, fail=false, saved=false, revision='r1';
let expectedRevision='r1';
Object.defineProperty(w.document,'hidden',{get:()=>hidden});
let sequence=0; const timers=new Map(),calls=[];
w.setTimeout=(fn,delay)=>{const id=++sequence;timers.set(id,{fn,delay});return id;};
w.clearTimeout=id=>timers.delete(id);
w.fetch=async(_,options)=>{
  const action=options.body.get('action'),payload=JSON.parse(options.body.get('payload'));
  calls.push({action,payload});
  if(pause)await new Promise(resolve=>resume=resolve);
  if(fail)return{ok:false,json:async()=>({ok:false})};
  if(action.endsWith('_enable')){
    assert.equal(payload.policy_revision,expectedRevision); // Preserve the original edit revision.
    return{ok:false,json:async()=>({ok:false})};
  }
  return{ok:true,json:async()=>({ok:true,data:{target:'t',enabled:saved,policy_revision:revision,bindings:[]}})};
};
const settle=async()=>{for(let i=0;i<6;i++)await new Promise(r=>setImmediate(r));};
const fire=async()=>{assert.equal(timers.size,1);const [id,t]=[...timers][0];
  timers.delete(id);t.fn();await settle();};
(async()=>{
  w.eval(fs.readFileSync('webfrontend/htmlauth/knx-read-delegation.js','utf8'));await settle();
  assert.equal(el('badge').textContent,'Disabled');assert.equal(el('badge').dataset.kind,'inactive');
  assert.equal([...timers.values()][0].delay,10000);
  // Prepare an unsaved disable before another browser enables the policy.
  el('enabled').dispatchEvent(new w.Event('change'));saved=true;revision='r2';
  pause=true;const pending=fire();await settle();
  assert(el('loading').hidden);assert.equal(section.getAttribute('aria-busy'),null);
  w.document.dispatchEvent(new w.Event('visibilitychange'));await fire();
  assert.equal(calls.length,2); // No overlapping refresh while the first request is pending.
  pause=false;resume();await pending;await settle();
  assert.equal(el('badge').textContent,'Enabled');assert.equal(el('enabled').checked,false);
  el('enable-form').dispatchEvent(new w.Event('submit',{cancelable:true}));await settle();
  assert.equal(calls.at(-1).payload.policy_revision,'r1');assert.equal(el('badge').textContent,'Unknown');
  hidden=true;w.document.dispatchEvent(new w.Event('visibilitychange'));assert.equal(timers.size,0);
  hidden=false;w.document.dispatchEvent(new w.Event('visibilitychange'));
  assert.equal([...timers.values()][0].delay,0);
  fail=true;await fire();assert.equal(el('badge').textContent,'Unknown');
  assert(el('loading').hidden);
  fail=false;await fire();assert.equal(el('badge').textContent,'Enabled');
  assert.equal(el('enabled').checked,false);assert.equal(el('announcement').textContent,'');
  // A submit without local change must still bind value and revision before the poll finishes.
  saved=false;revision='r3';el('reload').click();await settle();expectedRevision='r3';
  saved=true;revision='r4';pause=true;const next=fire();await settle();
  el('enable-form').dispatchEvent(new w.Event('submit',{cancelable:true}));
  pause=false;resume();await next;await settle();
  assert.equal(calls.at(-1).payload.policy_revision,'r3');
  assert.equal(calls.at(-1).payload.enabled,false);
  // Poll completion cannot unlock controls while a catalog operation is pending.
  pause=true;const poll=fire();await settle();
  const page=w.document.getElementById('knx-page');page.setAttribute('aria-busy','true');
  await settle();pause=false;resume();await poll;await settle();
  assert(el('enabled').disabled);assert(el('reload').disabled);
  page.removeAttribute('aria-busy');page.dispatchEvent(new w.Event('knx-idle'));await settle();
  assert(!el('enabled').disabled);
  // Global completion cannot unlock a foreground delegation request either.
  pause=true;el('reload').click();await settle();page.setAttribute('aria-busy','true');
  page.removeAttribute('aria-busy');
  section.querySelectorAll('button,input').forEach(e=>e.disabled=false);
  page.dispatchEvent(new w.Event('knx-idle'));await settle();assert(el('enabled').disabled);
  pause=false;resume();await settle();assert(!el('enabled').disabled);
  dom.window.close();
})().catch(error=>{dom.window.close();console.error(error);process.exitCode=1;});
"""
    result = subprocess.run(
        ["node", "-e", script, prefix], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("prefix", ["knx-read", "knx-drafts", "knx-write"])
def test_foreground_actions_queued_during_polling_execute_in_order(prefix):
    script = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),{JSDOM}=require('jsdom');
const html=fs.readFileSync('templates/knx.html','utf8').replace(/<TMPL_VAR[^>]*>/g,'label');
const dom=new JSDOM(html,{url:'https://local.example/knx.cgi',runScripts:'outside-only'}),w=dom.window;
const prefix=process.argv[1];
for(const other of ['knx-read','knx-drafts','knx-write'])
  if(other!==prefix)w.document.getElementById(other+'-delegation').remove();
const el=id=>w.document.getElementById(prefix+'-'+id);
Object.defineProperty(w.document,'hidden',{get:()=>false});
const calls=[],timers=new Map();let sequence=0,pause=false,resume,active=0,maxActive=0;
w.setTimeout=(fn,delay)=>{const id=++sequence;timers.set(id,fn);return id;};
w.clearTimeout=id=>timers.delete(id);
const data={target:'t',enabled:false,policy_revision:'r1',bindings:[
  {binding:'binding',eligible:true,approved:false,retained:true}]};
w.fetch=async(_,options)=>{
  const action=options.body.get('action');calls.push(action);
  active++;maxActive=Math.max(maxActive,active);
  if(pause)await new Promise(resolve=>resume=resolve);
  active--;return{ok:true,json:async()=>({ok:true,data})};
};
const dialog=w.document.getElementById('knx-confirm');
dialog.showModal=()=>{dialog.returnValue='continue';dialog.dispatchEvent(new w.Event('close'));};
const settle=async()=>{for(let i=0;i<10;i++)await new Promise(r=>setImmediate(r));};
(async()=>{
  w.eval(fs.readFileSync('webfrontend/htmlauth/knx-read-delegation.js','utf8'));await settle();
  pause=true;const [id,timer]=[...timers][0];timers.delete(id);timer();await settle();
  assert(!el('reload').disabled);
  const buttons=[...el('bindings').querySelectorAll('button')];
  el('enable-form').dispatchEvent(new w.Event('submit',{cancelable:true}));
  assert(el('reload').disabled);assert(el('enabled').disabled);
  // Already delivered events must also survive; queueing cannot overwrite a prior action.
  el('reload').dispatchEvent(new w.Event('click'));
  buttons.forEach(button=>button.dispatchEvent(new w.Event('click')));
  assert.equal(calls.length,2);
  pause=false;resume();await settle();
  const actionPrefix=prefix.replace('-','_');
  assert.deepEqual(calls.map(action=>action.slice(actionPrefix.length)),
    ['_page','_page','_enable','_page','_grant','_revoke']);
  assert.equal(maxActive,1);assert(!el('reload').disabled);assert(!el('enabled').disabled);
  assert.equal(timers.size,1);dom.window.close();
})().catch(error=>{dom.window.close();console.error(error);process.exitCode=1;});
"""
    result = subprocess.run(
        ["node", "-e", script, prefix], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_knx_section_cards_preserve_reload_state_without_extra_requests():
    script = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),{JSDOM}=require('jsdom');
const html=fs.readFileSync('templates/knx.html','utf8').replace(/<TMPL_VAR[^>]*>/g,'label');
const source=fs.readFileSync('webfrontend/htmlauth/knx.js','utf8');
const key='mcpserver.knx.sections.v1', admin='mcpserver.admin.sections.v2';
const saved=new Map([[admin,'{"help":false}']]);
const setOpen=async(view,id,open)=>{
  const card=view.card(id);if(card.open===open)return;
  const toggled=new Promise(resolve=>card.addEventListener('toggle',resolve,{once:true}));
  card.open=open;await toggled;
};
const make=(mode='normal',url='https://local.example/knx.cgi')=>{
  const dom=new JSDOM(html,{url,runScripts:'outside-only'}),w=dom.window;
  let requests=0,errors=0;
  w.addEventListener('error',()=>errors++);
  Object.defineProperty(w,'localStorage',{get:()=>{
    if(mode==='blocked')throw Error('storage blocked');
    return {getItem:k=>saved.get(k)??null,setItem:(k,v)=>{
      if(mode==='write-blocked')throw Error('write blocked');
      saved.set(k,v);
    }};
  }});
  w.fetch=()=>{requests++;return new Promise(()=>{});};
  w.eval(source);
  return {dom,w,card:id=>w.document.getElementById(id),requests:()=>requests,errors:()=>errors};
};
(async()=>{
  let view=make();
  const ids=[...view.w.document.querySelectorAll('details[data-persist-collapse]')].map(e=>e.id);
  const expected=['knx-read-delegation','knx-drafts-delegation','knx-write-delegation',
    'knx-corrections','knx-label-section','knx-address-section','knx-import-section','knx-json-section',
    'knx-advanced-labels','knx-group-management','knx-individual-addresses',
    'knx-project-section','knx-compare-section','knx-xml-section'];
  const collapsed=new Set(['knx-json-section','knx-advanced-labels','knx-group-management']);
  assert.deepEqual(ids.slice().sort(),expected.sort());
  assert(ids.every(id=>view.card(id).open===!collapsed.has(id)));
  await setOpen(view,'knx-json-section',true);view.dom.window.close();view=make();
  assert.equal(view.card('knx-json-section').open,true);
  await setOpen(view,'knx-json-section',false);
  const requests=view.requests();
  for(const id of ['knx-read-delegation','knx-label-section',
    'knx-address-section','knx-import-section'])
    await setOpen(view,id,false);
  assert.equal(view.requests(),requests);
  const state=JSON.parse(saved.get(key));
  assert.deepEqual(Object.keys(state).sort(),ids.sort());
  assert(Object.values(state).every(v=>typeof v==='boolean'));
  view.dom.window.close();
  view=make('normal','https://local.example/knx.cgi?lang=en');
  for(const id of ['knx-read-delegation','knx-label-section',
    'knx-address-section','knx-import-section'])
    assert.equal(view.card(id).open,false);
  assert.equal(view.card('knx-project-section').open,true);
  await setOpen(view,'knx-import-section',true);view.dom.window.close();
  view=make();
  assert.equal(view.card('knx-address-section').open,false);
  assert.equal(view.card('knx-import-section').open,true);
  await setOpen(view,'knx-address-section',true);await setOpen(view,'knx-label-section',true);
  view.dom.window.close();
  view=make();
  assert.equal(view.card('knx-read-delegation').open,false);
  assert.equal(view.card('knx-label-section').open,true);
  assert.equal(view.card('knx-address-section').open,true);
  assert.equal(view.card('knx-import-section').open,true);
  view.dom.window.close();assert.equal(saved.get(admin),'{"help":false}');
  for(const malformed of ['{','null','[]','"invalid"','{"knx-label-section":"false"}']){
    saved.set(key,malformed);view=make();
    assert(ids.every(id=>view.card(id).open===!collapsed.has(id)));view.dom.window.close();
  }
  saved.set(key,'{"knx-label-section":false}');
  for(const mode of ['blocked','write-blocked']){
    view=make(mode);
    assert.equal(view.card('knx-label-section').open,mode==='blocked');
    await setOpen(view,'knx-label-section',true);
    await setOpen(view,'knx-read-delegation',false);
    assert.equal(view.card('knx-read-delegation').open,false);
    assert.equal(view.errors(),0);view.dom.window.close();
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    subprocess.run(["node", "-e", script], check=True, timeout=30)


@pytest.mark.parametrize("failure", ["none", "section", "request"])
def test_initial_hydration_uses_one_request_and_recovers_independent_sections(failure):
    script = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),{JSDOM}=require('jsdom');
let html=fs.readFileSync('templates/knx.html','utf8');
const failure=process.argv[1],calls=[],timers=new Map();
let resume,serial=0;
const data={target:'synthetic',target_display:'synthetic',revision:0,taxonomy_revision:'t1',
  items:[],taxonomy:[],imported_labels:[],offset:0,total:0,
  sections:{knx_read_page:{ok:true,data:{target:'synthetic',enabled:true,
    policy_revision:'read-r1',bindings:[]}},knx_drafts_page:{ok:true,data:{target:'synthetic',
    enabled:false,policy_revision:'draft-r1',bindings:[]}},
    knx_write_page:{ok:true,data:{target:'synthetic',enabled:false,
      policy_revision:'write-r1',bindings:[]}},
    knx_correction_page:{ok:true,data:{target:'synthetic',drafts:[]}}}};
if(failure==='section')data.sections.knx_read_page={ok:false,error:{code:'internal_error'}};
const envelope=failure==='request'?{ok:false,error:{code:'internal_error'}}:{ok:true,data};
html=html.replace(/<TMPL_VAR[^>]*>/g,'label');
const dom=new JSDOM(html,{url:'https://local.example/knx.cgi',runScripts:'outside-only'}),w=dom.window;
const read={target:'synthetic',enabled:true,policy_revision:'read-r1',bindings:[]};
const drafts={target:'synthetic',enabled:false,policy_revision:'draft-r1',bindings:[]};
const write={target:'synthetic',enabled:false,policy_revision:'write-r1',bindings:[]};
const corrections={target:'synthetic',drafts:[]};
w.setTimeout=(fn,delay)=>{timers.set(++serial,{fn,delay});return serial;};
w.clearTimeout=id=>timers.delete(id);
w.fetch=async(_,options)=>{
  const action=options.body.get('action'),payload=JSON.parse(options.body.get('payload'));
  calls.push({action,payload});
  if(action==='knx_page'){
    assert.equal(payload.include_sections,true);await new Promise(resolve=>resume=resolve);
    if(failure==='request')throw Error('synthetic failure');
    return {ok:true,json:async()=>envelope};
  }
  const data={knx_read_page:read,knx_drafts_page:drafts,knx_write_page:write,
    knx_correction_page:corrections}[action];
  assert(data);return{ok:true,json:async()=>({ok:true,data})};
};
const settle=async()=>{for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));};
(async()=>{
  for(const file of ['knx.js','knx-import.js','knx-read-delegation.js','knx-corrections.js'])
    w.eval(fs.readFileSync('webfrontend/htmlauth/'+file,'utf8'));
  const initialRequests=1;
  await settle();assert.equal(calls.length,initialRequests);
  assert.equal(w.document.getElementById('knx-page').getAttribute('aria-busy'),'true');
  resume();await settle();assert.equal(calls.length,1);
  assert.equal(w.document.getElementById('knx-initial-state'),null);
  assert.equal(w.document.querySelectorAll('[aria-busy="true"]').length,0);
  assert.equal(w.document.getElementById('knx-ets-apply').disabled,true);
  assert.equal(w.document.getElementById('knx-ets-previous').disabled,true);
  assert.equal(w.document.getElementById('knx-ets-next').disabled,true);
  if(failure==='none'){
    assert.equal(w.document.getElementById('knx-read-enabled').checked,true);
    assert.equal(w.document.getElementById('knx-drafts-enabled').checked,false);
    assert.equal(w.document.getElementById('knx-read-enabled').disabled,false);
  } else {
    assert.equal(w.document.getElementById('knx-read-badge').dataset.kind,undefined);
    assert.equal(w.document.getElementById('knx-read-enabled').disabled,true);
  }
  if(failure!=='request'){
    assert.equal(w.document.getElementById('knx-drafts-enabled').disabled,false);
    assert.equal(w.document.getElementById('knx-write-enabled').disabled,false);
    assert.equal(w.document.getElementById('knx-write-badge').dataset.kind,'inactive');
  }
  w.document.getElementById('knx-read-reload').click();await settle();
  assert.equal(calls[initialRequests].action,'knx_read_page');
  assert.equal(w.document.getElementById('knx-read-enabled').checked,true);
  // Late subscribers still receive the completed initial result without another request.
  const initial=await w.MCPKnx.initialSections;
  assert.equal(initial===null,failure==='request');
  assert.equal(calls.length,initialRequests+1);dom.window.close();
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    subprocess.run(["node", "-e", script, failure], check=True, timeout=30)
