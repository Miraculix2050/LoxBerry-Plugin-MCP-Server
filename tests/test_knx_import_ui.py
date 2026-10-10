"""Browser-domain regressions; installed browser acceptance remains a separate gate."""

from __future__ import annotations

import subprocess
from pathlib import Path


def test_import_review_and_source_overrides_use_html_controls() -> None:
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {JSDOM} = require('jsdom');
const html = fs.readFileSync('templates/knx.html', 'utf8').replace(/<TMPL_VAR[^>]*>/g, 'label');
const w = new JSDOM(html, {url: 'http://localhost/knx.cgi', runScripts: 'outside-only'}).window;
const page = w.document.getElementById('knx-page');
const ui = w.document.getElementById('knx-import-section');
Object.assign(page.dataset, {unknown: 'Unknown', empty: 'Empty',
  override: 'Override', inherited: 'Import'});
Object.assign(ui.dataset, {target: 'Target', changed: 'Changed', additional: 'Attributes',
  review: 'Review', discarded: 'Discarded', stale: 'Stale'});
const row = {address_id: 2563, address_format: 'three_level', address: '1/2/3',
  imported: {name: 'ETS', description: 'Source'}, overrides: {description: 'Local'},
  effective: {name: 'ETS', description: 'Local'}};
const state = {target: 't', target_display: 'Configured target', revision: 1,
  taxonomy_revision: 'labels', items: [row], taxonomy: [], total: 1, offset: 0};
const initial = {target: 't', revision: 1, draft_id: 'd', preview_token: 'token',
  selected_groups: [], groups: [
    {identity: 'group:three_level:1', prefix: '1', fields: {name: 'Main'}},
    {identity: 'group:three_level:2', prefix: '2', fields: {name: 'Other'}}],
  groups_count: 1, addresses: 1, additions: 0, updates: 1, merged_duplicates: 0,
  conflict_count: 1, conflicts: [{identity: 'address:2563', candidates: [
    {index: 0, address: '1/2/3', fields: {name: 'A'}, source: {attributes: {Name: 'A'}}},
    {index: 1, address: '1/2/3', fields: {name: 'B'}, source: {attributes: {Name: 'B'}}}]}],
  changes: [], offset: 0, has_more: false, conflict_offset: 0, has_more_conflicts: false,
  mode: 'merge', complete_export: true, encoding: 'utf-8', address_format: 'three_level',
  removals: 0, preserved_overrides: 0, nameless_overrides: 0, name_policy_required: false};
let preview = structuredClone(initial), rejectUpload = false;
const requests = [];
w.confirm = w.alert = w.prompt = () => {throw new Error('Native dialog forbidden');};
w.fetch = async (_url, options) => {
  const action = options.body.get('action'), payload = JSON.parse(options.body.get('payload'));
  requests.push({action, payload});
  if (action === 'knx_import_preview' && w.delayPreview)
    await new Promise(resolve => {w.resumePreview = resolve;});
  if (action === 'knx_import_load' && rejectUpload)
    return {ok: true, json: async () => ({ok: false, error: {code: 'knx_xml_invalid'}})};
  let data = state;
  if (action === 'knx_import_load') {preview = structuredClone(initial); data = preview;}
  if (action === 'knx_import_preview') {
    preview.selected_groups = payload.selected_groups;
    preview.mode = payload.mode;
    if (Object.hasOwn(payload.choices, 'address:2563')) {
      preview.conflict_count = 0; preview.conflicts = [];
      preview.changes = [{address: '1/2/3', kind: 'changed', old_imported: {name: 'ETS'},
        new_imported: {name: payload.choices['address:2563'] === 1 ? 'B' : 'A'}, overrides: {}}];
    }
    data = preview;
  }
  if (action === 'knx_import_discard') data = {discarded: true};
  return {ok: true, json: async () => ({ok: true, data: structuredClone(data)})};
};
const tick = () => new Promise(resolve => setTimeout(resolve, 10));
const click = async id => {w.document.getElementById(id).click(); await tick();};
(async () => {
  w.eval(fs.readFileSync('webfrontend/htmlauth/knx.js', 'utf8'));
  w.eval(fs.readFileSync('webfrontend/htmlauth/knx-import.js', 'utf8'));
  await tick();
  assert.match(w.document.getElementById('knx-target').textContent, /Configured target/);
  const form = w.document.getElementById('knx-record-form');
  w.document.querySelector('#knx-addresses button').click();
  form.dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true})); await tick();
  assert.deepEqual(requests.at(-1).payload.record.fields, {description: 'Local'});
  w.document.querySelector('#knx-addresses button').click();
  w.document.querySelector('[data-knx-use-import="description"]').click();
  assert.equal(form.elements.namedItem('description').value, 'Source');
  form.dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true})); await tick();
  assert.deepEqual(requests.at(-1).payload.record.fields, {});
  w.document.querySelector('#knx-addresses button').click();
  form.elements.namedItem('description').value = '';
  form.elements.namedItem('description').dispatchEvent(new w.Event('input', {bubbles: true}));
  form.dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true})); await tick();
  assert.deepEqual(requests.at(-1).payload.record.fields, {description: ''});
  const file = w.document.getElementById('knx-ets-file');
  Object.defineProperty(file, 'files', {value: [{size: 6,
    arrayBuffer: async () => new Uint8Array([60, 120, 109, 108, 47, 62]).buffer}]});
  await click('knx-ets-load');
  assert.equal(w.document.getElementById('knx-ets-preview').hidden, false);
  assert.equal(w.document.getElementById('knx-ets-apply').disabled, true);
  w.document.querySelectorAll('#knx-ets-conflicts input')[1].click(); await tick();
  assert.equal(requests.at(-1).payload.choices['address:2563'], 1);
  assert.equal(w.document.getElementById('knx-ets-apply').disabled, false);
  assert.match(w.document.getElementById('knx-ets-changes').textContent, /B/);
  w.delayPreview = true;
  const boxes = w.document.querySelectorAll('#knx-ets-groups input');
  boxes[0].click();
  assert.equal(boxes[0].disabled, true);
  assert.equal(boxes[1].disabled, true);
  boxes[1].click();
  assert.equal(boxes[1].checked, false);
  w.delayPreview = false; w.resumePreview(); await tick();
  assert.deepEqual(requests.at(-1).payload.selected_groups, ['group:three_level:1']);
  rejectUpload = true;
  await click('knx-ets-load');
  assert.match(w.document.getElementById('knx-status').textContent, /knx_xml_invalid/);
  assert.match(w.document.getElementById('knx-ets-changes').textContent, /B/);
  assert.equal(w.document.getElementById('knx-ets-preview').hidden, false);
  state.revision = 2;
  w.MCPKnx.render(structuredClone(state));
  assert.equal(w.document.getElementById('knx-ets-apply').disabled, true);
  assert.equal(w.document.getElementById('knx-ets-stale').textContent, 'Stale');
  await click('knx-ets-discard');
  assert.equal(w.document.getElementById('knx-ets-preview').hidden, true);
  assert.equal(requests.at(-1).action, 'knx_import_discard');
  assert.equal(requests.some(r => r.action === 'knx_import_apply'), false);
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
    subprocess.run(
        ["node", "-e", script], check=True, cwd=Path(__file__).resolve().parents[1], timeout=30
    )
