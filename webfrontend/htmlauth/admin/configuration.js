window.McpAdmin.createConfiguration = (
  core, certificate, service,
) => {
  const {label, postAjax, setAjaxStatus, setSummaryBadge, status} = core;
  const updateEmergencyStopRuntimeMismatch = service.updateMismatch;
  const configurationFallbackLink = document.getElementById('configuration-fallback-link');
  const miniserverSelect = document.getElementById('miniserver-select');
  const manualEndpointFields = document.getElementById('manual-endpoint-fields');
  const miniserverEndpoint = document.getElementById('miniserver-endpoint');
  const mcpConfigForm = document.getElementById('mcp-config-form');
  const mqttConfigForm = document.querySelector('form[data-ajax="save_mqtt_config"]');
  const configurationFieldsets = [
    document.getElementById('mcp-config-fields'),
    document.getElementById('mqtt-config-fields'),
    document.getElementById('logging-config-fields'),
  ];
  const historyEnabled = document.getElementById('loxone-history-enabled');
  const eventHistoryEnabled = document.getElementById('event-history-enabled');
  const operateEnabled = document.getElementById('loxberry-operate-enabled');
  const explorerLink = document.getElementById('explorer-link');
  const explorerPath = '/admin/plugins/mcpserver/explorer.cgi';
  explorerLink.href = `${window.location.origin}${explorerPath}`;
  const configurationSummaryBadge = document.getElementById('configuration-summary-badge');
  const mqttSummaryBadge = document.getElementById('mqtt-summary-badge');
  const emergencyStopSelect = document.getElementById('emergency-stop-select');
  const emergencyStopValue = document.getElementById('emergency-stop-value');
  const emergencyStopStatus = document.getElementById('emergency-stop-status');
  const emergencyStopRetry = document.getElementById('emergency-stop-retry');
  const mqttUseLoxberryGateway = document.getElementById('mqtt-use-loxberry-gateway');
  const mqttHost = document.getElementById('mqtt-host');
  const mqttPort = document.getElementById('mqtt-port');
  const mqttUsername = document.getElementById('mqtt-username');
  const mqttPassword = document.getElementById('mqtt-password');
  const mqttClearPassword = document.getElementById('mqtt-clear-password');
  let mqttGateway = null;
  let mqttCustomBroker = {
    host: mqttHost.value,
    port: mqttPort.value,
    username: mqttUsername.value,
  };
  const mqttPasswordStatus = document.getElementById('mqtt-password-status');
  const mqttPageStateStatus = document.getElementById('mqtt-page-state-status');
  const loggingControls = document.getElementById('logging-controls');
  const loggingCurrent = document.getElementById('logging-current');
  const loggingLevel = document.getElementById('logging-level');
  let emergencyStopDiscoveryGeneration = 0;
  let configurationLoaded = false;
  let configurationLoadInFlight = false;
  let savedPublicOrigin = null;
  const renderLogging = (configuration) => {
    const configured = configuration && configuration.logging ? configuration.logging : {};
    const level = ['off', 'error', 'warning', 'info', 'debug'].includes(configured.level)
      ? configured.level : 'warning';
    loggingLevel.value = level;
    loggingCurrent.textContent = loggingControls.dataset[
      `level${level[0].toUpperCase()}${level.slice(1)}`
    ];
  };
  const setConfigurationFieldsDisabled = (disabled) => {
    for (const fieldset of configurationFieldsets) fieldset.disabled = disabled;
    mcpConfigForm.setAttribute('aria-busy', String(disabled));
    mqttConfigForm.setAttribute('aria-busy', String(disabled));
  };
  const setFormValue = (form, name, value) => {
    const field = form.elements.namedItem(name);
    if (field instanceof HTMLInputElement || field instanceof HTMLSelectElement) {
      field.value = String(value ?? '');
    }
  };
  const setFormChecked = (form, name, checked) => {
    const field = form.elements.namedItem(name);
    if (field instanceof HTMLInputElement) field.checked = Boolean(checked);
  };
  const renderConfigurationBadges = (configuration) => {
    const enabled = (value) => value === true
      ? [label('SUMMARY.ENABLED'), 'success']
      : value === false
        ? [label('SUMMARY.DISABLED'), 'inactive']
        : [label('SUMMARY.UNKNOWN'), ''];
    setSummaryBadge(configurationSummaryBadge, ...enabled(configuration?.server?.enabled));
    setSummaryBadge(mqttSummaryBadge, ...enabled(configuration?.mqtt?.enabled));
  };
  const renderConfiguration = (configuration) => {
    const server = configuration?.server || {};
    const loxone = configuration?.loxone || {};
    const tools = configuration?.tools || {};
    const limits = configuration?.limits || {};
    const cache = configuration?.cache || {};
    const mqtt = configuration?.mqtt || {};
    const emergencyStop = configuration?.emergency_stop || {};
    const eventHistory = configuration?.event_history || {};
    const publicOrigin = String(server.public_origin || '')
      || String(mcpConfigForm.elements.namedItem('public_origin')?.value || '');
    savedPublicOrigin = String(server.public_origin || '');
    renderConfigurationBadges(configuration);
    setFormValue(mcpConfigForm, 'public_origin', publicOrigin);
    setFormChecked(mcpConfigForm, 'enabled', server.enabled);
    setFormValue(mcpConfigForm, 'connection_timeout', loxone.connection_timeout);
    const endpoint = String(loxone.endpoint || miniserverEndpoint.value || '');
    miniserverEndpoint.value = endpoint;
    miniserverSelect.value = [...miniserverSelect.options].some((option) => option.value === endpoint)
      ? endpoint : '';
    setFormChecked(mcpConfigForm, 'loxone_history_enabled', tools.loxone_history_enabled);
    setFormChecked(mcpConfigForm, 'loxone_control_enabled', tools.loxone_control_enabled);
    setFormChecked(mcpConfigForm, 'loxberry_read_enabled', tools.loxberry_read_enabled);
    setFormChecked(mcpConfigForm, 'loxberry_operate_enabled', tools.loxberry_operate_enabled);
    for (const name of [
      'requests_per_minute', 'control_requests_per_minute', 'loxberry_requests_per_minute',
      'history_requests_per_minute', 'loxberry_operate_requests_per_minute',
      'explorer_binding_retention_hours', 'max_parallel_calls',
      'structure_refresh_seconds', 'max_active_runtime_sessions', 'runtime_session_idle_seconds',
      'miniserver_auth_probe_initial_seconds', 'miniserver_auth_probe_max_seconds',
      'max_structure_controls', 'max_structure_state_references', 'max_structure_depth',
      'max_states_per_identity',
    ]) setFormValue(mcpConfigForm, name, limits[name]);
    setFormValue(mcpConfigForm, 'statistics_memory_max_mib', cache.statistics_memory_max_mib);
    setFormChecked(mcpConfigForm, 'event_history_enabled', eventHistory.enabled);
    setFormValue(mcpConfigForm, 'event_history_retention_days', eventHistory.retention_days);
    setFormValue(mcpConfigForm, 'event_history_maximum_mib', eventHistory.maximum_mib);
    document.getElementById('event-history-sources').value = JSON.stringify(eventHistory.sources || []);
    emergencyStopValue.value = String(emergencyStop.virtual_status_uuid || '');
    updateEmergencyStopRuntimeMismatch();
    setFormChecked(mqttConfigForm, 'mqtt_enabled', mqtt.enabled);
    setFormChecked(mqttConfigForm, 'mqtt_use_loxberry_gateway', mqtt.use_loxberry_gateway);
    setFormValue(mqttConfigForm, 'mqtt_host', mqtt.host);
    setFormValue(mqttConfigForm, 'mqtt_port', mqtt.port);
    setFormValue(mqttConfigForm, 'mqtt_username', mqtt.username);
    setFormValue(mqttConfigForm, 'mqtt_root_topic', mqtt.root_topic);
    setFormValue(mqttConfigForm, 'mqtt_heartbeat_seconds', mqtt.heartbeat_seconds);
    mqttCustomBroker = {host: mqttHost.value, port: mqttPort.value, username: mqttUsername.value};
    syncMiniserverSelection();
    syncOperateDependency();
    resetEmergencyStopOptions();
    void loadCachedEmergencyStopOptions(emergencyStopDiscoveryGeneration);
    updateMqttBrokerFields();
    renderLogging(configuration);
  };
  const loadConfiguration = async (suppliedResult) => {
    if (configurationLoaded || configurationLoadInFlight) return;
    configurationLoadInFlight = true;
    setAjaxStatus('', label('AJAX.WORKING'));
    try {
      const body = new URLSearchParams();
      body.set('action', 'get_config');
      body.set('ajax', '1');
      const result = await postAjax(body, 7000, suppliedResult);
      renderConfiguration(result.data.configuration);
      configurationLoaded = true;
      setConfigurationFieldsDisabled(false);
      configurationFallbackLink.hidden = true;
      status.hidden = true;
    } catch {
      if (core.unloading) return;
      renderConfigurationBadges(null);
      setAjaxStatus('error', label('AJAX.ERROR'));
      configurationFallbackLink.hidden = false;
    } finally {
      configurationLoadInFlight = false;
    }
  };
  const updateMqttGateway = (gateway) => {
    mqttGateway = gateway?.gateway_configured ? gateway : null;
    updateMqttBrokerFields();
  };
  const updateMqttBrokerFields = () => {
    const useGateway = mqttUseLoxberryGateway.checked;
    if (useGateway && !mqttHost.disabled) {
      mqttCustomBroker = {
        host: mqttHost.value,
        port: mqttPort.value,
        username: mqttUsername.value,
      };
    }
    if (useGateway && mqttGateway) {
      mqttHost.value = String(mqttGateway.host || '');
      mqttPort.value = String(mqttGateway.port || '');
      mqttUsername.value = String(mqttGateway.username || '');
      mqttPassword.value = '';
    } else if (!useGateway) {
      mqttHost.value = mqttCustomBroker.host;
      mqttPort.value = mqttCustomBroker.port;
      mqttUsername.value = mqttCustomBroker.username;
    }
    for (const field of [mqttHost, mqttPort, mqttUsername, mqttPassword, mqttClearPassword]) {
      field.disabled = useGateway;
    }
  };
  const syncOperateDependency = () => {
    operateEnabled.disabled = !historyEnabled.checked;
    if (operateEnabled.disabled) operateEnabled.checked = false;
    eventHistoryEnabled.disabled = !historyEnabled.checked;
    if (eventHistoryEnabled.disabled) eventHistoryEnabled.checked = false;
  };
  const syncMiniserverSelection = () => {
    const selectedEndpoint = miniserverSelect.value;
    if (selectedEndpoint) miniserverEndpoint.value = selectedEndpoint;
    miniserverEndpoint.readOnly = Boolean(selectedEndpoint);
    miniserverEndpoint.required = !selectedEndpoint;
    manualEndpointFields.hidden = Boolean(selectedEndpoint);
  };
  miniserverSelect.addEventListener('change', syncMiniserverSelection);
  historyEnabled.addEventListener('change', syncOperateDependency);
  syncMiniserverSelection();
  syncOperateDependency();
  const addEmergencyStopOption = (value, label, selected = false) => {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = label;
    option.selected = selected;
    emergencyStopSelect.append(option);
  };
  const resetEmergencyStopOptions = () => {
    emergencyStopDiscoveryGeneration += 1;
    const selectedValue = emergencyStopValue.value;
    emergencyStopSelect.replaceChildren();
    emergencyStopSelect.disabled = false;
    emergencyStopSelect.setAttribute('aria-busy', 'false');
    addEmergencyStopOption('', label('SETUP.EMERGENCY_STOP_NONE'), selectedValue === '');
    if (selectedValue !== '') {
      addEmergencyStopOption(
        selectedValue,
        label('SETUP.EMERGENCY_STOP_SELECTED') + ' (' + selectedValue + ')',
        true,
      );
    }
    emergencyStopStatus.hidden = true;
    emergencyStopRetry.dataset.retry = 'false';
    emergencyStopRetry.textContent = label('SETUP.EMERGENCY_STOP_LOAD');
    emergencyStopRetry.hidden = false;
    emergencyStopRetry.disabled = false;
  };
  const renderEmergencyStopOptions = (options, selectedValue) => {
    emergencyStopSelect.replaceChildren();
    addEmergencyStopOption('', label('SETUP.EMERGENCY_STOP_NONE'), selectedValue === '');
    let selectedAvailable = selectedValue === '';
    for (const option of options) {
      if (!option || typeof option.uuid !== 'string' || typeof option.name !== 'string') continue;
      const selected = option.uuid === selectedValue;
      addEmergencyStopOption(option.uuid, option.name, selected);
      selectedAvailable = selectedAvailable || selected;
    }
    if (!selectedAvailable) {
      addEmergencyStopOption(
        selectedValue,
        label('SETUP.EMERGENCY_STOP_CURRENT') + ' (' + selectedValue + ')',
        true,
      );
    }
  };
  const loadCachedEmergencyStopOptions = async (generation) => {
    const body = new URLSearchParams();
    body.set('action', 'emergency_stop_cached_options');
    body.set('ajax', '1');
    try {
      const result = await postAjax(body, 15000);
      if (generation !== emergencyStopDiscoveryGeneration) return;
      if (result.data.status === 'available') {
        const options = Array.isArray(result.data.options) ? result.data.options : [];
        renderEmergencyStopOptions(options, emergencyStopValue.value);
        emergencyStopStatus.textContent = result.data.stale
          ? label('SETUP.EMERGENCY_STOP_STALE')
          : options.length
            ? label('SETUP.EMERGENCY_STOP_CACHED')
            : label('SETUP.EMERGENCY_STOP_NO_OPTIONS');
        emergencyStopStatus.dataset.kind = 'info';
        emergencyStopStatus.hidden = false;
        emergencyStopRetry.textContent = label('SETUP.EMERGENCY_STOP_REFRESH');
      } else {
        emergencyStopStatus.textContent = result.data.status === 'not_configured'
          ? label('SETUP.EMERGENCY_STOP_NOT_CONFIGURED')
          : label('SETUP.EMERGENCY_STOP_NOT_LOADED');
        emergencyStopStatus.dataset.kind = 'info';
        emergencyStopStatus.hidden = false;
      }
    } catch {
      if (core.unloading || generation !== emergencyStopDiscoveryGeneration) return;
      emergencyStopStatus.textContent = label('SETUP.EMERGENCY_STOP_LOAD_ERROR');
      emergencyStopStatus.dataset.kind = 'error';
      emergencyStopStatus.hidden = false;
    }
  };
  const loadEmergencyStopOptions = async (
    expectedGeneration = emergencyStopDiscoveryGeneration, manualRetry = false,
  ) => {
    if (expectedGeneration !== emergencyStopDiscoveryGeneration) return;
    const generation = ++emergencyStopDiscoveryGeneration;
    const selectedValue = emergencyStopValue.value;
    const body = new URLSearchParams();
    body.set('action', manualRetry ? 'emergency_stop_retry' : 'emergency_stop_options');
    body.set('ajax', '1');
    emergencyStopSelect.disabled = true;
    emergencyStopSelect.setAttribute('aria-busy', 'true');
    emergencyStopStatus.textContent = label('SETUP.EMERGENCY_STOP_LOADING');
    emergencyStopStatus.dataset.kind = 'info';
    emergencyStopStatus.hidden = false;
    emergencyStopRetry.hidden = true;
    emergencyStopRetry.disabled = true;
    try {
      const result = await postAjax(body, 180000);
      if (generation !== emergencyStopDiscoveryGeneration) return;
      const options = Array.isArray(result.data.options) ? result.data.options : [];
      const status = result.data.status;
      renderEmergencyStopOptions(options, selectedValue);
      if (status === 'available' && options.length === 0) {
        emergencyStopStatus.textContent = label('SETUP.EMERGENCY_STOP_NO_OPTIONS');
        emergencyStopStatus.dataset.kind = 'info';
        emergencyStopStatus.hidden = false;
      } else if (status !== 'available') {
        emergencyStopStatus.textContent = status === 'not_configured'
          ? label('SETUP.EMERGENCY_STOP_NOT_CONFIGURED')
          : result.data.failure_text || label('SETUP.EMERGENCY_STOP_LOAD_ERROR');
        if (result.data.stale) {
          emergencyStopStatus.textContent += ' ' + label('SETUP.EMERGENCY_STOP_STALE');
        }
        emergencyStopStatus.dataset.kind = 'error';
        emergencyStopStatus.hidden = false;
        emergencyStopRetry.dataset.retry = 'true';
        emergencyStopRetry.textContent = label('SETUP.EMERGENCY_STOP_RETRY');
        emergencyStopRetry.hidden = false;
        emergencyStopRetry.disabled = false;
        if (result.data.status === 'unavailable'
            && Number.isInteger(result.data.retry_not_before)) {
          const retryAt = result.data.retry_not_before * 1000;
          emergencyStopStatus.textContent += ' ' + new Date(retryAt).toLocaleString();
          const enableRetry = () => {
            if (generation !== emergencyStopDiscoveryGeneration) return;
            emergencyStopRetry.disabled = Date.now() < retryAt;
          };
          enableRetry();
          window.setTimeout(enableRetry, Math.max(0, retryAt - Date.now()));
        }
      } else {
        emergencyStopStatus.hidden = true;
      }
      if (status === 'available') {
        emergencyStopRetry.dataset.retry = 'false';
        emergencyStopRetry.textContent = label('SETUP.EMERGENCY_STOP_REFRESH');
        emergencyStopRetry.hidden = false;
        emergencyStopRetry.disabled = false;
      }
    } catch {
      if (core.unloading) return;
      if (generation !== emergencyStopDiscoveryGeneration) return;
      emergencyStopStatus.textContent = label('SETUP.EMERGENCY_STOP_LOAD_ERROR');
      emergencyStopStatus.dataset.kind = 'error';
      emergencyStopStatus.hidden = false;
      emergencyStopRetry.dataset.retry = 'true';
      emergencyStopRetry.textContent = label('SETUP.EMERGENCY_STOP_RETRY');
      emergencyStopRetry.hidden = false;
      emergencyStopRetry.disabled = false;
    } finally {
      if (generation !== emergencyStopDiscoveryGeneration) return;
      emergencyStopSelect.disabled = false;
      emergencyStopSelect.setAttribute('aria-busy', 'false');
    }
  };
  emergencyStopSelect.addEventListener('change', () => {
    emergencyStopValue.value = emergencyStopSelect.value;
    updateEmergencyStopRuntimeMismatch();
  });
  emergencyStopRetry.addEventListener('click', () => {
    if (!emergencyStopRetry.disabled) {
      loadEmergencyStopOptions(
        emergencyStopDiscoveryGeneration, emergencyStopRetry.dataset.retry === 'true',
      );
    }
  });
  const loadInitialState = async (suppliedResult) => {
    const body = new URLSearchParams();
    body.set('action', 'page_state');
    body.set('ajax', '1');
    mqttPageStateStatus.textContent = label('AJAX.WORKING');
    mqttPageStateStatus.dataset.kind = 'info';
    mqttPageStateStatus.hidden = false;
    try {
      const result = await postAjax(body, 15000, suppliedResult);
      mqttPasswordStatus.hidden = !Boolean(result.data.mqtt_password_configured);
      updateMqttGateway(result.data.mqtt_gateway);
      updateMqttBrokerFields();
      mqttPageStateStatus.hidden = true;
    } catch {
      if (core.unloading) return;
      mqttPageStateStatus.textContent = label('AJAX.ERROR');
      mqttPageStateStatus.dataset.kind = 'error';
    }
  };
  for (const field of [mqttHost, mqttPort, mqttUsername]) {
    field.addEventListener('input', () => {
      if (!mqttUseLoxberryGateway.checked) {
        mqttCustomBroker = {
          host: mqttHost.value,
          port: mqttPort.value,
          username: mqttUsername.value,
        };
      }
    });
  }
  mqttUseLoxberryGateway.addEventListener('change', updateMqttBrokerFields);
  updateMqttBrokerFields();
  const onMcpSaved = (data) => {
    const nextPublicOrigin = String(data.configuration.server.public_origin || '');
    if (savedPublicOrigin !== nextPublicOrigin) certificate.refreshAfterOriginChange();
    savedPublicOrigin = nextPublicOrigin;
    renderConfigurationBadges(data.configuration);
    const savedEndpoint = data.configuration.loxone.endpoint;
    emergencyStopValue.value = data.configuration.emergency_stop.virtual_status_uuid;
    resetEmergencyStopOptions();
    void loadCachedEmergencyStopOptions(emergencyStopDiscoveryGeneration);
    service.scheduleServicePoll(0);
    miniserverEndpoint.value = savedEndpoint;
    explorerLink.href = `${window.location.origin}${explorerPath}`;
  };
  const onMqttSaved = (data) => {
    mqttPassword.value = '';
    mqttClearPassword.checked = false;
    mqttPasswordStatus.hidden = !Boolean(data.mqtt_password_configured);
    renderConfigurationBadges(data.configuration);
  };
  return {mcpConfigForm, loadConfiguration, loadInitialState,
    onMcpSaved, onMqttSaved, renderLogging, renderConfigurationBadges};
};
