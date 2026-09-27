(() => {
  const root = document.querySelector('.mcp-history-charts');
  if (!root) return;
  const api = window.McpEventHistoryApi;
  const $ = (id) => document.getElementById(id);
  const label = (name) => root.dataset[name] || name;
  const status = $('chart-status');
  const panels = $('chart-panels');
  const maxRange = 90 * 86400;
  const maxEvents = 4000;
  const sourcePattern = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{16}$/;
  let requested = [];
  try {
    const parsed = JSON.parse(new URL(window.location.href).searchParams.get('sources') || 'null');
    if (Array.isArray(parsed) && parsed.length >= 1 && parsed.length <= 4 && parsed.every(
      (item) => item && sourcePattern.test(item.control_uuid)
        && sourcePattern.test(item.state_uuid))) requested = parsed;
  } catch { /* Invalid selections show a safe empty state. */ }
  let selection = null;
  let range = {start: Date.now() / 1000 - 86400, end: Date.now() / 1000};
  let sourceStates = [];
  let sequence = 0;
  let busy = false;
  let syncing = false;
  let applyingScale = false;
  const time = (value) => new Date(value * 1000).toLocaleString();
  const localInput = (value) => {
    const date = new Date(value * 1000);
    return new Date(date.getTime() - date.getTimezoneOffset() * 60000)
      .toISOString().slice(0, 16);
  };
  const valueText = (value) => typeof value === 'string' ? value : JSON.stringify(value);
  const setStatus = (message, kind = 'info') => {
    status.textContent = message;
    status.dataset.kind = kind;
  };
  const clear = () => {
    for (const state of sourceStates) state.plot?.destroy();
    sourceStates = [];
    panels.replaceChildren();
    selection = null;
  };
  const syncRange = (origin, min, max) => {
    if (syncing || applyingScale || !Number.isFinite(min) || !Number.isFinite(max)) return;
    syncing = true;
    for (const state of sourceStates) {
      if (state.plot && state.plot !== origin) state.plot.setScale('x', {min, max});
    }
    syncing = false;
    if (Math.abs(min - range.start) > 1 || Math.abs(max - range.end) > 1) {
      window.setTimeout(() => replaceRange(min, max), 0);
    }
  };
  const render = (state) => {
    state.plot?.destroy();
    state.plot = null;
    state.plotHost.replaceChildren();
    state.tableBody.replaceChildren();
    const events = [...state.events.values()].sort((a, b) =>
      a.observed_at - b.observed_at || a.id - b.id);
    state.notice.textContent = state.reduced ? label('chartReduced')
      : (events.length ? label('chartCoverage') : label('chartEmpty'));
    const numeric = events.filter((event) => typeof event.new_value === 'number'
      && Number.isFinite(event.new_value));
    const boolean = events.filter((event) => typeof event.new_value === 'boolean');
    const plotted = numeric.length >= boolean.length ? numeric : boolean;
    const plottedKind = numeric.length >= boolean.length ? 'number' : 'boolean';
    if (plotted.length && typeof window.uPlot === 'function') {
      const x = [], y = [], refs = [];
      let priorCoverage = null;
      for (const event of plotted) {
        const coverage = (state.coverage || []).findIndex((item) =>
          item.started_at <= event.observed_at
          && (item.ended_at == null || item.ended_at >= event.observed_at));
        if (priorCoverage !== null && (state.coverageTruncated || priorCoverage !== coverage
          || (state.reduced && x.length && event.observed_at - x[x.length - 1]
            > (range.end - range.start) / 64))) {
          x.push(event.observed_at - 0.000001);
          y.push(null);
          refs.push(null);
        }
        x.push(event.observed_at);
        y.push(plottedKind === 'boolean' ? Number(event.new_value) : event.new_value);
        refs.push(event);
        priorCoverage = coverage;
      }
      const options = {
        width: Math.max(280, Math.floor(state.plotHost.clientWidth || 600)),
        height: 220,
        scales: {x: {time: true}},
        series: [{}, {
          label: label('chartValue'), stroke: '#2373a4', width: 2,
          spanGaps: false,
          ...(plottedKind === 'boolean' ? {paths: window.uPlot.paths.stepped({align: 1})} : {}),
        }],
        cursor: {sync: {key: 'mcp-history-charts'}},
        hooks: {
          setCursor: [(plot) => {
            const event = refs[plot.cursor.idx];
            if (event) state.focus.textContent = `${time(event.observed_at)} · ${valueText(event.new_value)}`;
          }],
          setScale: [(plot, key) => {
            if (key === 'x') syncRange(plot, plot.scales.x.min, plot.scales.x.max);
          }],
        },
      };
      applyingScale = true;
      try {
        state.plot = new window.uPlot(options, [x, y], state.plotHost);
        state.plot.setScale('x', {min: range.start, max: range.end});
      } finally { applyingScale = false; }
    }
    for (const event of events.slice(-200).reverse()) {
      const tr = document.createElement('tr');
      for (const content of [time(event.observed_at), valueText(event.new_value)]) {
        const td = document.createElement('td');
        td.textContent = content;
        tr.append(td);
      }
      state.tableBody.append(tr);
    }
    const boundaries = [
      ['chartCapture', state.capture], ['chartRetained', state.retained],
      ['chartRemoved', state.removed],
    ].filter((item) => Number.isFinite(item[1]));
    state.boundaries.textContent = boundaries.map(([name, value]) =>
      `${label(name)}: ${time(value)}`).join(' · ');
    state.coverageList.replaceChildren();
    for (const interval of state.coverage || []) {
      const item = document.createElement('li');
      item.textContent = `${time(interval.started_at)} – ${interval.ended_at == null
        ? '…' : time(interval.ended_at)}`;
      state.coverageList.append(item);
    }
  };
  const createPanels = () => {
    panels.replaceChildren();
    sourceStates = selection.sources.map((source) => {
      const panel = document.createElement('section');
      panel.className = 'mcp-card mcp-history-chart-panel';
      const title = document.createElement('h2');
      title.textContent = `${source.control_name} · ${source.state_name}`;
      const context = document.createElement('p');
      context.className = 'mcp-help';
      context.textContent = [
        `${label('chartRoom')}: ${source.room || label('chartUnknown')}`,
        `${label('chartCategory')}: ${source.category || label('chartUnknown')}`,
        `${label('chartType')}: ${source.control_type}`,
      ].join(' · ');
      const notice = document.createElement('p');
      notice.setAttribute('role', 'status');
      const boundaries = document.createElement('p');
      boundaries.className = 'mcp-help';
      const plotHost = document.createElement('div');
      plotHost.className = 'mcp-history-chart-plot';
      const focus = document.createElement('p');
      focus.setAttribute('aria-live', 'polite');
      const details = document.createElement('details');
      const summary = document.createElement('summary');
      summary.textContent = label('chartValue');
      const scroll = document.createElement('div');
      scroll.className = 'mcp-history-chart-events';
      const table = document.createElement('table');
      const head = document.createElement('thead');
      const headingRow = document.createElement('tr');
      for (const name of ['chartTime', 'chartValue']) {
        const th = document.createElement('th');
        th.scope = 'col';
        th.textContent = label(name);
        headingRow.append(th);
      }
      head.append(headingRow);
      const tableBody = document.createElement('tbody');
      table.append(head, tableBody);
      scroll.append(table);
      details.append(summary, scroll);
      const coverageDetails = document.createElement('details');
      const coverageSummary = document.createElement('summary');
      coverageSummary.textContent = label('chartIntervals');
      const coverageList = document.createElement('ul');
      coverageDetails.append(coverageSummary, coverageList);
      panel.append(title, context, notice, boundaries, coverageDetails, plotHost, focus, details);
      panels.append(panel);
      return {source, events: new Map(), cursor: 0, generation: null, reduced: false,
        coverage: [], plot: null, plotHost, focus, notice, boundaries, coverageList, tableBody};
    });
  };
  const prepare = async () => {
    const result = await api.request('event_history_chart_prepare',
      {sources: JSON.stringify(requested)}, 120000);
    if (!Array.isArray(result.sources) || result.sources.length !== requested.length) {
      throw new Error('Invalid chart source response');
    }
    const changed = !selection || selection.generation !== result.generation;
    if (changed) clear();
    selection = result;
    if (changed) createPanels();
  };
  const query = async (state, reset, token) => {
    let after = reset ? 0 : state.cursor;
    let count = 0;
    do {
      const result = await api.request('event_history_chart_query', {
        ...state.source, generation: selection.generation,
        start: range.start, end: range.end, after_id: after,
      }, 15000);
      if (token !== sequence) return;
      if (state.generation !== null && result.generation !== state.generation) {
        throw Object.assign(new Error('History changed'), {code: 'history_changed'});
      }
      state.generation = result.generation;
      state.reduced = state.reduced || result.reduced;
      state.coverage = result.coverage;
      state.coverageTruncated = result.coverage_truncated;
      state.reduced = state.reduced || result.coverage_truncated;
      state.capture = result.capture_started_at;
      state.retained = result.retained_from;
      state.removed = result.recording_ended_at;
      for (const event of result.events) state.events.set(event.id, event);
      if (state.events.size > maxEvents) {
        throw Object.assign(new Error('Chart memory limit reached'), {code: 'history_changed'});
      }
      count += result.events.length;
      after = result.next_id;
      state.cursor = after;
      if (!result.has_more) {
        state.cursor = Math.max(after, result.latest_id);
        break;
      }
      if (count >= maxEvents) {
        state.reduced = true;
        state.cursor = result.latest_id;
        break;
      }
    } while (true);
    render(state);
  };
  const load = async (fresh = false) => {
    if (busy || document.hidden || !requested.length) return;
    busy = true;
    const token = ++sequence;
    if (fresh || !selection) setStatus(label('loading'));
    try {
      if (fresh || !selection || Date.now() / 1000 - selection.verified_at >= 50) {
        if (fresh) clear();
        await prepare();
      }
      for (const state of sourceStates) await query(state, fresh || state.generation === null, token);
      if (token === sequence) setStatus('');
    } catch (error) {
      if (token !== sequence) return;
      if (error.code === 'history_changed') {
        for (const state of sourceStates) {
          state.events.clear(); state.generation = null; state.cursor = 0; state.reduced = false;
          render(state);
        }
        window.setTimeout(() => { void load(false); }, 0);
      } else {
        clear();
        setStatus(error.code === 'forbidden' || error.code === 'stale_configuration'
          ? label('chartDenied') : label('chartError'), 'warning');
      }
    } finally { busy = false; }
  };
  const replaceRange = (start, end) => {
    const now = Date.now() / 1000;
    if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0
      || start >= end || end - start > maxRange || end > now + 60) {
      setStatus(label('chartError'), 'warning');
      return;
    }
    range = {start, end};
    for (const state of sourceStates) {
      state.events.clear(); state.cursor = 0; state.generation = null; state.reduced = false;
      render(state);
    }
    void load(false);
  };
  $('chart-range').addEventListener('change', (event) => {
    const custom = event.target.value === 'custom';
    for (const id of ['chart-from', 'chart-to', 'chart-apply']) $(id).disabled = !custom;
    if (custom) {
      $('chart-from').value = localInput(range.start);
      $('chart-to').value = localInput(range.end);
    }
    if (!custom) {
      const end = Date.now() / 1000;
      replaceRange(end - Number(event.target.value), end);
    }
  });
  $('chart-apply').addEventListener('click', () => {
    replaceRange(new Date($('chart-from').value).getTime() / 1000,
      new Date($('chart-to').value).getTime() / 1000);
  });
  $('chart-previous').addEventListener('click', () => {
    const shift = (range.end - range.start) / 2;
    replaceRange(range.start - shift, range.end - shift);
  });
  $('chart-next').addEventListener('click', () => {
    const shift = Math.min((range.end - range.start) / 2, Date.now() / 1000 - range.end);
    replaceRange(range.start + shift, range.end + shift);
  });
  $('chart-zoom-out').addEventListener('click', () => {
    const width = Math.min(maxRange, (range.end - range.start) * 2);
    replaceRange(Math.max(0, range.end - width), range.end);
  });
  $('chart-zoom-in').addEventListener('click', () => {
    const width = (range.end - range.start) / 2;
    const center = (range.start + range.end) / 2;
    replaceRange(center - width / 2, center + width / 2);
  });
  $('chart-refresh').addEventListener('click', () => { void load(true); });
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) void load(false);
  });
  window.addEventListener('resize', () => {
    for (const state of sourceStates) state.plot?.setSize({width:
      Math.max(280, Math.floor(state.plotHost.clientWidth)), height: 220});
  });
  window.setInterval(() => { void load(false); }, 10000);
  if (requested.length) void load(true);
  else setStatus(label('chartDenied'), 'warning');
})();
