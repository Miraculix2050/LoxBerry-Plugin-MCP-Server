"""Saved KNX policy state must remain distinct from local form edits."""

import subprocess

import pytest


@pytest.mark.parametrize("prefix", ["knx-read", "knx-drafts"])
def test_saved_badge_polling_preserves_edits_revision_and_visible_tab_boundaries(prefix):
    script = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),{JSDOM}=require('jsdom');
const html=fs.readFileSync('templates/knx.html','utf8').replace(/<TMPL_VAR[^>]*>/g,'label');
const dom=new JSDOM(html,
  {url:'https://local.example/knx.cgi',runScripts:'outside-only'}), w=dom.window;
const prefix=process.argv[1], other=prefix==='knx-read'?'knx-drafts':'knx-read';
w.document.getElementById(other+'-delegation').remove();
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


@pytest.mark.parametrize("prefix", ["knx-read", "knx-drafts"])
def test_foreground_actions_queued_during_polling_execute_in_order(prefix):
    script = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),{JSDOM}=require('jsdom');
const html=fs.readFileSync('templates/knx.html','utf8').replace(/<TMPL_VAR[^>]*>/g,'label');
const dom=new JSDOM(html,{url:'https://local.example/knx.cgi',runScripts:'outside-only'}),w=dom.window;
const prefix=process.argv[1],other=prefix==='knx-read'?'knx-drafts':'knx-read';
w.document.getElementById(other+'-delegation').remove();
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
