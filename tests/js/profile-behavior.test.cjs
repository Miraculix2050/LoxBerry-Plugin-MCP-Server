'use strict';

const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const {JSDOM} = require('jsdom');

function harness() {
  const html = fs.readFileSync('templates/profile.html', 'utf8');
  const dom = new JSDOM(html, {runScripts: 'outside-only', url: 'https://synthetic.local/profile.cgi'});
  const {window} = dom;
  const calls = [];
  let revision = 1;
  const binding = {
    binding_id: 'synthetic', control_uuid: 'control', control_name: '<script>private</script>',
    source_kind: 'state', state_uuid: null, series_id: null, role: 'operating_state',
    status: 'invalid', confirmed: false,
  };
  window.HTMLElement.prototype.scrollIntoView = () => {};
  window.confirm = () => { throw new Error('Native dialogs must not be used'); };
  window.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  window.HTMLDialogElement.prototype.close = function (value) {
    this.returnValue = value || this.returnValue;
    this.open = false;
    this.dispatchEvent(new window.Event('close'));
  };
  window.fetch = async (_url, options) => {
    const action = options.body.get('action');
    const payload = JSON.parse(options.body.get('payload'));
    calls.push({action, payload});
    if (action === 'profile_put') revision++;
    return {ok: true, json: async () => ({ok: true, data: {
      status: 'available', installation: 'synthetic-installation', revision,
      bindings: [binding], sources: [{control_uuid: 'control', source_kind: 'state', source_id: 'state', control_name: 'Synthetic', source_name: 'value'}],
      next_offset: null, sources_truncated: false,
    }})};
  };
  window.eval(fs.readFileSync('webfrontend/htmlauth/profile.js', 'utf8'));
  const tick = () => new Promise((resolve) => setImmediate(resolve));
  return {window, calls, tick, get: (id) => window.document.getElementById(`profile-${id}`), close: () => window.close()};
}

test('editing an invalid binding exposes exact IDs and resets confirmation', async (t) => {
  const h = harness(); t.after(h.close); await h.tick();
  h.get('confirmed').checked = true;
  h.get('bindings').querySelector('button').click();
  assert.equal(h.get('confirmed').checked, false);
  assert.equal(h.get('exact').open, true);
  assert.equal(h.get('source-id').value, '');
  assert.equal(h.get('bindings').querySelector('script'), null);
});

test('delete cancellation and Escape preserve the binding and restore focus', async (t) => {
  const h = harness(); t.after(h.close); await h.tick();
  const remove = h.get('bindings').querySelectorAll('button')[1];
  remove.click();
  assert.equal(h.get('confirm').open, true);
  assert.equal(h.window.document.activeElement, h.get('confirm-cancel'));
  h.get('confirm').close('cancel'); await h.tick();
  assert.equal(h.calls.filter((item) => item.action === 'profile_delete').length, 0);
  assert.equal(h.window.document.activeElement, remove);
  remove.click();
  // Browsers close an HTML dialog on Escape with its default return value.
  h.get('confirm').dispatchEvent(new h.window.Event('cancel', {cancelable: true}));
  h.get('confirm').close(); await h.tick();
  assert.equal(h.calls.filter((item) => item.action === 'profile_delete').length, 0);
});

test('HTML confirmation distinguishes binding and profile deletion and blocks duplicate prompts', async (t) => {
  const h = harness(); t.after(h.close); await h.tick();
  const page = h.window.document.getElementById('profile-page');
  page.dataset.deleteBindingConfirm = 'Binding only';
  page.dataset.deleteAllConfirm = 'Entire profile';
  h.get('bindings').querySelectorAll('button')[1].click();
  h.get('delete-all').click();
  assert.equal(h.get('confirm-message').textContent, 'Binding only');
  h.get('confirm').close('delete'); await h.tick();
  assert.deepEqual(h.calls.find((item) => item.action === 'profile_delete').payload, {
    installation: 'synthetic-installation', revision: 1, binding_id: 'synthetic', confirm: true,
  });
  h.get('delete-all').click();
  assert.equal(h.get('confirm-message').textContent, 'Entire profile');
  h.get('confirm').close('delete'); await h.tick();
  assert.equal(h.calls.filter((item) => item.action === 'profile_delete')[1].payload.binding_id, null);
});

test('saving uses the loaded revision and preserves the explicit confirmation choice', async (t) => {
  const h = harness(); t.after(h.close); await h.tick();
  h.get('confirmed').checked = true;
  h.get('form').dispatchEvent(new h.window.Event('submit', {cancelable: true}));
  await h.tick();
  const save = h.calls.find((item) => item.action === 'profile_put');
  assert.equal(save.payload.revision, 1);
  assert.equal(save.payload.binding.confirmed, true);
  assert.equal(save.payload.binding.state_uuid, 'state');
  assert.equal(h.get('confirmed').checked, false);
  h.get('form').dispatchEvent(new h.window.Event('submit', {cancelable: true}));
  await h.tick();
  const saves = h.calls.filter((item) => item.action === 'profile_put');
  assert.equal(saves[1].payload.revision, 2);
  assert.equal(saves[1].payload.binding.confirmed, false);
});
