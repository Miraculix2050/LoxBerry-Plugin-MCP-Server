'use strict';

const assert = require('node:assert/strict');
const {test} = require('node:test');
const {createHarness, readTool, SCRIPT_NAMES} = require('./explorer-harness.cjs');

test('shipped scripts restore a session and execute an unknown read-only tool', async (t) => {
  const h = createHarness();
  t.after(h.close);
  await h.ready();
  assert.deepEqual(SCRIPT_NAMES, [
    'explorer-adapters.js', 'explorer-core.js', 'explorer-state.js',
    'explorer-auth.js', 'explorer-client.js', 'explorer-views.js', 'explorer.js',
  ]);
  assert.deepEqual(h.requests.filter((item) => item.body?.method)
    .map((item) => item.body.method),
  ['initialize', 'notifications/initialized', 'tools/list']);
  assert.equal(h.byId('connection-badge').dataset.kind, 'success');
  assert.match(h.byId('scope-list').textContent, /loxone:read/);

  const search = h.byId('tool-search');
  search.value = 'future';
  search.dispatchEvent(new h.window.Event('input', {bubbles: true}));
  assert.deepEqual([...h.byId('tools').querySelectorAll('button')]
    .map((button) => button.querySelector('strong').textContent), ['future_read']);
  search.value = '';
  search.dispatchEvent(new h.window.Event('input', {bubbles: true}));
  const other = h.byId('tool-filters').querySelector('[data-tool-group="other"]');
  other.checked = true;
  other.dispatchEvent(new h.window.Event('change', {bubbles: true}));
  assert.equal(h.byId('tools').querySelectorAll('button').length, 2);

  await h.click([...h.byId('tools').querySelectorAll('button')]
    .find((button) => button.textContent.includes('future_read')));
  const fields = h.byId('form');
  const query = [...fields.querySelectorAll('input[type="text"]')]
    .find((input) => input.labels?.[0]?.textContent.includes('query'));
  assert.ok(query);
  query.value = 'sample';
  query.dispatchEvent(new h.window.Event('input', {bubbles: true}));
  const optional = [...fields.querySelectorAll('input[type="checkbox"]')]
    .find((input) => input.labels?.[0]?.textContent.includes('optional'));
  assert.ok(optional);
  optional.checked = true;
  optional.dispatchEvent(new h.window.Event('change', {bubbles: true}));
  assert.equal(JSON.parse(h.byId('json').value).query, 'sample');
  assert.ok(Object.hasOwn(JSON.parse(h.byId('json').value), 'optional'));
  await h.click(h.byId('json-tab'));
  assert.equal(h.byId('json-panel').hidden, false);
  await h.click(h.byId('form-tab'));
  assert.equal(h.byId('form-panel').hidden, false);
  await h.click(h.byId('run'));
  await h.waitFor(() => h.calls().length === 1 && h.byId('history').querySelector('button'));
  assert.deepEqual(h.calls()[0].body.params, {
    name: 'future_read', arguments: {query: 'sample', optional: ''},
  });
  assert.match(h.byId('result-tree').textContent, /items/);
  const expand = h.byId('result-tree').querySelector('[aria-expanded="false"]');
  assert.ok(expand);
  await h.click(expand);
  assert.equal(expand.getAttribute('aria-expanded'), 'true');
  await h.click(h.byId('history').querySelector('button'));
  assert.equal(h.byId('history-arguments').hidden, false);
  assert.match(h.byId('result-context').textContent, /future_read/);

  await h.click(h.byId('disconnect'));
  assert.equal(h.byId('connection-badge').dataset.kind, 'inactive');
  assert.equal(h.byId('history').querySelector('button'), null);
  assert.equal(h.byId('result-raw').textContent, '');
  assert.equal(h.byId('scope-list').textContent, '');
  assert.equal(h.byId('json').value, '{}');
  assert.doesNotMatch(JSON.stringify({...h.window.localStorage}), /synthetic-token|sample/);
  assert.equal(JSON.stringify({...h.window.sessionStorage}), '{}');
  assert.doesNotMatch(h.byId('transcript').textContent, /synthetic-token/);
});

test('write flow rejects missing scope, then requires explicit confirmation', async (t) => {
  const denied = createHarness({scope: 'loxone:read'});
  t.after(denied.close);
  await denied.ready();
  await denied.click([...denied.byId('tools').querySelectorAll('button')]
    .find((button) => button.textContent.includes('loxone_operate_control')));
  denied.byId('json').value = JSON.stringify({control_uuid: 'test-control', action: 'on'});
  await denied.click(denied.byId('run'));
  assert.equal(denied.calls().length, 0);
  assert.equal(denied.byId('confirm').open, false);
  assert.equal(denied.byId('call-feedback').dataset.kind, 'error');

  const allowed = createHarness();
  t.after(allowed.close);
  await allowed.ready();
  await allowed.click([...allowed.byId('tools').querySelectorAll('button')]
    .find((button) => button.textContent.includes('loxone_operate_control')));
  allowed.byId('json').value = JSON.stringify({control_uuid: 'test-control', action: 'on'});
  await allowed.click(allowed.byId('run'));
  assert.equal(allowed.byId('confirm').open, true);
  assert.equal(allowed.calls().length, 0);
  allowed.byId('confirm').close('cancel');
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(allowed.calls().length, 0);
  await allowed.click(allowed.byId('run'));
  assert.equal(allowed.calls().length, 0);
  allowed.byId('confirm').close('confirm');
  await allowed.waitFor(() => allowed.calls().length === 1);
  assert.deepEqual(allowed.calls()[0].body.params, {
    name: 'loxone_operate_control',
    arguments: {control_uuid: 'test-control', action: 'on'},
  });
});

test('filters preserve selection and drafts; JSON edits update the form', async (t) => {
  const h = createHarness();
  t.after(h.close);
  await h.ready();
  const select = async (name) => h.click([...h.byId('tools').querySelectorAll('button')]
    .find((button) => button.textContent.includes(name)));
  await select('future_read');
  const query = [...h.byId('form').querySelectorAll('input[type="text"]')]
    .find((input) => input.labels?.[0]?.textContent.includes('query'));
  query.value = 'draft-kept';
  query.dispatchEvent(new h.window.Event('input', {bubbles: true}));
  const search = h.byId('tool-search');
  search.value = 'another';
  search.dispatchEvent(new h.window.Event('input', {bubbles: true}));
  assert.equal(h.byId('selected-tool').textContent.includes('future_read'), true);
  assert.equal(JSON.parse(h.byId('json').value).query, 'draft-kept');
  assert.equal(h.requests.filter((item) => item.body?.method === 'tools/list').length, 1);
  await select('another_read');
  search.value = '';
  search.dispatchEvent(new h.window.Event('input', {bubbles: true}));
  await select('future_read');
  assert.equal(JSON.parse(h.byId('json').value).query, 'draft-kept');
  await h.click(h.byId('json-tab'));
  h.byId('json').value = JSON.stringify({query: 'json-edited'});
  h.byId('json').dispatchEvent(new h.window.Event('change', {bubbles: true}));
  await h.click(h.byId('form-tab'));
  const updated = [...h.byId('form').querySelectorAll('input[type="text"]')]
    .find((input) => input.labels?.[0]?.textContent.includes('query'));
  assert.equal(updated.value, 'json-edited');
});

test('protocol view redacts schema secrets and never shows the Authorization header', async (t) => {
  const h = createHarness({tools: [readTool]});
  t.after(h.close);
  await h.ready();
  h.byId('json').value = JSON.stringify({query: 'public', password: 'private-password'});
  await h.click(h.byId('run'));
  await h.waitFor(() => h.calls().length === 1 && h.byId('history').querySelector('button'));
  assert.equal(h.calls()[0].body.params.arguments.password, 'private-password');
  const entries = h.byId('transcript').querySelectorAll('details');
  entries[entries.length - 1].open = true;
  entries[entries.length - 1].dispatchEvent(new h.window.Event('toggle'));
  const visible = h.byId('transcript').textContent;
  assert.match(visible, /\[redacted\]/);
  assert.doesNotMatch(visible, /private-password|synthetic-token|Authorization/);
  assert.doesNotMatch(h.byId('history').textContent, /private-password/);
  assert.doesNotMatch(JSON.stringify({...h.window.localStorage}), /private-password|synthetic-token/);
  assert.equal(h.requests.find((item) => item.pathname.endsWith('/explorer-session')).credentials,
    'same-origin');
});

test('token refresh updates the displayed granted scopes', async (t) => {
  const h = createHarness();
  t.after(h.close);
  await h.ready();
  const controlScope = () => [...h.byId('scope-list').querySelectorAll('li')]
    .find((item) => item.querySelector('code')?.textContent === 'loxone:control');
  assert.match(controlScope().textContent, /SCOPE_GRANTED/);
  h.setScope('loxone:read');
  h.advance(285000);
  await h.click([...h.byId('tools').querySelectorAll('button')]
    .find((button) => button.textContent.includes('future_read')));
  h.byId('json').value = JSON.stringify({query: 'refresh'});
  await h.click(h.byId('run'));
  await h.waitFor(() => h.calls().length === 1);
  assert.match(controlScope().textContent, /SCOPE_NOT_GRANTED/);
  assert.equal(h.requests.filter((item) => item.body?.action === 'access').length, 2);
});

test('expiry and logout discard sensitive state and late call results', async (t) => {
  const h = createHarness({deferCall: true, sessionMs: 60000});
  t.after(h.close);
  await h.ready();
  await h.click([...h.byId('tools').querySelectorAll('button')]
    .find((button) => button.textContent.includes('future_read')));
  h.byId('json').value = JSON.stringify({query: 'private-value'});
  await h.click(h.byId('run'));
  assert.equal(h.calls().length, 1);
  h.advance(60000);
  assert.equal(h.byId('connection-badge').dataset.kind, 'inactive');
  h.resolveCall();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(h.byId('history').querySelector('button'), null);
  assert.doesNotMatch(h.byId('result-tree').textContent, /result/);
  assert.doesNotMatch(h.byId('transcript').textContent, /private-value|synthetic-token/);

  const expired = createHarness({sessionMs: 60000});
  t.after(expired.close);
  await expired.ready();
  expired.advance(60000);
  assert.equal(expired.byId('connection-badge').dataset.kind, 'inactive');
  assert.equal(expired.byId('scope-list').textContent, '');
  assert.equal(expired.byId('run').disabled, true);
  assert.equal(expired.calls().length, 0);
});

test('failed restore stays disconnected without MCP calls', async (t) => {
  const h = createHarness({restoreFailure: true});
  t.after(h.close);
  await h.ready();
  await h.waitFor(() => h.byId('connection-badge').dataset.kind === 'inactive');
  assert.equal(h.requests.some((item) => item.pathname === '/plugins/mcpserver/mcp'), false);
  assert.equal(h.byId('run').disabled, true);
});
