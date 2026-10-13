'use strict';

const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const {JSDOM} = require('jsdom');

function harness(config = {}) {
  const html = fs.readFileSync('templates/profile.html', 'utf8');
  const dom = new JSDOM(html, {runScripts: 'outside-only', url: 'https://synthetic.local/profile.cgi'});
  const {window} = dom;
  const calls = [];
  let revision = 1;
  const binding = config.binding || {
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
    if (action === 'profile_permissions' || action.startsWith('profile_permission_')) {
      return {ok: true, json: async () => ({ok: true, data: {
        enabled: false, sessions: [{id: 'synthetic-session', label: 'Synthetic client', approved: false}], bindings: [],
      }})};
    }
    if (action === 'profile_put') revision++;
    return {ok: true, json: async () => ({ok: true, data: {
      status: 'available', installation: 'synthetic-installation', revision,
      bindings: config.bindings || [binding], sources: config.sources || [{control_uuid: 'control', source_kind: 'state', source_id: 'state', control_name: 'Synthetic', source_name: 'value'}],
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
  h.get('confirm').close('confirm'); await h.tick();
  assert.deepEqual(h.calls.find((item) => item.action === 'profile_delete').payload, {
    installation: 'synthetic-installation', revision: 1, binding_id: 'synthetic', confirm: true,
  });
  h.get('delete-all').click();
  assert.equal(h.get('confirm-message').textContent, 'Entire profile');
  h.get('confirm').close('confirm'); await h.tick();
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

test('separate profile approval uses an HTML dialog and the captured exact session', async (t) => {
  const h = harness(); t.after(h.close); await h.tick();
  h.get('permission-allow').click();
  assert.equal(h.get('confirm').open, true);
  assert.ok(h.get('confirm-message').textContent.includes('Synthetic client'));
  h.get('confirm').close('cancel'); await h.tick();
  assert.equal(h.calls.filter((item) => item.action === 'profile_permission_allow').length, 0);
  h.get('permission-allow').click();
  h.get('confirm').close('confirm'); await h.tick();
  assert.deepEqual(h.calls.find((item) => item.action === 'profile_permission_allow').payload, {
    session_id: 'synthetic-session', confirm: true,
  });
});

test('weather selection has its own mode and field without a fake control anchor', async (t) => {
  const h = harness({sources: [{source_kind: 'weather', source_id: 'weather', mode: 'forecast', field: 'temperature'}]});
  t.after(h.close); await h.tick();
  assert.equal(h.get('kind').value, 'weather');
  assert.equal(h.get('control').required, false);
  assert.equal(h.get('weather-fields').hidden, false);
  assert.equal(h.get('role').value, 'weather_context');
  h.get('form').dispatchEvent(new h.window.Event('submit', {cancelable: true})); await h.tick();
  const binding = h.calls.find((item) => item.action === 'profile_put').payload.binding;
  assert.equal(binding.weather_state_uuid, 'weather');
  assert.equal(binding.mode, 'forecast'); assert.equal(binding.field, 'temperature');
  assert.equal('control_uuid' in binding, false); assert.equal('state_uuid' in binding, false);
});

test('editing PV declarations preserves arrays and coordinates but resets confirmation', async (t) => {
  const h = harness({binding: {
    binding_id: 'production', source_kind: 'state', control_uuid: 'control', control_name: 'Synthetic',
    state_uuid: 'state', role: 'production', status: 'confirmed', confirmed: true,
    pv_parameters: {installed_kwp: 5, latitude: 50, longitude: 10,
      arrays: [{array_id: 'south', installed_kwp: 3, azimuth_degrees: 180, tilt_degrees: 30, shading: '<script>declared</script>'}]},
  }});
  t.after(h.close); await h.tick();
  h.get('bindings').querySelector('button').click();
  assert.equal(h.get('confirmed').checked, false);
  assert.equal(h.get('pv-fields').disabled, false);
  assert.equal(h.get('pv-arrays').querySelector('script'), null);
  h.get('form').dispatchEvent(new h.window.Event('submit', {cancelable: true})); await h.tick();
  const binding = h.calls.find((item) => item.action === 'profile_put').payload.binding;
  assert.equal(binding.confirmed, false);
  assert.equal(binding.pv_parameters.installed_kwp, 5);
  assert.equal(binding.pv_parameters.latitude, 50);
  assert.equal(binding.pv_parameters.arrays[0].array_id, 'south');
  assert.equal(binding.pv_parameters.arrays[0].azimuth_degrees, 180);
  assert.equal(binding.pv_parameters.arrays[0].shading, '<script>declared</script>');
});

test('schema-valid small capacities and azimuths below 360 round-trip through Edit', async (t) => {
  const h = harness({binding: {
    binding_id: 'production', source_kind: 'state', control_uuid: 'control', control_name: 'Synthetic',
    state_uuid: 'state', role: 'production', status: 'confirmed', confirmed: true,
    pv_parameters: {installed_kwp: 1e-7, arrays: [{array_id: 'a', installed_kwp: 1e-7, azimuth_degrees: 359.9999999}]},
  }});
  t.after(h.close); await h.tick();
  h.get('bindings').querySelector('button').click();
  assert.equal(h.get('form').checkValidity(), true);
  h.get('form').dispatchEvent(new h.window.Event('submit', {cancelable: true})); await h.tick();
  const pv = h.calls.find((item) => item.action === 'profile_put').payload.binding.pv_parameters;
  assert.equal(pv.installed_kwp, 1e-7);
  assert.equal(pv.arrays[0].azimuth_degrees, 359.9999999);
});

test('exclusive PV boundaries reject zero capacity and 360 azimuth then clear on reset', async (t) => {
  const h = harness(); t.after(h.close); await h.tick();
  h.get('pv-enabled').checked = true; h.get('pv-enabled').dispatchEvent(new h.window.Event('change'));
  h.get('pv-capacity').value = '0'; h.get('pv-capacity').dispatchEvent(new h.window.Event('input'));
  assert.equal(h.get('pv-capacity').checkValidity(), false);
  h.get('pv-add-array').click();
  const azimuth = h.get('pv-arrays').querySelector('[data-key="azimuth_degrees"]');
  azimuth.value = '360'; azimuth.dispatchEvent(new h.window.Event('input'));
  assert.equal(azimuth.checkValidity(), false);
  h.get('new').click();
  assert.equal(h.get('pv-capacity').validationMessage, '');
});


const flexibleBinding = {
  binding_id: 'load', source_kind: 'state', control_uuid: 'control', control_name: 'Synthetic',
  state_uuid: 'state', role: 'consumer', status: 'confirmed', confirmed: true,
  load_constraints_present: true,
  load_flexibility: {
    timezone: 'Europe/Berlin', operating_binding_id: 'operating', cycle_identity: 'active_episode_only',
    windows: [{weekdays: [0, 2, 6], start: '23:00', end: '01:00', end_day_offset: 1}],
    latest_completion: '02:00', completion_day_offset: 1, duration_seconds: 7200,
    interruptible: false, minimum_run_seconds: 3600, minimum_off_seconds: 1800,
    energy_profile_origin: 'observed_intervals', declared_cycle_energy_wh: null,
    rationale: '<script>owner declaration</script>', native_lock_policy: 'never_override',
  },
};
const operatingBinding = {
  binding_id: 'operating', source_kind: 'state', control_uuid: 'control', control_name: 'Synthetic',
  state_uuid: 'state', role: 'operating_state', status: 'confirmed', confirmed: true,
  load_operating_source_eligible: true,
};

test('load constraints round-trip with explicit midnight offsets and renewed confirmation', async (t) => {
  const h = harness({bindings: [flexibleBinding, operatingBinding]}); t.after(h.close); await h.tick();
  h.get('bindings').querySelector('button').click();
  assert.equal(h.get('flex-section').hidden, false);
  assert.equal(h.get('confirmed').checked, false);
  assert.equal(h.get('flex-fields').disabled, false);
  assert.equal(h.get('flex-operating').value, 'operating');
  assert.equal(h.get('flex-rationale').value, '<script>owner declaration</script>');
  assert.equal(h.get('flex-windows').querySelector('script'), null);
  h.get('confirmed').checked = true;
  h.get('flex-duration').value = '7300';
  h.get('flex-duration').dispatchEvent(new h.window.Event('input', {bubbles: true}));
  assert.equal(h.get('confirmed').checked, false);
  h.get('flex-duration').value = '7200'; h.get('confirmed').checked = true;
  h.get('form').dispatchEvent(new h.window.Event('submit', {cancelable: true})); await h.tick();
  const saved = h.calls.find((c) => c.action === 'profile_put').payload.binding;
  assert.deepEqual(saved.load_flexibility, flexibleBinding.load_flexibility);
  assert.equal(saved.confirmed, true);
});

test('declared energy and weekday/window limits are validated without asserting a measurement', async (t) => {
  const h = harness({bindings: [flexibleBinding, operatingBinding]}); t.after(h.close); await h.tick();
  h.get('bindings').querySelector('button').click();
  h.get('flex-origin').value = 'user_declared';
  h.get('flex-origin').dispatchEvent(new h.window.Event('change', {bubbles: true}));
  assert.equal(h.get('flex-energy').disabled, false); assert.equal(h.get('flex-energy').required, true);
  h.get('flex-energy').value = '0'; h.get('flex-energy').dispatchEvent(new h.window.Event('input', {bubbles: true}));
  assert.equal(h.get('flex-energy').checkValidity(), false);
  h.get('flex-energy').value = '1200'; h.get('flex-energy').dispatchEvent(new h.window.Event('input', {bubbles: true}));
  assert.equal(h.get('flex-energy').checkValidity(), true);
  for (let i = 0; i < 20; i++) h.get('flex-add-window').click();
  assert.equal(h.get('flex-windows').children.length, 16);
  assert.equal(h.get('flex-windows').lastElementChild.querySelector('[data-weekday]').checkValidity(), false);
  for (const row of [...h.get('flex-windows').children]) row.querySelector('[data-remove]').click();
  assert.equal(h.get('flex-enabled').checkValidity(), false);
  h.get('flex-enabled').checked = false; h.get('flex-enabled').dispatchEvent(new h.window.Event('change', {bubbles: true}));
  assert.equal(h.get('flex-enabled').checkValidity(), true);
});

test('editing masked constraints cannot silently remove them and New restores editing', async (t) => {
  const h = harness({binding: {...flexibleBinding, load_flexibility: null}}); t.after(h.close); await h.tick();
  h.get('bindings').querySelector('button').click();
  assert.equal(h.get('form').querySelector('button[type="submit"]').disabled, true);
  h.get('form').dispatchEvent(new h.window.Event('submit', {cancelable: true})); await h.tick();
  assert.equal(h.calls.filter((c) => c.action === 'profile_put').length, 0);
  h.get('new').click();
  assert.equal(h.get('form').querySelector('button[type="submit"]').disabled, false);
  assert.equal(h.get('flex-windows').children.length, 0);
});
