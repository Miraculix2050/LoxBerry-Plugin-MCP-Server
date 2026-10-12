"""Comparison UI stays read-only, source-aware and bound to current page state."""

import subprocess

import pytest


def test_comparison_sources_paging_late_responses_and_html_only_controls():
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {JSDOM} = require('jsdom');
const html = fs.readFileSync('templates/knx.html', 'utf8').replace(/<TMPL_VAR[^>]*>/g, 'label');
const w = new JSDOM(html, {url: 'http://localhost/knx.cgi', runScripts: 'outside-only'}).window;
const page = w.document.getElementById('knx-page');
const ui = w.document.getElementById('knx-compare-section');
Object.assign(page.dataset, {unknown: 'Unknown', empty: 'Empty'});
Object.assign(ui.dataset, {
  summary: '{address_added}/{address_removed}/{address_changed}/{address_manual}',
  info: '{file_format}:{encoding}:{scope}', before: 'Before', after: 'After', changed: 'Changed',
  manual: 'Manual', partial: 'Partial', complete: 'Complete', stale: 'Stale', catalog: 'Catalog',
  fileOnly: 'Files exclude local overrides', cleared: 'Cleared'});
let state = {target: 'target', revision: 7, taxonomy_revision: 'labels'};
let delayed = null, resume = null;
const requests = [], errors = [], pending = [];
w.confirm = w.alert = w.prompt = () => {throw new Error('Native dialog forbidden');};
const row = n => ({kind: 'address', identity: String(n), address_id: n, change: 'changed',
  before_address: '0/0/'+n, after_address: '0/0/'+n,
  before_format: 'three_level', after_format: 'three_level',
  before: {name: '<img src=x onerror="synthetic">'}, after: {name: 'After', description: ''},
  changed_fields: ['name', 'description'], manual: {description: 'Local override'}});
w.MCPKnx = {snapshot: () => state, message: text => {w.message = text;},
  run: operation => {const task = operation().catch(error => {errors.push(error.message);})
    .finally(() => page.dispatchEvent(new w.CustomEvent('knx-idle')));
    pending.push(task); return task;},
  api: async (action, payload) => {
    requests.push({action, payload});
    if (action === 'knx_compare_load') return {target: state.target, revision: state.revision,
      taxonomy_revision: state.taxonomy_revision,
      draft_id: payload.side, side: payload.side, file_format: 'xml', encoding: 'utf-8',
      complete_export: payload.complete_export, addresses: 51, groups: 0, merged_duplicates: 0};
    if (action === 'knx_compare_discard') return {discarded: true};
    assert.equal(action, 'knx_compare_page');
    const result = {target: state.target, revision: state.revision,
      taxonomy_revision: state.taxonomy_revision, offset: payload.offset,
      rows: Array.from({length: payload.offset ? 1 : 50}, (_,n) => row(n+payload.offset)),
      total: 51,
      has_more: !payload.offset, counts: {address: {added: 0, removed: 0, changed: 51, manual: 0}},
      left: {completeness: payload.left_id === 'current' ? 'unknown' : 'complete'},
      right: {completeness: 'partial'},
      manual_scope: payload.left_id === 'current' ? 'current_catalog_only' : 'not_part_of_files'};
    if (delayed) await new Promise(resolve => {resume = resolve;});
    return result;
  }};
for (const side of ['left','right']) Object.defineProperty(
  w.document.getElementById(`knx-compare-${side}-file`), 'files',
  {configurable: true, value: [{size: 1, arrayBuffer: async () => new Uint8Array([120]).buffer}]});
w.eval(fs.readFileSync('webfrontend/htmlauth/knx-compare.js', 'utf8'));
const click = async id => {
  w.document.getElementById(id).click(); await Promise.all(pending.splice(0));};
(async () => {
  const file = w.document.getElementById('knx-compare-right-file');
  for (const side of ['left','right']) Object.defineProperty(
    w.document.getElementById(`knx-compare-${side}-file`), 'files',
    {configurable: true, value: []});
  page.dispatchEvent(new w.CustomEvent('knx-idle'));
  assert(w.document.getElementById('knx-compare-clear').disabled);
  Object.defineProperty(file, 'files', {configurable: true,
    value: [{size: 1, arrayBuffer: async () => new Uint8Array([120]).buffer}]});
  file.dispatchEvent(new w.Event('change'));
  assert(!w.document.getElementById('knx-compare-clear').disabled);
  assert(w.document.getElementById('knx-compare-run').disabled);
  await click('knx-compare-right-load');
  assert.equal(requests[0].payload.file, 'eA==');
  assert.equal(requests[0].payload.file_format, 'auto');
  assert.equal(requests[0].payload.complete_export, false);
  assert(!w.document.getElementById('knx-compare-run').disabled);
  await click('knx-compare-run');
  assert.equal(requests.at(-1).payload.left_id, 'current');
  assert.equal(w.document.getElementById('knx-compare-count').textContent, '1\u201350 / 51');
  assert.equal(w.document.querySelectorAll('#knx-compare-rows img').length, 0);
  assert.match(w.document.getElementById('knx-compare-rows').textContent, /Unknown/);
  assert.match(w.document.getElementById('knx-compare-rows').textContent, /Empty/);
  assert.match(w.document.getElementById('knx-compare-rows').textContent, /Local override/);
  await click('knx-compare-next');
  assert.equal(requests.at(-1).payload.offset, 50);
  assert.equal(w.document.getElementById('knx-compare-count').textContent, '51\u201351 / 51');
  assert(w.document.getElementById('knx-compare-next').disabled);
  const mode = w.document.getElementById('knx-compare-mode');
  mode.value = 'file'; mode.dispatchEvent(new w.Event('change'));
  Object.defineProperty(w.document.getElementById('knx-compare-left-file'), 'files',
    {configurable: true, value: [{size: 1,
      arrayBuffer: async () => new Uint8Array([120]).buffer}]});
  await click('knx-compare-left-load'); await click('knx-compare-run');
  assert.equal(requests.at(-1).payload.left_id, 'left');
  assert.match(w.document.getElementById('knx-compare-scope').textContent,
    /Files exclude local overrides/);
  delayed = true; w.document.getElementById('knx-compare-next').click();
  await new Promise(resolve => setImmediate(resolve));
  state = {target: 'target', revision: 8, taxonomy_revision: 'labels'};
  page.dispatchEvent(new w.CustomEvent('knx-state'));
  resume(); await Promise.all(pending.splice(0)); delayed = false;
  assert.equal(errors.at(-1), 'knx_revision_conflict');
  assert(w.document.getElementById('knx-compare-run').disabled);
  mode.value = 'current'; mode.dispatchEvent(new w.Event('change'));
  await click('knx-compare-right-load');
  // The unused earlier input may be stale in current-catalog mode.
  assert(!w.document.getElementById('knx-compare-run').disabled);
  await click('knx-compare-run');
  state = {...state, taxonomy_revision: 'changed-labels'};
  page.dispatchEvent(new w.CustomEvent('knx-state'));
  assert(w.document.getElementById('knx-compare-next').disabled);
  assert(w.document.getElementById('knx-compare-run').disabled);
  assert.equal(w.document.getElementById('knx-compare-stale').textContent, 'Stale');
  w.document.getElementById('knx-compare-right-file').dispatchEvent(new w.Event('change'));
  for (const side of ['left','right']) Object.defineProperty(
    w.document.getElementById(`knx-compare-${side}-file`), 'files',
    {configurable: true, value: []});
  page.dispatchEvent(new w.CustomEvent('knx-idle'));
  assert(!w.document.getElementById('knx-compare-clear').disabled); // Retained server drafts.
  await click('knx-compare-clear');
  assert.deepEqual(JSON.parse(JSON.stringify(requests.at(-1))),
    {action: 'knx_compare_discard', payload: {target: 'target'}});
  assert.equal(w.document.getElementById('knx-compare-count').textContent, '');
  assert.equal(w.message, 'Cleared');
  assert(w.document.getElementById('knx-compare-clear').disabled);
  assert(requests.every(item => item.action.startsWith('knx_compare_')));
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("feature", ["compare", "xml"])
@pytest.mark.parametrize("failure", ["network", "json", "preflight"])
def test_uncertain_draft_responses_remain_discardable(feature, failure):
    script = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),{JSDOM}=require('jsdom');
const html=fs.readFileSync('templates/knx.html','utf8').replace(/<TMPL_VAR[^>]*>/g,'label');
const dom=new JSDOM(html,{url:'https://local.example/knx.cgi',runScripts:'outside-only'});
const w=dom.window,page=w.document.getElementById('knx-page');
const feature=process.argv[1],failure=process.argv[2];
const el=id=>w.document.getElementById('knx-'+feature+'-'+id);
const state={target:'target',revision:1,taxonomy_revision:'labels'};
let source={...state,binding:'project',items:[{address_id:1,project_objects:[],
  local_metadata:{address:'0/0/1',imported:{name:'ETS'}}}]};
const requests=[],pending=[],errors=[];let persisted=false,failDiscard=true;
w.MCPKnx={snapshot:()=>state,message:text=>{w.message=text;},
  run:operation=>{
    page.setAttribute('aria-busy','true');page.dispatchEvent(new w.Event('knx-idle'));
    const task=operation().catch(error=>errors.push(error.message)).finally(()=>{
      page.removeAttribute('aria-busy');page.dispatchEvent(new w.Event('knx-idle'));
    });pending.push(task);return task;
  },
  api:async(action,payload)=>{
    requests.push({action,payload});
    if(action.endsWith('_load')||action.endsWith('_preview')){
      persisted=true;
      if(failure==='network')throw new Error('connection_lost');
      return JSON.parse('{'); // Server saved the draft, but the response cannot be decoded.
    }
    assert.equal(action,'knx_'+feature+'_discard');
    if(failDiscard)throw new Error('discard_unavailable');
    persisted=false;return{discarded:true};
  }};
w.MCPKnxProject={snapshot:()=>source,validate:async()=>{
  if(failure==='preflight')throw new Error('permission_denied');
}};
let selectedFiles=[{size:1,arrayBuffer:async()=>{
  if(failure==='preflight')throw new Error('file_unavailable');
  return new Uint8Array([120]).buffer;
}}];
if(feature==='compare'){
  Object.defineProperty(el('right-file'),'files',{get:()=>selectedFiles});
  Object.defineProperty(el('left-file'),'files',{get:()=>[]});
}
w.eval(fs.readFileSync('webfrontend/htmlauth/knx-'+
  (feature==='compare'?'compare':'xml-export')+'.js','utf8'));
const click=async id=>{el(id).click();await Promise.all(pending.splice(0));};
(async()=>{
  if(feature==='xml')el('rows').querySelector('input[type="checkbox"]').click();
  await click(feature==='compare'?'right-load':'preview');
  assert.equal(errors.length,1);assert(!el('clear').disabled);
  if(failure==='preflight'){
    assert.equal(requests.length,0);assert(!persisted);
    await click('clear');assert.equal(requests.length,0);
  }
  // Forget local files/selection and invalidate the source after the failed request.
  if(feature==='compare'){
    selectedFiles=[];el('right-file').dispatchEvent(new w.Event('change'));
  }else{
    source=null;page.dispatchEvent(new w.Event('knx-project-state'));
  }
  if(failure==='preflight'){
    assert(el('clear').disabled);dom.window.close();return;
  }
  assert(persisted);assert(!el('clear').disabled);
  await click('clear');assert.equal(errors.at(-1),'discard_unavailable');
  assert(persisted);assert(!el('clear').disabled);assert.equal(w.message,undefined);
  failDiscard=false;await click('clear');
  assert(!persisted);assert(el('clear').disabled);
  assert.equal(requests.filter(item=>item.action.endsWith('_discard')).length,2);
  assert.equal(requests.filter(item=>!item.action.endsWith('_discard')).length,1);
  assert.deepEqual(JSON.parse(JSON.stringify(requests.at(-1).payload)),{target:'target'});
  dom.window.close();
})().catch(error=>{dom.window.close();console.error(error);process.exitCode=1;});
"""
    result = subprocess.run(
        ["node", "-e", script, feature, failure],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
