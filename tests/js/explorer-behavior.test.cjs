'use strict';

const assert = require('node:assert/strict');
const {test} = require('node:test');
const {createHarness, readTool, writeTool, SCRIPT_NAMES} = require('./explorer-harness.cjs');

test('shipped scripts restore a session and execute an unknown read-only tool', async (t) => {
  const h = createHarness({deferLogout: true});
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
  assert.equal(h.requests.some((item) => item.body?.action === 'logout'), true);
  assert.equal(h.byId('connection-badge').dataset.kind, 'inactive');
  assert.equal(h.byId('history').querySelector('button'), null);
  assert.equal(h.byId('result-raw').textContent, '');
  assert.equal(h.byId('scope-list').textContent, '');
  assert.equal(h.byId('json').value, '{}');
  h.resolveLogout();
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

test('an unknown mutating tool requires confirmation before its first call', async (t) => {
  const unknownWrite = {
    name: 'future_write',
    inputSchema: {type: 'object', properties: {value: {type: 'string'}}, required: ['value']},
  };
  const h = createHarness({tools: [unknownWrite]});
  t.after(h.close);
  await h.ready();
  const toolButton = h.byId('tools').querySelector('button');
  assert.equal(toolButton.querySelector('.mcp-explorer-badge').dataset.kind, 'danger');
  h.byId('json').value = JSON.stringify({value: 'new-value'});
  await h.click(h.byId('run'));
  assert.equal(h.byId('confirm').open, true);
  assert.equal(h.calls().length, 0);
  h.byId('confirm').close('confirm');
  await h.waitFor(() => h.calls().length === 1);
  assert.deepEqual(h.calls()[0].body.params, {
    name: 'future_write', arguments: {value: 'new-value'},
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

test('logout clears another Explorer tab before logout and its pending call settle', async (t) => {
  const channelBus = new Set();
  const first = createHarness({channelBus, deferLogout: true});
  const second = createHarness({channelBus, deferCall: true});
  t.after(first.close);
  t.after(second.close);
  await Promise.all([first.ready(), second.ready()]);
  await second.click([...second.byId('tools').querySelectorAll('button')]
    .find((button) => button.textContent.includes('future_read')));
  second.byId('json').value = JSON.stringify({query: 'private-other-tab'});
  await second.click(second.byId('run'));
  assert.equal(second.calls().length, 1);

  await first.click(first.byId('disconnect'));
  assert.equal(first.requests.some((item) => item.body?.action === 'logout'), true);
  assert.equal(second.byId('connection-badge').dataset.kind, 'inactive');
  assert.equal(second.byId('scope-list').textContent, '');
  assert.equal(second.byId('json').value, '{}');
  assert.equal(second.byId('run').disabled, true);
  assert.doesNotMatch(second.byId('transcript').textContent, /private-other-tab/);
  second.resolveCall();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(second.byId('history').querySelector('button'), null);
  assert.doesNotMatch(second.byId('result-tree').textContent, /result/);
  first.resolveLogout();
});

test('session expiry closes an open mutation confirmation and erases its arguments', async (t) => {
  const h = createHarness({tools: [writeTool], sessionMs: 60000});
  t.after(h.close);
  await h.ready();
  h.byId('json').value = JSON.stringify({control_uuid: 'private-control', action: 'on'});
  await h.click(h.byId('run'));
  assert.equal(h.byId('confirm').open, true);
  assert.match(h.byId('confirm-arguments').textContent, /private-control/);
  assert.equal(h.calls().length, 0);
  h.advance(60000);
  assert.equal(h.byId('confirm').open, false);
  assert.equal(h.byId('confirm-tool').textContent, '');
  assert.equal(h.byId('confirm-arguments').textContent, '');
  assert.equal(h.byId('connection-badge').dataset.kind, 'inactive');
  assert.equal(h.calls().length, 0);
});

test('failed restore stays disconnected without MCP calls', async (t) => {
  const h = createHarness({restoreFailure: true});
  t.after(h.close);
  await h.ready();
  await h.waitFor(() => h.byId('connection-badge').dataset.kind === 'inactive');
  assert.equal(h.requests.some((item) => item.pathname === '/plugins/mcpserver/mcp'), false);
  assert.equal(h.byId('run').disabled, true);
});

const compactReadTool = {
  name: 'loxone_read_controls', description: 'Compact reads',
  annotations: {readOnlyHint: true, destructiveHint: false},
  inputSchema: {type: 'object', required: ['targets'], $defs: {
    Target: {type: 'object', additionalProperties: false, required: ['control_uuid'],
      properties: {control_uuid: {type: 'string', minLength: 1, maxLength: 128},
        state_names: {anyOf: [{type: 'array', minItems: 1, maxItems: 100, items: {type: 'string'}}, {type: 'null'}], default: null}}},
  }, properties: {targets: {type: 'array', minItems: 1, maxItems: 2, items: {$ref: '#/$defs/Target'}},
    include_semantics: {type: 'boolean', default: false}}},
};

test('object-list form edits rows and optional states, preserves drafts and bounds adds', async (t) => {
  const h = createHarness({tools: [compactReadTool, readTool]});
  t.after(h.close);
  await h.ready();
  const select = (name) => h.click([...h.byId('tools').querySelectorAll('button')]
    .find((button) => button.querySelector('strong')?.textContent === name));
  await select(compactReadTool.name);
  const add = () => h.byId('form').querySelector('.mcp-explorer-object-list > button');
  await h.click(add());
  const editUuid = (index, value) => {
    const input = h.byId('form').querySelectorAll('fieldset input[type="text"]')[index];
    input.value = value;
    input.dispatchEvent(new h.window.Event('input', {bubbles: true}));
  };
  editUuid(0, 'first');
  editUuid(0, 'first-edited');
  let entry = h.byId('form').querySelector('fieldset');
  await h.click(entry.querySelector('input[type="checkbox"]'));
  entry = h.byId('form').querySelector('fieldset');
  const states = entry.querySelector('textarea');
  states.value = '["position"]';
  states.dispatchEvent(new h.window.Event('change', {bubbles: true}));
  await h.click(add());
  editUuid(1, 'second');
  assert.equal(add().disabled, true);
  assert.deepEqual(JSON.parse(h.byId('json').value).targets, [
    {control_uuid: 'first-edited', state_names: ['position']}, {control_uuid: 'second'},
  ]);
  await select(readTool.name);
  await select(compactReadTool.name);
  assert.equal(h.byId('form').querySelectorAll('.mcp-explorer-list-entry').length, 2);
  await h.click(h.byId('form').querySelector('fieldset button'));
  assert.deepEqual(JSON.parse(h.byId('json').value).targets, [{control_uuid: 'second'}]);
  assert.equal(add().disabled, false);
  assert.equal(h.calls().length, 0);
});

test('UUID result transfer builds a schema-valid nested target without submitting it', async (t) => {
  const core = require('../../webfrontend/htmlauth/explorer-core.js');
  const candidate = core.compatibleTargets([compactReadTool], 'visible-control', {sourcePath: ['data', 'uuid']});
  assert.deepEqual(candidate, [{tool: compactReadTool.name, field: 'targets', mode: 'object-array:control_uuid'}]);
  const draft = core.transferArguments(compactReadTool, 'targets', 'visible-control',
    candidate[0].mode, null, {include_semantics: true, targets: [{control_uuid: 'old'}], cursor: 'old'});
  assert.deepEqual(draft, {include_semantics: true, targets: [{control_uuid: 'visible-control'}]});
  assert.deepEqual(core.validateArguments(draft, compactReadTool.inputSchema), []);
  assert.deepEqual(core.compatibleTargets([compactReadTool], ''), []);
  const h = createHarness({tools: [compactReadTool]});
  t.after(h.close);
  await h.ready();
  await h.click(h.byId('tools').querySelector('button'));
  h.byId('json').value = JSON.stringify(draft);
  h.byId('json').dispatchEvent(new h.window.Event('change', {bubbles: true}));
  await h.click(h.byId('form-tab'));
  assert.equal(h.byId('form').querySelector('fieldset input[type="text"]').value, 'visible-control');
  assert.equal(h.calls().length, 0);
});

test('nested transfer refuses missing required siblings and unknown schema constraints', () => {
  const core = require('../../webfrontend/htmlauth/explorer-core.js');
  const tool = JSON.parse(JSON.stringify(compactReadTool));
  tool.inputSchema.$defs.Target.required.push('other_required');
  tool.inputSchema.$defs.Target.properties.other_required = {type: 'string', minLength: 1};
  assert.deepEqual(core.compatibleTargets([tool], 'control'), []);
  tool.inputSchema.$defs.Target.required.pop();
  tool.inputSchema.$defs.Target.properties.control_uuid.format = 'unsupported-format';
  // Unrecognized formats are not offered as reusable targets.
  assert.deepEqual(core.compatibleTargets([tool], 'control'), []);
});

test('response UUID can be transferred through the actual dialog into targets', async (t) => {
  const h = createHarness({tools: [readTool, compactReadTool],
    callResult: {ok: true, data: {uuid: 'visible-control'}}});
  t.after(h.close);
  await h.ready();
  await h.click([...h.byId('tools').querySelectorAll('button')]
    .find((button) => button.querySelector('strong')?.textContent === readTool.name));
  h.byId('json').value = JSON.stringify({query: 'control'});
  await h.click(h.byId('run'));
  await h.waitFor(() => h.byId('result-tree').querySelector('.mcp-explorer-value') && h.calls().length === 1);
  const uuid = [...h.byId('result-tree').querySelectorAll('.mcp-explorer-value')]
    .find((button) => button.textContent.startsWith('uuid:'));
  assert.ok(uuid);
  await h.click(uuid);
  h.byId('transfer-tool').value = compactReadTool.name;
  h.byId('transfer-tool').dispatchEvent(new h.window.Event('change', {bubbles: true}));
  assert.match(h.byId('transfer-field').selectedOptions[0].textContent, /targets\[\]\.control_uuid/);
  h.byId('transfer').close('apply');
  await h.waitFor(() => h.byId('form').querySelector('fieldset input[type="text"]'));
  assert.deepEqual(JSON.parse(h.byId('json').value).targets, [{control_uuid: 'visible-control'}]);
  assert.equal(h.calls().length, 1);
});

test('optional object-list omission disables its entire group and preserves other arguments', async (t) => {
  const tool = JSON.parse(JSON.stringify(compactReadTool));
  tool.inputSchema.required = [];
  const h = createHarness({tools: [tool]});
  t.after(h.close);
  await h.ready();
  await h.click(h.byId('tools').querySelector('button'));
  let group = h.byId('form').querySelector('.mcp-explorer-object-list');
  assert.equal(group.disabled, true);
  let toggle = group.parentElement.querySelector('input[type="checkbox"]');
  await h.click(toggle);
  group = h.byId('form').querySelector('.mcp-explorer-object-list');
  assert.equal(group.disabled, false);
  assert.equal(group.ownerDocument.activeElement, group.querySelector(':scope > button'));
  await h.click(group.querySelector(':scope > button'));
  group = h.byId('form').querySelector('.mcp-explorer-object-list');
  toggle = group.parentElement.querySelector('input[type="checkbox"]');
  await h.click(toggle);
  assert.equal(group.disabled, true);
  assert.equal(Object.hasOwn(JSON.parse(h.byId('json').value), 'targets'), false);
  assert.equal(h.calls().length, 0);
});

test('root action changes still remove old operation fields after valid draft edits', async (t) => {
  const tool = JSON.parse(JSON.stringify(writeTool));
  tool.inputSchema.properties.action = {type: 'string', enum: ['set_level', 'off'], default: 'set_level'};
  tool.inputSchema.properties.level = {type: 'number', default: 50};
  const h = createHarness({tools: [tool]});
  t.after(h.close);
  await h.ready();
  await h.click(h.byId('tools').querySelector('button'));
  const uuid = h.byId('form').querySelector('input[type="text"]');
  uuid.value = 'visible-control';
  uuid.dispatchEvent(new h.window.Event('input', {bubbles: true}));
  const action = h.byId('form').querySelector('select');
  action.value = JSON.stringify('off');
  action.dispatchEvent(new h.window.Event('change', {bubbles: true}));
  assert.deepEqual(JSON.parse(h.byId('json').value), {control_uuid: 'visible-control', action: 'off'});
  assert.equal(h.calls().length, 0);
});


test('adding an object row focuses an enabled control when its first field is optional', async (t) => {
  const tool = JSON.parse(JSON.stringify(compactReadTool));
  tool.inputSchema.properties.targets.items.properties = {
    state_names: {type: 'array', items: {type: 'string'}},
    control_uuid: {type: 'string'},
  };
  const h = createHarness({tools: [tool]});
  t.after(h.close);
  await h.ready();
  await h.click(h.byId('tools').querySelector('button'));
  await h.click(h.byId('form').querySelector('.mcp-explorer-object-list > button'));
  const entry = h.byId('form').querySelector('.mcp-explorer-list-entry');
  const focused = entry.ownerDocument.activeElement;
  assert.equal(entry.contains(focused), true);
  assert.equal(focused.disabled, false);
  assert.notEqual(focused.tagName, 'FIELDSET');
  assert.equal(entry.querySelector('textarea').disabled, true);
});

const modbusAnalysisTool = {
  name: 'loxone_analyze_project', description: 'Static project analysis',
  annotations: {readOnlyHint: true, destructiveHint: false},
  inputSchema: {type: 'object', properties: {
    scope: {type: 'string', enum: ['knx', 'modbus'], default: 'knx'},
    analyses: {anyOf: [{type: 'array', items: {type: 'string'}}, {type: 'null'}],
      default: null, 'x-analyses-by-scope': {
        knx: ['address_patterns'], modbus: ['inventory', 'configured_register_mappings',
          'direct_consumers', 'configured_polling', 'evidence_gaps'],
      }},
    cursor: {type: 'string'},
  }},
};

test('analysis scope changes clear stale selections and cursor and retain keyboard focus', async (t) => {
  const h = createHarness({tools: [modbusAnalysisTool]});
  t.after(h.close);
  await h.ready();
  const field = (name) => [...h.document.querySelectorAll('.mcp-explorer-field')]
    .find((row) => [...row.querySelectorAll('label')].some((label) => label.textContent === name));
  const toggle = field('scope').querySelector('input[type=checkbox]');
  if (!toggle.checked) await h.click(toggle);
  const scope = field('scope').querySelector('select');
  scope.focus();
  scope.value = JSON.stringify('modbus');
  scope.dispatchEvent(new h.window.Event('change', {bubbles: true}));
  assert.equal(h.document.activeElement.id, scope.id);
  const analyses = field('analyses').querySelector('select');
  assert.equal(analyses.multiple, true);
  assert.deepEqual([...analyses.options].map((option) => option.value),
    modbusAnalysisTool.inputSchema.properties.analyses['x-analyses-by-scope'].modbus);
  await h.click(field('analyses').querySelector('input[type=checkbox]'));
  const selection = field('analyses').querySelector('select');
  selection.options[0].selected = true;
  selection.dispatchEvent(new h.window.Event('change', {bubbles: true}));
  assert.deepEqual(JSON.parse(h.byId('json').value), {scope: 'modbus', analyses: ['inventory']});
  await h.click(field('cursor').querySelector('input[type=checkbox]'));
  const cursor = field('cursor').querySelector('input:not([type=checkbox])');
  cursor.value = 'synthetic-old-cursor';
  cursor.dispatchEvent(new h.window.Event('input', {bubbles: true}));
  const nextScope = field('scope').querySelector('select');
  nextScope.value = JSON.stringify('knx');
  nextScope.dispatchEvent(new h.window.Event('change', {bubbles: true}));
  assert.deepEqual(JSON.parse(h.byId('json').value), {scope: 'knx'});
  assert.deepEqual([...field('analyses').querySelector('select').options].map((option) => option.value),
    ['address_patterns']);
});

test('Modbus results keep facts, review candidates, gaps and partial coverage visible', async (t) => {
  const h = createHarness({tools: [modbusAnalysisTool], callResult: {ok: true, data: {
    scope: 'modbus', findings: [
      {classification: 'fact', finding_type: 'direct_consumer_summary'},
      {classification: 'review_candidate', finding_type: 'configured_mapping_repeated'},
      {classification: 'evidence_gap', finding_type: 'modbus_evidence_gap'},
    ], coverage: {presentation_complete: true, candidate_scan_complete: true,
      source_ingestion_complete: true, supported_type_coverage_complete: true},
    check_status: {direct_consumers: {status: 'partial'}},
  }}});
  t.after(h.close);
  await h.ready();
  h.byId('json').value = JSON.stringify({scope: 'modbus'});
  await h.click(h.byId('run'));
  await h.waitFor(() => h.calls().length === 1 && h.byId('result-tree').firstChild?.className === 'mcp-explorer-stack');
  const summary = h.byId('result-tree').firstChild;
  assert.equal(summary.querySelectorAll('p').length, 3);
  assert.match(summary.firstChild.textContent, /1.*1.*1/);
  assert.ok(summary.querySelector('.mcp-explorer-warning'));
  assert.doesNotMatch(summary.textContent, /unused|healthy|fault/);
});
