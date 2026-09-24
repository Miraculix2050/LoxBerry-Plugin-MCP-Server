(() => {
  const core = window.McpAdmin.createCore();
  const {label, postAjax, setAjaxStatus, hideSuccess, status} = core;
  // The target runs each AJAX action in its own CGI helper. Serial hydration avoids
  // transient request failures during the resource-constrained initial page load.
  const backgroundHydrationLimit = 1;
  const backgroundHydrationQueue = [];
  let backgroundHydrationRunning = 0;
  let backgroundHydrationStarted = false;
  let initialBackgroundHydrationComplete = false;
  const drainBackgroundHydration = () => {
    while (backgroundHydrationRunning < backgroundHydrationLimit
        && backgroundHydrationQueue.length > 0) {
      const task = backgroundHydrationQueue.shift();
      backgroundHydrationRunning += 1;
      Promise.resolve()
        .then(task)
        .catch(() => undefined)
        .finally(() => {
          backgroundHydrationRunning -= 1;
          drainBackgroundHydration();
        });
    }
  };
  const queueBackgroundHydration = (tasks) => {
    backgroundHydrationQueue.push(...tasks);
    if (backgroundHydrationStarted) drainBackgroundHydration();
  };
  const startBackgroundHydration = () => {
    if (backgroundHydrationStarted) return;
    backgroundHydrationStarted = true;
    if (window.performance && typeof window.performance.mark === 'function') {
      window.performance.mark('mcp-admin-background-hydration-started');
    }
    queueBackgroundHydration([
      loadLoxberryNotifications,
      loadConfiguration,
      loadInitialState,
      () => pollServiceStatus({initial: true}),
      loadCertificateStatus,
      () => pollSessions({initial: true}),
      loadPluginLogList,
      () => { initialBackgroundHydrationComplete = true; },
    ]);
  };
  const scheduleBackgroundHydration = () => {
    if (document.hidden) {
      startBackgroundHydration();
      return;
    }
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(startBackgroundHydration);
    });
  };
  const certificate = window.McpAdmin.createCertificate(core, queueBackgroundHydration);
  const sessions = window.McpAdmin.createSessions(core);
  const service = window.McpAdmin.createService(core);
  const configuration = window.McpAdmin.createConfiguration(
    core, queueBackgroundHydration, certificate, service,
  );
  const {loadCertificateStatus} = certificate;
  const {pollSessions} = sessions;
  const {pollServiceStatus} = service;
  const {loadConfiguration, loadInitialState} = configuration;
  const {loadLoxberryNotifications, loadPluginLogList} = core;
  const accessSection = document.getElementById('access');
  const sessionsSection = document.getElementById('sessions');
  accessSection.addEventListener('toggle', () => {
    if (accessSection.open && initialBackgroundHydrationComplete) {
      queueBackgroundHydration([loadCertificateStatus]);
    }
  });
  sessionsSection.addEventListener('toggle', () => {
    if (sessionsSection.open && initialBackgroundHydrationComplete) {
      queueBackgroundHydration([() => pollSessions()]);
    }
  });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      service.stopPoll();
      sessions.stopPoll();
    } else {
      service.scheduleServicePoll(0);
      sessions.scheduleSessionPoll(0);
    }
  });
  scheduleBackgroundHydration();
  const actionTimeout = (action) => ({
    save_mcp_config: 90000,
    save_mqtt_config: 165000,
    set_service_enabled: 75000,
    set_logging: 75000,
    revoke_session: 75000,
    revoke_all: 75000,
    renew_certificate: 30000,
    service_action: 75000,
    service_status: 7000,
    list_sessions: 15000,
    clear_event_history: 30000,
  })[action] || 15000;
  document.addEventListener('submit', async (event) => {
    const form = event.target.closest('form[data-ajax]');
    if (!form) return;
    event.preventDefault();
    if (form.dataset.ajax === 'clear_event_history'
        && !window.confirm(label('STATUS.CONFIRM_CLEAR_EVENT_HISTORY'))) return;
    if (!service.confirmAction(form)) return;
    delete form.dataset.confirmed;
    const button = event.submitter || form.querySelector('button[type="submit"]');
    const submittedAction = form === configuration.mcpConfigForm ? button.value : form.dataset.ajax;
    const serviceAction = form.dataset.ajax === 'service_action'
      || form.dataset.ajax === 'set_service_enabled';
    let keepButtonDisabled = false;
    let sessionAction = null;
    if (serviceAction) service.beginAction();
    if (sessions.isSessionAction(form.dataset.ajax)) {
      sessionAction = sessions.beginAction(form, button);
      if (!sessionAction) return;
    }
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    if (!sessionAction || !sessions.hasFailures) {
      setAjaxStatus('', serviceAction ? label('STATUS.ACTION_RUNNING') : label('AJAX.WORKING'));
    }
    const body = new URLSearchParams(new FormData(form));
    if (form === configuration.mcpConfigForm) body.set('action', submittedAction);
    const requestedServiceEnabled = service.requestedEnabled(form);
    if (requestedServiceEnabled !== null) {
      body.set('service_enabled', requestedServiceEnabled ? '1' : '0');
    }
    body.set('ajax', '1');
    try {
      const result = await postAjax(body, actionTimeout(submittedAction));
      service.validateEnabledResult(result, requestedServiceEnabled);
      if (sessionAction && sessions.hasFailures) {
        sessions.showSessionActionFailure();
      } else {
        const cleanupFailed = form.dataset.ajax === 'save_mqtt_config'
          && result.data.retained_cleanup?.status === 'failed';
        setAjaxStatus(cleanupFailed ? 'warning' : 'success', cleanupFailed
          ? label('AJAX.MQTT_CLEANUP_WARNING') : label('AJAX.SUCCESS'));
        if (!cleanupFailed) hideSuccess(status, () => sessions.activeActions > 0);
      }
      if (result.data.service) {
        service.renderService(result.data.service, {
          updateEnabledSetting: form.dataset.ajax === 'set_service_enabled',
          emergencyStopRuntime: result.data.emergency_stop_runtime,
        });
      }
      if (sessionAction) sessions.actionSucceeded(form, sessionAction, result.data);
      if (result.data.certificate) certificate.updateCertificate(result.data.certificate);
      if (form.dataset.ajax === 'save_mqtt_config') configuration.onMqttSaved(result.data);
      if (submittedAction === 'save_mcp_config') configuration.onMcpSaved(result.data);
      if (form.dataset.ajax === 'set_logging') configuration.renderLogging(result.data.configuration);
      if (form.dataset.ajax === 'renew_certificate') {
        keepButtonDisabled = true;
        form.querySelector('input[name="securepin"]').value = '';
        certificate.onRenewScheduled(button);
      }
    } catch (error) {
      if (core.unloading) return;
      service.actionFailed(form);
      const errorMessage = error instanceof DOMException && error.name === 'AbortError'
        ? label('AJAX.TIMEOUT')
        : error instanceof TypeError
          ? label('AJAX.NETWORK')
          : error instanceof Error ? error.message : label('AJAX.ERROR');
      if (sessionAction) sessions.actionFailed(sessionAction, errorMessage);
      else setAjaxStatus('error', errorMessage);
    } finally {
      if (serviceAction) service.finishAction();
      if (sessionAction) sessions.finishAction(sessionAction);
      if (!keepButtonDisabled) {
        button.disabled = false;
        button.removeAttribute('aria-busy');
        if (sessionAction) sessions.updateSessionActionControls();
      }
    }
  });
})();
