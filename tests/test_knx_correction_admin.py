"""Admin inspection of shared proposals does not expand delegated MCP ownership."""

import hashlib
import shutil
import subprocess
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
    foreign = CorrectionDraftStore(owner.path, "c" * 64)
    assert foreign.list_corrections(target) == []
    with pytest.raises(KnxError, match="knx_draft_unavailable"):
        foreign.inspect_correction(created["draft_id"], target)
    owner.update_correction(created["draft_id"], target, 1, plan["changes"])
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
