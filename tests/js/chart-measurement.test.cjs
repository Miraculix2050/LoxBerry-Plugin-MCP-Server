const test = require('node:test');
const assert = require('node:assert/strict');
const {JSDOM} = require('jsdom');
const {install} = require('../../tools/browser/chart-probe.js');
const {events, createServer} = require('../../tools/browser/chart-fixture.cjs');
const {measure, bundle} = require('../../tools/browser/measure-chart.cjs');

function setup() {
  const dom = new JSDOM('<button id="chart-zoom-in"></button><div id="host"></div>',
    {url: 'https://private-endpoint.example/event_history.cgi?private-token', pretendToBeVisual: true});
  const win = dom.window;
  let clock = 0, frames = [];
  Object.defineProperty(win.performance, 'now', {value: () => clock});
  win.requestAnimationFrame = (callback) => frames.push(callback);
  Object.defineProperties(win, {innerWidth: {value: 390}, innerHeight: {value: 844},
    visualViewport: {value: {width: 390, height: 844, scale: 1}}});
  win.fetch = async () => {
    clock += 10;
    return {ok: true, status: 200, json: async () => {clock += 20;
      return {ok: true, data: {results: [{events: [{uuid: 'private-uuid',
        name: 'private-name', token: 'private-token', project: 'private-project'}], reduced: true}]}};}};
  };
  win.uPlot = class {
    static paths = {stepped() {}};
    constructor(options, data, host) {
      this.options = options; this.root = host; this.data = data;
      this.scales = {x: {min: 0, max: 10}};
      this.root.getBoundingClientRect = () => ({top: 10, bottom: 200, left: 10, right: 300, width: 290, height: 190});
    }
    draw() {for (const hook of this.options.hooks.draw) hook(this);}
  };
  const original = win.fetch;
  const probe = install(win);
  const plot = new win.uPlot({}, [[1, 2], [null, 3]], win.document.getElementById('host'));
  const paint = () => {for (let index = 0; index < 2; index++) {
    clock += 16; const queue = frames; frames = []; queue.forEach((callback) => callback());
  }};
  return {win, probe, plot, paint, original, advance: (value) => {clock += value;}};
}
test('visible nonempty draw and changed scale require two paint opportunities', () => {
  const {win, probe, plot, paint} = setup();
  plot.draw(); assert.equal(probe.report().first_content_ms, null);
  paint(); assert.equal(probe.report().first_content_ms, 32);
  win.document.getElementById('chart-zoom-in').click();
  plot.draw(); paint(); assert.equal(probe.report().interactions[0].status, 'pending');
  plot.scales.x = {min: 1, max: 5}; plot.draw(); paint();
  assert.equal(probe.report().interactions[0].render_ms, 64);
  assert.equal(probe.report().interactions[0].trusted, false);
  win.close();
});
test('empty, offscreen, out-of-range and hidden draws cannot establish first content', () => {
  for (const kind of ['empty', 'offscreen', 'range', 'hidden']) {
    const {win, probe, plot, paint} = setup();
    if (kind === 'empty') plot.data[1] = [null, null];
    if (kind === 'range') plot.scales.x = {min: 100, max: 200};
    if (kind === 'hidden') Object.defineProperty(win.document, 'hidden', {value: true});
    if (kind === 'offscreen') plot.root.getBoundingClientRect = () => ({top: 900, bottom: 1100, width: 100, height: 200});
    plot.draw(); paint(); assert.equal(probe.report().first_content_ms, null);
    win.close();
  }
});
test('request completion includes JSON parse, retains no values and restores fetch', async () => {
  const {win, probe, original} = setup();
  const response = await win.fetch('event_history.cgi', {method: 'POST',
    body: new win.URLSearchParams({action: 'event_history_chart_query', sources: 'private-uuid'})});
  assert.equal(probe.report().requests[0].status, 'pending');
  const result = await response.json(); assert.equal(result.data.results[0].events[0].token, 'private-token');
  const report = probe.stop();
  assert.equal(report.requests[0].headers_ms, 10);
  assert.equal(report.requests[0].body_ms, 30);
  assert.equal(report.requests[0].events, 1); assert.equal(report.requests[0].reduced, true);
  assert.equal(report.cpu, null); assert.equal(report.heap, null);
  for (const sentinel of ['private-token', 'private-uuid', 'private-name', 'private-project', 'private-endpoint']) {
    assert.ok(!JSON.stringify(report).includes(sentinel));
  }
  assert.equal(win.fetch, original); win.close();
});
test('sparse exact and dense bounded fixtures retain coverage semantics', () => {
  const query = {start: 86400, end: 172800, after_id: 0};
  const sparse = events(query, false, 172800), dense = events(query, true, 172800);
  assert.equal(sparse.reduced, false); assert.ok(sparse.events.length < 30);
  assert.equal(dense.reduced, true); assert.equal(dense.events.length, 2000);
  assert.equal(dense.has_more, false); assert.equal(dense.events.at(-1).id, 100000);
  for (const result of [sparse, dense]) {
    assert.equal(result.coverage.length, 1);
    assert.ok(result.events.every((event) => result.coverage[0].started_at <= event.observed_at
      && result.coverage[0].ended_at >= event.observed_at));
  }
});
test('fixture serves real local scripts and rejects writes and arbitrary paths', async () => {
  const server = createServer(); await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const origin = 'http://127.0.0.1:' + server.address().port;
  try {
    const html = await (await fetch(origin + '/?case=dense&count=4')).text();
    assert.ok(html.includes('charts.js')); assert.ok(!html.includes('TMPL_VAR'));
    assert.equal((await fetch(origin + '/api.js')).status, 200);
    assert.equal((await fetch(origin + '/chart-cache.js')).status, 200);
    assert.equal((await fetch(origin + '/../../config/default-config.json')).status, 404);
    assert.equal((await fetch(origin + '/event_history.cgi', {method: 'POST',
      body: 'action=event_history_purge_source'})).status, 403);
  } finally {await new Promise((resolve) => server.close(resolve));}
});
test('driver validates viewport, missing metrics and trusted interaction acceptance', async () => {
  const originalWindow = global.window, originalDocument = global.document;
  try {
    for (const mode of ['supported', 'unsupported', 'viewport', 'metric_failure', 'no_thread_cpu',
      'request_failure', 'untrusted', 'timed_out', 'redirect_failure', 'redirect_origin']) {
      const report = {first_content_ms: 10, dropped: 0, viewport: {width: 390, height: 844,
        visual_width: mode === 'viewport' ? 375 : 390, visual_height: 844, visual_scale: 1},
        requests: mode === 'request_failure' ? [{action: 'event_history_chart_query', status: 'failed'}] : [],
        interactions: [], cpu: null, heap: null};
      global.window = {chartProbe: {report: () => report, stop: () => report}};
      global.document = {getElementById: () => ({textContent: ''})};
      let calls = 0, detached = false;
      const cdp = {send: async (name, args) => {
        if (mode === 'no_thread_cpu' && name === 'Performance.enable'
          && args.timeDomain === 'threadTicks') throw new Error('Unsupported thread clock');
        if (name !== 'Performance.getMetrics') return {};
        calls++;
        if (mode === 'metric_failure' && calls > 1) throw new Error('private-endpoint');
        return {metrics: [{name: 'TaskDuration', value: calls / 10},
          {name: 'JSHeapUsedSize', value: 1234}, {name: 'JSHeapTotalSize', value: 5678},
          {name: 'private-project', value: 99}]};
      }, detach: async () => {detached = true;}};
      let closed = false, initializerCount = 0;
      const target = {setViewportSize: async () => {},
        url: () => mode === 'redirect_origin' ? 'https://redirect.example/auth' : 'https://fixture.example/chart',
        addInitScript: async () => {initializerCount++;},
        goto: async () => {
          if (mode === 'redirect_failure') throw new Error('Redirected navigation failed');
        }, close: async () => {closed = true;},
        context: () => ({newCDPSession: async () => {
          if (mode === 'unsupported') throw new Error('private-token'); return cdp;
        }}), waitForFunction: async () => {}, evaluate: async (fn, arg) => fn(arg),
        locator: (id) => ({click: async () => report.interactions.push({kind: id.includes('zoom') ? 'zoom' : 'pan',
          trusted: mode !== 'untrusted', visible: true,
          status: mode === 'timed_out' ? 'pending' : 'completed', render_ms: 32})})};
      // The caller has no mutation APIs: all instrumentation must use its disposable sibling.
      const page = {url: () => 'https://fixture.example/chart',
        context: () => ({newPage: async () => target})};
      if (mode === 'redirect_failure') {
        await assert.rejects(measure(page), /Redirected navigation failed/);
        assert.equal(closed, true); assert.equal(detached, true);
        continue;
      }
      if (mode === 'redirect_origin') {
        await assert.rejects(measure(page), /Measurement navigation changed origin/);
        assert.equal(closed, true); assert.equal(detached, true);
        continue;
      }
      const output = await measure(page);
      assert.equal(output.accepted, !['viewport', 'request_failure', 'untrusted', 'timed_out'].includes(mode));
      assert.equal(output.cpu === null, ['unsupported', 'metric_failure', 'no_thread_cpu'].includes(mode));
      if (mode === 'supported') {
        assert.equal(output.cpu.renderer_thread_cpu_ms, 100); assert.equal(output.heap.used_bytes, 1234);
      }
      assert.equal(detached, mode !== 'unsupported');
      assert.ok(!JSON.stringify(output).includes('private'));
      assert.equal(closed, true); assert.equal(initializerCount, 1);
    }
    assert.ok(bundle().startsWith('async (page)'));
    await assert.rejects(measure({}, {timeout: 120001}), /Invalid measurement bounds/);
  } finally {
    global.window = originalWindow; global.document = originalDocument;
  }
});
