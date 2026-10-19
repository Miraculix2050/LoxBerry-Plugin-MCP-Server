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
from mcpserver.config import AtomicConfigStore, ConfigPersistenceUncertain, PluginConfig
from mcpserver.knx.admin import dispatch_knx
from mcpserver.knx.catalog import labels_revision
from mcpserver.knx.correction_drafts import CorrectionDraftStore
from mcpserver.knx.correction_service import CorrectionService
from mcpserver.knx.model import KnxError
from mcpserver.knx.store import KnxStore


@pytest.mark.parametrize("hint", ["valid", "shortened", "missing", "target", "invalid"])
def test_initial_page_inspects_selected_draft_with_current_revision(tmp_path, monkeypatch, hint):
    target = "https://first.example"
    monkeypatch.setenv("LBPDATA", str(tmp_path))
    monkeypatch.setenv("MCPSERVER_KNX_ADMIN_SESSION", "b" * 64)
    monkeypatch.setenv("MCPSERVER_AUTH_STORE", str(tmp_path / "auth.json"))
    config = replace(PluginConfig.defaults(), loxone_endpoint=target)
    configs = AtomicConfigStore(tmp_path / "config.json")
    configs.save(config)
    store = KnxStore(tmp_path / "knx" / "metadata.sqlite3")
    owner = CorrectionDraftStore(tmp_path / "knx" / "drafts.sqlite3", "a" * 64)
    plan = CorrectionService(store, owner).plan(
        config,
        target,
        0,
        labels_revision(config, target),
        [
            dict(
                destination="local_metadata",
                kind="prefix",
                prefix="1",
                address_format="three_level",
                field="label",
                operation="set",
                value="Synthetic",
            )
        ],
    )
    created = owner.create_correction(target, 0, plan["manual_revision"], plan["changes"])
    selection = dict(
        target=hashlib.sha256(target.encode()).hexdigest(),
        draft_id=created["draft_id"],
        offset=0,
        sort=None,
    )
    if hint == "shortened":
        selection["offset"] = 10
    elif hint == "missing":
        selection["draft_id"] = "f" * 48
    elif hint == "target":
        selection["target"] = "f" * 64
    elif hint == "invalid":
        selection["offset"] = True
    page = dispatch_knx(
        "knx_page", dict(include_sections=True, initial_correction=selection), configs
    )
    inspected = page["sections"]["knx_correction_inspect"]
    assert page["sections"]["knx_correction_page"]["ok"]
    if hint in {"valid", "shortened"}:
        assert inspected["ok"]
        assert inspected["request"]["offset"] == 0
        direct = dispatch_knx(
            "knx_correction_inspect", dict(selection, offset=0, draft_revision=1), configs
        )
        assert inspected["data"] == direct
    else:
        assert not inspected["ok"]
    assert store.page(target)["total"] == 0


def test_admin_retention_management_cannot_apply_archived_or_restore_approval(
    tmp_path, monkeypatch
):
    target = "https://first.example"
    monkeypatch.setenv("LBPDATA", str(tmp_path))
    monkeypatch.setenv("MCPSERVER_KNX_ADMIN_SESSION", "b" * 64)
    config = replace(PluginConfig.defaults(), loxone_endpoint=target)
    configs = AtomicConfigStore(tmp_path / "config.json")
    configs.save(config)
    original_config = (tmp_path / "config.json").read_bytes()
    store = KnxStore(tmp_path / "knx" / "metadata.sqlite3")
    store.put(
        target, 0, dict(address="1/2/3", address_format="three_level", fields={"name": "Old"})
    )
    owner = CorrectionDraftStore(tmp_path / "knx" / "drafts.sqlite3", "a" * 64)
    service = CorrectionService(store, owner)
    plan = service.plan(
        config,
        target,
        1,
        labels_revision(config, target),
        [
            dict(
                destination="local_metadata",
                kind="address",
                address="1/2/3",
                address_format="three_level",
                field="name",
                operation="set",
                value="New",
            )
        ],
    )
    created = owner.create_correction(
        target,
        1,
        plan["manual_revision"],
        [{**row, "decision": "accepted"} for row in plan["changes"]],
    )
    manage = dict(
        target=hashlib.sha256(target.encode()).hexdigest(),
        draft_id=created["draft_id"],
        draft_revision=1,
        request_id="1" * 32,
        operation="archive",
    )
    assert dispatch_knx("knx_correction_manage", manage, configs)["managed"]
    with pytest.raises(KnxError, match="knx_correction_archived"):
        service.approved_selection(
            created["draft_id"],
            config,
            target,
            2,
            1,
            plan["manual_revision"],
            [created["changes"][0]["change_id"]],
        )
    dispatch_knx(
        "knx_correction_manage",
        dict(manage, draft_revision=2, request_id="2" * 32, operation="restore"),
        configs,
    )
    restored = owner.inspect_correction(created["draft_id"], target)
    assert restored["changes"][0]["decision"] == "proposed"
    assert (tmp_path / "config.json").read_bytes() == original_config
    assert store.page(target)["items"][0]["effective"]["name"] == "Old"
    with pytest.raises(AdminError) as denied:
        dispatch_knx("knx_correction_manage", dict(manage, target="f" * 64), configs)
    assert denied.value.code == "knx_target_conflict"
    deletion = dict(manage, draft_revision=3, request_id="3" * 32, operation="delete")
    assert dispatch_knx("knx_correction_manage", deletion, configs)["managed"]
    assert dispatch_knx("knx_correction_manage", deletion, configs)["managed"]
    with pytest.raises(AdminError) as conflict:
        dispatch_knx("knx_correction_manage", dict(deletion, draft_revision=2), configs)
    assert conflict.value.code == "knx_correction_request_conflict"
    monkeypatch.setenv("MCPSERVER_KNX_ADMIN_SESSION", "d" * 64)
    with pytest.raises(AdminError) as other_session:
        dispatch_knx("knx_correction_manage", deletion, configs)
    assert other_session.value.code == "knx_draft_unavailable"


@pytest.mark.parametrize("kind", ["address", "prefix"])
def test_admin_applies_only_confirmed_accepted_local_selection(tmp_path, monkeypatch, caplog, kind):
    caplog.set_level("INFO", logger="mcpserver.knx.admin")
    target = "https://first.example"
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
    change = dict(
        destination="local_metadata",
        kind=kind,
        address_format="three_level",
        field="name" if kind == "address" else "label",
        operation="set",
        value="Agreed",
    )
    change["address" if kind == "address" else "prefix"] = "1/2/3" if kind == "address" else "1/2"
    plan = CorrectionService(store, owner).plan(
        config, target, 1, labels_revision(config, target), [change]
    )
    created = owner.create_correction(target, 1, plan["manual_revision"], plan["changes"])
    payload = dict(
        target=hashlib.sha256(target.encode()).hexdigest(),
        draft_id=created["draft_id"],
        draft_revision=1,
        catalog_revision=1,
        manual_revision=plan["manual_revision"],
        request_id="c" * 32,
        approved_change_ids=[created["changes"][0]["change_id"]],
        storage="addresses" if kind == "address" else "prefix_labels",
        confirmed=True,
        action="apply",
    )
    with pytest.raises(AdminError) as unaccepted:
        dispatch_knx("knx_correction_apply", payload, configs)
    assert unaccepted.value.code == "knx_correction_not_accepted"
    changes = [{**row, "decision": "accepted"} for row in created["changes"]]
    owner.update_correction(created["draft_id"], target, 1, changes)
    payload["draft_revision"] = 2
    with pytest.raises(AdminError) as unconfirmed:
        dispatch_knx("knx_correction_apply", {**payload, "confirmed": False}, configs)
    assert unconfirmed.value.code == "knx_correction_invalid"
    result = dispatch_knx("knx_correction_apply", payload, configs)
    assert result["outcome"] == "applied"
    assert (
        not result["loxone_written"] and not result["import_written"] and not result["exports_file"]
    )
    # Exact receipts remain observable after the source revision changes.
    observed = dispatch_knx("knx_correction_apply", {**payload, "action": "reconcile"}, configs)
    assert observed == result
    assert dispatch_knx("knx_correction_apply", payload, configs) == result
    absent = dispatch_knx(
        "knx_correction_apply", {**payload, "action": "reconcile", "request_id": "d" * 32}, configs
    )
    assert absent["outcome"] == "not_observed" and not absent["automatic_retry_allowed"]
    assert "mode=reconcile outcome=not_observed" in caplog.text
    assert "mode=apply outcome=applied" in caplog.text
    if kind == "address":
        assert store.page(target)["items"][0]["effective"]["name"] == "Agreed"
    else:
        assert configs.load().knx_address_taxonomy[0].label == "Agreed"
        assert store.page(target)["items"][0]["effective"]["name"] == "Local"
    assert not configs.load().loxberry_knx_write_enabled
    owner.discard_correction(created["draft_id"], target, 2)
    assert (
        dispatch_knx("knx_correction_apply", {**payload, "action": "reconcile"}, configs) == result
    )
    monkeypatch.setenv("MCPSERVER_KNX_ADMIN_SESSION", "e" * 64)
    foreign = dispatch_knx("knx_correction_apply", {**payload, "action": "reconcile"}, configs)
    assert foreign["outcome"] == "not_observed"


def test_admin_project_bound_selection_cannot_use_browser_binding(tmp_path, monkeypatch):
    target = "https://first.example"
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
                field="name",
                operation="set",
                value="Agreed",
            )
        ],
    )
    created = owner.create_correction(
        target,
        1,
        plan["manual_revision"],
        [{**row, "decision": "accepted"} for row in plan["changes"]],
        project_binding="unverified-project",
    )
    payload = dict(
        target=hashlib.sha256(target.encode()).hexdigest(),
        draft_id=created["draft_id"],
        draft_revision=1,
        catalog_revision=1,
        manual_revision=plan["manual_revision"],
        request_id="c" * 32,
        approved_change_ids=[created["changes"][0]["change_id"]],
        storage="addresses",
        confirmed=True,
        action="apply",
    )
    with pytest.raises(AdminError) as bound:
        dispatch_knx("knx_correction_apply", payload, configs)
    assert bound.value.code == "knx_project_evidence_required"
    with pytest.raises(AdminError):
        dispatch_knx(
            "knx_correction_apply", {**payload, "project_binding": "unverified-project"}, configs
        )
    assert store.page(target)["items"][0]["effective"]["name"] == "Local"


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


def test_correction_inspection_service_has_no_eager_project_analysis_import():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import mcpserver.knx.correction_service; "
            "assert 'mcpserver.loxone.project.analysis' not in sys.modules; "
            "assert 'mcpserver.loxone.project.ets_comparison' not in sys.modules",
        ],
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
    data={target:'b'.repeat(64),draft_id:draft.draft_id,draft_revision:draft.draft_revision};
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


@pytest.mark.parametrize("error_code", [None, "persistence_uncertain", "knx_revision_conflict"])
def test_admin_local_apply_confirms_full_value_and_reconciles_without_retry(error_code):
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {JSDOM} = require('jsdom');
const html=fs.readFileSync('templates/knx.html','utf8').replace(/<TMPL_VAR[^>]*>/g,'label');
const dom=new JSDOM(html,{url:'https://local.example/knx.cgi',runScripts:'outside-only'});
const w=dom.window, calls=[];
const draft={draft_id:'a'.repeat(48),draft_revision:2,catalog_revision:1,
 manual_revision:'b'.repeat(64)};
const full='Full synthetic agreed name';
const failure=ERROR_CODE;
const item={change_id:'c'.repeat(24),identity:'1/2/3',kind:'address',field:'name',operation:'set',
 destination:'local_metadata',decision:'accepted',imported:{state:'missing'},manual:{state:'value',value:'Original'},
 proposed:{state:'value',value:'truncated',truncated:true}};
let confirm=false,questions=[];
w.MCPKnx={ask:async text=>{questions.push(text);return confirm;}};
w.confirm=()=>{throw Error('native dialog forbidden');};
w.fetch=async (_,options)=>{
 const action=options.body.get('action'), payload=JSON.parse(options.body.get('payload'));
 calls.push({action,payload});
 let data;
 if(action==='knx_correction_page') data={
 target:'d'.repeat(64),drafts:[{...draft,change_count:1,expires_at:2000000000}]};
 else if(action==='knx_correction_apply') {
   if(payload.action==='apply') {
    if(!failure) throw Error('uncertain response');
    return {ok:true,json:async()=>({ok:false,error:{code:failure}})};
   }
   data={outcome:'applied'};
 } else data={draft,next_offset:null,catalog_stale:false,manual_stale:false,
 project_status:'not_required',
   changes:[payload.detail?{...item,proposed:{state:'value',value:full}}:item]};
 return {ok:true,json:async()=>({ok:true,data})};
};
const tick=()=>new Promise(r=>setTimeout(r,0));
(async()=>{
 w.eval(fs.readFileSync('webfrontend/htmlauth/knx-corrections.js','utf8'));
 await tick();await tick();
 w.document.querySelector('#knx-corrections-list button').click();
 await tick();await tick();
 w.document.querySelector('#knx-corrections-values button').click();
 await tick();await tick();
 assert.equal(calls.filter(c=>c.action==='knx_correction_apply').length,0);
 assert.ok(questions[0].includes(full));assert.ok(!questions[0].includes('truncated'));
 confirm=true;w.document.querySelector('#knx-corrections-values button').click();
 await tick();await tick();
 assert.equal(calls.filter(c=>c.action==='knx_correction_apply').length,1);
 const first=calls.at(-1).payload;
 assert.deepEqual(first.approved_change_ids,[item.change_id]);assert.equal(first.storage,'addresses');
 const reconcile=w.document.getElementById('knx-corrections-reconcile');
 assert.equal(reconcile.hidden,failure==='knx_revision_conflict');
 if(failure==='knx_revision_conflict') {
  assert.equal(w.sessionStorage.getItem('mcp-knx-admin-pending-apply-v1'),null);
  dom.window.close();return;
 }
 const retained=w.sessionStorage.getItem('mcp-knx-admin-pending-apply-v1');
 assert.ok(retained && !retained.includes(full));
 const resumed=new JSDOM(html,{url:'https://local.example/knx.cgi',runScripts:'outside-only'});
 const other=resumed.window;other.fetch=w.fetch;other.MCPKnx=w.MCPKnx;
 other.sessionStorage.setItem('mcp-knx-admin-pending-apply-v1',retained);
 other.eval(fs.readFileSync('webfrontend/htmlauth/knx-corrections.js','utf8'));
 await tick();await tick();
 const recovered=other.document.getElementById('knx-corrections-reconcile');
 assert.equal(recovered.hidden,false);
 recovered.click();
 await tick();await tick();
 const observed=calls.at(-1).payload;
 assert.equal(observed.action,'reconcile');assert.equal(observed.request_id,first.request_id);
 assert.equal(calls.filter(c=>c.payload.action==='apply').length,1);
 assert.equal(recovered.hidden,true);
 resumed.window.close();dom.window.close();
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    script = script.replace("ERROR_CODE", "null" if error_code is None else repr(error_code))
    node = shutil.which("node")
    assert node is not None
    result = subprocess.run(
        [node, "-e", script],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_admin_apply_audit_retains_uncertain_outcome(tmp_path, monkeypatch, caplog):
    caplog.set_level("INFO", logger="mcpserver.knx.admin")
    configs = AtomicConfigStore(tmp_path / "config.json")

    def uncertain(operation):
        raise ConfigPersistenceUncertain("Synthetic durability uncertainty")

    monkeypatch.setattr(configs, "transaction", uncertain)
    with pytest.raises(ConfigPersistenceUncertain):
        dispatch_knx("knx_correction_apply", {"action": "apply"}, configs)
    assert "mode=apply outcome=uncertain" in caplog.text
    assert "Synthetic durability uncertainty" not in caplog.text


@pytest.mark.parametrize("mode, expected", [("apply", "uncertain"), ("reconcile", "rejected")])
def test_admin_storage_error_audit_matches_uncertain_apply(
    tmp_path, monkeypatch, caplog, mode, expected
):
    caplog.set_level("INFO", logger="mcpserver.knx.admin")
    configs = AtomicConfigStore(tmp_path / "config.json")

    def failed(operation):
        raise KnxError("knx_storage_failed")

    monkeypatch.setattr(configs, "transaction", failed)
    with pytest.raises(AdminError):
        dispatch_knx("knx_correction_apply", {"action": mode}, configs)
    assert f"mode={mode} outcome={expected}" in caplog.text


@pytest.mark.parametrize("mode, outcome", [("apply", "uncertain"), ("reconcile", "rejected")])
def test_bridged_storage_failure_audit_matches_operation(
    tmp_path, monkeypatch, caplog, mode, outcome
):
    from mcpserver.knx import admin_bridge

    configs = AtomicConfigStore(tmp_path / "config.json")
    monkeypatch.setenv("HTTP_X_LOXONE_AUTHORIZATION", "Bearer synthetic")

    def failed(*args):
        raise AdminError("Synthetic storage failure", code="knx_storage_failed")

    monkeypatch.setattr(admin_bridge, "forward", failed)
    caplog.set_level("INFO", logger="mcpserver.knx.admin")
    with pytest.raises(AdminError):
        dispatch_knx("knx_correction_apply", {"action": mode}, configs)
    assert f"mode={mode} outcome={outcome}" in caplog.text
    assert "Synthetic storage failure" not in caplog.text


@pytest.mark.parametrize(
    "scenario",
    [
        "reload",
        "bootstrap",
        "bundled",
        "bundled_revision",
        "bundled_sort",
        "missing",
        "target",
        "blocked",
        "malformed",
        "shortened",
        "expired",
        "read_failure",
    ],
)
def test_selected_draft_survives_reload_using_only_fresh_server_data(scenario):
    script = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),{JSDOM}=require('jsdom');
const html=fs.readFileSync('templates/knx.html','utf8').replace(/<TMPL_VAR[^>]*>/g,'label');
const source=fs.readFileSync('webfrontend/htmlauth/knx-corrections.js','utf8');
const mode=process.argv[1],key='mcp-knx-admin-draft-view-v1',saved=new Map();
const calls=[];let generation=1;
const create=()=>{
 const w=new JSDOM(html,{url:'https://local.example/knx.cgi',runScripts:'outside-only'}).window;
 Object.defineProperty(w,'sessionStorage',{value:{getItem:k=>{
  if(mode==='blocked')throw Error('blocked');return saved.get(k)||null;},
  setItem:(k,v)=>{if(mode==='blocked')throw Error('blocked');saved.set(k,v);},
  removeItem:k=>saved.delete(k)}});
 const target=generation===2&&mode==='target'?'c'.repeat(64):'b'.repeat(64);
 const draft={draft_id:'a'.repeat(48),draft_revision:generation,expires_at:2000000000,
  change_count:generation===2&&mode==='shortened'?5:21};
 const page={target,drafts:generation===2&&mode==='missing'?[]:[draft]};
 w.document.getElementById('knx-corrections').dataset.selectionUnavailable='Unavailable';
 if(generation===2&&mode==='bootstrap')w.MCPKnx={initialSections:Promise.resolve({
  knx_correction_page:{ok:true,data:page}})};
 w.fetch=async(_,options)=>{
  const action=options.body.get('action'),payload=JSON.parse(options.body.get('payload'));
  calls.push({action,payload,generation});
  if(generation===2&&action==='knx_correction_inspect'&&mode==='read_failure')
   throw Error('offline');
  if(generation===2&&action==='knx_correction_inspect'&&mode==='expired')
   return{ok:true,json:async()=>({ok:false,error:{code:'knx_draft_expired'}})};
  if(action==='knx_correction_inspect')assert.equal(payload.draft_revision,generation);
  const field={state:'value',value:generation===1?'old value':'fresh value',truncated:false};
  const data=action==='knx_correction_page'?page:{draft,next_offset:payload.offset===0?10:null,
   catalog_stale:false,manual_stale:false,project_status:'not_required',changes:[{
    change_id:'d'.repeat(24),identity:'1/2/3',field:'name',operation:'set',destination:'ets_export',
    decision:'accepted',imported:field,manual:field,proposed:field}]};
  return{ok:true,json:async()=>({ok:true,data})};
 };
 if(generation===2&&mode.startsWith('bundled')){
  const field={state:'value',value:'fresh value',truncated:false};
  w.MCPKnx={initialSections:Promise.resolve({knx_correction_page:{ok:true,data:page},
   knx_correction_inspect:{ok:true,request:{target,draft_id:draft.draft_id,offset:10,
    sort:mode==='bundled_sort'?{field:'address',direction:'ascending'}:null},
    data:{target,draft:{...draft,draft_revision:mode==='bundled_revision'?1:2},next_offset:null,
     catalog_stale:false,manual_stale:false,project_status:'not_required',changes:[{
      change_id:'d'.repeat(24),identity:'1/2/3',field:'name',operation:'set',destination:'ets_export',
      decision:'accepted',imported:field,manual:field,proposed:field}]}}})};
 }
 w.eval(source);return w;
};
const settle=async()=>{for(let i=0;i<8;i++)await new Promise(r=>setImmediate(r));};
(async()=>{
 let w=create();await settle();w.document.querySelector('#knx-corrections-list button').click();
 await settle();w.document.getElementById('knx-corrections-more').click();await settle();
 if(mode!=='blocked'){
  const record=JSON.parse(saved.get(key));
  assert.deepEqual(Object.keys(record).sort(),['draft_id','offset','target']);assert.equal(record.offset,10);
 }
 w.close();generation=2;if(mode==='malformed')saved.set(key,'{"offset":-1}');
 w=create();await settle();
 const reads=calls.filter(c=>c.generation===2&&c.action==='knx_correction_inspect');
 if(['missing','target','blocked','malformed'].includes(mode)){
  assert.equal(reads.length,0);
  assert.equal(w.document.querySelectorAll('#knx-corrections-values tr').length,0);
  if(['missing','target'].includes(mode))assert.equal(saved.has(key),false);
 }else if(mode==='expired'){
  assert.equal(saved.has(key),false);
  assert.equal(w.document.getElementById('knx-corrections-status').textContent,'Unavailable');
 }else if(mode==='read_failure'){
  assert(saved.has(key));
  assert.equal(w.document.querySelectorAll('#knx-corrections-values tr').length,0);
  assert.equal(w.document.getElementById('knx-corrections').dataset.loadFailed,'true');
 }else{
  assert.equal(reads.length,mode==='bundled'?0:1);
  if(reads.length)assert.equal(reads[0].payload.offset,mode==='shortened'?0:10);
  assert(w.document.getElementById('knx-corrections-values').textContent.includes('fresh value'));
  const choice=w.document.querySelector('#knx-corrections-values input[type=checkbox]');
  assert.equal(choice.checked,false);
 }
 w.close();
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run(
        ["node", "-e", script, scenario], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("failure", ["write", "refresh"])
def test_decision_failure_preserves_view_and_never_replays_uncertain_write(failure):
    script = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),{JSDOM}=require('jsdom');
const html=fs.readFileSync('templates/knx.html','utf8').replace(/<TMPL_VAR[^>]*>/g,'label');
const w=new JSDOM(html,{url:'https://local.example/knx.cgi',runScripts:'outside-only'}).window;
const ui=w.document.getElementById('knx-corrections'),mode=process.argv[1],calls=[];
Object.assign(ui.dataset,{accept:'Accept',accepted:'Accepted',proposed:'Proposed',
 savedRefreshFailed:'Saved; refresh failed',decisionUnconfirmed:'Unconfirmed'});
const target='b'.repeat(64),draft={draft_id:'a'.repeat(48),draft_revision:1,expires_at:2000000000,
 change_count:1,catalog_revision:1,manual_revision:'labels'};
let fail=true,decision='proposed';
w.fetch=async(_,options)=>{
 const action=options.body.get('action'),payload=JSON.parse(options.body.get('payload'));
 calls.push(action);
 if(action==='knx_correction_review'){
  decision='accepted';draft.draft_revision++;
  if(mode==='write')throw Error('response lost');
  return{ok:true,json:async()=>({ok:true,data:{target,draft_id:draft.draft_id,
   draft_revision:draft.draft_revision}})};
 }
 if(action==='knx_correction_inspect'&&draft.draft_revision>1&&fail)throw Error('read failed');
 const field={state:'value',value:'Complete target',truncated:false};
 const data=action==='knx_correction_page'?{target,drafts:[{...draft}]}:
  {draft:{...draft},next_offset:null,
  catalog_stale:false,manual_stale:false,project_status:'not_required',changes:[{
   change_id:'d'.repeat(24),identity:'1/2/3',field:'name',operation:'set',destination:'local_metadata',
   decision,imported:field,manual:field,proposed:field}]};
 return{ok:true,json:async()=>({ok:true,data})};
};
const settle=async()=>{for(let i=0;i<8;i++)await new Promise(r=>setImmediate(r));};
(async()=>{
 w.eval(fs.readFileSync('webfrontend/htmlauth/knx-corrections.js','utf8'));await settle();
 w.document.querySelector('#knx-corrections-list button').click();await settle();
 const before=calls.length;w.document.querySelector('#knx-corrections-values summary').click();
 await settle();assert.equal(calls.length,before); // Complete editor values need no request.
 assert.equal(w.document.querySelector('#knx-corrections-values textarea').value,'Complete target');
 [...w.document.querySelectorAll('#knx-corrections-values button')]
  .find(b=>b.textContent==='Accept').click();
 await settle();assert.equal(calls.filter(a=>a==='knx_correction_review').length,1);
 assert.equal(calls.filter(a=>a==='knx_correction_page').length,1); // No redundant list refresh.
 assert.equal(w.document.querySelectorAll('#knx-corrections-values tr').length,1);
 assert([...w.document.querySelectorAll('#knx-corrections-values button')].every(b=>b.disabled));
 assert.equal(w.document.getElementById('knx-corrections-status').textContent,
  mode==='write'?'Unconfirmed':'Saved; refresh failed');
 // Core catalog operations must not re-enable stale correction actions.
 const page=w.document.getElementById('knx-page');page.setAttribute('aria-busy','true');
 await settle();
 page.querySelectorAll('input,select,textarea,button').forEach(control=>control.disabled=false);
 page.removeAttribute('aria-busy');page.dispatchEvent(new w.Event('knx-idle'));await settle();
 assert([...w.document.querySelectorAll('#knx-corrections-values button')].every(b=>b.disabled));
 fail=false;w.document.getElementById('knx-corrections-reload').click();await settle();
 assert.equal(calls.filter(a=>a==='knx_correction_review').length,1);
 assert(w.document.getElementById('knx-corrections-values').textContent.includes('Accepted'));
 assert.equal(ui.dataset.loadFailed,'false');w.close();
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run(
        ["node", "-e", script, failure], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stdout + result.stderr
