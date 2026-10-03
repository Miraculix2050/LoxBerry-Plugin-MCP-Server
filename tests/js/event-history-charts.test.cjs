const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');

const source = {control_uuid: '00000000-0000-0000-0000000000000001',
  state_uuid: '00000000-0000-0000-0000000000000002'};
const script = fs.readFileSync(path.join(__dirname,
  '../../webfrontend/htmlauth/event-history/charts.js'), 'utf8');
const cacheScript = fs.readFileSync(path.join(__dirname,
  '../../webfrontend/htmlauth/event-history/chart-cache.js'), 'utf8');
const html = `<main class="mcp-history-charts" data-loading="Loading"
  data-chart-denied="Denied" data-chart-error="Failed" data-chart-empty="Empty"
  data-chart-timeout="Timed out" data-chart-unavailable="Unavailable"
  data-chart-invalid="Invalid range" data-chart-stale="Data may be stale"
  data-chart-reference="Reference"
  data-chart-reloading="Refreshing" data-chart-cache-full="Display limit"
  data-chart-reduced="Reduced" data-chart-value="Value" data-chart-number="Number"
  data-chart-boolean="Boolean value">
  <select id="chart-range"><option value="3600">Hour</option><option value="86400">Day</option><option value="custom">Custom</option></select>
  <input id="chart-from"><input id="chart-to"><button id="chart-apply"></button>
  <button id="chart-previous"></button><button id="chart-next"></button>
  <button id="chart-zoom-in"></button>
  <button id="chart-zoom-out"></button><button id="chart-refresh"></button>
  <p id="chart-status"></p><div id="chart-panels"></div></main>`;
const flush = async () => {
  for (let index = 0; index < 10; index++) await new Promise((resolve) => setImmediate(resolve));
};

const otherSource = {...source, state_uuid: '00000000-0000-0000-0000000000000003'};
async function overflowFixture({initialCount = 4000, replacement = 'reduced',
  both = false, duplicate = false, controller = script, saved = null} = {}) {
  const now = Date.now() / 1000;
  const dom = new JSDOM(html, {url: 'https://example.test/?sources=' +
    encodeURIComponent(JSON.stringify([source, otherSource])), runScripts: 'outside-only'});
  const {window} = dom;
  if (saved) window.sessionStorage.setItem('mcp-event-history-chart-v1', JSON.stringify(saved));
  window.Date.now = () => now * 1000;
  let hidden = false, tick, release, updating = false, replacing = false;
  const calls = [], plots = [];
  Object.defineProperty(window.document, 'hidden', {get: () => hidden});
  window.setInterval = (callback) => { tick = callback; return 1; };
  window.uPlot = class {
    static paths = {stepped: () => () => ({})};
    constructor(options, data, host) {
      this.options = options; this.data = data; this.host = host;
      this.scales = {x: {min: 0, max: 1}};
      this.over = window.document.createElement('div'); host.append(this.over); plots.push(this);
    }
    setData(data) { this.data = data; }
    setScale(_key, value) { this.scales.x = value; }
    destroy() { this.destroyed = true; this.host.replaceChildren(); }
  };
  const event = (id) => ({id, observed_at: now - 5000 + id, new_value: id});
  const page = (events, overrides = {}) => ({events, generation: 1,
    has_more: false, latest_id: events.at(-1)?.id || 0, next_id: events.at(-1)?.id || 0,
    reduced: false, coverage: [{started_at: now - 86400, ended_at: null, outcome: 'recording'}],
    capture_started_at: now - 86400, retained_from: now - 86400,
    recording_ended_at: null, ...overrides});
  window.McpEventHistoryApi = {request: async (action, fields) => {
    calls.push({action, fields});
    if (action === 'event_history_chart_prepare') return {
      generation: 'a'.repeat(24), history_generation: 1, verified_at: now,
      sources: [source, otherSource].map((item, index) => ({...item,
        control_name: `Control ${index}`, state_name: 'State', room: 'Room',
        category: 'Category', control_type: 'Number'}))};
    const queries = JSON.parse(fields.queries);
    if (updating && queries.some((query) => query.after_id === 0
      || (queries.length === 1 && replacing
        && ['pages', 'paged-exact'].includes(replacement) && query.after_id < 4000))) {
      replacing = true;
      await new Promise((resolve) => { release = resolve; });
      if (replacement === 'timeout') throw Object.assign(new Error(), {code: 'query_timeout'});
      if (replacement === 'network') throw new window.TypeError('Network');
      if (replacement === 'forbidden') throw Object.assign(new Error(), {code: 'forbidden'});
      if (replacement === 'stale') throw Object.assign(new Error(), {code: 'stale_configuration'});
      return {results: queries.map(() => replacement === 'overflow'
        ? page(Array.from({length: 4001}, (_, index) => event(index + 1)))
        : replacement === 'pages'
          ? page([event(queries[0].after_id + 1)], {has_more: true,
            next_id: queries[0].after_id + 1, latest_id: 5000})
        : replacement === 'paged-exact'
          ? page([event(queries[0].after_id + 1)], {has_more: queries[0].after_id === 0,
            next_id: queries[0].after_id + 1, latest_id: 4001})
        : page([event(1), event(4001)], {latest_id: 4001,
          reduced: replacement === 'reduced', generation: replacement === 'changed' ? 2 : 1}))};
    }
    return {results: queries.map((query) => {
      const primary = query.state_uuid === source.state_uuid;
      if (updating) return primary || both
        ? page([event(duplicate ? initialCount : 4001)], {latest_id: duplicate ? initialCount : 4001})
        : page([event(11)]);
      const total = primary || both ? initialCount : 10;
      const first = query.after_id + 1, last = Math.min(total, first + 499);
      return page(Array.from({length: Math.max(0, last - first + 1)}, (_, index) => event(first + index)),
        {has_more: last < total, latest_id: total, next_id: last});
    })};
  }};
  window.eval(cacheScript); window.eval(controller); await flush();
  return {window, calls, plots, event, page,
    snapshot: () => JSON.parse(window.sessionStorage.getItem('mcp-event-history-chart-v1')),
    update: async () => { updating = true; tick(); await flush(); },
    release: async () => { release?.(); await flush(); },
    get replacing() { return replacing; },
    stopUpdating: () => { updating = false; },
    hide: () => { hidden = true; }, tick, close: () => dom.window.close()};
}

test('cache overflow keeps both plots visible and atomically replaces only its source', async () => {
  const fixture = await overflowFixture();
  const {window, plots, calls} = fixture;
  assert.equal(fixture.snapshot().sources[0].events.length, 4000);
  await fixture.update();
  assert.equal(fixture.replacing, true);
  assert.equal(plots.length, 2);
  assert.ok(plots.every((plot) => !plot.destroyed && plot.data[0].length));
  assert.match(window.document.querySelector('#chart-panels section').textContent, /Refreshing/);
  const replacementQuery = JSON.parse(calls.at(-1).fields.queries);
  assert.equal(replacementQuery.length, 1);
  assert.equal(replacementQuery[0].after_id, 0);
  assert.equal(replacementQuery[0].state_uuid, source.state_uuid);
  await fixture.release();
  const saved = fixture.snapshot();
  assert.deepEqual(saved.sources[0].events.map((event) => event.id), [1, 4001]);
  assert.equal(saved.sources[0].cursor, 4001);
  assert.equal(saved.sources[0].exact.length, 0);
  assert.equal(saved.sources[0].sampled.length, 1);
  assert.equal(saved.sources[1].events.length, 11);
  assert.equal(saved.sources[1].cursor, 11);
  assert.deepEqual(saved.sources[0].coverage, saved.sources[1].coverage);
  assert.match(window.document.querySelector('#chart-panels section').textContent, /Reduced/);
  const before = calls.length;
  await fixture.update();
  assert.equal(calls.length, before + 1, 'next incremental update does not reload');
  assert.equal(fixture.snapshot().sources[0].events.length, 2, 'duplicate IDs stay unique');
  assert.ok(plots.every((plot) => !plot.destroyed));
  const restored = await overflowFixture({saved: fixture.snapshot()});
  assert.equal(restored.snapshot().sources[0].events.length, 2);
  assert.equal(restored.snapshot().sources[0].sampled.length, 1);
  assert.ok(restored.calls.filter((call) => call.action === 'event_history_chart_query')
    .every((call) => JSON.parse(call.fields.queries).every((query) => query.after_id > 0)),
  'restored replacement fetches only newer values after fresh preparation');
  restored.close();
  fixture.close();
});

for (const replacement of ['timeout', 'network', 'overflow']) {
  test(`failed ${replacement} replacement retains values and retries only on a later update`, async () => {
    const fixture = await overflowFixture({replacement});
    await fixture.update(); await fixture.release();
    assert.equal(fixture.snapshot().sources[0].events.length, 4000);
    assert.equal(fixture.snapshot().sources[0].cursor, 4000);
    assert.equal(fixture.snapshot().sources[1].events.length, 11);
    const count = fixture.calls.length;
    await flush();
    assert.equal(fixture.calls.length, count, 'no immediate retry loop');
    assert.match(fixture.window.document.querySelector('#chart-panels section').textContent,
      replacement === 'overflow' ? /Display limit/ : /stale/);
    fixture.hide(); fixture.tick(); await flush();
    assert.equal(fixture.calls.length, count, 'hidden tabs do not retry');
    fixture.close();
  });
}

test('a successful empty fixed-range update clears a previous source recovery warning', async () => {
  const fixture = await overflowFixture({replacement: 'timeout'});
  const select = fixture.window.document.getElementById('chart-range');
  select.value = 'custom';
  select.dispatchEvent(new fixture.window.Event('change'));
  await fixture.update(); await fixture.release();
  assert.match(fixture.window.document.querySelector('#chart-panels section').textContent, /stale/);
  fixture.stopUpdating(); fixture.tick(); await flush();
  assert.doesNotMatch(fixture.window.document.querySelector('#chart-panels section').textContent, /stale/);
  assert.equal(fixture.snapshot().sources[0].events.length, 4000);
  fixture.close();
});

test('3999 events accept the 4000th and 4000 events accept duplicate IDs without replacement', async () => {
  for (const options of [{initialCount: 3999}, {initialCount: 4000, duplicate: true}]) {
    const fixture = await overflowFixture(options);
    const before = fixture.calls.length;
    await fixture.update();
    assert.equal(fixture.replacing, false);
    assert.equal(fixture.snapshot().sources[0].events.length, 4000);
    assert.equal(fixture.calls.length, before + 1);
    fixture.close();
  }
});

test('a range change discards an in-flight replacement', async () => {
  const fixture = await overflowFixture();
  await fixture.update();
  fixture.window.document.querySelector('#chart-zoom-in').click();
  await fixture.release();
  assert.equal(fixture.snapshot().sources[0].events.length, 4000);
  assert.equal(fixture.snapshot().sources[0].sampled.length, 0);
  fixture.close();
});

test('permission loss during replacement clears values and metadata', async () => {
  const fixture = await overflowFixture({replacement: 'forbidden'});
  await fixture.update(); await fixture.release();
  assert.equal(fixture.window.document.querySelector('#chart-panels').textContent, '');
  assert.equal(fixture.window.document.querySelector('#chart-status').textContent, 'Denied');
  fixture.close();
});

test('repeated stale visibility ends the source loading notice after the single fresh retry', async () => {
  const fixture = await overflowFixture({replacement: 'stale'});
  await fixture.update(); await fixture.release(); await fixture.release();
  const section = fixture.window.document.querySelector('#chart-panels section');
  assert.doesNotMatch(section.textContent, /Refreshing/);
  assert.match(section.textContent, /stale/);
  assert.equal(fixture.snapshot().sources[0].events.length, 4000);
  assert.equal(fixture.calls.filter((call) => call.action === 'event_history_chart_prepare').length, 2);
  const count = fixture.calls.length;
  await flush();
  assert.equal(fixture.calls.length, count, 'no further immediate retries');
  fixture.close();
});

test('exact replacement commits only after its last page', async () => {
  const fixture = await overflowFixture({replacement: 'paged-exact'});
  await fixture.update(); await fixture.release();
  assert.equal(fixture.snapshot().sources[0].events.length, 4000);
  assert.ok(fixture.plots.every((plot) => !plot.destroyed));
  await fixture.release();
  assert.equal(fixture.snapshot().sources[0].events.length, 2);
  assert.equal(fixture.snapshot().sources[0].cursor, 4001);
  assert.equal(fixture.snapshot().sources[0].sampled.length, 0);
  assert.equal(fixture.snapshot().sources[0].exact.length, 1);
  fixture.close();
});

test('replacement pagination stops at eight pages without committing a partial cursor', async () => {
  const fixture = await overflowFixture({replacement: 'pages'});
  const initialCalls = fixture.calls.length;
  await fixture.update();
  for (let index = 0; index < 8; index++) await fixture.release();
  const replacements = fixture.calls.slice(initialCalls).filter((call) => call.action === 'event_history_chart_query'
    && JSON.parse(call.fields.queries).length === 1);
  assert.equal(replacements.length, 8);
  assert.equal(fixture.snapshot().sources[0].cursor, 4000);
  assert.equal(fixture.snapshot().sources[0].events.length, 4000);
  fixture.close();
});

test('two overflowing sources recover independently without destroying either plot', async () => {
  const fixture = await overflowFixture({both: true});
  await fixture.update(); await fixture.release(); await fixture.release();
  assert.deepEqual(fixture.snapshot().sources.map((state) => state.events.length), [2, 2]);
  assert.ok(fixture.plots.every((plot) => !plot.destroyed));
  fixture.close();
});

test('initial page-limit exhaustion stops locally without clearing a completed second source', async () => {
  const fixture = await overflowFixture({initialCount: 4001});
  assert.equal(fixture.snapshot().sources[1].events.length, 10);
  assert.ok(fixture.snapshot().sources[0].events.length <= 4000);
  assert.match(fixture.window.document.querySelector('#chart-panels section').textContent, /Display limit/);
  assert.ok(fixture.plots.every((plot) => !plot.destroyed));
  const before = fixture.calls.length;
  await flush();
  assert.equal(fixture.calls.length, before);
  fixture.close();
});

test('an actual history-generation change during replacement retains global invalidation', async () => {
  const fixture = await overflowFixture({replacement: 'changed'});
  await fixture.update(); await fixture.release();
  assert.ok(fixture.plots.every((plot) => plot.destroyed));
  assert.equal(fixture.window.sessionStorage.getItem('mcp-event-history-chart-v1'), null);
  fixture.close();
});

test('chart cache keeps interval and event operations independent of the DOM', () => {
  const dom = new JSDOM('', {runScripts: 'outside-only'});
  dom.window.eval(cacheScript);
  const cache = dom.window.McpEventHistoryChartCache;
  const intervals = cache.mergeInterval([{start: 0, end: 10}], 8, 20);
  assert.deepEqual(JSON.parse(JSON.stringify(intervals)), [{start: 0, end: 20}]);
  assert.deepEqual(JSON.parse(JSON.stringify(cache.missingIntervals(intervals, 0, 25))),
    [{start: 20, end: 25}]);
  assert.deepEqual(JSON.parse(JSON.stringify(cache.compactEvent({id: 1,
    observed_at: 5, old_value: 'private', new_value: 'visible'}))),
  {id: 1, observed_at: 5, new_value: 'visible'});
  const state = {events: new Map([[1, {id: 1, observed_at: 5}], [2, {id: 2, observed_at: 15}]]),
    loaded: [{start: 0, end: 20}], exact: [{start: 0, end: 20}], sampled: [],
    coverageExact: [{start: 0, end: 20}], coverageTruncatedRanges: [], coverage: [], cursor: 2};
  assert.equal(cache.eventCount(state, [{id: 2}, {id: 3}]), 3);
  cache.trimToRange(state, {start: 10, end: 20});
  assert.deepEqual([...state.events.keys()], [2]);
  assert.equal(state.exact[0].start, 10, 'evicted periods lose their exact interval claim');
  assert.equal(state.cursor, 2, 'trimming does not move the incremental cursor');
  dom.window.close();
});

test('reload reuses bounded values only after fresh visibility and history checks', async () => {
  const url = `https://example.test/event_history.cgi?view=charts&sources=${encodeURIComponent(JSON.stringify([source]))}`;
  const fixedNow = Date.now();
  const open = async ({saved = null, selector = 'a'.repeat(24), history = 1,
    denied = false} = {}) => {
    const dom = new JSDOM(html, {url, runScripts: 'outside-only'});
    const {window} = dom;
    window.Date.now = () => fixedNow;
    Object.defineProperty(window.document, 'hidden', {get: () => false});
    if (saved) window.sessionStorage.setItem('mcp-event-history-chart-v1', saved);
    window.setInterval = () => 1;
    window.uPlot = class {
      static paths = {stepped: () => () => ({})};
      constructor(_options, _data, host) {
        this.host = host;
        this.scales = {x: {min: 0, max: 1}};
        this.over = window.document.createElement('div');
        host.append(this.over);
      }
      setScale(_key, value) { this.scales.x = value; }
      setData() {}
      destroy() { this.host.replaceChildren(); }
    };
    const calls = [];
    window.McpEventHistoryApi = {request: async (action, fields) => {
      calls.push({action, fields});
      if (action === 'event_history_chart_prepare') {
        if (denied) throw Object.assign(new Error('denied'), {code: 'forbidden'});
        return {generation: selector, history_generation: history,
          verified_at: fixedNow / 1000, sources: [{...source, control_name: 'Control',
            state_name: 'State', room: 'Room', category: 'Category', control_type: 'Switch'}]};
      }
      if (action === 'event_history_chart_query') {
        const query = JSON.parse(fields.queries)[0];
        return {results: [{generation: history,
          events: query.after_id ? [] : [{id: 7, observed_at: fixedNow / 1000 - 10,
            old_value: 0, new_value: 42}], has_more: false, latest_id: 7,
          next_id: 7, reduced: false, coverage: [], capture_started_at: null,
          retained_from: null, recording_ended_at: null}]};
      }
      throw new Error(`Unexpected action ${action}`);
    }};
    window.eval(cacheScript);
    window.eval(script);
    await flush();
    return {window, calls,
      saved: window.sessionStorage.getItem('mcp-event-history-chart-v1')};
  };
  const first = await open();
  assert.equal(first.calls.length, 2, first.window.document.querySelector('#chart-status').textContent);
  assert.equal(JSON.parse(first.calls[1].fields.queries)[0].after_id, 0);
  assert.ok(first.saved);
  assert.equal(JSON.parse(first.saved).sources[0].events[0].old_value, undefined);
  const reload = await open({saved: first.saved});
  assert.deepEqual(reload.calls.map(({action}) => action),
    ['event_history_chart_prepare', 'event_history_chart_query']);
  assert.equal(JSON.parse(reload.calls[1].fields.queries)[0].after_id, 7);
  const legacyValue = JSON.parse(first.saved);
  legacyValue.sources[0].events[0].old_value = 0;
  const legacy = await open({saved: JSON.stringify(legacyValue)});
  assert.equal(JSON.parse(legacy.calls[1].fields.queries)[0].after_id, 7);
  assert.equal(JSON.parse(legacy.saved).sources[0].events[0].old_value, undefined);
  assert.match(reload.window.document.querySelector('#chart-panels').textContent, /Control/);
  const hour = first.window.document.querySelector('#chart-range');
  hour.value = '3600';
  hour.dispatchEvent(new first.window.Event('change'));
  await flush();
  const hourReload = await open({saved: first.window.sessionStorage.getItem('mcp-event-history-chart-v1')});
  assert.equal(hourReload.window.document.querySelector('#chart-range').value, '3600');
  const changed = await open({saved: first.saved, history: 2});
  assert.equal(JSON.parse(changed.calls[1].fields.queries)[0].after_id, 0);
  const expiredValue = JSON.parse(first.saved);
  expiredValue.saved_at -= 301;
  const expired = await open({saved: JSON.stringify(expiredValue)});
  assert.equal(JSON.parse(expired.calls[1].fields.queries)[0].after_id, 0);
  const renamed = await open({saved: first.saved, selector: 'b'.repeat(24)});
  assert.equal(JSON.parse(renamed.calls[1].fields.queries)[0].after_id, 0);
  const revoked = await open({saved: first.saved, denied: true});
  assert.deepEqual(revoked.calls.map(({action}) => action), ['event_history_chart_prepare']);
  assert.equal(revoked.saved, null);
  assert.equal(revoked.window.document.querySelector('#chart-panels').textContent, '');
  for (const page of [first, reload, legacy, hourReload, changed, expired, renamed, revoked]) {
    page.window.close();
  }
});

test('chart tab loads only selected values, pauses hidden polling, and clears revoked data', async () => {
  const url = `https://example.test/event_history.cgi?view=charts&sources=${encodeURIComponent(JSON.stringify([source]))}`;
  const dom = new JSDOM(html, {url, runScripts: 'outside-only'});
  const {window} = dom;
  const calls = [];
  let denied = false;
  let holdNext = false;
  let releaseHeld;
  let tick;
  let wake;
  let hidden = false;
  let queryCount = 0;
  let failCode = null;
  let failOnce = false;
  let failPrepareOnce = false;
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
    static destroys = 0;
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
    destroy() { window.uPlot.destroys++; this.host.replaceChildren(); }
  };
  window.McpEventHistoryApi = {subscribeUpdates: (onChange) => { wake = onChange; },
    request: async (action, fields) => {
    calls.push({action, fields});
    if (action === 'event_history_chart_prepare') {
      if (failPrepareOnce) {
        failPrepareOnce = false;
        throw Object.assign(new Error('selector refresh in progress'),
          {code: 'stale_configuration'});
      }
      if (denied) throw Object.assign(new Error('denied'), {code: 'forbidden'});
      return {generation: selectorGeneration, verified_at: Date.now() / 1000,
        sources: [{...source, control_name: selectorGeneration[0] === 'b' ? 'Renamed' : 'Control',
          state_name: 'State',
          room: 'Room', category: 'Category', control_type: 'Switch'}]};
    }
    if (action === 'event_history_chart_query') {
      queryCount++;
      if (failCode) {
        const code = failCode;
        if (failOnce) { failCode = null; failOnce = false; }
        throw Object.assign(new Error('failed'), {code, requestId: 'abc-123'});
      }
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
  window.eval(cacheScript);
  window.eval(script);
  await flush();
  assert.deepEqual(calls.map(({action}) => action),
    ['event_history_chart_prepare', 'event_history_chart_query']);
  assert.deepEqual(Object.keys(JSON.parse(calls[1].fields.queries)[0]).sort(),
    ['after_id', 'control_uuid', 'end', 'generation', 'start', 'state_uuid']);
  assert.equal(window.document.querySelectorAll('#chart-panels canvas').length, 1);
  assert.match(window.document.querySelector('#chart-panels').textContent, /Control/);
  const panel = window.document.querySelector('#chart-panels section');
  assert.equal(panel.querySelectorAll('.mcp-history-chart-meta dl dt').length, 3,
    'source context stays in the compact metadata column');
  assert.ok(panel.querySelector('.mcp-history-chart-body .mcp-history-chart-plot'),
    'plot has a separate layout column');
  assert.equal(panel.querySelector('.mcp-history-chart-meta [role="status"]').textContent,
    'Reduced', 'source-specific reduced-detail warning remains beside the plot');
  assert.equal(window.document.querySelector('#chart-panels section .mcp-history-chart-body > details:last-of-type').hidden,
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
  failPrepareOnce = true;
  tick();
  await flush();
  assert.equal(window.uPlot.destroys, 0,
    'transient verification failure retains the existing plot');
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
  failCode = 'stale_configuration';
  failOnce = true;
  tick();
  await flush();
  assert.equal(window.uPlot.instances.length, 1,
    'a concurrent selector refresh keeps the existing plot during revalidation');
  assert.equal(window.document.querySelectorAll('#chart-panels section').length, 1);
  window.Date.now = originalNow;
  pendingEvent = {id: 3, observed_at: fixedRange.end - 5, old_value: 1, new_value: 2};
  const originalPlot = window.uPlot.instances[0];
  wake();
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
  assert.equal(window.document.querySelector('#chart-panels section .mcp-history-chart-body > details:last-of-type').hidden,
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
  assert.equal(window.document.querySelector('#chart-panels section .mcp-history-chart-body > details:last-of-type').hidden,
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
