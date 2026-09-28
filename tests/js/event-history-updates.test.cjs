const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const script = fs.readFileSync(path.join(__dirname,
  '../../webfrontend/htmlauth/event-history/api.js'), 'utf8');
const flush = async () => {
  for (let index = 0; index < 5; index++) await new Promise((resolve) => setImmediate(resolve));
};

test('recorder wakeup carries no values and catches changes before the first token', async () => {
  const pending = [];
  const actions = [];
  const window = {setTimeout: () => 1, clearTimeout: () => {}};
  const document = {hidden: false, addEventListener: () => {}, removeEventListener: () => {}};
  const context = {window, document, URLSearchParams, AbortController,
    fetch: (_url, {body}) => {
      actions.push({action: body.get('action'), token: body.get('token')});
      return new Promise((resolve) => pending.push((data) => resolve({ok: true,
        json: async () => ({ok: true, data})})));
    }};
  vm.runInNewContext(script, context);
  let updates = 0;
  const stop = window.McpEventHistoryApi.subscribeUpdates(() => { updates++; },
    () => assert.fail('unexpected fallback'));
  await flush();
  assert.deepEqual(actions, [{action: 'event_history_wait_update', token: ''}]);
  pending.shift()({availability: 'available', token: 'a'.repeat(16), changed: true});
  await flush();
  assert.equal(updates, 1, 'initial wakeup must cover a change during page load');
  assert.deepEqual(actions[1], {action: 'event_history_wait_update', token: 'a'.repeat(16)});
  pending.shift()({availability: 'available', token: 'b'.repeat(16), changed: true});
  await flush();
  assert.equal(updates, 2);
  stop();
  pending.shift()({availability: 'available', token: 'b'.repeat(16), changed: false});
  await flush();
  assert.equal(actions.length, 3);
});
