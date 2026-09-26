(() => {
  const root = document.querySelector('.mcp-event-history');
  if (!root) return;
  const api = window.McpEventHistoryApi;
  const $ = (id) => document.getElementById(id);
  const message = $('history-message');
  const rows = $('history-source-rows');
  const controlList = $('history-control-list');
  const stateSelect = $('history-state');
  const stateSearch = $('history-state-search');
  let controls = [];
  let selectedControl = '';
  let selectorGeneration = '';
  let catalogMode = 'loading';
  let visibleCount = 0;
  let pageOffset = 0;
  let querySequence = 0;
  const stateCache = new Map();
  let discoveryGeneration = 0;
  let stateGeneration = 0;
  let loadedStateCount = 0;
  let activeCount = 0;
  let overviewLoaded = false;
  let busy = false;
  const label = (name) => root.dataset[name] || name;
  const errorLabel = (error) => ({
    outcome_unknown: label('uncertain'),
    temporarily_unavailable: label('unavailable'),
    not_found: label('errorNotFound'),
    feature_disabled: label('errorDisabled'),
    confirmation_required: label('errorConfirmation'),
    apply_failed: label('errorApply'),
    stale_configuration: label('errorStaleConfiguration'),
    authentication_busy: label('authenticationBusy'),
    source_ip_blocked: label('sourceIpBlocked'),
    rate_limited: label('sourceLimit'),
  })[error?.code] || label('error');
  const setMessage = (value, kind = 'info') => {
    message.textContent = value;
    message.dataset.kind = kind;
  };
  const date = (value) => Number.isFinite(value)
    ? new Date(value * 1000).toLocaleString() : label('unknown');
  const cell = (name, content) => {
    const td = document.createElement('td');
    td.dataset.label = name;
    if (content instanceof Node) td.append(content);
    else td.textContent = content;
    return td;
  };
  const text = (tag, value, className) => {
    const item = document.createElement(tag);
    item.textContent = value;
    if (className) item.className = className;
    return item;
  };
  const namedSource = (name, type, uuid) => {
    const wrap = text('div', '');
    wrap.append(text('strong', name));
    if (type) wrap.append(text('small', type, 'mcp-event-history-subtext'));
    const details = document.createElement('details');
    details.className = 'mcp-event-history-uuid';
    details.append(text('summary', 'UUID'), text('code', uuid));
    wrap.append(details);
    return wrap;
  };
  const sourceAction = (source, recording) => {
    const button = text('button', label(recording ? 'stop' : 'purge'));
    button.type = 'button';
    button.className = 'lb-button';
    button.addEventListener('click', async () => {
      const action = recording ? 'event_history_remove_source' : 'event_history_purge_source';
      if (!window.confirm(label(recording ? 'confirmRemove' : 'confirmPurge'))) return;
      await mutate(action, {control_uuid: source.control_uuid, state_uuid: source.state_uuid,
        confirm: '1'});
    });
    return button;
  };
  const renderRows = (sources, unverified, visibilityStatus) => {
    rows.replaceChildren();
    $('history-empty').hidden = sources.length + unverified.length > 0;
    for (const source of sources) {
      const tr = document.createElement('tr');
      const recording = source.recording_status === 'active';
      const badge = text('span', label(recording ? 'active' : 'removed'), 'mcp-event-history-badge');
      badge.dataset.kind = recording ? 'active' : 'removed';
      const period = document.createElement('div');
      if (source.event_count) {
        period.append(text('span', `${label('from')} ${date(source.oldest_event_at)}`));
        period.append(text('span', `${label('to')} ${date(source.newest_event_at)}`));
      } else period.append(text('span', label('noEvents')));
      const coverage = document.createElement('details');
      coverage.append(text('summary', label('coverage')));
      if (!(source.recent_coverage || []).length) coverage.append(text('small', label('noCoverage')));
      for (const item of source.recent_coverage || []) {
        coverage.append(text('small', `${date(item.started_at)} – ${item.ended_at == null
          ? label('openInterval') : date(item.ended_at)}`,
          'mcp-event-history-subtext'));
      }
      if (source.capture_started_at != null) coverage.append(text('small',
        `${label('captureStart')}: ${date(source.capture_started_at)}`, 'mcp-event-history-subtext'));
      if (source.recording_ended_at != null) coverage.append(text('small',
        `${label('recordingEnd')}: ${date(source.recording_ended_at)}`, 'mcp-event-history-subtext'));
      period.append(coverage);
      const actions = document.createElement('div');
      actions.className = 'mcp-actions';
      actions.append(sourceAction(source, recording));
      tr.append(
        cell(root.querySelector('th:nth-child(1)').textContent,
          namedSource(source.control_name, source.control_type, source.control_uuid)),
        cell(root.querySelector('th:nth-child(2)').textContent,
          namedSource(source.state_name, '', source.state_uuid)),
        cell(root.querySelector('th:nth-child(3)').textContent, badge),
        cell(label('events'), String(source.event_count)),
        cell(root.querySelector('th:nth-child(5)').textContent, period),
        cell(root.querySelector('th:nth-child(6)').textContent, actions),
      );
      rows.append(tr);
    }
    for (const source of unverified) {
      const tr = document.createElement('tr');
      const name = visibilityStatus === 'available'
        ? label('sourceNotVisible') : label('sourceUnverified');
      tr.append(
        cell(root.querySelector('th:nth-child(1)').textContent,
          namedSource(name, '', source.control_uuid)),
        cell(root.querySelector('th:nth-child(2)').textContent,
          namedSource(label('unknown'), '', source.state_uuid)),
        cell(root.querySelector('th:nth-child(3)').textContent, label('selected')),
        cell(label('events'), label('unknown')),
        cell(root.querySelector('th:nth-child(5)').textContent, label('unknown')),
        cell(root.querySelector('th:nth-child(6)').textContent, sourceAction(source, true)),
      );
      rows.append(tr);
    }
  };
  const renderOverview = (data) => {
      overviewLoaded = true;
      activeCount = data.active_source_count;
      $('history-retention').value = data.retention_days;
      $('history-maximum').value = data.maximum_mib;
      $('history-policy').textContent = `${data.retention_days} d · ${data.maximum_mib} MiB`;
      $('history-measured').textContent = date(data.measured_at);
      $('history-storage').textContent = data.store_status === 'available'
        ? `${((data.database_bytes + data.wal_bytes) / 1048576).toLocaleString(undefined,
          {maximumFractionDigits: 2})} MiB` : label('unavailable');
      $('history-source-count').textContent = data.visibility_status === 'available'
        ? `${data.sources_truncated ? `${label('listed')}: ` : ''}${data.visible_active_count} ${label('active')} · ${data.visible_removed_count} ${label('removed')}`
        : `${data.active_source_count} ${label('unknown')}`;
      $('history-events').textContent = data.visibility_status === 'available'
        ? `${data.visible_event_count} ${label('visibleEvents')}` : label('unknown');
      $('history-visibility-warning').hidden = data.visibility_status === 'available';
      const sourceWarning = $('history-source-warning');
      sourceWarning.hidden = !data.hidden_sources_present && !data.sources_truncated;
      sourceWarning.textContent = [
        data.hidden_sources_present ? label('hiddenSources') : '',
        data.sources_truncated ? label('sourcesTruncated') : '',
      ].filter(Boolean).join(' ');
      renderRows(Array.isArray(data.sources) ? data.sources : [],
        Array.isArray(data.unverified_sources) ? data.unverified_sources : [],
        data.visibility_status);
      setMessage(data.store_status === 'available' ? label('loaded') : label('unavailable'),
        data.store_status === 'available' ? 'success' : 'warning');
  };
  const loadQuickSummary = async () => {
    try {
      const data = await api.request('event_history_quick_summary', {}, 5000);
      if (overviewLoaded) return;
      activeCount = data.active_source_count;
      $('history-retention').value = data.retention_days;
      $('history-maximum').value = data.maximum_mib;
      $('history-policy').textContent = `${data.retention_days} d · ${data.maximum_mib} MiB`;
      $('history-measured').textContent = date(data.measured_at);
      $('history-storage').textContent = data.size_bytes == null ? label('unavailable')
        : `${(data.size_bytes / 1048576).toLocaleString(undefined,
          {maximumFractionDigits: 2})} MiB`;
      $('history-source-count').textContent = `${data.active_source_count} ${label('active')}`;
    } catch {
      // The full overview reports a localized failure if the quick path is unavailable.
    }
  };
  const loadStatus = async () => {
    if (document.hidden) return;
    try {
      const data = await api.request('event_history_runtime_status', {}, 5000);
      const reasons = {
        store_unavailable: 'statusStoreUnavailable',
        no_sources: 'statusNoSources',
        no_visible_sources: 'statusNoVisibleSources',
        unsupported_value: 'statusUnsupportedValue',
        subscription_unavailable: 'statusSubscriptionUnavailable',
        size_enforcement_failed: 'statusSizeEnforcementFailed',
      };
      $('history-recorder').textContent = data.availability === 'available'
        ? (data.status === 'recording' ? label('recording')
          : data.status === 'disabled' ? label('disabled')
            : data.reason && reasons[data.reason] ? label(reasons[data.reason]) : label('unknown'))
        : label('unknown');
      $('history-recorder-time').textContent = data.availability === 'available'
        ? date(data.observed_at) : '';
    } catch {
      $('history-recorder').textContent = label('unknown');
      $('history-recorder-time').textContent = '';
    }
  };
  const mutate = async (action, fields) => {
    if (busy) return;
    busy = true;
    setMessage(label('loading'));
    let feedback = label('saved');
    let feedbackKind = 'success';
    try {
      const result = await api.request(action, fields, 240000);
      if (result.changed === false) feedback = label('unchanged');
    } catch (error) {
      feedback = errorLabel(error);
      feedbackKind = 'error';
    } finally {
      busy = false;
      await loadControls();
      await loadStatus();
      setMessage(feedback, feedbackKind);
    }
  };
  const facetSelection = Object.fromEntries(['room', 'category', 'type']
    .map((field) => [field, new Set()]));
  const selectedFilters = () => Object.fromEntries(['room', 'category', 'type']
    .map((field) => [field, Array.from(facetSelection[field])]));
  const controlMatches = (control, needle, filters) =>
    (!needle || control.name.toLocaleLowerCase().includes(needle)
      || control.uuid.toLocaleLowerCase().includes(needle))
    && ['room', 'category', 'type'].every((field) =>
      !filters[field].length || filters[field].includes(
        control[{room: 'room_id', category: 'category_id', type: 'type'}[field]] || ''));
  const renderControls = (items) => {
    controlList.replaceChildren();
    for (const control of items) {
      const row = document.createElement('label');
      const radio = document.createElement('input');
      radio.type = 'radio';
      radio.name = 'history-control';
      radio.value = control.uuid;
      radio.checked = selectedControl === control.uuid;
      radio.addEventListener('change', () => {
        selectedControl = radio.value;
        stateSearch.value = '';
        void loadStates();
      });
      const title = document.createElement('span');
      title.append(text('strong', control.name));
      title.append(text('small', [control.type, control.room, control.category]
        .filter(Boolean).join(' · ')));
      title.append(text('small', control.uuid));
      row.append(radio, title);
      controlList.append(row);
    }
  };
  const updateControlCount = (total) => {
    $('history-search-status').textContent =
      `${total} ${label('selectorFiltered')} · ${total ? pageOffset + 1 : 0}–${visibleCount}`
      + (selectedControl && !controlList.querySelector('input:checked')
        ? ` · ${label('selectedHidden')}` : '');
    $('history-more-controls').hidden = visibleCount >= total;
    $('history-prev-controls').hidden = pageOffset === 0;
    $('history-clear-filters').disabled = false;
  };
  const invalidateSelector = () => {
    selectorGeneration = '';
    controls = [];
    selectedControl = '';
    controlList.replaceChildren();
    stateSelect.replaceChildren(new Option(label('selectState'), ''));
    stateSelect.disabled = true;
    stateSearch.disabled = true;
    $('history-add').disabled = true;
    $('history-more-controls').hidden = true;
    $('history-prev-controls').hidden = true;
    $('history-more-states').hidden = true;
  };
  const applyFilters = async (offset = 0) => {
    if (!selectorGeneration) return;
    const request = ++querySequence;
    const needle = $('history-search').value.trim().toLocaleLowerCase();
    const filters = selectedFilters();
    if (catalogMode === 'local') {
      const matches = controls.filter((control) => controlMatches(control, needle, filters));
      pageOffset = offset;
      const page = matches.slice(offset, offset + 50);
      renderControls(page);
      visibleCount = offset + page.length;
      updateControlCount(matches.length);
      if (!matches.length) $('history-search-status').textContent = label('noControls');
      return;
    }
    $('history-search-status').textContent = label('loading');
    try {
      const data = await api.request('event_history_selector_query', {
        generation: selectorGeneration, query: $('history-search').value,
        offset,
        room: JSON.stringify(filters.room), category: JSON.stringify(filters.category),
        type: JSON.stringify(filters.type),
      });
      if (request !== querySequence) return;
      pageOffset = offset;
      renderControls(data.controls || []);
      visibleCount = offset + (data.controls?.length || 0);
      updateControlCount(data.total);
      if (!data.total) $('history-search-status').textContent = label('noControls');
    } catch (error) {
      if (error.code === 'stale_configuration') invalidateSelector();
      if (request === querySequence) $('history-search-status').textContent = errorLabel(error);
    }
  };
  const renderFacets = (facets) => {
    for (const field of ['room', 'category', 'type']) {
      const panel = root.querySelector(`[data-facet="${field}"]`);
      const list = panel.querySelector('.mcp-event-history-facet-options');
      const search = panel.querySelector('input[type="search"]');
      const options = facets[field] || [];
      const available = new Set(options.map((option) => option.id));
      for (const value of facetSelection[field]) {
        if (!available.has(value)) facetSelection[field].delete(value);
      }
      const renderOptions = () => {
        const needle = search.value.trim().toLocaleLowerCase();
        const matches = options.filter((option) =>
          (option.name || option.id || label('filterUnknown'))
            .toLocaleLowerCase().includes(needle));
        list.replaceChildren();
        for (const option of matches.slice(0, 100)) {
          const row = document.createElement('label');
          const checkbox = document.createElement('input');
          checkbox.type = 'checkbox';
          checkbox.value = option.id;
          checkbox.checked = facetSelection[field].has(option.id);
          checkbox.addEventListener('change', () => {
            if (checkbox.checked && facetSelection[field].size >= 100) {
              checkbox.checked = false;
              $('history-search-status').textContent = label('filterLimit');
              return;
            }
            if (checkbox.checked) facetSelection[field].add(option.id);
            else facetSelection[field].delete(option.id);
            void applyFilters();
          });
          row.append(checkbox, text('span', option.name || option.id || label('filterUnknown')));
          list.append(row);
        }
        const count = text('small', `${Math.min(matches.length, 100)} / ${matches.length}`);
        list.append(count);
      };
      search.oninput = renderOptions;
      renderOptions();
    }
  };
  const loadControls = async () => {
    const request = ++discoveryGeneration;
    const previousControl = selectedControl;
    const previousState = stateSelect.value;
    invalidateSelector();
    ++querySequence;
    catalogMode = 'loading';
    ++stateGeneration;
    $('history-search').disabled = true;
    $('history-search-status').textContent = label('loading');
    try {
      const data = await api.request('event_history_prepare_selector', {}, 60000);
      if (request !== discoveryGeneration) return;
      selectorGeneration = data.generation;
      renderOverview(data.overview);
      $('history-search').disabled = false;
      $('history-search-status').textContent =
        `${data.total} ${label('selectorCount')} · ${label('selectorVerified')}: ${date(data.verified_at)}`;
      renderControls(data.controls || []);
      pageOffset = 0;
      visibleCount = data.controls?.length || 0;
      $('history-more-controls').hidden = visibleCount >= data.total;
      const [catalog, facets] = await Promise.all([
        api.request('event_history_selector_catalog', {generation: selectorGeneration}),
        api.request('event_history_selector_facets', {generation: selectorGeneration}),
      ]);
      if (request !== discoveryGeneration) return;
      catalogMode = catalog.mode;
      controls = catalog.controls || [];
      renderFacets(facets);
      if (previousControl) {
        const found = catalogMode === 'local'
          ? controls.find((item) => item.uuid === previousControl)
          : (await api.request('event_history_selector_query', {
            generation: selectorGeneration, query: previousControl, offset: 0,
            room: '[]', category: '[]', type: '[]',
          })).controls?.find((item) => item.uuid === previousControl);
        if (request !== discoveryGeneration) return;
        if (found) {
          selectedControl = previousControl;
          await applyFilters();
          await loadStates(previousState);
        }
      }
      if (!selectedControl) await applyFilters();
    } catch (error) {
      if (request === discoveryGeneration) {
        invalidateSelector();
        $('history-search-status').textContent = errorLabel(error);
      }
    }
  };
  const loadStates = async (restoreState = '', append = false) => {
    const request = ++stateGeneration;
    const control = selectedControl;
    const status = $('history-state-search-status');
    const priorState = append ? stateSelect.value : restoreState;
    if (!append) {
      stateSelect.replaceChildren(new Option(label('selectState'), ''));
      loadedStateCount = 0;
    }
    if (!append) $('history-more-states').hidden = true;
    stateSelect.disabled = true;
    $('history-add').disabled = true;
    if (!control || !selectorGeneration) { status.textContent = ''; return; }
    stateSearch.disabled = false;
    stateSearch.closest('.mcp-field').hidden = false;
    status.textContent = label('loading');
    try {
      const query = stateSearch.value.trim().toLocaleLowerCase();
      const cached = stateCache.get(`${selectorGeneration}:${control}`);
      const data = cached
        ? {states: cached.states.filter((state) => !query
          || state.name.toLocaleLowerCase().includes(query)
          || state.uuid.toLocaleLowerCase().includes(query)),
        total: cached.states.filter((state) => !query
          || state.name.toLocaleLowerCase().includes(query)
          || state.uuid.toLocaleLowerCase().includes(query)).length}
        : await api.request('event_history_selector_states',
          {generation: selectorGeneration, control_uuid: control, query,
            offset: append ? loadedStateCount : 0});
      if (request !== stateGeneration || control !== selectedControl) return;
      if (!query && data.total <= 200) stateCache.set(`${selectorGeneration}:${control}`, data);
      const displayedStates = new Set(Array.from(stateSelect.options, (option) => option.value));
      for (const state of data.states || []) {
        if (!displayedStates.has(state.uuid)) {
          stateSelect.add(new Option(`${state.name} · ${state.uuid}`, state.uuid));
          displayedStates.add(state.uuid);
        }
      }
      loadedStateCount += data.states?.length || 0;
      if (restoreState && !query && !Array.from(stateSelect.options)
        .some((state) => state.value === restoreState)) {
        const exact = await api.request('event_history_selector_states',
          {generation: selectorGeneration, control_uuid: control, query: restoreState, offset: 0});
        if (request !== stateGeneration || control !== selectedControl) return;
        const restored = exact.states?.find((state) => state.uuid === restoreState);
        if (restored) stateSelect.add(new Option(`${restored.name} · ${restored.uuid}`,
          restored.uuid));
      }
      stateSelect.disabled = stateSelect.options.length <= 1;
      if (priorState && Array.from(stateSelect.options).some((state) => state.value === priorState)) {
        stateSelect.value = priorState;
        $('history-add').disabled = false;
      }
      $('history-more-states').hidden =
        loadedStateCount >= Math.min(data.total, 2000);
      status.textContent = data.total > loadedStateCount ? label('moreStates') : '';
      stateSearch.closest('.mcp-field').hidden = data.total <= 10 && !query;
    } catch (error) {
      if (error.code === 'stale_configuration') invalidateSelector();
      if (request === stateGeneration) status.textContent = errorLabel(error);
    }
  };
  stateSelect.addEventListener('change', () => {
    $('history-add').disabled = !stateSelect.value;
  });
  $('history-more-states').addEventListener('click', () => { void loadStates('', true); });
  $('history-search-button').addEventListener('click', loadControls);
  $('history-more-controls').addEventListener('click', () => { void applyFilters(visibleCount); });
  $('history-prev-controls').addEventListener('click', () => {
    void applyFilters(Math.max(0, pageOffset - 50));
  });
  $('history-clear-filters').addEventListener('click', () => {
    $('history-search').value = '';
    for (const field of ['room', 'category', 'type']) {
      facetSelection[field].clear();
      for (const checkbox of root.querySelectorAll(`[data-facet="${field}"] input:checked`)) {
        checkbox.checked = false;
      }
    }
    void applyFilters();
  });
  let filterTimer;
  $('history-search').addEventListener('input', () => {
    window.clearTimeout(filterTimer);
    filterTimer = window.setTimeout(() => { void applyFilters(); }, 180);
  });
  stateSearch.addEventListener('input', () => {
    window.clearTimeout(filterTimer);
    filterTimer = window.setTimeout(() => { void loadStates(); }, 180);
  });
  stateSearch.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') event.preventDefault();
  });
  $('history-add-form').addEventListener('submit', (event) => {
    event.preventDefault();
    if (activeCount >= 64) { setMessage(label('sourceLimit'), 'warning'); return; }
    void mutate('event_history_add_source', {control_uuid: selectedControl,
      state_uuid: stateSelect.value});
  });
  $('history-policy-form').addEventListener('submit', (event) => {
    event.preventDefault();
    void mutate('event_history_save_policy', {retention_days: $('history-retention').value,
      maximum_mib: $('history-maximum').value});
  });
  $('history-clear').addEventListener('click', () => {
    if (window.confirm(label('confirmClear'))) void mutate('clear_event_history', {confirm: '1'});
  });
  $('history-refresh').addEventListener('click', () => { void loadControls(); void loadStatus(); });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) void loadStatus(); });
  window.setInterval(loadStatus, 30000);
  void loadQuickSummary();
  void loadStatus();
  void loadControls();
})();
