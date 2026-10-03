window.McpEventHistoryChartCache = (() => {
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
  const compactEvent = (event) => ({
    id: event.id, observed_at: event.observed_at, new_value: event.new_value,
  });
  const eventCount = (state, events) => new Set([
    ...state.events.keys(), ...events.map((event) => event.id),
  ]).size;
  const trimToRange = (state, range) => {
    for (const name of ['loaded', 'exact', 'sampled', 'coverageExact',
      'coverageTruncatedRanges']) state[name] = trimIntervals(state[name], range.start, range.end);
    for (const [id, event] of state.events) {
      if (event.observed_at < range.start || event.observed_at > range.end) state.events.delete(id);
    }
    state.coverage = state.coverage.filter((item) => item.started_at <= range.end
      && (item.ended_at ?? Infinity) >= range.start);
  };
  const resetCache = (state) => {
    state.events.clear();
    state.loaded = [];
    state.exact = [];
    state.sampled = [];
    state.coverageExact = [];
    state.coverageTruncatedRanges = [];
    state.cursor = 0;
    state.generation = null;
    state.coverage = [];
  };
  const limitCache = (state, range, maxRange) => {
    if (state.loaded.length <= 8 && state.exact.length <= 8
      && state.sampled.length <= 8 && state.coverageExact.length <= 8
      && state.coverageTruncatedRanges.length <= 8 && state.coverage.length <= 128
      && (!state.loaded.length
        || state.loaded.at(-1).end - state.loaded[0].start <= maxRange * 2)) return false;
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
    return true;
  };
  return {mergeInterval, missingIntervals, loadedForRange, unresolvedInRange,
    trimIntervals, compactEvent, eventCount, trimToRange, resetCache, limitCache};
})();
