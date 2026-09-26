(() => {
  const root = document.querySelector('.mcp-event-history');
  if (!root) return;
  const api = window.McpEventHistoryApi;
  const $ = (id) => document.getElementById(id);
  const message = $('history-message');
  const rows = $('history-source-rows');
  const controlSelect = $('history-control');
  const stateSelect = $('history-state');
  const stateSearch = $('history-state-search');
  let overviewGeneration = 0;
  let controls = [];
  let discoveryGeneration = 0;
  let stateGeneration = 0;
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
  const loadOverview = async () => {
    const generation = ++overviewGeneration;
    setMessage(label('loading'));
    try {
      const data = await api.request('event_history_overview');
      if (generation !== overviewGeneration) return;
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
    } catch (error) {
      if (generation === overviewGeneration) setMessage(errorLabel(error), 'error');
    }
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
      await loadOverview();
      await loadStatus();
      setMessage(feedback, feedbackKind);
    }
  };
  const loadControls = async () => {
    const generation = ++discoveryGeneration;
    ++stateGeneration;
    const status = $('history-search-status');
    status.textContent = label('loading');
    controlSelect.disabled = true;
    stateSelect.disabled = true;
    stateSelect.replaceChildren(new Option(label('selectState'), ''));
    stateSearch.disabled = true;
    stateSearch.value = '';
    $('history-state-search-button').disabled = true;
    $('history-add').disabled = true;
    try {
      const data = await api.request('event_history_discover',
        {query: $('history-search').value}, 45000);
      if (generation !== discoveryGeneration) return;
      controls = Array.isArray(data.controls) ? data.controls : [];
      controlSelect.replaceChildren(new Option(root.querySelector('#history-control option')?.textContent || '', ''));
      for (const control of controls) controlSelect.add(new Option(
        `${control.name} (${control.type}) · ${control.uuid}`, control.uuid));
      controlSelect.disabled = controls.length === 0;
      stateSelect.replaceChildren(new Option(label('selectState'), ''));
      $('history-state-search-status').textContent = '';
      status.textContent = data.more ? label('moreControls')
        : controls.length ? '' : label('noControls');
    } catch (error) {
      if (generation === discoveryGeneration) status.textContent = errorLabel(error);
    }
  };
  const loadStates = async () => {
    const generation = ++stateGeneration;
    const control = controlSelect.value;
    const status = $('history-state-search-status');
    stateSelect.replaceChildren(new Option(label('selectState'), ''));
    stateSelect.disabled = true;
    $('history-add').disabled = true;
    if (!control) { status.textContent = ''; return; }
    status.textContent = label('loading');
    try {
      const data = await api.request('event_history_discover_states',
        {control_uuid: control, query: stateSearch.value}, 45000);
      if (generation !== stateGeneration || control !== controlSelect.value) return;
      for (const state of data.states || []) stateSelect.add(new Option(
        `${state.name} · ${state.uuid}`, state.uuid));
      stateSelect.disabled = !data.states?.length;
      status.textContent = data.more ? label('moreStates') : '';
    } catch (error) {
      if (generation === stateGeneration) status.textContent = errorLabel(error);
    }
  };
  controlSelect.addEventListener('change', () => {
    ++stateGeneration;
    stateSearch.value = '';
    stateSearch.disabled = !controlSelect.value;
    $('history-state-search-button').disabled = !controlSelect.value;
    void loadStates();
  });
  stateSelect.addEventListener('change', () => {
    $('history-add').disabled = !stateSelect.value;
  });
  $('history-search-button').addEventListener('click', loadControls);
  $('history-state-search-button').addEventListener('click', loadStates);
  stateSearch.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') { event.preventDefault(); void loadStates(); }
  });
  $('history-search').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') { event.preventDefault(); void loadControls(); }
  });
  $('history-add-form').addEventListener('submit', (event) => {
    event.preventDefault();
    if (activeCount >= 64) { setMessage(label('sourceLimit'), 'warning'); return; }
    void mutate('event_history_add_source', {control_uuid: controlSelect.value,
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
  $('history-refresh').addEventListener('click', () => { void loadOverview(); void loadStatus(); });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) void loadStatus(); });
  window.setInterval(loadStatus, 30000);
  void loadOverview();
  void loadQuickSummary();
  void loadStatus();
})();
