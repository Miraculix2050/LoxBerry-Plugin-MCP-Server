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
  data-chart-timeout="Timed out" data-chart-unavailable="Unavailable"
  data-chart-invalid="Invalid range" data-chart-stale="Data may be stale"
  data-chart-reference="Reference"
  data-chart-reduced="Reduced" data-chart-value="Value" data-chart-number="Number"
  data-chart-boolean="Boolean value" data-chart-coverage="Coverage">
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
  let queryCount = 0;
  let failCode = null;
  let historyGeneration = 1;
  let selectorGeneration = 'a'.repeat(24);
  let pendingEvent = null;
  let latestId = 2;
  let reducedMode = false;
  let coverage = [{started_at: Date.now() / 1000 - 30,
    ended_at: Date.now() / 1000 - 20, outcome: 'stopped'}];
  Object.defineProperty(window.document, 'hidden', {get: () => hidden});
  window.setInterval = (callback) => { tick = callback; return 1; };
  window.uPlot = class {
    static paths = {stepped: () => () => ({})};
    static instances = [];
    static dataUpdates = 0;
    constructor(options, data, host) {
      this.options = options; this.data = data; this.host = host;
      window.uPlot.instances.push(this);
      host.append(window.document.createElement('canvas'));
      this.over = window.document.createElement('div');
      this.over.className = 'u-over';
      this.over.getBoundingClientRect = () => ({left: 100, width: 400, height: 220});
      host.append(this.over);
      this.scales = {x: {min: data[0][0], max: data[0].at(-1)}};
    }
    setData(data) { this.data = data; window.uPlot.dataUpdates++; }
    setScale(_key, {min, max}) { this.scales.x = {min, max}; }
    setSize() {}
    destroy() { this.host.replaceChildren(); }
  };
  window.McpEventHistoryApi = {request: async (action, fields) => {
    calls.push({action, fields});
    if (action === 'event_history_chart_prepare') {
      if (denied) throw Object.assign(new Error('denied'), {code: 'forbidden'});
      return {generation: selectorGeneration, verified_at: Date.now() / 1000,
        sources: [{...source, control_name: selectorGeneration[0] === 'b' ? 'Renamed' : 'Control',
          state_name: 'State',
          room: 'Room', category: 'Category', control_type: 'Switch'}]};
    }
    if (action === 'event_history_chart_query') {
      queryCount++;
      if (failCode) throw Object.assign(new Error('failed'),
        {code: failCode, requestId: 'abc-123'});
      const events = pendingEvent ? [pendingEvent] : queryCount === 1 ? [
        {id: 1, observed_at: Date.now() / 1000 - 10, old_value: false, new_value: true},
        {id: 2, observed_at: Date.now() / 1000 - 9, old_value: 0,
          new_value: {integer_decimal: '9007199254740993'}},
      ] : [];
      if (pendingEvent) { latestId = pendingEvent.id; pendingEvent = null; }
      const answer = {results: [{
      generation: historyGeneration, events, has_more: false, latest_id: latestId,
      next_id: latestId, reduced: reducedMode, coverage, capture_started_at: null,
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
  assert.equal(window.document.querySelector('#chart-panels section > details:last-of-type').hidden,
    true);
  const chart = window.uPlot.instances[0];
  assert.equal(chart.options.series.length, 3, 'mixed scalar values use both plot series');
  assert.equal(chart.options.series[1].points.show, true,
    'an isolated numeric observation remains visible in a dense mixed range');
  assert.equal(chart.options.series[2].points.show, true,
    'an isolated Boolean observation remains visible in a dense mixed range');
  assert.ok(chart.data[1].some((value) => value > 1000), 'numeric value is plotted');
  assert.ok(chart.data[2].includes(1), 'Boolean value is plotted');
  chart.cursor = {idx: chart.data[0].length - 1};
  chart.options.hooks.setCursor[0](chart);
  assert.match(window.document.querySelector('#chart-panels section [aria-live="polite"]').textContent,
    /9007199254740993/);
  const plotHost = window.document.querySelector('#chart-panels .mcp-history-chart-plot');
  plotHost.dispatchEvent(new window.KeyboardEvent('keydown', {key: 'End', bubbles: true}));
  assert.match(window.document.querySelector('#chart-panels section [aria-live="polite"]').textContent,
    /9007199254740993/);
  assert.equal(window.document.querySelectorAll('#chart-panels ul li').length, 1);

  const queries = () => calls.filter(({action}) => action === 'event_history_chart_query');
  const initialRange = JSON.parse(queries()[0].fields.queries)[0];
  const originalNow = window.Date.now;
  window.Date.now = () => originalNow() + 60000;
  coverage = [];
  tick();
  await flush();
  assert.equal(window.document.querySelectorAll('#chart-panels ul li').length, 0);
  const advancedRange = JSON.parse(queries()[1].fields.queries)[0];
  assert.ok(advancedRange.end > initialRange.end + 59);
  assert.ok(advancedRange.start > initialRange.start + 59);
  const rangeSelect = window.document.querySelector('#chart-range');
  rangeSelect.value = 'custom';
  rangeSelect.dispatchEvent(new window.Event('change'));
  window.Date.now = () => originalNow() + 120000;
  tick();
  await flush();
  const fixedRange = JSON.parse(queries().at(-1).fields.queries)[0];
  assert.equal(fixedRange.end, advancedRange.end);
  window.Date.now = originalNow;
  pendingEvent = {id: 3, observed_at: fixedRange.end - 5, old_value: 1, new_value: 2};
  const originalPlot = window.uPlot.instances[0];
  tick();
  await flush();
  assert.equal(window.uPlot.instances.length, 1, 'new numeric value reuses the plot');
  assert.ok(window.uPlot.dataUpdates > 0);
  assert.ok(originalPlot.data[0].length >= 2);
  const wheelQueries = queries().length;
  const wheelStart = originalPlot.scales.x.min;
  const wheelEnd = originalPlot.scales.x.max;
  const plainWheel = new window.WheelEvent('wheel', {deltaY: -100, clientX: 500,
    bubbles: true, cancelable: true});
  originalPlot.over.dispatchEvent(plainWheel);
  assert.equal(plainWheel.defaultPrevented, false, 'ordinary wheel keeps page scrolling');
  assert.equal(originalPlot.scales.x.min, wheelStart);
  const outsideWheel = new window.WheelEvent('wheel', {deltaY: -100, ctrlKey: true,
    clientX: 500, bubbles: true, cancelable: true});
  plotHost.dispatchEvent(outsideWheel);
  assert.equal(outsideWheel.defaultPrevented, false, 'Ctrl+wheel outside the plot is untouched');
  const zoomInWheel = new window.WheelEvent('wheel', {deltaY: -100, ctrlKey: true,
    clientX: 500, bubbles: true, cancelable: true});
  originalPlot.over.dispatchEvent(zoomInWheel);
  await flush();
  assert.equal(zoomInWheel.defaultPrevented, true);
  assert.equal(queries().length, wheelQueries, 'wheel zoom inside loaded data stays local');
  assert.ok(originalPlot.scales.x.min > wheelStart);
  assert.ok(Math.abs(originalPlot.scales.x.max - wheelEnd) < 0.01,
    'wheel zoom anchors the time at the pointer');
  const zoomOutWheel = new window.WheelEvent('wheel', {deltaY: 100, ctrlKey: true,
    clientX: 500, bubbles: true, cancelable: true});
  originalPlot.over.dispatchEvent(zoomOutWheel);
  await flush();
  assert.equal(queries().length, wheelQueries);
  assert.ok(Math.abs(originalPlot.scales.x.min - wheelStart) < 0.01);
  pendingEvent = {id: 4, observed_at: fixedRange.end - 4,
    old_value: 2, new_value: 'offline'};
  tick();
  await flush();
  assert.equal(window.document.querySelector('#chart-panels section > details:last-of-type').hidden,
    false);
  assert.match(window.document.querySelector('#chart-panels table').textContent, /offline/);
  failCode = 'outcome_unknown';
  tick();
  await flush();
  assert.equal(window.document.querySelectorAll('#chart-panels canvas').length, 1);
  assert.match(window.document.querySelector('#chart-status').textContent,
    /Timed out.*Data may be stale.*abc-123/);
  failCode = 'query_timeout';
  tick();
  await flush();
  assert.match(window.document.querySelector('#chart-status').textContent, /Timed out/);
  failCode = null;
  tick();
  await flush();
  assert.equal(window.document.querySelector('#chart-status').textContent, '');
  failCode = 'temporarily_unavailable';
  window.document.querySelector('#chart-refresh').click();
  await flush();
  assert.equal(window.document.querySelectorAll('#chart-panels canvas').length, 1,
    'successful visibility recheck preserves values after transient query failure');
  assert.match(window.document.querySelector('#chart-status').textContent, /Unavailable/);
  failCode = null;
  tick();
  await flush();
  selectorGeneration = 'b'.repeat(24);
  failCode = 'temporarily_unavailable';
  window.document.querySelector('#chart-refresh').click();
  await flush();
  assert.equal(window.document.querySelectorAll('#chart-panels canvas').length, 1,
    'a changed selector generation retains verified values after a transient query error');
  assert.match(window.document.querySelector('#chart-panels section h2').textContent, /Renamed/);
  failCode = null;
  tick();
  await flush();

  rangeSelect.value = '86400';
  rangeSelect.dispatchEvent(new window.Event('change'));
  await flush();
  assert.doesNotMatch(window.document.querySelector('#chart-panels table').textContent,
    /offline/, 'text events outside the active range are hidden');
  assert.equal(window.document.querySelector('#chart-panels section > details:last-of-type').hidden,
    true);
  holdNext = true;
  tick();
  await flush();
  assert.equal(typeof releaseHeld, 'function');
  const heldRange = JSON.parse(queries().at(-1).fields.queries)[0];
  window.document.querySelector('#chart-previous').click();
  assert.equal(rangeSelect.value, 'custom');
  assert.equal(window.document.querySelector('#chart-from').disabled, false);
  assert.equal(window.document.querySelector('#chart-apply').disabled, false);
  coverage = [{started_at: Date.now() / 1000 - 30,
    ended_at: Date.now() / 1000 - 20, outcome: 'stopped'}];
  releaseHeld();
  await flush();
  const replay = JSON.parse(queries().at(-1).fields.queries)[0];
  assert.equal(replay.after_id, 0);
  assert.ok(replay.end < fixedRange.end);
  assert.ok(Math.abs(replay.end - heldRange.start) < 2,
    'Earlier requests only the missing left interval');
  assert.equal(window.document.querySelectorAll('#chart-panels ul li').length, 0,
    'coverage outside the active range stays out of the visible list');
  const beforeZoom = queries().length;
  window.document.querySelector('#chart-zoom-in').click();
  await flush();
  assert.equal(queries().length, beforeZoom, 'zoom inside the loaded interval stays local');
  const activePlot = window.uPlot.instances.at(-1);
  const width = activePlot.scales.x.max - activePlot.scales.x.min;
  activePlot.scales.x = {min: activePlot.scales.x.min + width / 4,
    max: activePlot.scales.x.max - width / 4};
  activePlot.options.hooks.setScale[0](activePlot, 'x');
  await new Promise((resolve) => window.setTimeout(resolve, 0));
  await flush();
  assert.equal(queries().length, beforeZoom, 'drag zoom inside loaded data stays local');
  pendingEvent = {id: 5, observed_at: activePlot.scales.x.max - 5,
    old_value: false, new_value: true};
  tick();
  await flush();
  assert.ok(window.uPlot.instances.at(-1).options.series[1].paths,
    'the active boolean-only range selects a stepped plot despite cached numeric values');
  plotHost.dispatchEvent(new window.KeyboardEvent('keydown', {key: 'End', bubbles: true}));
  assert.match(window.document.querySelector('#chart-panels section [aria-live="polite"]')
    .textContent, /true/, 'keyboard navigation reads only the active boolean range');
  historyGeneration++;
  reducedMode = true;
  const beforeChange = queries().length;
  tick();
  await flush();
  assert.ok(queries().length > beforeChange + 1, 'history mutation retries after busy clears');
  assert.match(window.document.querySelector('#chart-panels section').textContent, /Reduced/);
  plotHost.dispatchEvent(new window.KeyboardEvent('keydown', {key: 'End', bubbles: true}));
  assert.equal(window.document.querySelector('#chart-panels section [aria-live="polite"]')
    .textContent, '', 'cleared history has no stale keyboard value');
  reducedMode = false;
  const beforeReducedZoom = queries().length;
  window.document.querySelector('#chart-zoom-in').click();
  await flush();
  assert.equal(queries().length, beforeReducedZoom + 1,
    'narrowing a sampled interval requests more detailed values');
  assert.doesNotMatch(window.document.querySelector('#chart-panels section').textContent,
    /Reduced/, 'an exact narrowed range clears the old reduction notice');
  window.document.querySelector('#chart-from').value = 'invalid';
  window.document.querySelector('#chart-apply').click();
  assert.equal(window.document.querySelector('#chart-status').textContent, 'Invalid range');
  window.document.querySelector('#chart-zoom-in').click();
  await flush();
  assert.equal(window.document.querySelector('#chart-status').textContent, '',
    'a valid cached zoom clears the earlier invalid-range warning');
  failCode = 'history_changed';
  const beforeRepeatedChange = queries().length;
  tick();
  await flush();
  assert.equal(queries().length, beforeRepeatedChange + 2,
    'a persistent history change gets one immediate retry');
  assert.equal(window.document.querySelector('#chart-status').textContent, 'Unavailable');
  failCode = null;
  tick();
  await flush();
  assert.equal(window.document.querySelector('#chart-status').textContent, '',
    'the next visible-tab poll recovers after the bounded retry');

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
