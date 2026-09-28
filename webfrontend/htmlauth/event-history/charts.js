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
  let rolling = true;
  let sourceStates = [];
  let sequence = 0;
  let busy = false;
  let rerun = false;
  let rerunPoll = false;
  let rerunFresh = false;
  let syncing = false;
  let applyingScale = false;
  let staleRetries = 0;
  let historyRetries = 0;
  const time = (value) => new Date(value * 1000).toLocaleString();
  const localInput = (value) => {
    const date = new Date(value * 1000);
    return new Date(date.getTime() - date.getTimezoneOffset() * 60000)
      .toISOString().slice(0, 16);
  };
  const decimalInteger = (value) => value && typeof value === 'object'
    && typeof value.integer_decimal === 'string' && /^-?\d+$/.test(value.integer_decimal);
  const numericValue = (value) => decimalInteger(value) ? Number(value.integer_decimal)
    : (typeof value === 'number' ? value : null);
  const valueText = (value) => decimalInteger(value) ? value.integer_decimal
    : (typeof value === 'string' ? value : JSON.stringify(value));
  const setStatus = (message, kind = 'info') => {
    status.textContent = message;
    status.dataset.kind = kind;
  };
  const queryErrorStatus = (error) => {
    const name = error.code === 'outcome_unknown' || error.code === 'query_timeout'
      ? 'chartTimeout'
      : error.code === 'temporarily_unavailable' || error instanceof TypeError
        ? 'chartUnavailable'
        : error.code === 'invalid_request' ? 'chartInvalid' : 'chartError';
    const reference = error.requestId ? ` ${label('chartReference')}: ${error.requestId}.` : '';
    return `${label(name)} ${label('chartStale')}${reference}`;
  };
  const clear = () => {
    for (const state of sourceStates) state.plot?.destroy();
    sourceStates = [];
    panels.replaceChildren();
    selection = null;
  };
  const mergeInterval = (intervals, start, end) => {
    const result = [];
    for (const item of [...intervals, {start, end}].sort((a, b) => a.start - b.start)) {
      const last = result.at(-1);
      if (last && item.start <= last.end) last.end = Math.max(last.end, item.end);
      else result.push({...item});
    }
    return result;
  };
  const missingIntervals = (intervals, start, end) => {
    const missing = [];
    let cursor = start;
    for (const item of intervals) {
      if (item.end < cursor) continue;
      if (item.start > cursor) missing.push({start: cursor, end: Math.min(end, item.start)});
      cursor = Math.max(cursor, item.end);
      if (cursor >= end) break;
    }
    if (cursor < end) missing.push({start: cursor, end});
    return missing.filter((item) => item.start < item.end);
  };
  const loadedForRange = (state, start, end) => [
    ...state.exact,
    ...state.sampled.filter((item) => item.start >= start && item.end <= end),
  ].sort((a, b) => a.start - b.start);
  const unresolvedInRange = (marked, exact, start, end) => marked.some((item) => {
    const overlapStart = Math.max(start, item.start);
    const overlapEnd = Math.min(end, item.end);
    return overlapStart < overlapEnd
      && missingIntervals(exact, overlapStart, overlapEnd).length > 0;
  });
  const trimIntervals = (intervals, start, end) => intervals.map((item) => ({
    start: Math.max(item.start, start), end: Math.min(item.end, end),
  })).filter((item) => item.start < item.end);
  const resetSource = (state) => {
    state.events.clear();
    state.loaded = [];
    state.exact = [];
    state.sampled = [];
    state.coverageExact = [];
    state.coverageTruncatedRanges = [];
    state.cursor = 0;
    state.generation = null;
    state.coverage = [];
    state.refs = [];
    state.focusIndex = null;
    state.focus.textContent = '';
  };
  const limitCache = (state) => {
    if (state.loaded.length <= 8 && state.exact.length <= 8
      && state.sampled.length <= 8 && state.coverageExact.length <= 8
      && state.coverageTruncatedRanges.length <= 8 && state.coverage.length <= 128
      && (!state.loaded.length
        || state.loaded.at(-1).end - state.loaded[0].start <= maxRange * 2)) return;
    state.loaded = trimIntervals(state.loaded, range.start, range.end);
    state.exact = trimIntervals(state.exact, range.start, range.end);
    state.sampled = trimIntervals(state.sampled, range.start, range.end).slice(-8);
    state.coverageExact = trimIntervals(state.coverageExact, range.start, range.end);
    state.coverageTruncatedRanges = trimIntervals(state.coverageTruncatedRanges,
      range.start, range.end).slice(-8);
    for (const [id, event] of state.events) {
      if (event.observed_at < range.start || event.observed_at > range.end) {
        state.events.delete(id);
      }
    }
    state.coverage = state.coverage.filter((item) => item.started_at <= range.end
      && (item.ended_at ?? Infinity) >= range.start).slice(-128);
    render(state);
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
  const renderTextEvents = (state) => {
    state.tableBody.replaceChildren();
    const textEvents = [...state.events.values()].filter((event) =>
      event.observed_at >= range.start && event.observed_at <= range.end
      && !Number.isFinite(numericValue(event.new_value))
      && typeof event.new_value !== 'boolean')
      .sort((a, b) => b.observed_at - a.observed_at || b.id - a.id);
    state.valueDetails.hidden = textEvents.length === 0;
    for (const event of textEvents.slice(0, 200)) {
      const tr = document.createElement('tr');
      for (const content of [time(event.observed_at), valueText(event.new_value)]) {
        const td = document.createElement('td');
        td.textContent = content;
        tr.append(td);
      }
      state.tableBody.append(tr);
    }
  };
  const render = (state) => {
    const events = [...state.events.values()].filter((event) =>
      event.observed_at >= range.start && event.observed_at <= range.end).sort((a, b) =>
      a.observed_at - b.observed_at || a.id - b.id);
    const reduced = unresolvedInRange(state.sampled, state.exact, range.start, range.end);
    const coverageTruncated = unresolvedInRange(state.coverageTruncatedRanges,
      state.coverageExact, range.start, range.end);
    state.notice.textContent = reduced || coverageTruncated
      || events.some((event) => decimalInteger(event.new_value))
      ? label('chartReduced')
      : (events.length ? label('chartCoverage') : label('chartEmpty'));
    const numeric = events.filter((event) => Number.isFinite(numericValue(event.new_value)));
    const boolean = events.filter((event) => typeof event.new_value === 'boolean');
    const plottedKind = numeric.length && boolean.length ? 'mixed'
      : (numeric.length ? 'number' : 'boolean');
    const plotted = plottedKind === 'mixed' ? events.filter((event) =>
      Number.isFinite(numericValue(event.new_value)) || typeof event.new_value === 'boolean')
      : (plottedKind === 'number' ? numeric : boolean);
    if (plotted.length && typeof window.uPlot === 'function') {
      const x = [], y = [], booleanY = [], refs = [];
      let priorCoverage = null;
      for (const event of plotted) {
        const coverage = (state.coverage || []).findIndex((item) =>
          item.started_at <= event.observed_at
          && (item.ended_at == null || item.ended_at >= event.observed_at));
        if (priorCoverage !== null && (coverageTruncated || coverage < 0
          || priorCoverage < 0 || priorCoverage !== coverage
          || (reduced && x.length && event.observed_at - x[x.length - 1]
            > (range.end - range.start) / 64))) {
          x.push(event.observed_at - 0.000001);
          y.push(null);
          if (plottedKind === 'mixed') booleanY.push(null);
          refs.push(null);
        }
        x.push(event.observed_at);
        const isBoolean = typeof event.new_value === 'boolean';
        y.push(isBoolean ? (plottedKind === 'mixed' ? null : Number(event.new_value))
          : numericValue(event.new_value));
        if (plottedKind === 'mixed') booleanY.push(isBoolean ? Number(event.new_value) : null);
        refs.push(event);
        priorCoverage = coverage;
      }
      const options = {
        width: Math.max(280, Math.floor(state.plotHost.clientWidth || 600)),
        height: 220,
        scales: {x: {time: true}},
        series: [{}, {
          label: label(plottedKind === 'mixed' ? 'chartNumber' : 'chartValue'),
          stroke: '#2373a4', width: 2,
          spanGaps: false,
          ...(plottedKind === 'mixed' ? {scale: 'numeric', points: {show: true}} : {}),
          ...(plottedKind === 'boolean' ? {paths: window.uPlot.paths.stepped({align: 1})} : {}),
        }, ...(plottedKind === 'mixed' ? [{
          label: label('chartBoolean'), scale: 'boolean', stroke: '#b35f19', width: 2,
          spanGaps: false, paths: window.uPlot.paths.stepped({align: 1}),
          points: {show: true},
        }] : [])],
        ...(plottedKind === 'mixed' ? {axes: [{}, {scale: 'numeric'},
          {scale: 'boolean', side: 1, grid: {show: false}}]} : {}),
        cursor: {sync: {key: 'mcp-history-charts'}},
        hooks: {
          setCursor: [(plot) => {
            const event = state.refs[plot.cursor.idx];
            if (event) state.focus.textContent = `${time(event.observed_at)} · ${valueText(event.new_value)}`;
          }],
          setScale: [(plot, key) => {
            if (key === 'x') syncRange(plot, plot.scales.x.min, plot.scales.x.max);
          }],
        },
      };
      state.refs = refs;
      if (state.plot && state.plotKind !== plottedKind) {
        state.plot.destroy();
        state.plot = null;
      }
      applyingScale = true;
      try {
        const data = plottedKind === 'mixed' ? [x, y, booleanY] : [x, y];
        if (state.plot) state.plot.setData(data);
        else state.plot = new window.uPlot(options, data, state.plotHost);
        state.plotKind = plottedKind;
        state.plot.setScale('x', {min: range.start, max: range.end});
      } finally { applyingScale = false; }
    } else if (state.plot) {
      state.plot.destroy();
      state.plot = null;
      state.plotKind = null;
      state.refs = [];
      state.focusIndex = null;
      state.focus.textContent = '';
    }
    renderTextEvents(state);
    const boundaries = [
      ['chartCapture', state.capture], ['chartRetained', state.retained],
      ['chartRemoved', state.removed],
    ].filter((item) => Number.isFinite(item[1]));
    state.boundaries.textContent = boundaries.map(([name, value]) =>
      `${label(name)}: ${time(value)}`).join(' · ');
    state.coverageList.replaceChildren();
    for (const interval of (state.coverage || []).filter((item) =>
      item.started_at <= range.end && (item.ended_at ?? Infinity) >= range.start)) {
      const item = document.createElement('li');
      item.textContent = `${time(interval.started_at)} – ${interval.ended_at == null
        ? '…' : time(interval.ended_at)}`;
      state.coverageList.append(item);
    }
  };
  const sourceContext = (source) => [
    `${label('chartRoom')}: ${source.room || label('chartUnknown')}`,
    `${label('chartCategory')}: ${source.category || label('chartUnknown')}`,
    `${label('chartType')}: ${source.control_type}`,
  ].join(' · ');
  const createPanels = () => {
    panels.replaceChildren();
    sourceStates = selection.sources.map((source) => {
      const panel = document.createElement('section');
      panel.className = 'mcp-card mcp-history-chart-panel';
      const title = document.createElement('h2');
      title.textContent = `${source.control_name} · ${source.state_name}`;
      const context = document.createElement('p');
      context.className = 'mcp-help';
      context.textContent = sourceContext(source);
      const notice = document.createElement('p');
      notice.setAttribute('role', 'status');
      const boundaries = document.createElement('p');
      boundaries.className = 'mcp-help';
      const plotHost = document.createElement('div');
      plotHost.className = 'mcp-history-chart-plot';
      plotHost.tabIndex = 0;
      plotHost.setAttribute('role', 'group');
      plotHost.setAttribute('aria-label', title.textContent);
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
      const state = {source, title, context, events: new Map(), loaded: [], exact: [],
        sampled: [],
        coverageExact: [], coverageTruncatedRanges: [], cursor: 0, generation: null,
        coverage: [], plot: null, plotKind: null, refs: [], plotHost,
        focus, notice, boundaries, coverageList, tableBody, valueDetails: details};
      plotHost.addEventListener('keydown', (event) => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        const values = state.refs.filter((value) => value
          && value.observed_at >= range.start && value.observed_at <= range.end);
        if (!values.length) return;
        event.preventDefault();
        if (event.key === 'Home') state.focusIndex = 0;
        else if (event.key === 'End') state.focusIndex = values.length - 1;
        else state.focusIndex = Math.max(0, Math.min(values.length - 1,
          (state.focusIndex ?? (event.key === 'ArrowLeft' ? values.length : -1))
            + (event.key === 'ArrowLeft' ? -1 : 1)));
        const value = values[state.focusIndex];
        focus.textContent = `${time(value.observed_at)} · ${valueText(value.new_value)}`;
      });
      return state;
    });
  };
  const prepare = async () => {
    const result = await api.request('event_history_chart_prepare',
      {sources: JSON.stringify(requested)}, 120000);
    if (!Array.isArray(result.sources) || result.sources.length !== requested.length) {
      throw new Error('Invalid chart source response');
    }
    const first = !selection;
    selection = result;
    if (first) createPanels();
    else for (let index = 0; index < sourceStates.length; index++) {
      const state = sourceStates[index];
      const source = result.sources[index];
      state.source = source;
      state.title.textContent = `${source.control_name} · ${source.state_name}`;
      state.context.textContent = sourceContext(source);
      state.plotHost.setAttribute('aria-label', state.title.textContent);
    }
  };
  const fetchJobs = async (jobs, token) => {
    let pending = jobs;
    const counts = new Map(jobs.map((job) => [job, 0]));
    while (pending.length) {
      const response = await api.request('event_history_chart_query', {
        queries: JSON.stringify(pending.map((job) => ({
          control_uuid: job.state.source.control_uuid,
          state_uuid: job.state.source.state_uuid,
          generation: selection.generation,
          start: job.start, end: job.end, after_id: job.afterId,
        }))),
      }, 15000);
      if (token !== sequence) return false;
      if (!Array.isArray(response.results) || response.results.length !== pending.length) {
        throw new Error('Invalid chart query response');
      }
      const next = [];
      for (let index = 0; index < pending.length; index++) {
        const job = pending[index];
        const state = job.state;
        const result = response.results[index];
        if (state.generation !== null && result.generation !== state.generation) {
          throw Object.assign(new Error('History changed'), {code: 'history_changed'});
        }
        const coverage = state.coverage.filter((item) => job.initial
          || item.started_at > job.end || (item.ended_at ?? Infinity) < job.start);
        for (const item of result.coverage) {
          if (!coverage.some((existing) => existing.started_at === item.started_at
            && existing.ended_at === item.ended_at && existing.outcome === item.outcome)) {
            coverage.push(item);
          }
        }
        coverage.sort((a, b) => a.started_at - b.started_at);
        const metadataChanged = JSON.stringify(state.coverage) !== JSON.stringify(coverage)
          || state.capture !== result.capture_started_at
          || state.retained !== result.retained_from
          || state.removed !== result.recording_ended_at;
        const renderNeeded = state.generation === null || result.events.length > 0
          || result.reduced || result.coverage_truncated || metadataChanged;
        state.generation = result.generation;
        state.coverage = coverage;
        if (result.coverage_truncated) state.coverageTruncatedRanges = mergeInterval(
          state.coverageTruncatedRanges, job.start, job.end);
        else state.coverageExact = mergeInterval(state.coverageExact, job.start, job.end);
        state.capture = result.capture_started_at;
        state.retained = result.retained_from;
        state.removed = result.recording_ended_at;
        for (const event of result.events) state.events.set(event.id, event);
        if (state.events.size > maxEvents) {
          throw Object.assign(new Error('Chart memory limit reached'), {code: 'cache_full'});
        }
        counts.set(job, counts.get(job) + result.events.length);
        state.cursor = Math.max(state.cursor, result.latest_id);
        if (result.has_more) {
          if (counts.get(job) >= maxEvents) {
            throw Object.assign(new Error('Chart page limit reached'), {code: 'cache_full'});
          }
          job.afterId = result.next_id;
          next.push(job);
        } else if (job.initial) {
          state.loaded = mergeInterval(state.loaded, job.start, job.end);
          if (result.reduced) state.sampled.push({start: job.start, end: job.end});
          else state.exact = mergeInterval(state.exact, job.start, job.end);
        }
        if (renderNeeded || job.initial) render(state);
        limitCache(state);
      }
      pending = next;
    }
    return true;
  };
  const query = async (token, poll) => {
    const initiallyEmpty = sourceStates.every((state) => state.loaded.length === 0);
    while (true) {
      const jobs = sourceStates.flatMap((state) => {
        const missing = missingIntervals(loadedForRange(state, range.start, range.end),
          range.start, range.end);
        return missing.length ? [{state, ...missing[0], afterId: 0, initial: true}] : [];
      });
      if (!jobs.length) break;
      if (!await fetchJobs(jobs, token)) return;
    }
    if (poll && !initiallyEmpty) {
      await fetchJobs(sourceStates.map((state) => ({state,
        start: range.start, end: range.end, afterId: state.cursor, initial: false})), token);
    }
  };
  const load = async (fresh = false, poll = true) => {
    if (busy || document.hidden || !requested.length) {
      if (busy) { rerun = true; rerunPoll ||= poll; rerunFresh ||= fresh; }
      return;
    }
    if (rolling) {
      const end = Date.now() / 1000;
      const shift = Math.max(0, end - range.end);
      range = {start: range.start + shift, end: range.end + shift};
      for (const state of sourceStates) {
        let removed = false;
        for (const [id, event] of state.events) {
          if (event.observed_at < range.start) {
            state.events.delete(id);
            removed = true;
          }
        }
        if (removed) render(state);
        else if (shift > 0) render(state);
        if (shift > 0) {
          state.focus.textContent = '';
          state.focusIndex = null;
        }
        state.loaded = state.loaded.map((item) =>
          ({start: Math.max(item.start, range.start), end: item.end}))
          .filter((item) => item.start < item.end);
        state.exact = trimIntervals(state.exact, range.start, Infinity);
        state.sampled = trimIntervals(state.sampled, range.start, Infinity);
        state.coverageExact = trimIntervals(state.coverageExact, range.start, Infinity);
        state.coverageTruncatedRanges = trimIntervals(state.coverageTruncatedRanges,
          range.start, Infinity);
      }
      if (shift > 0) {
        applyingScale = true;
        for (const state of sourceStates) {
          state.plot?.setScale('x', {min: range.start, max: range.end});
        }
        applyingScale = false;
      }
    }
    busy = true;
    const token = ++sequence;
    let verifying = false;
    if (fresh || !selection) setStatus(label('loading'));
    try {
      if (fresh || !selection || Date.now() / 1000 - selection.verified_at >= 50) {
        verifying = true;
        await prepare();
        verifying = false;
      }
      if (token !== sequence) return;
      await query(token, poll);
      if (token === sequence) {
        staleRetries = 0;
        historyRetries = 0;
        setStatus('');
      }
    } catch (error) {
      if (token !== sequence) return;
      if (verifying) clear();
      if (error.code === 'history_changed' || error.code === 'cache_full') {
        for (const state of sourceStates) {
          resetSource(state);
          render(state);
        }
        if (historyRetries < 1) {
          historyRetries++;
          rerun = true;
          rerunPoll = true;
        } else setStatus(label('chartUnavailable'), 'warning');
      } else if (error.code === 'stale_configuration' && staleRetries < 1) {
        staleRetries++;
        clear();
        rerun = true;
      } else {
        if (error.code === 'forbidden' || error.code === 'stale_configuration') {
          clear();
          setStatus(label('chartDenied'), 'warning');
        } else {
          setStatus(queryErrorStatus(error), 'warning');
        }
      }
    } finally {
      busy = false;
      if (rerun) {
        const nextPoll = rerunPoll;
        const nextFresh = rerunFresh;
        rerun = false;
        rerunPoll = false;
        rerunFresh = false;
        void load(nextFresh, nextPoll);
      }
    }
  };
  const replaceRange = (start, end, follow = false) => {
    const now = Date.now() / 1000;
    if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0
      || start >= end || end - start > maxRange || end > now + 60) {
      setStatus(label('chartInvalid'), 'warning');
      return;
    }
    range = {start, end};
    rolling = follow;
    if (status.textContent === label('chartInvalid')) setStatus('');
    if (!follow) {
      $('chart-range').value = 'custom';
      for (const id of ['chart-from', 'chart-to', 'chart-apply']) $(id).disabled = false;
      $('chart-from').value = localInput(start);
      $('chart-to').value = localInput(end);
    }
    sequence++;
    applyingScale = true;
    for (const state of sourceStates) {
      state.plot?.setScale('x', {min: start, max: end});
      state.focus.textContent = '';
      state.focusIndex = null;
      render(state);
    }
    applyingScale = false;
    if (busy) rerun = true;
    else if (sourceStates.some((state) =>
      missingIntervals(loadedForRange(state, start, end), start, end).length)) {
      void load(false, false);
    }
  };
  $('chart-range').addEventListener('change', (event) => {
    const custom = event.target.value === 'custom';
    for (const id of ['chart-from', 'chart-to', 'chart-apply']) $(id).disabled = !custom;
    if (custom) {
      rolling = false;
      $('chart-from').value = localInput(range.start);
      $('chart-to').value = localInput(range.end);
    }
    if (!custom) {
      const end = Date.now() / 1000;
      replaceRange(end - Number(event.target.value), end, true);
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
