"""Browser-domain regressions; installed browser acceptance remains a separate gate."""

from __future__ import annotations

import configparser
import html
import re
import subprocess
from pathlib import Path

import pytest


def test_import_review_and_source_overrides_use_html_controls() -> None:
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {JSDOM} = require('jsdom');
const html = fs.readFileSync('templates/knx.html', 'utf8').replace(/<TMPL_VAR[^>]*>/g, 'label');
const w = new JSDOM(html, {url: 'http://localhost/knx.cgi', runScripts: 'outside-only'}).window;
const page = w.document.getElementById('knx-page');
const ui = w.document.getElementById('knx-import-section');
const cards = [...page.querySelectorAll(':scope > details.mcp-card')];
assert.deepEqual(cards.map(card => card.id), ['knx-read-delegation', 'knx-drafts-delegation',
  'knx-write-delegation',
  'knx-corrections', 'knx-label-section',
  'knx-address-section', 'knx-project-section', 'knx-compare-section', 'knx-xml-section']);
assert(cards.every(card => card.firstElementChild.tagName === 'SUMMARY'));
assert.equal(ui.parentElement.parentElement.id, 'knx-address-section');
assert.equal(ui.parentElement.firstElementChild, ui);
assert.equal(ui.firstElementChild.querySelector('h3').textContent, 'label');
Object.assign(page.dataset, {unknown: 'Unknown', empty: 'Empty',
  override: 'Override', inherited: 'Import'});
Object.assign(ui.dataset, {target: 'Target', changed: 'Changed', additional: 'Attributes',
  review: 'Review', discarded: 'Discarded', stale: 'Stale'});
const row = {address_id: 2563, address_format: 'three_level', address: '1/2/3',
  imported: {name: 'ETS', description: 'Source', security: '<img src=x onerror="synthetic">'},
  overrides: {description: 'Local'},
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
w.holdPage = true;
w.confirm = w.alert = w.prompt = () => {throw new Error('Native dialog forbidden');};
w.fetch = async (_url, options) => {
  const action = options.body.get('action'), payload = JSON.parse(options.body.get('payload'));
  requests.push({action, payload});
  if (action === 'knx_page' && w.holdPage)
    await new Promise(resolve => {w.resumePage = resolve;});
  if (action === 'knx_page' && w.failPage)
    return {ok: true, json: async () => ({ok: false, error: {code: 'knx_revision_conflict'}})};
  if (action === 'knx_import_preview' && w.delayPreview)
    await new Promise(resolve => {w.resumePreview = resolve;});
  if (action === 'knx_import_load' && rejectUpload)
    return {ok: true, json: async () => ({ok: false, error: {code: 'knx_xml_invalid'}})};
  let data = state;
  if (action === 'knx_page' && payload.filters) {
    state.filters = {query: payload.filters.query || '', source: payload.filters.source || 'all',
      deviations_only: payload.filters.deviations_only || false};
    state.offset = payload.offset;
  }
  if (action === 'knx_import_load') {preview = structuredClone(initial); data = preview;}
  if (action === 'knx_import_preview') {
    preview.selected_groups = payload.selected_groups;
    preview.mode = payload.mode;
    preview.orphan_name_policy = payload.orphan_name_policy;
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
  const hints = [...page.querySelectorAll('[data-knx-catalog-loading]')];
  assert.equal(hints.length, 3);
  assert.equal(hints.filter(hint => hint.getAttribute('role') === 'status').length, 0);
  assert.equal(hints.filter(hint => hint.getAttribute('aria-hidden') === 'true').length, 3);
  const announcement = w.document.getElementById('knx-catalog-announcement');
  assert.equal(page.contains(announcement), false);
  assert.equal(announcement.closest('[aria-busy="true"]'), null);
  assert.equal(announcement.textContent, announcement.dataset.loading);
  assert(hints.every(hint => !hint.hidden && hint.closest('.mcp-card').ariaBusy === 'true'));
  w.holdPage = false; w.resumePage();
  await tick();
  assert(hints.every(hint => hint.hidden && !hint.closest('.mcp-card').hasAttribute('aria-busy')));
  assert.equal(announcement.textContent, '');
  assert.match(w.document.getElementById('knx-target').textContent, /Configured target/);
  assert.equal(w.document.querySelectorAll('#knx-addresses img').length, 0);
  assert.match(w.document.querySelector('.mcp-knx-sources').textContent, /<img src=x/);
  const search = w.document.getElementById('knx-search-form');
  w.document.getElementById('knx-search-query').value = 'Hidden imported name';
  w.document.getElementById('knx-search-source').value = 'both';
  w.document.getElementById('knx-search-deviations').checked = true;
  state.total = 51;
  search.dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true})); await tick();
  assert.equal(requests.at(-1).action, 'knx_page');
  assert.deepEqual(requests.at(-1).payload.filters,
    {query: 'Hidden imported name', source: 'both', deviations_only: true});
  assert.equal(requests.at(-1).payload.target, 't');
  assert.equal(w.document.getElementById('knx-address-badge').textContent, String(state.total));
  assert.equal(w.document.getElementById('knx-address-badge').hidden, false);
  w.failPage = true; await click('knx-next');
  assert.match(w.document.getElementById('knx-status').textContent, /knx_revision_conflict/);
  assert(hints.every(hint => hint.hidden));
  assert.equal(announcement.textContent, '');
  w.failPage = false;
  w.holdPage = true; w.document.getElementById('knx-next').click(); await tick();
  assert(hints.every(hint => !hint.hidden));
  assert.equal(announcement.textContent, announcement.dataset.loading);
  w.holdPage = false; w.resumePage(); await tick();
  assert(hints.every(hint => hint.hidden));
  await click('knx-next');
  assert.equal(w.document.getElementById('knx-status').textContent, '');
  assert.equal(requests.at(-1).payload.offset, 50);
  assert.equal(requests.at(-1).payload.query_revision, 1);
  assert.equal(requests.at(-1).payload.filters.query, 'Hidden imported name');
  state.total = 1; await click('knx-search-clear');
  assert.equal(w.document.getElementById('knx-address-badge').textContent, '1');
  assert.equal(w.document.getElementById('knx-search-query').value, '');
  assert.equal(w.document.getElementById('knx-search-source').value, 'all');
  assert.equal(w.document.getElementById('knx-search-deviations').checked, false);
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
  assert.equal(requests.at(-1).payload.file_format, 'auto');
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
  const mode = w.document.getElementById('knx-ets-mode');
  mode.value = 'replace'; mode.dispatchEvent(new w.Event('change', {bubbles: true})); await tick();
  assert.equal(requests.at(-1).payload.orphan_name_policy, 'retain_import_name');
  const orphan = w.document.getElementById('knx-ets-orphan-policy');
  orphan.value = 'keep_unknown';
  orphan.dispatchEvent(new w.Event('change', {bubbles: true})); await tick();
  assert.equal(requests.at(-1).payload.orphan_name_policy, 'keep_unknown');
  mode.value = 'merge'; mode.dispatchEvent(new w.Event('change', {bubbles: true})); await tick();
  mode.value = 'replace'; mode.dispatchEvent(new w.Event('change', {bubbles: true})); await tick();
  assert.equal(requests.at(-1).payload.orphan_name_policy, 'keep_unknown');
  const fileFormat = w.document.getElementById('knx-ets-file-format');
  fileFormat.value = 'csv'; fileFormat.dispatchEvent(new w.Event('change', {bubbles: true}));
  assert.equal(w.document.getElementById('knx-ets-apply').disabled, true);
  assert.equal(w.document.getElementById('knx-ets-stale').textContent, 'Stale');
  rejectUpload = true;
  await click('knx-ets-load');
  assert.equal(requests.at(-1).payload.file_format, 'csv');
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


@pytest.mark.parametrize("language", ["de", "en"])
def test_group_address_sections_and_localized_editor_titles(language):
    root = Path(__file__).resolve().parents[1]
    translations = configparser.ConfigParser(interpolation=None, strict=False)
    translations.optionxform = str
    translations.read(root / f"templates/lang/language_{language}.ini", encoding="utf-8")
    values = {
        f"{section}.{key}": value
        for section in translations.sections()
        for key, value in translations[section].items()
    }
    template = re.sub(
        r"<TMPL_VAR\s+([A-Z0-9_.]+)(?:\s+ESCAPE=HTML)?>",
        lambda match: html.escape(values.get(match[1], "fixture"), quote=True),
        (root / "templates/knx.html").read_text(encoding="utf-8"),
    )
    script = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),{JSDOM}=require('jsdom');
const w=new JSDOM(fs.readFileSync(0,'utf8'),
  {url:'https://local.example/knx.cgi',runScripts:'outside-only'}).window;
const el=id=>w.document.getElementById(id);
const sections=['knx-import-section','knx-json-section','knx-filter-section',
  'knx-results-section','knx-editor-section'];
for(let i=1;i<sections.length;i++){
  assert.equal(el(sections[i]).parentElement,el(sections[0]).parentElement);
  assert(el(sections[i-1]).compareDocumentPosition(el(sections[i]))&4);
}
assert.equal(el('knx-import-section').nextElementSibling.id,'knx-json-section');
assert.equal(el('knx-json-section').open,false);
assert(el('knx-json-section').hasAttribute('data-persist-collapse'));
for(const id of ['knx-json-import','knx-json-export','knx-json-preview','knx-json-apply'])
  assert(el('knx-json-section').contains(el(id)));
assert(el('knx-filter-section').contains(el('knx-search-form')));
assert(el('knx-results-section').contains(el('knx-addresses')));
assert(el('knx-editor-section').contains(el('knx-record-form')));
assert(el('knx-filter-section').classList.contains('mcp-knx-filter'));
const help=el('knx-json-section').textContent, german=process.argv[1]==='de';
assert(help.includes(german?'Adressseite':'address page'));
assert(el('knx-json-section').textContent.includes(process.argv[1]==='de'?'Haupt-/Mittelgruppen':'main/middle'));
assert(help.includes(german?'Rekonstruktionsherkunft':'reconstruction provenance'));
const ids=[...w.document.querySelectorAll('[id]')].map(e=>e.id);
assert.equal(ids.length,new Set(ids).size);
const state={target:'synthetic',target_display:'fixture',revision:1,taxonomy_revision:'labels',
  taxonomy:[],imported_labels:[],offset:0,total:1,items:[{address_id:2563,address:'1/2/3',
  address_format:'three_level',imported:{name:'Imported'},overrides:{},effective:{name:'Imported'},
  imported_groups:[{level:'main',prefix:'1',fields:{name:'Main'}},
    {level:'middle',prefix:'1/2',fields:{name:'Middle'}}]}]};
w.fetch=async()=>({ok:true,json:async()=>({ok:true,data:structuredClone(state)})});
const settle=async()=>{for(let i=0;i<8;i++)await new Promise(r=>setImmediate(r));};
(async()=>{
  w.eval(fs.readFileSync('webfrontend/htmlauth/knx.js','utf8'));await settle();
  const title=el('knx-editor-title'),editor=el('knx-editor-section');
  assert.equal(title.textContent,editor.dataset.newTitle);
  const cells=el('knx-addresses').querySelector('tr').children;
  assert.equal(cells[1].textContent,'1 — Main');assert.equal(cells[2].textContent,'1/2 — Middle');
  const search=el('knx-search-query');search.value='Imported';
  el('knx-search-form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));
  await settle();assert.equal(title.textContent,editor.dataset.newTitle);
  el('knx-addresses').querySelector('button').click();await settle();
  assert.equal(title.textContent,editor.dataset.editTitle.replace('{address}','1/2/3'));
  assert.equal(w.document.activeElement,el('knx-record-form').elements.namedItem('name'));
  el('knx-record-form').reset();await settle();
  assert.equal(title.textContent,editor.dataset.newTitle);
  assert.equal(el('knx-record-form').elements.namedItem('address').readOnly,false);
  w.close();
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run(
        ["node", "-e", script, language],
        input=template,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=root,
    )
    assert result.returncode == 0, result.stdout + result.stderr
