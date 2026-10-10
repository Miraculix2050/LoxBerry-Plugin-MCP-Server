from __future__ import annotations

import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from mcpserver.admin import AdminError
from mcpserver.config import AtomicConfigStore, PluginConfig
from mcpserver.knx.admin import dispatch_knx
from mcpserver.knx.model import KnxError, address
from mcpserver.knx.store import KnxStore
from mcpserver.loxone.project.taxonomy import AddressTaxonomyEntry


def record(name: str = "Additional name") -> dict[str, object]:
    return {
        "address": "1/2/3",
        "address_format": "three_level",
        "fields": {"name": name, "description": "", "dpts": ["DPST-1-1"]},
    }


def test_address_identity_preserves_display_and_rejects_variants() -> None:
    assert address("1/2/3", "three_level")[0] == address("1/515", "two_level")[0]
    for value in ("1/8/3", "32/0/0", "1/2/256", "01/2/3", "1/2/3:0"):
        with pytest.raises(KnxError):
            address(value, "three_level")


def test_store_target_isolation_concurrent_revision_and_restart(tmp_path: Path) -> None:
    store = KnxStore(tmp_path / "catalog.sqlite3")
    assert store.put("target-a", 0, record()) == 1
    with pytest.raises(KnxError, match="revision_conflict"):
        store.put("target-a", 0, record("Stale"))
    assert (
        KnxStore(store.path).page("target-a")["items"][0]["effective"]["name"] == "Additional name"
    )
    assert store.page("target-b")["total"] == 0
    assert store.delete("target-a", 1, address("1/2/3", "three_level")[0]) == 2
    assert store.page("target-a")["total"] == 0


def test_exchange_is_validated_before_commit_and_contains_no_target(tmp_path: Path) -> None:
    store = KnxStore(tmp_path / "catalog.sqlite3")
    store.put("private-target", 0, record())
    document = store.export("private-target")
    assert "private-target" not in str(document)
    store.restore("another-target", 0, document)
    assert store.page("another-target")["items"] == store.page("private-target")["items"]
    document["records"].append(document["records"][0])
    with pytest.raises(KnxError, match="duplicate"):
        store.restore("another-target", 1, document)
    assert store.page("another-target")["revision"] == 1


def test_admin_target_and_revision_binding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LBPDATA", str(tmp_path))
    config_store = AtomicConfigStore(tmp_path / "config.json")
    config_store.save(replace(PluginConfig.defaults(), loxone_endpoint="http://192.168.10.20"))
    state = dispatch_knx("knx_page", {}, config_store)
    dispatch_knx(
        "knx_put", {"target": state["target"], "revision": 0, "record": record()}, config_store
    )
    config_store.mutate(lambda c: replace(c, loxone_endpoint="http://192.168.10.21"))
    with pytest.raises(AdminError, match="target changed"):
        dispatch_knx(
            "knx_put", {"target": state["target"], "revision": 1, "record": record()}, config_store
        )
    assert dispatch_knx("knx_page", {}, config_store)["total"] == 0
    config_store.mutate(lambda c: replace(c, loxone_endpoint="http://192.168.10.20"))
    assert dispatch_knx("knx_page", {}, config_store)["total"] == 1


def test_prefix_labels_survive_two_target_switches(tmp_path: Path) -> None:
    store = AtomicConfigStore(tmp_path / "config.json")
    store.save(
        replace(
            PluginConfig.defaults(),
            loxone_endpoint="http://192.168.10.22",
            knx_address_taxonomy_endpoint="http://192.168.10.22",
            knx_address_taxonomy=(AddressTaxonomyEntry("1/2", "A", "three_level"),),
        )
    )
    store.mutate(lambda c: replace(c, loxone_endpoint="http://192.168.10.23"))
    store.mutate(
        lambda c: replace(
            c,
            knx_address_taxonomy_endpoint="http://192.168.10.23",
            knx_address_taxonomy=(AddressTaxonomyEntry("1/2", "B", "three_level"),),
        )
    )
    store.mutate(lambda c: replace(c, loxone_endpoint="http://192.168.10.22"))
    assert store.load().knx_address_taxonomy[0].label == "A"
    store.mutate(lambda c: replace(c, loxone_endpoint="http://192.168.10.23"))
    assert store.load().knx_address_taxonomy[0].label == "B"


def test_knx_page_uses_authenticated_narrow_same_origin_boundary() -> None:
    root = Path(__file__).resolve().parents[1]
    cgi = (root / "webfrontend/htmlauth/knx.cgi").read_text(encoding="utf-8")
    js = (root / "webfrontend/htmlauth/knx.js").read_text(encoding="utf-8")
    assert "MCPServer::RequestSecurity::same_origin_post()" in cgi
    assert "knx_put|knx_delete|knx_export|knx_restore|knx_taxonomy" in cgi
    assert "textContent = value" in js
    assert "taxonomy_revision: labelsRevision ?? state.taxonomy_revision" in js
    assert 'href="knx.cgi"' in (root / "templates/index.html").read_text(encoding="utf-8")


def test_browser_preserves_independent_drafts_and_locks_edited_address() -> None:
    root = Path(__file__).resolve().parents[1]
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {JSDOM} = require('jsdom');
const html = fs.readFileSync('templates/knx.html', 'utf8').replace(/<TMPL_VAR[^>]*>/g, 'label');
const dom = new JSDOM(html, {url: 'http://localhost/knx.cgi', runScripts: 'outside-only'});
const w = dom.window;
const record = {address_id: 2563, address: '1/2/3', address_format: 'three_level',
  effective: {name: 'Additional'}, overrides: {name: 'Additional'}, imported: {}};
let state = {target: 'target', revision: 1, taxonomy_revision: 'labels', offset: 0,
  total: 1, items: [record],
  taxonomy: [{address_format: 'three_level', prefix: '1/2', label: 'Saved'}]};
w.confirm = () => true;
w.fetch = async (_url, options) => {
  const action = options.body.get('action');
  w.requests = (w.requests || []).concat(action);
  w.lastPayload = JSON.parse(options.body.get('payload'));
  if (action === 'knx_put' && w.lastPayload.revision !== state.revision) {
    return {ok: true, json: async () =>
      ({ok: false, error: {code: 'knx_revision_conflict'}})};
  }
  if (action === 'knx_put') state.revision += 1;
  return {ok: true, json: async () => ({ok: true, data: structuredClone(state)})};
};
const tick = () => new Promise(resolve => setTimeout(resolve, 10));
(async () => {
  w.eval(fs.readFileSync('webfrontend/htmlauth/knx.js', 'utf8'));
  await tick();
  assert.equal(w.document.getElementById('knx-count').textContent, '1\u20131 / 1');
  const labels = w.document.getElementById('knx-taxonomy-entries');
  const form = w.document.getElementById('knx-record-form');
  labels.value = '3:1/2=Unsaved'; labels.dispatchEvent(new w.Event('input', {bubbles: true}));
  form.elements.namedItem('address').value = '1/2/4';
  form.elements.namedItem('name').value = 'New additional name';
  form.dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
  await tick();
  assert.equal(labels.value, '3:1/2=Unsaved');
  const unload = new w.Event('beforeunload', {cancelable: true});
  w.dispatchEvent(unload); assert.equal(unload.defaultPrevented, true);
  w.document.querySelector('#knx-addresses button').click();
  assert.equal(form.elements.namedItem('address').readOnly, true);
  assert.equal(form.elements.namedItem('name').value, 'Additional');
  state.revision += 1; state.total = 100;
  w.document.getElementById('knx-next').disabled = false;
  w.document.getElementById('knx-next').click(); await tick();
  form.dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true})); await tick();
  assert.match(w.document.getElementById('knx-status').textContent, /knx_revision_conflict/);
  assert.equal(w.lastPayload.revision, state.revision - 1);
  state.taxonomy_revision = 'changed-labels';
  w.document.getElementById('knx-next').disabled = false;
  w.document.getElementById('knx-next').click(); await tick();
  w.document.getElementById('knx-taxonomy-form').dispatchEvent(
    new w.Event('submit', {bubbles: true, cancelable: true})); await tick();
  assert.equal(w.lastPayload.taxonomy_revision, 'labels');
  labels.dispatchEvent(new w.Event('input', {bubbles: true}));
  state.target = 'different-target'; state.total = 100;
  w.document.getElementById('knx-next').disabled = false;
  w.document.getElementById('knx-next').click(); await tick();
  assert.match(w.document.getElementById('knx-status').textContent, /knx_target_conflict/);
  form.dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true})); await tick();
  // The old target remains bound to the retained edit after rejected refresh.
  form.reset(); assert.equal(form.elements.namedItem('address').readOnly, false);
  const stillDirty = new w.Event('beforeunload', {cancelable: true});
  w.dispatchEvent(stillDirty); assert.equal(stillDirty.defaultPrevented, true);
  dom.window.close();
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    node = shutil.which("node")
    assert node is not None
    subprocess.run([node, "-e", script], cwd=root, check=True, capture_output=True, text=True)


def test_admin_preview_reports_source_changes_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LBPDATA", str(tmp_path))
    config = AtomicConfigStore(tmp_path / "config.json")
    config.save(replace(PluginConfig.defaults(), loxone_endpoint="http://192.168.10.20"))
    state = dispatch_knx("knx_page", {}, config)
    state = dispatch_knx(
        "knx_put", {"target": state["target"], "revision": 0, "record": record()}, config
    )
    document = dispatch_knx("knx_export", {}, config)["document"]
    document["records"][0]["imported"] = document["records"][0]["overrides"]
    document["records"][0]["overrides"] = {}
    preview = dispatch_knx("knx_preview", {"target": state["target"], "document": document}, config)
    assert preview["updates"] == 1
    assert preview["changes"][0]["fields"] == ["imported", "overrides"]
    assert (
        dispatch_knx("knx_page", {}, config)["items"][0]["overrides"]["name"] == "Additional name"
    )
    document["schema_version"] = True
    with pytest.raises(AdminError):
        dispatch_knx("knx_preview", {"target": state["target"], "document": document}, config)
