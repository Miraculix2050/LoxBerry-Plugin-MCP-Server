(() => {
  const root = document.querySelector('.mcp-event-history');
  if (!root) return;
  const api = window.McpEventHistoryApi;
  const $ = (id) => document.getElementById(id);
  const message = $('history-message');
  const refreshButton = $('history-refresh');
  const refreshButtonText = refreshButton.textContent;
  const rows = $('history-source-rows');
  const controlList = $('history-control-list');
  const stateSelect = $('history-state');
  const stateSearch = $('history-state-search');
  const stateSearchWrap = $('history-state-search-wrap');
  const addButton = $('history-add');
  const addStatus = $('history-add-status');
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
  let controlsLoading = false;
  let controlsLoadPromise = null;
  let staleRecoveryScheduled = false;
  let sourceRevisionChecking = false;
  let knownSourceRevision = '';
  let selectorVerificationPending = false;
  let nextRevisionRefreshAt = 0;
  let revisionRefreshFailures = 0;
  let messageVersion = 0;
  let savedPolicy = null;
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
    messageVersion += 1;
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
  const renderPolicy = (data) => {
    const retention = $('history-retention');
    const maximum = $('history-maximum');
    const retentionDirty = savedPolicy !== null
      && retention.value !== String(savedPolicy.retention_days);
    const maximumDirty = savedPolicy !== null
      && maximum.value !== String(savedPolicy.maximum_mib);
    if (!retentionDirty) retention.value = String(data.retention_days);
    if (!maximumDirty) maximum.value = String(data.maximum_mib);
    savedPolicy = {retention_days: data.retention_days, maximum_mib: data.maximum_mib};
    $('history-policy').textContent = `${data.retention_days} d · ${data.maximum_mib} MiB`;
  };
  const renderOverview = (data) => {
      overviewLoaded = true;
      if (data.store_status === 'available' && typeof data.source_revision === 'string') {
        knownSourceRevision = data.source_revision;
        selectorVerificationPending = data.visibility_status !== 'available';
        if (!selectorVerificationPending) {
          nextRevisionRefreshAt = 0;
          revisionRefreshFailures = 0;
        }
      }
      activeCount = data.active_source_count;
      renderPolicy(data);
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
      const complete = data.store_status === 'available' && data.visibility_status === 'available';
      setMessage(label(complete ? 'loaded' : 'unavailable'), complete ? 'success' : 'warning');
  };
  const loadQuickSummary = async () => {
    try {
      const data = await api.request('event_history_quick_summary', {}, 5000);
      if (overviewLoaded) return;
      activeCount = data.active_source_count;
      renderPolicy(data);
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
    refreshButton.disabled = true;
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
      if (controlsLoadPromise) await controlsLoadPromise;
      await loadControls();
      await loadStatus();
      busy = false;
      refreshButton.disabled = false;
      addButton.disabled = stateSelect.disabled || !selectedControl || !stateSelect.value;
      stateSearch.disabled = !selectedControl || stateSearchWrap.hidden;
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
        addStatus.textContent = '';
        addStatus.hidden = true;
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
    stateCache.clear();
    controlList.replaceChildren();
    stateSelect.replaceChildren(new Option(label('selectState'), ''));
    stateSelect.disabled = true;
    stateSearch.value = '';
    stateSearch.disabled = true;
    stateSearchWrap.hidden = true;
    $('history-search').disabled = true;
    $('history-state-search-status').textContent = '';
    addButton.disabled = true;
    for (const field of ['room', 'category', 'type']) {
      facetSelection[field].clear();
      const panel = root.querySelector(`[data-facet="${field}"]`);
      panel.open = false;
      const search = panel.querySelector('input[type="search"]');
      search.value = '';
      search.disabled = true;
      search.oninput = null;
      panel.querySelector('.mcp-event-history-facet-options').replaceChildren();
    }
    $('history-clear-filters').disabled = true;
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
      if (error.code === 'stale_configuration') recoverStaleSelector();
      if (request === querySequence) $('history-search-status').textContent = errorLabel(error);
    }
  };
  const renderFacets = (facets) => {
    for (const field of ['room', 'category', 'type']) {
      const panel = root.querySelector(`[data-facet="${field}"]`);
      const list = panel.querySelector('.mcp-event-history-facet-options');
      const search = panel.querySelector('input[type="search"]');
      search.disabled = false;
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
  const performLoadControls = async (restore = null) => {
    controlsLoading = true;
    refreshButton.disabled = true;
    refreshButton.textContent = label('refreshWorking');
    const request = ++discoveryGeneration;
    const previousControl = restore?.control ?? selectedControl;
    const previousState = restore?.state ?? stateSelect.value;
    const previousFilters = restore?.filters ?? selectedFilters();
    invalidateSelector();
    ++querySequence;
    catalogMode = 'loading';
    ++stateGeneration;
    $('history-search').disabled = true;
    $('history-search-status').textContent = label('loading');
    try {
      const data = await api.request('event_history_prepare_selector', {}, 120000);
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
      for (const field of ['room', 'category', 'type']) {
        for (const value of previousFilters[field]) facetSelection[field].add(value);
      }
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
      return data.overview?.store_status === 'available'
        && data.overview?.visibility_status === 'available';
    } catch (error) {
      if (request === discoveryGeneration) {
        invalidateSelector();
        $('history-search-status').textContent = errorLabel(error);
        try {
          const local = await api.request('event_history_local_overview', {}, 10000);
          if (request === discoveryGeneration) renderOverview(local);
        } catch {
          if (request === discoveryGeneration) setMessage(label('unavailable'), 'warning');
        }
        if (error.code === 'stale_configuration') recoverStaleSelector();
      }
      return false;
    } finally {
      controlsLoading = false;
      refreshButton.disabled = busy;
      refreshButton.textContent = refreshButtonText;
    }
  };
  const loadControls = (restore = null) => {
    if (controlsLoadPromise) return controlsLoadPromise;
    controlsLoadPromise = performLoadControls(restore).finally(() => { controlsLoadPromise = null; });
    return controlsLoadPromise;
  };
  const recoverStaleSelector = (restoreState = null) => {
    if (staleRecoveryScheduled) return;
    staleRecoveryScheduled = true;
    const restore = {control: selectedControl, state: restoreState ?? stateSelect.value,
      filters: selectedFilters()};
    const ongoing = controlsLoadPromise;
    if (ongoing) {
      ++discoveryGeneration;
      invalidateSelector();
    }
    void (async () => {
      try {
        if (ongoing) await ongoing;
        await loadControls(restore);
      } catch {
        setMessage(label('unavailable'), 'warning');
      } finally {
        staleRecoveryScheduled = false;
      }
    })();
  };
  const checkSourceRevision = async () => {
    if (document.hidden || busy || controlsLoading || sourceRevisionChecking
      || !knownSourceRevision) return;
    sourceRevisionChecking = true;
    try {
      const data = await api.request('event_history_source_revision', {}, 15000);
      if (data.availability === 'available'
        && (data.revision !== knownSourceRevision || selectorVerificationPending)
        && Date.now() >= nextRevisionRefreshAt) {
        const verified = await loadControls();
        if (!verified || knownSourceRevision !== data.revision) {
          selectorVerificationPending = true;
          revisionRefreshFailures += 1;
          nextRevisionRefreshAt = Date.now()
            + Math.min(300000, 30000 * (2 ** revisionRefreshFailures));
        }
      }
    } catch {
      // Keep the last verified view; the next visible poll can retry this local check.
    } finally {
      sourceRevisionChecking = false;
    }
  };
  const loadStates = async (restoreState = '', append = false) => {
    const request = ++stateGeneration;
    const control = selectedControl;
    const status = $('history-state-search-status');
    const priorState = append ? stateSelect.value : restoreState;
    const priorSelectEnabled = append && !stateSelect.disabled;
    const priorAddEnabled = append && !addButton.disabled;
    if (!append) {
      stateSelect.replaceChildren(new Option(label('statesLoading'), ''));
      loadedStateCount = 0;
      if (!stateSearch.value.trim()) stateSearchWrap.hidden = true;
    }
    if (!append) $('history-more-states').hidden = true;
    stateSelect.disabled = true;
    stateSearch.disabled = true;
    addButton.disabled = true;
    if (!control || !selectorGeneration) { status.textContent = ''; return; }
    status.textContent = label('statesLoading');
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
      if (!append) stateSelect.replaceChildren(new Option(label('selectState'), ''));
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
        addButton.disabled = busy;
      }
      $('history-more-states').hidden =
        loadedStateCount >= Math.min(data.total, 2000);
      status.textContent = !data.total ? label('noStates')
        : data.total > loadedStateCount ? label('moreStates') : '';
      stateSearchWrap.hidden = data.total <= 10 && !query;
      stateSearch.disabled = busy;
    } catch (error) {
      if (error.code === 'stale_configuration') recoverStaleSelector(priorState);
      if (request === stateGeneration) {
        if (append && error.code !== 'stale_configuration') {
          stateSelect.disabled = !priorSelectEnabled;
          addButton.disabled = busy || !priorAddEnabled;
        }
        if (!append && error.code !== 'stale_configuration') {
          stateSelect.replaceChildren(new Option(label('selectState'), ''));
          stateSearchWrap.hidden = false;
        }
        stateSearch.disabled = busy || error.code === 'stale_configuration';
        status.textContent = errorLabel(error);
      }
    }
  };
  stateSelect.addEventListener('change', () => {
    addButton.disabled = busy || !stateSelect.value;
    if (!busy) {
      addStatus.textContent = '';
      addStatus.hidden = true;
    }
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
  let controlFilterTimer;
  let stateFilterTimer;
  $('history-search').addEventListener('input', () => {
    window.clearTimeout(controlFilterTimer);
    controlFilterTimer = window.setTimeout(() => { void applyFilters(); }, 180);
  });
  stateSearch.addEventListener('input', () => {
    window.clearTimeout(stateFilterTimer);
    stateFilterTimer = window.setTimeout(() => { void loadStates(); }, 180);
  });
  stateSearch.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') event.preventDefault();
  });
  const startRecording = async () => {
    if (busy || !selectedControl || !stateSelect.value) return;
    const source = {control_uuid: selectedControl, state_uuid: stateSelect.value};
    busy = true;
    const locked = Array.from(root.querySelectorAll(
      '#history-add-form input, #history-add-form select, #history-add-form button, '
      + '#history-search, #history-search-button, #history-clear-filters, #history-refresh, '
      + '.mcp-event-history-filters input, #history-source-rows button'));
    const wasDisabled = new Map(locked.map((control) => [control, control.disabled]));
    for (const control of locked) control.disabled = true;
    addButton.disabled = true;
    addButton.textContent = label('addWorking');
    addStatus.textContent = label('addWorking');
    addStatus.dataset.kind = 'working';
    addStatus.hidden = false;
    let applied = false;
    let unchanged = false;
    try {
      const result = await api.request('event_history_add_source', source, 240000);
      applied = true;
      unchanged = result.changed === false;
      stateSelect.value = '';
      const refreshed = result.overview?.store_status === 'available'
        && result.overview?.visibility_status === 'available';
      if (result.overview) renderOverview(result.overview);
      void loadStatus();
      addStatus.textContent = refreshed
        ? label(unchanged ? 'unchanged' : 'addApplied') : label('addRefreshFailed');
      addStatus.dataset.kind = refreshed ? 'success' : 'warning';
    } catch (error) {
      addStatus.textContent = applied ? label('addRefreshFailed') : errorLabel(error);
      addStatus.dataset.kind = applied ? 'warning' : 'error';
    } finally {
      busy = false;
      for (const control of locked) {
        if (control.isConnected) control.disabled = wasDisabled.get(control);
      }
      addButton.textContent = label('add');
      addButton.disabled = applied || !stateSelect.value;
      stateSearch.disabled = !selectedControl || stateSearchWrap.hidden;
    }
  };
  $('history-add-form').addEventListener('submit', (event) => {
    event.preventDefault();
    if (activeCount >= 64) { setMessage(label('sourceLimit'), 'warning'); return; }
    void startRecording();
  });
  $('history-policy-form').addEventListener('submit', (event) => {
    event.preventDefault();
    void mutate('event_history_save_policy', {retention_days: $('history-retention').value,
      maximum_mib: $('history-maximum').value});
  });
  $('history-clear').addEventListener('click', () => {
    if (window.confirm(label('confirmClear'))) void mutate('clear_event_history', {confirm: '1'});
  });
  refreshButton.addEventListener('click', () => {
    if (busy || controlsLoading) return;
    setMessage(label('refreshWorking'), 'working');
    void (async () => {
      const refreshed = await loadControls();
      void loadStatus();
      setMessage(label(refreshed ? 'refreshed' : 'refreshFailed'),
        refreshed ? 'success' : 'warning');
      if (refreshed) {
        const shownVersion = messageVersion;
        window.setTimeout(() => {
          if (messageVersion === shownVersion) setMessage(label('loaded'), 'success');
        }, 5000);
      }
    })();
  });
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) { void loadStatus(); void checkSourceRevision(); }
  });
  window.setInterval(() => { void loadStatus(); }, 30000);
  window.setInterval(() => { void checkSourceRevision(); }, 60000);
  void loadQuickSummary();
  void loadStatus();
  void loadControls();
})();
