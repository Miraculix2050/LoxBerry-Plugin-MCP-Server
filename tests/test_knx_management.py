from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from mcpserver.admin import AdminError
from mcpserver.config import AtomicConfigStore, PluginConfig
from mcpserver.knx.admin import dispatch_knx
from mcpserver.knx.model import KnxError, address
from mcpserver.knx.store import KnxStore
from mcpserver.loxone.project.taxonomy import AddressTaxonomyEntry


def test_cgi_project_forwarder_does_not_import_server_models():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import mcpserver.admin; import mcpserver.knx.admin_bridge; "
            "assert 'mcpserver.auth.provider' not in sys.modules; "
            "assert 'mcpserver.loxone.runtime' not in sys.modules; "
            "assert 'starlette.requests' not in sys.modules; "
            "assert 'mcp.types' not in sys.modules",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("outcome", ["success", "oversize", "invalid", "transport"])
def test_fixed_loopback_forwarder_bounds_body_and_keeps_signed_binding(monkeypatch, outcome):
    import json
    import time
    from types import SimpleNamespace

    from mcpserver import admin as admin_module
    from mcpserver.knx import admin_bridge as bridge

    monkeypatch.setenv("HTTP_X_LOXONE_AUTHORIZATION", "Bearer synthetic")
    monkeypatch.setenv("MCPSERVER_KNX_ADMIN_SESSION", "a" * 64)
    monkeypatch.setattr(
        admin_module, "_auth_store", lambda: SimpleNamespace(pseudonym=lambda *_: "key")
    )
    calls = []
    closed = []
    raw = json.dumps({"ok": True, "data": {"result": "synthetic"}}).encode()
    if outcome == "oversize":
        raw = b"x" * 65
        monkeypatch.setattr(bridge, "MAX_RESPONSE", 64)
    elif outcome == "invalid":
        raw = b"invalid"

    class Connection:
        def __init__(self, host, port, timeout):
            assert (host, port, timeout) == ("127.0.0.1", 8765, 55)

        def request(self, method, path, *, body, headers):
            assert (method, path) == ("POST", bridge.PATH)
            assert headers["Host"] == "public.example"
            assert headers["Authorization"] == "Bearer synthetic"
            assert bridge.verify(
                "key", "a" * 64, body, headers[bridge.PROOF_HEADER], int(time.time())
            )
            calls.append(json.loads(body))

        def getresponse(self):
            if outcome == "transport":
                raise OSError("private diagnostic")
            return SimpleNamespace(read=lambda cap: raw[:cap])

        def close(self):
            closed.append(True)

    monkeypatch.setattr(bridge, "HTTPConnection", Connection)
    configs = SimpleNamespace(load=lambda: SimpleNamespace(public_origin="https://public.example"))
    if outcome == "success":
        assert bridge.forward("knx_project_page", {"revision": 1}, configs) == {
            "result": "synthetic"
        }
    else:
        with pytest.raises(AdminError) as failed:
            bridge.forward("knx_project_page", {"revision": 1}, configs)
        assert failed.value.code == "write_outcome_uncertain"
        assert "private diagnostic" not in str(failed.value)
    assert calls == [{"action": "knx_project_page", "payload": {"revision": 1}}]
    assert closed == [True]


def record(name: str = "Additional name") -> dict[str, object]:
    return {
        "address": "1/2/3",
        "address_format": "three_level",
        "fields": {"name": name, "description": "", "dpts": ["DPST-1-1"]},
    }


@pytest.mark.parametrize("kind", ["read", "drafts", "write"])
def test_knx_delegation_ui_requires_html_confirmation_before_grant_and_enable(kind) -> None:
    root = Path(__file__).resolve().parents[1]
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {JSDOM} = require('jsdom');
const html = fs.readFileSync('templates/knx.html', 'utf8').replace(/<TMPL_VAR[^>]*>/g, 'label');
const dom = new JSDOM(html,
  {url: 'http://localhost/knx.cgi', runScripts: 'outside-only', pretendToBeVisual: true});
const w = dom.window;
const calls = [];
let pauseRead = true, resumeRead, failRead = false;
let state = {target: 'synthetic-target', policy_revision: 'revision-1', enabled: false,
  bindings: [{binding: 'a'.repeat(64), client_name: '<img src=x onerror=attack()>',
    client: 'synthetic-client', identity: 'identity-ref', miniserver: 'ms-ref',
    eligible: true, approved: false, retained: false}]};
w.confirm = () => {throw new Error('Native dialog is forbidden');};
w.HTMLDialogElement.prototype.showModal = function () {this.open = true;};
w.HTMLDialogElement.prototype.close = function (value) {
  this.returnValue = value; this.open = false;
  // Chrome can retain focus inside the closed dialog through the next frame.
  this.dispatchEvent(new w.Event('close'));
};
w.fetch = async (_url, options) => {
  const action = options.body.get('action');
  const payload = JSON.parse(options.body.get('payload'));
  calls.push({action, payload});
  if (action === 'knx_read_page' && pauseRead)
    await new Promise(resolve => {resumeRead = resolve;});
  if (action === 'knx_read_page' && failRead) throw new Error('Synthetic read failure');
  if (action !== 'knx_read_page') {
    assert.equal(payload.target, state.target);
    assert.equal(payload.policy_revision, state.policy_revision);
    state = structuredClone(state);
    if (action === 'knx_read_grant') {
      assert.equal(payload.binding, state.bindings[0].binding);
      state.bindings[0].approved = state.bindings[0].retained = true;
    } else if (action === 'knx_read_enable') state.enabled = payload.enabled;
    else throw new Error('unexpected action');
    state.policy_revision += '-changed';
  }
  return {ok: true, json: async () => ({ok: true, data: structuredClone(state)})};
};
const tick = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  w.eval(fs.readFileSync('webfrontend/htmlauth/knx-read-delegation.js', 'utf8'));
  await tick();
  const section = w.document.getElementById('knx-read-delegation');
  assert.equal(w.document.getElementById('knx-read-loading').hidden, false);
  assert.equal(w.document.getElementById('knx-read-loading').getAttribute('aria-hidden'), 'true');
  assert.equal(w.document.getElementById('knx-read-status').getAttribute('role'), 'status');
  const announcement = w.document.getElementById('knx-read-announcement');
  assert.equal(w.document.getElementById('knx-page').contains(announcement), false);
  assert.equal(announcement.closest('[aria-busy="true"]'), null);
  assert.equal(announcement.textContent, announcement.dataset.loading);
  assert.equal(w.document.getElementById('knx-read-status').textContent, section.dataset.loading);
  pauseRead = false; resumeRead(); await tick();
  assert.equal(w.document.getElementById('knx-read-loading').hidden, true);
  assert.equal(announcement.textContent, '');
  const rows = w.document.getElementById('knx-read-bindings');
  assert.equal(rows.querySelector('img'), null);
  const dialog = w.document.getElementById('knx-confirm');
  rows.querySelector('button').click(); await tick();
  assert.equal(dialog.open, true);
  assert.match(w.document.getElementById('knx-confirm-message').textContent, /aaaaaaaa/);
  dialog.close('cancel'); await tick();
  await new Promise(resolve => w.requestAnimationFrame(resolve));
  assert.deepEqual(calls.map(call => call.action), ['knx_read_page']);
  const unsaved = w.document.getElementById('knx-read-enabled');
  unsaved.checked = true; unsaved.dispatchEvent(new w.Event('change'));
  rows.querySelector('button').click(); await tick(); dialog.close('continue'); await tick();
  assert.equal(unsaved.checked, true);
  assert.equal(w.document.getElementById('knx-read-badge').dataset.kind, 'inactive');
  assert.equal(calls.at(-1).action, 'knx_read_grant');
  assert.equal(state.enabled, false);
  const enabled = w.document.getElementById('knx-read-enabled');
  const form = w.document.getElementById('knx-read-enable-form');
  const submit = form.querySelector('button[type=submit]');
  submit.focus();
  enabled.checked = true;
  form.dispatchEvent(new w.Event('submit', {cancelable: true})); await tick();
  dialog.close('cancel'); await tick();
  await new Promise(resolve => w.requestAnimationFrame(resolve));
  assert.equal(enabled.checked, false);
  assert.equal(w.document.activeElement, submit);
  assert.equal(calls.at(-1).action, 'knx_read_grant');
  // A user who moves elsewhere during the pending confirmation keeps that focus.
  submit.focus(); enabled.checked = true;
  form.dispatchEvent(new w.Event('submit', {cancelable: true})); await tick();
  const outside = w.document.getElementById('knx-back');
  outside.focus(); dialog.close('cancel'); await tick();
  await new Promise(resolve => w.requestAnimationFrame(resolve));
  assert.equal(w.document.activeElement, outside);
  assert.equal(enabled.checked, false);
  enabled.checked = true;
  form.dispatchEvent(new w.Event('submit', {cancelable: true})); await tick();
  dialog.close('continue'); await tick();
  assert.equal(state.enabled, true);
  if (section.id === 'knx-write-delegation') {
    const prefixes = w.document.getElementById('knx-write-prefixes');
    assert.equal(prefixes.checked, false);
    prefixes.checked = true; prefixes.dispatchEvent(new w.Event('change'));
    const before = calls.length;
    form.dispatchEvent(new w.Event('submit', {cancelable:true})); await tick();
    assert.equal(dialog.open, true);
    dialog.close('cancel'); await tick();
    assert.equal(calls.length, before);
    assert.equal(prefixes.checked, false);
    prefixes.checked = true; prefixes.dispatchEvent(new w.Event('change'));
    form.dispatchEvent(new w.Event('submit', {cancelable:true})); await tick();
    dialog.close('continue'); await tick();
    assert.equal(calls.at(-1).payload.allow_prefixes, true);
    assert.equal(calls.at(-1).payload.enabled, true);
  }
  assert.equal(section.hasAttribute('aria-busy'), false);
  pauseRead = true; failRead = true;
  w.document.getElementById('knx-read-reload').click(); await tick();
  assert.equal(w.document.getElementById('knx-read-loading').hidden, false);
  pauseRead = false; resumeRead(); await tick();
  assert.equal(w.document.getElementById('knx-read-loading').hidden, true);
  assert.equal(w.document.getElementById('knx-read-status').textContent, section.dataset.failed);
  assert.equal(announcement.textContent, '');
  dom.window.close();
})().catch(error => {dom.window.close(); console.error(error); process.exitCode = 1;});
"""
    others = [item for item in ("read", "drafts", "write") if item != kind]
    script = script.replace("knx_read_", f"knx_{kind}_")
    script = script.replace("getElementById('knx-read-", f"getElementById('knx-{kind}-")
    script = script.replace(
        "const w = dom.window;",
        "const w = dom.window; "
        + " ".join(
            f"w.document.getElementById('knx-{other}-delegation').remove();" for other in others
        ),
    )
    node = shutil.which("node")
    assert node is not None
    result = subprocess.run(
        [node, "-e", script], cwd=root, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stdout + result.stderr


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
    assert '$ENV{MCPSERVER_AUTH_STORE} = "$lbpdatadir/auth/sessions.json";' in cgi
    assert "knx_put|knx_delete|knx_export|knx_restore|knx_taxonomy" in cgi
    assert "textContent = value" in js
    assert "taxonomy_revision: labelsRevision ?? state.taxonomy_revision" in js
    assert "beforeunload" not in js
    assert "confirm(" not in js
    assert "$navbar" not in cgi
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
  effective: {name: 'Additional'}, overrides: {name: 'Additional'}, imported: {},
  imported_groups: [{level: 'main', prefix: '1', fields: {name: '<Main>'}},
    {level: 'middle', prefix: '1/2', fields: {name: 'Middle & group'}}]};
let state = {target: 'target', revision: 1, taxonomy_revision: 'labels', offset: 0,
  total: 1, items: [record],
  imported_labels: [{address_format: 'three_level', prefix: '1/2', label: 'Imported'},
    {address_format: 'two_level', prefix: '1/2', label: 'Different format'}],
  taxonomy: [{address_format: 'three_level', prefix: '1/2', label: 'Saved'}]};
w.confirm = () => { throw new Error('Native browser dialogs are forbidden'); };
w.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
w.HTMLDialogElement.prototype.close = function (value = '') {
  this.returnValue = value; this.open = false; this.dispatchEvent(new w.Event('close'));
};
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
  const cells = w.document.querySelector('#knx-addresses tr').cells;
  assert.equal(cells.length, 8);
  assert.equal(cells[1].textContent, '1 — <Main>');
  assert.equal(cells[1].querySelector('main'), null);
  assert.equal(cells[2].textContent, '1/2 — Middle & group');
  const originalGroups = record.imported_groups;
  record.imported_groups = []; record.address_format = 'two_level';
  w.MCPKnx.render(state);
  assert.equal(w.document.querySelector('#knx-addresses tr').cells[1].textContent, 'label');
  assert.equal(w.document.querySelector('#knx-addresses tr').cells[2].textContent, '—');
  record.imported_groups = originalGroups; record.address_format = 'three_level';
  w.MCPKnx.render(state);
  record.import_info = {address_format: 'three_level'}; record.address_format = 'two_level';
  w.MCPKnx.render(state);
  assert.equal(w.document.querySelector('#knx-addresses tr').cells[2].textContent,
    '1/2 — Middle & group');
  record.import_info = {}; record.address_format = 'three_level';
  w.MCPKnx.render(state);
  const labels = w.document.getElementById('knx-taxonomy-entries');
  const form = w.document.getElementById('knx-record-form');
  assert.equal(w.document.getElementById('knx-label-badge').textContent, '2');
  state.items = []; state.total = 0; w.MCPKnx.render(state); await tick();
  const body = w.document.getElementById('knx-addresses');
  const wrapper = body.closest('.mcp-table-wrap'), note = wrapper.nextElementSibling;
  assert.equal(body.children.length, 0); assert.equal(wrapper.dataset.empty, 'true');
  assert.equal(note.hidden, false); assert.equal(note.closest('table'), null);
  w.document.getElementById('knx-page').setAttribute('aria-busy', 'true'); await tick();
  assert.equal(note.hidden, true);
  w.document.getElementById('knx-page').removeAttribute('aria-busy');
  state.items = [record]; state.total = 1; w.MCPKnx.render(state); await tick();
  assert.equal(wrapper.dataset.empty, 'false'); assert.equal(note.hidden, true);
  labels.value = '3:1/2=Unsaved'; labels.dispatchEvent(new w.Event('input', {bubbles: true}));
  assert.equal(w.document.getElementById('knx-label-badge').textContent, '2');
  form.elements.namedItem('address').value = '1/2/4';
  form.elements.namedItem('name').value = 'New additional name';
  form.dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
  await tick();
  assert.equal(labels.value, '3:1/2=Unsaved');
  const unload = new w.Event('beforeunload', {cancelable: true});
  w.dispatchEvent(unload); assert.equal(unload.defaultPrevented, false);
  const dialog = w.document.getElementById('knx-confirm');
  w.document.getElementById('knx-back').click();
  assert.equal(dialog.open, true);
  assert.equal(w.document.activeElement.id, 'knx-confirm-cancel');
  dialog.close('cancel'); await tick();
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
  w.dispatchEvent(stillDirty); assert.equal(stillDirty.defaultPrevented, false);
  const remove = w.document.querySelectorAll('#knx-addresses button')[1];
  const beforeDelete = w.requests.length;
  remove.click(); assert.equal(dialog.open, true);
  assert.match(w.document.getElementById('knx-confirm-message').textContent, /1\/2\/3/);
  dialog.close('cancel'); await tick();
  assert.equal(w.requests.length, beforeDelete);
  remove.click(); dialog.close('continue'); await tick();
  assert.equal(w.requests.at(-1), 'knx_delete');
  form.elements.namedItem('name').value = 'Retain draft';
  form.dispatchEvent(new w.Event('input', {bubbles: true}));
  form.reset(); assert.equal(dialog.open, true);
  dialog.close('cancel'); await tick();
  assert.equal(form.elements.namedItem('name').value, 'Retain draft');
  form.reset(); dialog.close('continue'); await tick();
  assert.equal(form.elements.namedItem('name').value, '');
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


def test_polling_logs_omit_successes_but_keep_failures_and_mutations():
    perl = shutil.which("perl")
    if perl is None:
        pytest.skip("Perl is required to execute the native logging predicate")
    source = (Path(__file__).resolve().parents[1] / "webfrontend/htmlauth/knx.cgi").read_text(
        encoding="utf-8"
    )
    predicate = re.search(r"my \$quiet_read = ([^;]+);", source)
    assert predicate is not None
    actions = ["knx_page", "knx_read_page", "knx_drafts_page", "knx_read_enable", "knx_read_grant"]
    code = (
        "use strict; use warnings; "
        + "for my $action (qw("
        + " ".join(actions)
        + ")) { "
        + "for my $success (0, 1) { my $q = {action => $action}; "
        + "my $result = {ok => $success}; my $quiet_read = "
        + predicate.group(1)
        + "; "
        + 'print "$action:$success:" . ($quiet_read ? 0 : 1) . "\\n"; }}'
    )
    result = subprocess.run([perl, "-e", code], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    expected = [
        f"{action}:{success}:{int(not (success and action in actions[:3]))}"
        for action in actions
        for success in (0, 1)
    ]
    assert result.stdout.splitlines() == expected


def test_initial_page_sections_match_individual_reads_without_config_writes(tmp_path, monkeypatch):
    from mcpserver import admin as admin_module
    from mcpserver.auth.store import AtomicJsonAuthStore

    monkeypatch.setenv("LBPDATA", str(tmp_path))
    monkeypatch.setenv("MCPSERVER_KNX_ADMIN_SESSION", "a" * 64)
    auth = AtomicJsonAuthStore(tmp_path / "auth.json")
    monkeypatch.setattr(admin_module, "_auth_store", lambda: auth)
    store = AtomicConfigStore(tmp_path / "config.json")
    store.save(replace(PluginConfig.defaults(), loxone_endpoint="http://192.168.10.20"))
    before = store.path.read_bytes()
    ordinary = dispatch_knx("knx_page", {}, store)
    snapshots = 0
    original_snapshot = auth.snapshot

    def counted_snapshot():
        nonlocal snapshots
        snapshots += 1
        return original_snapshot()

    monkeypatch.setattr(auth, "snapshot", counted_snapshot)
    combined = dispatch_knx("knx_page", {"include_sections": True}, store)
    assert snapshots == 1
    assert {key: value for key, value in combined.items() if key != "sections"} == ordinary
    assert set(combined["sections"]) == {
        "knx_read_page",
        "knx_drafts_page",
        "knx_write_page",
        "knx_correction_page",
    }
    for action, envelope in combined["sections"].items():
        assert envelope == {"ok": True, "data": dispatch_knx(action, {}, store)}
    assert store.path.read_bytes() == before
    assert "sections" not in dispatch_knx("knx_page", {"include_sections": False}, store)
    for invalid in (1, "true", None, [], {}):
        with pytest.raises(AdminError) as rejected:
            dispatch_knx("knx_page", {"include_sections": invalid}, store)
        assert rejected.value.code == "knx_page_invalid"


def test_initial_groups_are_optional_and_match_separate_page(tmp_path, monkeypatch):
    from mcpserver import admin as admin_module
    from mcpserver.auth.store import AtomicJsonAuthStore

    monkeypatch.setenv("LBPDATA", str(tmp_path))
    monkeypatch.setenv("MCPSERVER_KNX_ADMIN_SESSION", "a" * 64)
    auth = AtomicJsonAuthStore(tmp_path / "auth.json")
    monkeypatch.setattr(admin_module, "_auth_store", lambda: auth)
    store = AtomicConfigStore(tmp_path / "config.json")
    store.save(replace(PluginConfig.defaults(), loxone_endpoint="http://192.168.10.20"))
    combined = dispatch_knx("knx_page", {"include_sections": True, "initial_groups": {}}, store)
    assert combined["sections"]["knx_groups_page"] == {
        "ok": True,
        "data": dispatch_knx("knx_groups_page", {"target": combined["target"]}, store),
    }
    for invalid in (None, True, [], {"target": "other"}):
        with pytest.raises(AdminError):
            dispatch_knx("knx_page", {"include_sections": True, "initial_groups": invalid}, store)


def test_initial_section_failure_does_not_hide_other_sections(tmp_path, monkeypatch):
    from mcpserver import admin as admin_module

    monkeypatch.setenv("LBPDATA", str(tmp_path))
    monkeypatch.setenv("MCPSERVER_KNX_ADMIN_SESSION", "a" * 64)

    def failed_auth():
        raise RuntimeError("private diagnostic must not escape")

    monkeypatch.setattr(admin_module, "_auth_store", failed_auth)
    store = AtomicConfigStore(tmp_path / "config.json")
    store.save(replace(PluginConfig.defaults(), loxone_endpoint="http://192.168.10.20"))
    combined = dispatch_knx("knx_page", {"include_sections": True}, store)
    assert combined["total"] == 0
    assert combined["sections"]["knx_correction_page"]["ok"]
    for action in ("knx_read_page", "knx_drafts_page", "knx_write_page"):
        assert combined["sections"][action] == {"ok": False, "error": {"code": "internal_error"}}
    assert "private diagnostic" not in str(combined)


def test_delegation_poll_shares_one_fresh_snapshot_and_matches_separate_reads(
    tmp_path, monkeypatch
):
    from mcpserver import admin as admin_module
    from mcpserver.auth.store import AtomicJsonAuthStore

    monkeypatch.setenv("LBPDATA", str(tmp_path))
    auth = AtomicJsonAuthStore(tmp_path / "auth.json")
    monkeypatch.setattr(admin_module, "_auth_store", lambda: auth)
    store = AtomicConfigStore(tmp_path / "config.json")
    store.save(replace(PluginConfig.defaults(), loxone_endpoint="http://192.168.10.20"))
    snapshots = 0
    original = auth.snapshot

    def counted():
        nonlocal snapshots
        snapshots += 1
        return original()

    monkeypatch.setattr(auth, "snapshot", counted)
    data = dispatch_knx("knx_read_page", {"include_delegations": True}, store)
    assert snapshots == 1
    for action, envelope in data["delegations"].items():
        assert envelope == {"ok": True, "data": dispatch_knx(action, {}, store)}
    store.mutate(lambda config: replace(config, loxberry_knx_read_enabled=True))
    assert dispatch_knx("knx_read_page", {"include_delegations": True}, store)["enabled"]
    for payload in ({"include_delegations": "true"}, {"include_delegations": True, "extra": True}):
        with pytest.raises(AdminError):
            dispatch_knx("knx_read_page", payload, store)


@pytest.mark.parametrize("failed", ["knx_read", "knx_drafts", "knx_write"])
@pytest.mark.parametrize("unexpected", [False, True])
def test_combined_delegation_poll_isolates_each_projection_failure(
    tmp_path, monkeypatch, failed, unexpected
):
    from mcpserver import admin as admin_module
    from mcpserver.auth.store import AtomicJsonAuthStore
    from mcpserver.knx import read_admin

    monkeypatch.setenv("LBPDATA", str(tmp_path))
    auth = AtomicJsonAuthStore(tmp_path / "auth.json")
    monkeypatch.setattr(admin_module, "_auth_store", lambda: auth)
    store = AtomicConfigStore(tmp_path / "config.json")
    store.save(replace(PluginConfig.defaults(), loxone_endpoint="http://192.168.10.20"))
    original = read_admin.snapshot
    calls = []

    def project(config, view, target, policy):
        calls.append(policy.prefix)
        if policy.prefix == failed:
            if unexpected:
                raise RuntimeError("private diagnostic")
            raise KnxError("knx_delegation_capacity")
        return original(config, view, target, policy)

    monkeypatch.setattr(read_admin, "snapshot", project)
    result = dispatch_knx("knx_read_page", {"include_delegations": True}, store)
    assert calls == ["knx_read", "knx_drafts", "knx_write"]
    for action, section in result["delegations"].items():
        if action == f"{failed}_page":
            assert section == {
                "ok": False,
                "error": {"code": "internal_error" if unexpected else "knx_delegation_capacity"},
            }
        else:
            assert section["ok"]
            assert section["data"] == dispatch_knx(action, {}, store)
    assert "private diagnostic" not in str(result)
