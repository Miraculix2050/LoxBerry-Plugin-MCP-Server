"""Comparison UI stays read-only, source-aware and bound to current page state."""

import subprocess


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
  await click('knx-compare-clear');
  assert.deepEqual(JSON.parse(JSON.stringify(requests.at(-1))),
    {action: 'knx_compare_discard', payload: {target: 'target'}});
  assert.equal(w.document.getElementById('knx-compare-count').textContent, '');
  assert.equal(w.message, 'Cleared');
  assert(requests.every(item => item.action.startsWith('knx_compare_')));
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
