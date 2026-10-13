"""Admin inspection of shared proposals does not expand delegated MCP ownership."""

import hashlib
import os
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from mcpserver.admin import AdminError
from mcpserver.config import AtomicConfigStore, PluginConfig
from mcpserver.knx.admin import dispatch_knx
from mcpserver.knx.catalog import labels_revision
from mcpserver.knx.correction_drafts import CorrectionDraftStore
from mcpserver.knx.correction_service import CorrectionService
from mcpserver.knx.model import KnxError
from mcpserver.knx.store import KnxStore


@pytest.mark.parametrize("combined", [False, True])
def test_draft_list_does_not_load_project_analysis(tmp_path, combined):
    script = """
import os, sys
from pathlib import Path
from dataclasses import replace
from mcpserver.config import AtomicConfigStore, PluginConfig
from mcpserver.knx.admin import dispatch_knx
path = Path(sys.argv[1])
os.environ['LBPDATA'] = str(path)
os.environ['MCPSERVER_KNX_ADMIN_SESSION'] = 'a' * 64
os.environ['MCPSERVER_AUTH_STORE'] = str(path / 'auth.json')
store = AtomicConfigStore(path / 'config.json')
store.save(replace(PluginConfig.defaults(), loxone_endpoint='https://local.example'))
combined = sys.argv[2] == 'True'
result = dispatch_knx('knx_page' if combined else 'knx_correction_page',
                      {'include_sections': True} if combined else {}, store)
drafts = result['sections']['knx_correction_page']['data'] if combined else result
assert drafts['drafts'] == []
for module in ('mcpserver.knx.correction_service', 'mcpserver.loxone.project.analysis',
               'mcpserver.loxone.project.ets_comparison'):
    assert module not in sys.modules, module
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path), str(combined)],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_admin_inspects_same_owner_draft_without_transferring_ownership(tmp_path, monkeypatch):
    target = "https://first.example"
    token = hashlib.sha256(target.encode()).hexdigest()
    monkeypatch.setenv("LBPDATA", str(tmp_path))
    monkeypatch.setenv("MCPSERVER_KNX_ADMIN_SESSION", "b" * 64)
    config = replace(PluginConfig.defaults(), loxone_endpoint=target)
    configs = AtomicConfigStore(tmp_path / "config.json")
    configs.save(config)
    store = KnxStore(tmp_path / "knx" / "metadata.sqlite3")
    store.put(
        target, 0, dict(address="1/2/3", address_format="three_level", fields={"name": "Local"})
    )
    owner = CorrectionDraftStore(tmp_path / "knx" / "drafts.sqlite3", "a" * 64)
    plan = CorrectionService(store, owner).plan(
        config,
        target,
        1,
        labels_revision(config, target),
        [
            dict(
                destination="local_metadata",
                kind="address",
                address_format="three_level",
                address="1/2/3",
                field="description",
                operation="set",
                value="<img src=x>",
            )
        ],
    )
    created = owner.create_correction(target, 1, plan["manual_revision"], plan["changes"])
    page = dispatch_knx("knx_correction_page", {}, configs)
    assert page["target"] == token
    assert len(page["drafts"]) == 1
    assert "owner" not in page["drafts"][0]
    payload = dict(target=token, draft_id=created["draft_id"], draft_revision=1)
    inspected = dispatch_knx("knx_correction_inspect", payload, configs)
    assert inspected["changes"][0]["proposed"]["value"] == "<img src=x>"
    assert inspected["applies_changes"] is False
    shared = {**payload, "catalog_revision": 1, "manual_revision": plan["manual_revision"]}
    change_id = created["changes"][0]["change_id"]
    reviewed = dispatch_knx(
        "knx_correction_review",
        {
            **shared,
            "request_id": "a" * 32,
            "decisions": [{"change_id": change_id, "decision": "accepted"}],
        },
        configs,
    )
    assert reviewed["draft_revision"] == 2 and reviewed["applies_changes"] is False
    edited = dispatch_knx(
        "knx_correction_edit",
        {
            **shared,
            "draft_revision": 2,
            "request_id": "b" * 32,
            "change_id": change_id,
            "edit": {"operation": "set", "value": ""},
        },
        configs,
    )
    assert edited["draft_revision"] == 3
    own = owner.inspect_correction(created["draft_id"], target)
    assert own["changes"][0]["decision"] == "proposed"
    assert own["changes"][0]["value"] == ""
    assert own["expires_at"] == created["expires_at"]
    foreign = CorrectionDraftStore(owner.path, "c" * 64)
    assert foreign.list_corrections(target) == []
    with pytest.raises(KnxError, match="knx_draft_unavailable"):
        foreign.inspect_correction(created["draft_id"], target)
    owner.update_correction(created["draft_id"], target, 3, plan["changes"])
    with pytest.raises(AdminError) as stale:
        dispatch_knx("knx_correction_inspect", payload, configs)
    assert stale.value.code == "knx_revision_conflict"
    assert store.page(target)["items"][0]["effective"]["name"] == "Local"


def test_shared_admin_inspection_requires_session_and_current_target(tmp_path, monkeypatch):
    monkeypatch.setenv("LBPDATA", str(tmp_path))
    monkeypatch.delenv("MCPSERVER_KNX_ADMIN_SESSION", raising=False)
    configs = AtomicConfigStore(tmp_path / "config.json")
    configs.save(replace(PluginConfig.defaults(), loxone_endpoint="https://first.example"))
    token = hashlib.sha256(b"https://first.example").hexdigest()
    with pytest.raises(AdminError) as missing:
        dispatch_knx("knx_correction_page", {"target": token}, configs)
    assert missing.value.code == "knx_session_missing"
    monkeypatch.setenv("MCPSERVER_KNX_ADMIN_SESSION", "b" * 64)
    with pytest.raises(AdminError) as switched:
        dispatch_knx("knx_correction_page", {"target": "foreign"}, configs)
    assert switched.value.code == "knx_target_conflict"


def test_shared_view_escapes_sources_and_binds_continuation_revision():
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {JSDOM} = require('jsdom');
const html = fs.readFileSync('templates/knx.html', 'utf8').replace(/<TMPL_VAR[^>]*>/g, 'label');
const dom = new JSDOM(html, {url: 'https://local.example/knx.cgi', runScripts: 'outside-only'});
const w = dom.window;
for (const id of ['knx-drafts-delegation', 'knx-corrections']) {
  const card = w.document.getElementById(id);
  assert.equal(card.tagName, 'DETAILS');
  assert.equal(card.open, true);
  card.querySelector(':scope > summary').click();
  assert.equal(card.open, false);
  card.querySelector(':scope > summary').click();
  assert.equal(card.open, true);
}
w.confirm = () => {throw new Error('Native confirmations forbidden');};
const calls = [];
let pause = true, resume, fail = false;
const draft = {draft_id: 'a'.repeat(48), draft_revision: 3,
  expires_at: 2000000000, change_count: 11};
const field = {state: 'value', value: '<img src=x onerror=attack()>', truncated: false};
w.fetch = async (_, options) => {
  const action = options.body.get('action');
  const payload = JSON.parse(options.body.get('payload'));
  calls.push({action, payload});
  if (pause) await new Promise(resolve => {resume = resolve;});
  if (fail) throw new Error('Synthetic correction read failure');
  const data = action === 'knx_correction_page' ? {target: 'b'.repeat(64), drafts: [draft]}
    : {draft, next_offset: payload.offset === 0 ? 10 : null, catalog_stale: true,
       manual_stale: false, project_status: 'not_checked', changes: [{identity: '1/2/3',
       field: 'description', operation: 'set', destination: 'local_metadata', imported: field,
       manual: {state: 'missing'}, proposed: {...field, value: ''}}]};
  return {ok: true, json: async () => ({ok: true, data})};
};
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
(async () => {
  w.eval(fs.readFileSync('webfrontend/htmlauth/knx-corrections.js', 'utf8'));
  const loading = w.document.getElementById('knx-corrections-loading');
  const announcement = w.document.getElementById('knx-corrections-announcement');
  assert.equal(loading.hidden, false);
  assert.equal(announcement.closest('[aria-busy="true"]'), null);
  assert.equal(w.document.getElementById('knx-page').contains(announcement), false);
  assert.equal(announcement.textContent, announcement.dataset.loading);
  pause = false; resume();
  await tick();
  assert.equal(loading.hidden, true);
  assert.equal(announcement.textContent, '');
  w.document.querySelector('#knx-corrections-list button').click(); await tick();
  const rows = w.document.getElementById('knx-corrections-values');
  assert.equal(rows.querySelector('img'), null);
  assert.match(rows.textContent, /<img src=x/);
  assert.equal(w.document.getElementById('knx-corrections-more').hidden, false);
  w.document.getElementById('knx-corrections-more').click(); await tick();
  assert.equal(calls.at(-1).payload.draft_revision, 3);
  assert.equal(calls.at(-1).payload.offset, 10);
  assert.equal(w.document.getElementById('knx-corrections-more').hidden, true);
  assert.deepEqual(calls.map(item => item.action),
    ['knx_correction_page', 'knx_correction_inspect', 'knx_correction_inspect']);
  pause = true; fail = true;
  w.document.getElementById('knx-corrections-reload').click(); await tick();
  assert.equal(loading.hidden, false);
  pause = false; resume(); await tick();
  assert.equal(loading.hidden, true);
  assert.equal(announcement.textContent, '');
  assert.equal(w.document.getElementById('knx-corrections-status').textContent,
    w.document.getElementById('knx-corrections').dataset.failed);
  dom.window.close();
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
    node = shutil.which("node")
    assert node is not None
    result = subprocess.run(
        [node, "-e", script],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_shared_view_review_and_full_value_edit_use_html_controls_only():
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {JSDOM} = require('jsdom');
const html = fs.readFileSync('templates/knx.html', 'utf8').replace(/<TMPL_VAR[^>]*>/g, 'label');
const dom = new JSDOM(html, {url: 'https://local.example/knx.cgi', runScripts: 'outside-only'});
const w = dom.window;
for (const name of ['confirm','prompt','alert']) w[name] = () => {throw Error('Native dialog');};
const section = w.document.getElementById('knx-corrections');
Object.assign(section.dataset, {accepted:'Accepted', rejected:'Rejected', proposed:'Proposed',
  accept:'Accept', reject:'Reject', reset:'Reset', valueLabel:'Proposed target',
  edit:'Edit', saveEdit:'Save', operation:'Operation', set:'Set', remove:'Remove'});
const draft = {draft_id:'a'.repeat(48), draft_revision:1, expires_at:2000000000,
  change_count:1, catalog_revision:5, manual_revision:'c'.repeat(64)};
const full = '<script>literal</script>' + 'x'.repeat(400);
let decision = 'proposed', proposed = full;
const calls = [];
w.fetch = async (_, options) => {
  const action=options.body.get('action'), payload=JSON.parse(options.body.get('payload'));
  calls.push({action,payload});
  let data;
  if (action === 'knx_correction_page') data={target:'b'.repeat(64),drafts:[{...draft}]};
  else if (action === 'knx_correction_review' || action === 'knx_correction_edit') {
    assert.equal(payload.draft_revision, draft.draft_revision);
    assert.equal(payload.catalog_revision,5);
    assert.equal(payload.manual_revision,'c'.repeat(64));
    assert.match(payload.request_id,/^[0-9a-f]{32}$/);
    if (action === 'knx_correction_review') decision=payload.decisions[0].decision;
    else {proposed=payload.edit.value;decision='proposed';}
    draft.draft_revision++;
    data={draft_revision:draft.draft_revision};
  } else data={draft:{...draft},next_offset:null,catalog_stale:false,manual_stale:false,
    project_status:'not_required',changes:[{change_id:'d'.repeat(24),identity:'1/2/3',
      destination:'local_metadata',field:'description',operation:'set',decision,
      imported:{state:'missing'},manual:{state:'value',value:'source',truncated:false},
      proposed:{state:'value',value:payload.detail?proposed:proposed.slice(0,128),
                truncated:!payload.detail && proposed.length>128}}]};
  return {ok:true,json:async()=>({ok:true,data})};
};
const tick=()=>new Promise(resolve=>setTimeout(resolve,0));
(async()=>{
  w.eval(fs.readFileSync('webfrontend/htmlauth/knx-corrections.js','utf8'));
  await tick();
  w.document.querySelector('#knx-corrections-list button').click();await tick();
  let row=w.document.querySelector('#knx-corrections-values tr');
  assert.equal(row.querySelector('script'),null);
  [...row.querySelectorAll('button')].find(b=>b.textContent==='Accept').click();await tick();
  assert.equal(decision,'accepted');
  row=w.document.querySelector('#knx-corrections-values tr');
  row.querySelector('details summary').click();await tick();await tick();
  const textarea=row.querySelector('textarea');
  assert.equal(textarea.parentElement.textContent,'Proposed target');
  assert.equal(textarea.closest('form').className,'mcp-form');
  assert.equal(textarea.value,full); // Never save a truncated projection.
  assert.equal(calls.at(-1).payload.detail,true);
  textarea.value='';
  row.querySelector('form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));
  await tick();
  assert.equal(proposed,'');assert.equal(decision,'proposed');
  const edit=calls.find(c=>c.action==='knx_correction_edit').payload;
  assert.deepEqual(edit.edit,{operation:'set',value:''});
  assert.equal('owner' in edit,false);
  assert.equal(draft.draft_revision,3);
  assert.equal(w.document.querySelector('#knx-corrections-values script'),null);
  dom.window.close();
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    node = shutil.which("node")
    assert node is not None
    result = subprocess.run(
        [node, "-e", script],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
