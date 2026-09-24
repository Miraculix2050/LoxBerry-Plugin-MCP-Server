window.McpAdmin.createService = (core) => {
  const {label, postAjax} = core;
  const serviceSection = document.getElementById('status');
  const serviceState = document.getElementById('service-state');
  const serviceActiveState = document.getElementById('service-active-state');
  const serviceSubState = document.getElementById('service-sub-state');
  const servicePid = document.getElementById('service-pid');
  const serviceName = document.getElementById('service-name');
  const serviceInstalled = document.getElementById('service-installed');
  const serviceEnabled = document.getElementById('service-enabled');
  const serviceEnableForm = document.getElementById('service-enable-form');
  const serviceEnabledInput = document.getElementById('service-enabled-input');
  const serviceEnabledApplyButton = serviceEnableForm.querySelector('button[type="submit"]');
  const serviceEnabledSettingStatus = document.getElementById('service-enabled-setting-status');
  const emergencyStopRuntime = document.getElementById('emergency-stop-runtime');
  const emergencyStopRuntimeSignal = document.getElementById('emergency-stop-runtime-signal');
  const emergencyStopRuntimeUuid = document.getElementById('emergency-stop-runtime-uuid');
  const emergencyStopRuntimeState = document.getElementById('emergency-stop-runtime-state');
  const emergencyStopRuntimeMismatch = document.getElementById('emergency-stop-runtime-mismatch');
  const serviceConfirm = document.getElementById('service-confirm');
  const serviceConfirmMessage = document.getElementById('service-confirm-message');
  let pendingServiceForm = null;
  let serviceActionRunning = false;
  let servicePollInFlight = false;
  let servicePollTimer = null;
  let serviceEnabledSetting = serviceEnabledInput.checked;
  let serviceEnabledSettingLoaded = serviceEnableForm.dataset.serviceEnabledSettingKnown === '1';
  let serviceLoaded = false;
  const emergencyStopValue = document.getElementById('emergency-stop-value');
  let lastService = null;
  let lastEmergencyStopRuntime = null;
  const serviceInteractionActive = () => serviceActionRunning || pendingServiceForm !== null;
  const updateEmergencyStopRuntimeMismatch = () => {
    const runtime = lastEmergencyStopRuntime;
    emergencyStopRuntimeMismatch.hidden = !(
      runtime?.availability === 'available'
      && String(emergencyStopValue.value || '') !== String(runtime.signal_uuid || '')
    );
  };
  const renderEmergencyStopRuntime = (runtime) => {
    lastEmergencyStopRuntime = runtime && typeof runtime === 'object' ? runtime : null;
    const available = runtime?.availability === 'available';
    emergencyStopRuntime.setAttribute('aria-busy', 'false');
    if (!available) {
      const availability = runtime?.availability;
      emergencyStopRuntimeSignal.textContent = availability === 'service_inactive'
        ? emergencyStopRuntime.dataset.serviceInactive : emergencyStopRuntime.dataset.unavailable;
      emergencyStopRuntimeUuid.hidden = true;
      emergencyStopRuntimeState.textContent = 'unknown';
      emergencyStopRuntimeState.dataset.kind = 'inactive';
      updateEmergencyStopRuntimeMismatch();
      return;
    }
    const signalUuid = typeof runtime.signal_uuid === 'string' ? runtime.signal_uuid : '';
    const signalName = typeof runtime.signal_name === 'string' ? runtime.signal_name : '';
    const state = ['not_configured', 'clear', 'active', 'unknown'].includes(runtime.status)
      ? runtime.status : 'unknown';
    emergencyStopRuntimeSignal.textContent = state === 'not_configured'
      ? emergencyStopRuntime.dataset.notConfigured
      : signalName || signalUuid || emergencyStopRuntime.dataset.signalUnavailable;
    emergencyStopRuntimeUuid.textContent = signalUuid;
    emergencyStopRuntimeUuid.hidden = signalUuid === '';
    emergencyStopRuntimeState.textContent = state;
    emergencyStopRuntimeState.dataset.kind = ({clear: 'success', active: 'error', unknown: 'warning'})[state]
      || 'inactive';
    updateEmergencyStopRuntimeMismatch();
  };
  const renderService = (service, {updateEnabledSetting = false, emergencyStopRuntime: runtime} = {}) => {
    if (!service || typeof service !== 'object') return;
    lastService = service;
    serviceLoaded = true;
    const installed = Boolean(service.installed);
    const active = Boolean(service.active);
    const activeState = String(service.active_state || 'unknown');
    const subState = String(service.sub_state || 'unknown');
    const pid = Number.isInteger(service.pid) && service.pid > 0 ? String(service.pid) : '-';
    let label = serviceSection.dataset.stateUnknown;
    let kind = '';
    if (installed && active) {
      label = serviceSection.dataset.stateActive;
      kind = 'success';
    } else if (installed && activeState === 'failed') {
      label = serviceSection.dataset.stateFailed;
      kind = 'error';
    } else if (installed && ['inactive', 'activating', 'deactivating'].includes(activeState)) {
      label = serviceSection.dataset.stateInactive;
      kind = 'inactive';
    }
    serviceState.textContent = label;
    serviceState.dataset.kind = kind;
    serviceActiveState.textContent = activeState;
    serviceSubState.textContent = subState;
    servicePid.textContent = pid;
    serviceName.textContent = String(service.name || 'loxberry-mcpserver.service');
    serviceInstalled.textContent = installed ? serviceSection.dataset.yes : serviceSection.dataset.no;
    const enabled = Boolean(service.enabled);
    serviceEnabled.textContent = enabled ? serviceSection.dataset.yes : serviceSection.dataset.no;
    if (updateEnabledSetting || !serviceEnabledSettingLoaded) {
      serviceEnabledSetting = enabled;
      serviceEnabledSettingLoaded = true;
      serviceEnabledInput.checked = enabled;
    }
    serviceEnableForm.setAttribute('aria-busy', 'false');
    serviceEnabledSettingStatus.hidden = true;
    serviceEnabledInput.disabled = serviceActionRunning || !serviceEnabledSettingLoaded;
    serviceEnabledApplyButton.disabled = serviceActionRunning || !serviceEnabledSettingLoaded;
    if (serviceActionRunning) {
      serviceEnabledInput.setAttribute('aria-busy', 'true');
    } else {
      serviceEnabledInput.removeAttribute('aria-busy');
    }
    for (const form of document.querySelectorAll('form[data-service-command]')) {
      const command = form.dataset.serviceCommand;
      const visible = installed && (
        command === 'restart'
        || (command === 'start' && !active)
        || (command === 'stop' && active)
      );
      const commandReady = command === 'start' ? !active : active;
      const available = visible && commandReady && serviceEnabledSetting;
      form.hidden = !visible;
      const button = form.querySelector('button[type="submit"]');
      button.disabled = serviceActionRunning || !available;
      if (serviceActionRunning) button.setAttribute('aria-busy', 'true');
      else button.removeAttribute('aria-busy');
    }
    if (runtime !== undefined) renderEmergencyStopRuntime(runtime);
    else updateEmergencyStopRuntimeMismatch();
  };
  const serviceConfirmMessages = {
    stop: label('STATUS.CONFIRM_STOP'),
    disable: label('STATUS.CONFIRM_DISABLE'),
    restart: label('STATUS.CONFIRM_RESTART'),
  };
  serviceConfirm.addEventListener('close', () => {
    const form = pendingServiceForm;
    pendingServiceForm = null;
    if (serviceConfirm.returnValue !== 'confirm' || !form) {
      if (form?.dataset.ajax === 'set_service_enabled') {
        serviceEnabledInput.checked = serviceEnabledSetting;
      }
      scheduleServicePoll(0);
      return;
    }
    form.dataset.confirmed = 'true';
    form.requestSubmit();
  });
  const scheduleServicePoll = (delay = 10000) => {
    window.clearTimeout(servicePollTimer);
    servicePollTimer = null;
    if (!document.hidden && !serviceInteractionActive()) {
      servicePollTimer = window.setTimeout(pollServiceStatus, delay);
    }
  };
  const pollServiceStatus = async ({initial = false, suppliedResult} = {}) => {
    if ((!initial && document.hidden) || serviceInteractionActive() || servicePollInFlight) {
      scheduleServicePoll();
      return;
    }
    servicePollInFlight = true;
    try {
    const body = new URLSearchParams();
      body.set('action', 'service_status');
      body.set('ajax', '1');
      const result = await postAjax(body, 7000, suppliedResult);
      if (serviceInteractionActive()) return;
      renderService(result.data.service, {
        updateEnabledSetting: !serviceEnabledSettingLoaded,
        emergencyStopRuntime: result.data.emergency_stop_runtime,
      });
    } catch {
      if (core.unloading) return;
      if (!serviceLoaded) {
        serviceSection.setAttribute('aria-busy', 'false');
        serviceState.textContent = label('AJAX.ERROR');
        serviceState.dataset.kind = 'error';
        serviceActiveState.textContent = label('AJAX.ERROR');
        serviceSubState.textContent = label('AJAX.ERROR');
        serviceInstalled.textContent = label('AJAX.ERROR');
        serviceEnabled.textContent = label('AJAX.ERROR');
        serviceEnableForm.setAttribute('aria-busy', 'false');
        serviceEnabledSettingStatus.textContent = label('AJAX.ERROR');
        serviceEnabledSettingStatus.hidden = false;
      }
    } finally {
      servicePollInFlight = false;
      serviceSection.setAttribute('aria-busy', 'false');
      scheduleServicePoll();
    }
  };
  const confirmAction = (form) => {
    const command = form.dataset.serviceCommand;
    const key = form.dataset.ajax === 'set_service_enabled' && !serviceEnabledInput.checked
      ? 'disable' : command;
    if ((form.dataset.ajax === 'service_action' || form.dataset.ajax === 'set_service_enabled')
        && serviceConfirmMessages[key] && form.dataset.confirmed !== 'true') {
      pendingServiceForm = form;
      window.clearTimeout(servicePollTimer);
      servicePollTimer = null;
      serviceConfirmMessage.textContent = serviceConfirmMessages[key];
      serviceConfirm.returnValue = '';
      serviceConfirm.showModal();
      return false;
    }
    delete form.dataset.confirmed;
    return true;
  };
  const beginAction = () => {
    serviceActionRunning = true;
    window.clearTimeout(servicePollTimer);
    servicePollTimer = null;
    renderService(lastService);
  };
  const requestedEnabled = (form) => form.dataset.ajax === 'set_service_enabled'
    ? serviceEnabledInput.checked : null;
  const validateEnabledResult = (result, requested) => {
    if (requested === null) return;
    const value = result.data.service;
    if (!value || Boolean(value.enabled) !== requested || Boolean(value.active) !== requested) {
      throw new Error(label('STATUS.ERROR_ACTION'));
    }
  };
  const actionFailed = (form) => {
    if (form.dataset.ajax === 'set_service_enabled') {
      serviceEnabledInput.checked = serviceEnabledSetting;
    }
  };
  const finishAction = () => {
    serviceActionRunning = false;
    renderService(lastService);
    scheduleServicePoll(0);
  };
  const stopPoll = () => {
    window.clearTimeout(servicePollTimer);
    servicePollTimer = null;
  };
  return {pollServiceStatus, scheduleServicePoll, stopPoll, renderService,
    updateMismatch: updateEmergencyStopRuntimeMismatch, confirmAction,
    beginAction, requestedEnabled, validateEnabledResult, actionFailed, finishAction};
};
