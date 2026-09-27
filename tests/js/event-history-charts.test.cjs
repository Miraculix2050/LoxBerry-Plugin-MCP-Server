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
  <select id="chart-range"><option value="86400">Day</option></select>
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
    if (action === 'event_history_chart_query') return {
      generation: 1, events: [{id: 1, observed_at: Date.now() / 1000 - 10,
        old_value: false, new_value: true}], has_more: false, latest_id: 1,
      next_id: 1, reduced: false, coverage: [], capture_started_at: null,
      retained_from: null, recording_ended_at: null,
    };
    throw new Error(`Unexpected action ${action}`);
  }};
  window.eval(script);
  await flush();
  assert.deepEqual(calls.map(({action}) => action),
    ['event_history_chart_prepare', 'event_history_chart_query']);
  assert.equal(window.document.querySelectorAll('#chart-panels canvas').length, 1);
  assert.match(window.document.querySelector('#chart-panels').textContent, /Control/);

  hidden = true;
  tick();
  await flush();
  assert.equal(calls.length, 2);
  hidden = false;
  denied = true;
  window.document.querySelector('#chart-refresh').click();
  await flush();
  assert.equal(window.document.querySelector('#chart-panels').textContent, '');
  assert.equal(window.document.querySelector('#chart-status').textContent, 'Denied');
  dom.window.close();
});
