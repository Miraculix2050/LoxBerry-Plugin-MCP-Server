/* Development-only instrumentation. Install before the shipped chart scripts. */
(function (root) {
  'use strict';
  function install(win) {
    const started = win.performance.now();
    const originalFetch = win.fetch;
    const requests = [], interactions = [];
    let first = null, pending = null, stopped = false, dropped = 0, plotCount = 0;
    let draws = 0, longTasks = 0, longTaskMs = 0, observer = null, rawPlot;
    const actions = new Set(['event_history_chart_prepare', 'event_history_chart_query',
      'event_history_wait_update']);
    const buttons = {'chart-previous': 'pan', 'chart-next': 'pan',
      'chart-zoom-in': 'zoom', 'chart-zoom-out': 'zoom'};
    const viewport = () => ({width: win.innerWidth, height: win.innerHeight,
      client_width: win.document.documentElement.clientWidth,
      client_height: win.document.documentElement.clientHeight,
      visual_width: win.visualViewport?.width ?? null,
      visual_height: win.visualViewport?.height ?? null,
      visual_scale: win.visualViewport?.scale ?? null, dpr: win.devicePixelRatio});
    const visible = (plot) => {
      if (win.document.hidden || !plot.root?.isConnected) return false;
      const rect = plot.root.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0 || rect.bottom <= 0 || rect.right <= 0
        || rect.top >= win.innerHeight || rect.left >= win.innerWidth) return false;
      if (plot.root.checkVisibility && !plot.root.checkVisibility({checkOpacity: true,
        checkVisibilityCSS: true})) return false;
      const x = plot.data?.[0] || [], range = plot.scales?.x;
      return x.some((time, index) => Number.isFinite(time) && time >= range?.min
        && time <= range?.max && plot.data.slice(1).some((series) =>
          typeof series[index] === 'number' && Number.isFinite(series[index])));
    };
    const drawn = (plot) => {
      if (stopped) return;
      draws++;
      if (!visible(plot)) return;
      const operation = pending;
      const range = plot.scales.x;
      if (operation && operation.range
        && range.min === operation.range.min && range.max === operation.range.max) return;
      // Two animation frames establish a paint opportunity, not compositor proof.
      win.requestAnimationFrame(() => win.requestAnimationFrame(() => {
        if (stopped || !visible(plot)) return;
        const now = win.performance.now();
        if (first === null) first = now;
        if (operation && operation === pending) {
          operation.result.status = 'completed';
          operation.result.render_ms = now - operation.started;
          operation.result.visible = true;
          pending = null;
        }
      }));
    };
    const plots = new Set();
    const wrapPlot = (Original) => {
      if (typeof Original !== 'function') return Original;
      const Wrapped = new Proxy(Original, {construct(Target, args) {
        const options = {...args[0], hooks: {...args[0].hooks}};
        options.hooks.draw = [...(options.hooks.draw || []), drawn];
        const plot = Reflect.construct(Target, [options, ...args.slice(1)]);
        plots.add(new WeakRef(plot)); plotCount++;
        return plot;
      }});
      return Wrapped;
    };
    rawPlot = win.uPlot;
    let wrappedPlot = wrapPlot(rawPlot);
    const descriptor = Object.getOwnPropertyDescriptor(win, 'uPlot');
    if (descriptor && descriptor.configurable === false) throw new Error('Probe requires configurable uPlot');
    Object.defineProperty(win, 'uPlot', {configurable: true, get: () => wrappedPlot,
      set(value) {rawPlot = value; wrappedPlot = wrapPlot(value);}});
    win.fetch = async function (input, init) {
      let action = null;
      try {
        const url = new URL(typeof input === 'string' ? input : input.url, win.location.href);
        const candidate = new URLSearchParams(init?.body).get('action');
        if (url.origin === win.location.origin && url.pathname.endsWith('/event_history.cgi')
          && init?.method?.toUpperCase() === 'POST' && actions.has(candidate)) action = candidate;
      } catch { /* Unrelated requests remain untouched. */ }
      if (stopped || !action) return originalFetch.call(this, input, init);
      if (requests.length >= 512) {dropped++; return originalFetch.call(this, input, init);}
      const row = {action, start_ms: win.performance.now(), headers_ms: null,
        body_ms: null, status: 'pending', http_status: null, events: 0, reduced: false};
      requests.push(row);
      try {
        const response = await originalFetch.call(this, input, init);
        row.headers_ms = win.performance.now() - row.start_ms;
        row.http_status = response.status;
        const json = response.json.bind(response);
        response.json = async () => {
          try {
            const result = await json();
            row.body_ms = win.performance.now() - row.start_ms;
            row.status = response.ok && result?.ok === true ? 'completed' : 'failed';
            if (action === 'event_history_chart_query' && Array.isArray(result?.data?.results)) {
              for (const item of result.data.results.slice(0, 4)) {
                row.events += Array.isArray(item.events) ? item.events.length : 0;
                row.reduced ||= item.reduced === true;
              }
            }
            return result;
          } catch (error) {row.status = 'failed'; row.body_ms = win.performance.now() - row.start_ms; throw error;}
        };
        return response;
      } catch (error) {row.status = 'failed'; row.body_ms = win.performance.now() - row.start_ms; throw error;}
    };
    const clicked = (event) => {
      const kind = buttons[event.target.closest?.('button')?.id];
      if (!kind || stopped) return;
      if (pending) pending.result.status = 'superseded';
      if (interactions.length >= 64) {dropped++; pending = null; return;}
      const plot = [...plots].map((ref) => ref.deref()).find((value) => value && visible(value));
      const result = {kind, start_ms: win.performance.now(), trusted: event.isTrusted, status: 'pending', render_ms: null,
        visible: false};
      interactions.push(result);
      pending = {started: win.performance.now(), range: plot ? {...plot.scales.x} : null, result};
    };
    win.document.addEventListener('click', clicked, true);
    try {
      observer = new win.PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {longTasks++; longTaskMs += entry.duration;}
      });
      observer.observe({type: 'longtask', buffered: false});
    } catch {observer = null;}
    const report = () => JSON.parse(JSON.stringify({schema: 1, elapsed_ms: win.performance.now() - started,
      first_content_ms: first, first_content_from_probe_ms: first === null ? null : first - started,
      viewport: viewport(), plots_created: plotCount, draws, dropped,
      requests, interactions, long_tasks: observer ? {count: longTasks, duration_ms: longTaskMs} : null,
      cpu: null, heap: null}));
    const stop = () => {
      if (!stopped) {
        stopped = true; win.fetch = originalFetch;
        win.document.removeEventListener('click', clicked, true); observer?.disconnect();
        Object.defineProperty(win, 'uPlot', {configurable: true, writable: true, value: rawPlot});
      }
      return report();
    };
    return {report, stop};
  }
  if (typeof module !== 'undefined') module.exports = {install};
  else root.ChartMeasurement = {install};
})(typeof window === 'undefined' ? globalThis : window);
