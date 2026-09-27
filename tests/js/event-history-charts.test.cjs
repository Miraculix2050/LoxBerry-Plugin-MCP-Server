const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');

const source = {control_uuid: '00000000-0000-0000-0000000000000001',
  state_uuid: '00000000-0000-0000-0000000000000002'};
const script = fs.readFileSync(path.join(__dirname,
  '../../webfrontend/htmlauth/event-history/charts.js'), 'utf8');
const html = `<main class="mcp-history-charts" data-loading="Loading"
  data-chart-denied="Denied" data-chart-error="Failed" data-chart-empty="Empty"
  data-chart-reduced="Reduced" data-chart-value="Value" data-chart-coverage="Coverage">
  <select id="chart-range"><option value="86400">Day</option><option value="custom">Custom</option></select>
  <input id="chart-from"><input id="chart-to"><button id="chart-apply"></button>
  <button id="chart-previous"></button><button id="chart-next"></button>
  <button id="chart-zoom-in"></button>
  <button id="chart-zoom-out"></button><button id="chart-refresh"></button>
  <p id="chart-status"></p><div id="chart-panels"></div></main>`;
const flush = async () => {
  for (let index = 0; index < 10; index++) await new Promise((resolve) => setImmediate(resolve));
};

test('chart tab loads only selected values, pauses hidden polling, and clears revoked data', async () => {
  const url = `https://example.test/event_history.cgi?view=charts&sources=${encodeURIComponent(JSON.stringify([source]))}`;
  const dom = new JSDOM(html, {url, runScripts: 'outside-only'});
  const {window} = dom;
  const calls = [];
  let denied = false;
  let holdNext = false;
  let releaseHeld;
  let tick;
  let hidden = false;
  Object.defineProperty(window.document, 'hidden', {get: () => hidden});
  window.setInterval = (callback) => { tick = callback; return 1; };
  window.uPlot = class {
    static paths = {stepped: () => () => ({})};
    constructor(options, data, host) {
      this.options = options; this.data = data; this.host = host;
      host.append(window.document.createElement('canvas'));
      this.scales = {x: {min: data[0][0], max: data[0].at(-1)}};
    }
    setScale(_key, {min, max}) { this.scales.x = {min, max}; }
    setSize() {}
    destroy() { this.host.replaceChildren(); }
  };
  window.McpEventHistoryApi = {request: async (action, fields) => {
    calls.push({action, fields});
    if (action === 'event_history_chart_prepare') {
      if (denied) throw Object.assign(new Error('denied'), {code: 'forbidden'});
      return {generation: 'a'.repeat(24), verified_at: Date.now() / 1000,
        sources: [{...source, control_name: 'Control', state_name: 'State',
          room: 'Room', category: 'Category', control_type: 'Switch'}]};
    }
    if (action === 'event_history_chart_query') {
      const answer = {results: [{
      generation: 1, events: [{id: 1, observed_at: Date.now() / 1000 - 10,
        old_value: false, new_value: true}], has_more: false, latest_id: 1,
      next_id: 1, reduced: false, coverage: [], capture_started_at: null,
      retained_from: null, recording_ended_at: null,
      }]};
      if (holdNext) {
        holdNext = false;
        return new Promise((resolve) => { releaseHeld = () => resolve(answer); });
      }
      return answer;
    }
    throw new Error(`Unexpected action ${action}`);
  }};
  window.eval(script);
  await flush();
  assert.deepEqual(calls.map(({action}) => action),
    ['event_history_chart_prepare', 'event_history_chart_query']);
  assert.deepEqual(Object.keys(JSON.parse(calls[1].fields.queries)[0]).sort(),
    ['after_id', 'control_uuid', 'end', 'generation', 'start', 'state_uuid']);
  assert.equal(window.document.querySelectorAll('#chart-panels canvas').length, 1);
  assert.match(window.document.querySelector('#chart-panels').textContent, /Control/);

  const queries = () => calls.filter(({action}) => action === 'event_history_chart_query');
  const initialRange = JSON.parse(queries()[0].fields.queries)[0];
  const originalNow = window.Date.now;
  window.Date.now = () => originalNow() + 60000;
  tick();
  await flush();
  const advancedRange = JSON.parse(queries()[1].fields.queries)[0];
  assert.ok(advancedRange.end > initialRange.end + 59);
  assert.ok(advancedRange.start > initialRange.start + 59);
  const rangeSelect = window.document.querySelector('#chart-range');
  rangeSelect.value = 'custom';
  rangeSelect.dispatchEvent(new window.Event('change'));
  window.Date.now = () => originalNow() + 120000;
  tick();
  await flush();
  const fixedRange = JSON.parse(queries()[2].fields.queries)[0];
  assert.equal(fixedRange.end, advancedRange.end);
  window.Date.now = originalNow;

  holdNext = true;
  tick();
  await flush();
  assert.equal(typeof releaseHeld, 'function');
  window.document.querySelector('#chart-previous').click();
  releaseHeld();
  await flush();
  const replay = JSON.parse(queries().at(-1).fields.queries)[0];
  assert.equal(replay.after_id, 0);
  assert.ok(replay.end < fixedRange.end);

  hidden = true;
  const beforeHidden = calls.length;
  tick();
  await flush();
  assert.equal(calls.length, beforeHidden);
  hidden = false;
  denied = true;
  window.document.querySelector('#chart-refresh').click();
  await flush();
  assert.equal(window.document.querySelector('#chart-panels').textContent, '');
  assert.equal(window.document.querySelector('#chart-status').textContent, 'Denied');
  dom.window.close();
});
