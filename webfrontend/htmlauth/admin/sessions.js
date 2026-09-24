window.McpAdmin.createSessions = (core) => {
  const {label, postAjax, setSummaryBadge, setAjaxStatus, updateExpiry} = core;
  const sessionsSummaryBadge = document.getElementById('sessions-summary-badge');
  const approvalsSummaryBadge = document.getElementById('approvals-summary-badge');
  const sessionsSection = document.getElementById('sessions');
  const sessionList = document.getElementById('session-list');
  const sessionTableTemplate = document.getElementById('session-table-template');
  const loxberryBindingSection = document.getElementById('loxberry-binding-section');
  const loxberryBindingList = document.getElementById('loxberry-binding-list');
  const loxberryOperateBindingSection = document.getElementById('loxberry-operate-binding-section');
  const loxberryOperateBindingList = document.getElementById('loxberry-operate-binding-list');
  const remoteCleanupWarning = document.getElementById('remote-cleanup-warning');
  let sessionDataVersion = 0;
  let sessionsLoaded = false;
  let nextSessionActionToken = 0;
  const activeSessionActions = new Map();
  const sessionActionFailures = new Map();
  let sessionPollInFlight = false;
  let sessionPollTimer = null;
  const renderRemoteCleanup = (status) => {
    if (!status || status.available !== true) {
      remoteCleanupWarning.textContent = remoteCleanupWarning.dataset.unavailableLabel;
      remoteCleanupWarning.hidden = false;
      return;
    }
    const notices = [];
    if (status.breaker_state === 'open_source_ip_blocked') {
      notices.push(remoteCleanupWarning.dataset.breakerLabel);
    }
    if (Number.isInteger(status.pending) && status.pending > 0) {
      notices.push(remoteCleanupWarning.dataset.pendingLabel + ' ' + status.pending);
      if (Number.isInteger(status.retryable) && status.retryable > 0) {
        notices.push(remoteCleanupWarning.dataset.retryableLabel + ' ' + status.retryable);
      }
    }
    if (Number.isInteger(status.unconfirmed) && status.unconfirmed > 0) {
      notices.push(remoteCleanupWarning.dataset.unconfirmedLabel + ' ' + status.unconfirmed);
    }
    if (notices.length && Number.isInteger(status.last_failure_at)) {
      const labels = {
        authentication_rejected: remoteCleanupWarning.dataset.rejectedLabel,
        source_ip_blocked: remoteCleanupWarning.dataset.blockedLabel,
        transport_failed: remoteCleanupWarning.dataset.transportLabel,
        command_rejected: remoteCleanupWarning.dataset.commandLabel,
      };
      const category = labels[status.last_failure_category];
      if (category) {
        notices.push(remoteCleanupWarning.dataset.failureLabel + ' ' + category + ', '
          + new Date(status.last_failure_at * 1000).toLocaleString());
      }
    }
    remoteCleanupWarning.textContent = notices.join(' ');
    remoteCleanupWarning.hidden = notices.length === 0;
  };
  const sessionFingerprint = (session) => JSON.stringify([
    session.client_name || '', session.client || '', session.identity || '',
    session.scopes || '', String(session.expires_at ?? ''),
    Boolean(session.loxberry_read_eligible), Boolean(session.loxberry_read_approved),
    Boolean(session.loxberry_operate_eligible), Boolean(session.loxberry_operate_approved),
    Boolean(session.loxone_token_confirmation_required),
  ]);
  const createSessionRow = (session) => {
    const row = document.createElement('tr');
    row.dataset.sessionId = String(session.id);
    row.dataset.fingerprint = sessionFingerprint(session);
    const values = [session.client_name || sessionsSection.dataset.unnamedLabel, session.client, session.identity];
    const labels = [
      label('SESSIONS.CLIENT'),
      label('SESSIONS.INSTANCE'),
      label('SESSIONS.IDENTITY'),
    ];
    values.forEach((value, index) => {
      const cell = document.createElement('td');
      cell.dataset.label = labels[index];
      const content = index === 0 ? document.createTextNode(String(value ?? '')) : document.createElement('code');
      if (index !== 0) content.textContent = String(value ?? '');
      cell.append(content);
      row.append(cell);
    });
    const tokenCell = document.createElement('td');
    tokenCell.dataset.label = label('SESSIONS.TOKEN');
    tokenCell.dataset.sessionTokenState = '';
    tokenCell.textContent = session.loxone_token_confirmation_required
      ? label('SESSIONS.TOKEN_CONFIRMATION_REQUIRED')
      : label('SESSIONS.TOKEN_ACTIVE');
    row.append(tokenCell);
    const scopesCell = document.createElement('td');
    scopesCell.dataset.label = label('SESSIONS.SCOPES');
    const scopes = document.createElement('code');
    scopes.textContent = String(session.scopes || '');
    scopesCell.append(scopes);
    row.append(scopesCell);
    const expiryCell = document.createElement('td');
    expiryCell.dataset.label = label('SESSIONS.EXPIRES');
    const expiry = document.createElement('time');
    expiry.className = 'mcp-expiry';
    updateExpiry(expiry, session.expires_at);
    expiryCell.append(expiry);
    row.append(expiryCell);
    const actionCell = document.createElement('td');
    actionCell.dataset.label = label('SESSIONS.ACTION');
    if (session.loxone_token_confirmation_required) {
      const confirmForm = document.createElement('form');
      confirmForm.method = 'post';
      confirmForm.action = 'index.cgi';
      confirmForm.dataset.ajax = 'confirm_loxone_token';
      for (const [name, value] of [['action', 'confirm_loxone_token'], ['session_id', session.id]]) {
        const input = document.createElement('input');
        input.type = 'hidden';
        input.name = name;
        input.value = String(value || '');
        confirmForm.append(input);
      }
      const confirmButton = document.createElement('button');
      confirmButton.className = 'lb-button';
      confirmButton.type = 'submit';
      confirmButton.textContent = label('ACTION.CONFIRM_LOXONE_TOKEN');
      confirmForm.append(confirmButton);
      actionCell.append(confirmForm);
    }
    if (session.loxberry_read_eligible && !session.loxberry_read_approved) {
      const allowForm = document.createElement('form');
      allowForm.method = 'post';
      allowForm.action = 'index.cgi';
      allowForm.dataset.ajax = 'allow_loxberry_read';
      const allowAction = document.createElement('input');
      allowAction.type = 'hidden';
      allowAction.name = 'action';
      allowAction.value = 'allow_loxberry_read';
      const allowId = document.createElement('input');
      allowId.type = 'hidden';
      allowId.name = 'session_id';
      allowId.value = String(session.id);
      const allowButton = document.createElement('button');
      allowButton.className = 'lb-button';
      allowButton.type = 'submit';
      allowButton.textContent = label('ACTION.ALLOW_LOXBERRY_READ');
      allowForm.append(allowAction, allowId, allowButton);
      actionCell.append(allowForm);
    }
    if (session.loxberry_operate_eligible && !session.loxberry_operate_approved) {
      const allowForm = document.createElement('form');
      allowForm.method = 'post';
      allowForm.action = 'index.cgi';
      allowForm.dataset.ajax = 'allow_loxberry_operate';
      const allowAction = document.createElement('input');
      allowAction.type = 'hidden';
      allowAction.name = 'action';
      allowAction.value = 'allow_loxberry_operate';
      const allowId = document.createElement('input');
      allowId.type = 'hidden';
      allowId.name = 'session_id';
      allowId.value = String(session.id);
      const allowButton = document.createElement('button');
      allowButton.className = 'lb-button';
      allowButton.type = 'submit';
      allowButton.textContent = label('ACTION.ALLOW_LOXBERRY_OPERATE');
      allowForm.append(allowAction, allowId, allowButton);
      actionCell.append(allowForm);
    }
    const revokeForm = document.createElement('form');
    revokeForm.method = 'post';
    revokeForm.action = 'index.cgi';
    revokeForm.dataset.ajax = 'revoke_session';
    const action = document.createElement('input');
    action.type = 'hidden';
    action.name = 'action';
    action.value = 'revoke_session';
    const id = document.createElement('input');
    id.type = 'hidden';
    id.name = 'id';
    id.value = String(session.id);
    const button = document.createElement('button');
    button.className = 'lb-button';
    button.type = 'submit';
    button.textContent = label('ACTION.REVOKE');
    revokeForm.append(action, id, button);
    actionCell.append(revokeForm);
    row.append(actionCell);
    return row;
  };
  const updateSessionSummaryBadges = () => {
    const sessionCount = sessionList.querySelectorAll('tr[data-session-id]').length;
    const approvalCount = sessionList.querySelectorAll(
      'tr[data-session-id] form[data-ajax="confirm_loxone_token"], '
      + 'tr[data-session-id] form[data-ajax="allow_loxberry_read"], '
      + 'tr[data-session-id] form[data-ajax="allow_loxberry_operate"]',
    ).length;
    setSummaryBadge(sessionsSummaryBadge,
      `${label('SUMMARY.SESSIONS')}: ${sessionCount}`);
    approvalsSummaryBadge.hidden = approvalCount === 0;
    if (approvalCount > 0) {
      setSummaryBadge(approvalsSummaryBadge,
        `${label('SUMMARY.APPROVALS')}: ${approvalCount}`, 'error');
    }
  };
  const updateSessions = (sessions) => {
    if (!sessions.length) {
      const empty = document.createElement('p');
      empty.textContent = sessionsSection.dataset.emptyLabel;
      sessionList.replaceChildren(empty);
      updateSessionSummaryBadges();
      return;
    }
    let body = sessionList.querySelector('tbody');
    if (!body) {
      const fragment = sessionTableTemplate.content.cloneNode(true);
      sessionList.replaceChildren(fragment);
      body = sessionList.querySelector('tbody');
    }
    const existing = new Map([...body.querySelectorAll('tr[data-session-id]')]
      .map((row) => [row.dataset.sessionId, row]));
    for (const session of sessions) {
      const key = String(session.id);
      let row = existing.get(key);
      if (!row || row.dataset.fingerprint !== sessionFingerprint(session)) {
        const replacement = createSessionRow(session);
        if (row) row.replaceWith(replacement);
        row = replacement;
      }
      body.append(row);
      existing.delete(key);
    }
    for (const row of existing.values()) row.remove();
    updateSessionSummaryBadges();
  };
  const loxberryBindingRows = (bindings, section, actionName) => {
    const rows = [];
    for (const binding of bindings) {
      const related = Array.isArray(binding.rows) ? binding.rows : [];
      for (const bindingRow of related) {
        const row = document.createElement('tr');
        row.dataset.bindingId = String(bindingRow.binding_id || '');
        const clientName = document.createElement('td');
        clientName.dataset.label = label('SESSIONS.CLIENT');
        clientName.textContent = bindingRow.inactive
          ? (bindingRow.inactive_login_required
            ? label('SESSIONS.INACTIVE_LOGIN_REQUIRED')
            : label('SESSIONS.LEGACY_INACTIVE'))
          : String(bindingRow.client_name || section.dataset.unnamedLabel);
        if (bindingRow.inactive && bindingRow.retention_expires_at) {
          const expiry = document.createElement('div');
          expiry.className = 'mcp-help';
          expiry.textContent = label('SESSIONS.REMOVAL_SCHEDULED') + ' '
            + new Date(Number(bindingRow.retention_expires_at) * 1000).toLocaleString();
          clientName.append(expiry);
        }
        const client = document.createElement('td');
        client.dataset.label = label('SESSIONS.INSTANCE');
        const clientCode = document.createElement('code');
        clientCode.textContent = String(bindingRow.client || '');
        client.append(clientCode);
        const identity = document.createElement('td');
        identity.dataset.label = label('SESSIONS.IDENTITY');
        if (bindingRow.inactive) identity.textContent = section.dataset.noIdentityLabel;
        else {
          const identityCode = document.createElement('code');
          identityCode.textContent = String(bindingRow.identity || '');
          identity.append(identityCode);
        }
        const fingerprint = document.createElement('td');
        fingerprint.dataset.label = label('SESSIONS.BINDING_ID');
        const fingerprintCode = document.createElement('code');
        fingerprintCode.textContent = String(bindingRow.fingerprint || '');
        fingerprint.append(fingerprintCode);
        const actionCell = document.createElement('td');
        actionCell.dataset.label = label('SESSIONS.ACTION');
        const revokeForm = document.createElement('form');
        revokeForm.method = 'post';
        revokeForm.action = 'index.cgi';
        revokeForm.dataset.ajax = actionName;
        for (const [name, value] of [['action', actionName], ['binding_id', bindingRow.binding_id]]) {
          const input = document.createElement('input');
          input.type = 'hidden';
          input.name = name;
          input.value = String(value || '');
          revokeForm.append(input);
        }
        const button = document.createElement('button');
        button.className = 'lb-button';
        button.type = 'submit';
        button.textContent = label('ACTION.REVOKE');
        revokeForm.append(button);
        actionCell.append(revokeForm);
        row.append(clientName, client, identity, fingerprint, actionCell);
        rows.push(row);
      }
    }
    return rows;
  };
  const updateLoxberryBindingTable = (bindings, section, body, actionName) => {
    const rows = loxberryBindingRows(bindings, section, actionName);
    section.hidden = rows.length === 0;
    body.replaceChildren(...rows);
  };
  const mergeLoxberryBindingTable = (bindings, section, body, actionName) => {
    const rows = loxberryBindingRows(bindings, section, actionName);
    const bindingIds = new Set(rows.map((row) => row.dataset.bindingId));
    for (const row of [...body.querySelectorAll('tr[data-binding-id]')]) {
      if (bindingIds.has(row.dataset.bindingId)) row.remove();
    }
    body.append(...rows);
    section.hidden = !body.querySelector('tr');
  };
  const updateLoxberryBindings = (bindings) => {
    updateLoxberryBindingTable(
      bindings, loxberryBindingSection, loxberryBindingList, 'revoke_loxberry_read',
    );
  };
  const updateLoxberryOperateBindings = (bindings) => {
    updateLoxberryBindingTable(
      bindings, loxberryOperateBindingSection, loxberryOperateBindingList,
      'revoke_loxberry_operate',
    );
  };
  const mergeLoxberryBindings = (bindings) => {
    mergeLoxberryBindingTable(
      bindings, loxberryBindingSection, loxberryBindingList, 'revoke_loxberry_read',
    );
  };
  const mergeLoxberryOperateBindings = (bindings) => {
    mergeLoxberryBindingTable(
      bindings, loxberryOperateBindingSection, loxberryOperateBindingList,
      'revoke_loxberry_operate',
    );
  };
  // session-action-coordinator-start
  const sessionActionTypes = new Set([
    'revoke_session', 'revoke_all', 'confirm_loxone_token', 'allow_loxberry_read',
    'revoke_loxberry_read', 'allow_loxberry_operate', 'revoke_loxberry_operate',
  ]);
  const isSessionAction = (action) => sessionActionTypes.has(action);
  const sessionActionKey = (action, sessionId = '', bindingId = '') => {
    if (action === 'revoke_all') return 'global:revoke_all';
    if (action === 'revoke_session' || action === 'confirm_loxone_token'
        || action === 'allow_loxberry_read' || action === 'allow_loxberry_operate') {
      return `session:${action}:${sessionId}`;
    }
    return `binding:${bindingId}`;
  };
  const sessionActionsConflict = (left, right) => {
    if (left.action === 'revoke_all' || right.action === 'revoke_all') return true;
    if (left.key === right.key) return true;
    const leftIsBindingRevocation = left.action === 'revoke_loxberry_read'
      || left.action === 'revoke_loxberry_operate';
    const rightIsBindingRevocation = right.action === 'revoke_loxberry_read'
      || right.action === 'revoke_loxberry_operate';
    if (leftIsBindingRevocation !== rightIsBindingRevocation) return true;
    return left.sessionId !== '' && left.sessionId === right.sessionId
      && (left.action === 'revoke_session' || right.action === 'revoke_session');
  };
  const sessionActionDescriptor = (form) => {
    const action = form.dataset.ajax || '';
    if (!isSessionAction(action)) return null;
    const sessionId = action === 'revoke_session'
      ? form.querySelector('input[name="id"]')?.value || ''
      : form.querySelector('input[name="session_id"]')?.value || '';
    const bindingId = form.querySelector('input[name="binding_id"]')?.value || '';
    return {action, sessionId, bindingId, key: sessionActionKey(action, sessionId, bindingId)};
  };
  const beginSessionAction = (descriptor, button) => {
    if ([...activeSessionActions.values()].some(({descriptor: active}) => (
      sessionActionsConflict(descriptor, active)
    ))) return null;
    if (activeSessionActions.size === 0) sessionActionFailures.clear();
    const token = `session-action-${++nextSessionActionToken}`;
    activeSessionActions.set(token, {descriptor, button});
    sessionDataVersion += 1;
    return token;
  };
  const showSessionActionFailure = () => {
    const failures = [...sessionActionFailures.values()];
    const failure = failures[failures.length - 1];
    if (failure) setAjaxStatus('error', failure);
  };
  const finishSessionAction = (token) => {
    activeSessionActions.delete(token);
    return activeSessionActions.size === 0;
  };
  const updateSessionActionControls = () => {
    for (const form of document.querySelectorAll('form[data-ajax]')) {
      const descriptor = sessionActionDescriptor(form);
      if (!descriptor) continue;
      const button = form.querySelector('button[type="submit"]');
      if (!button) continue;
      const active = [...activeSessionActions.values()];
      const ownAction = active.some((entry) => entry.button === button);
      button.disabled = active.some((entry) => sessionActionsConflict(descriptor, entry.descriptor));
      if (ownAction) button.setAttribute('aria-busy', 'true');
      else button.removeAttribute('aria-busy');
      if (descriptor.action === 'revoke_session' || descriptor.action === 'revoke_loxberry_read'
          || descriptor.action === 'revoke_loxberry_operate') {
        const sameBindingRevocation = descriptor.bindingId && active.some(({descriptor: pending}) => (
          pending.action === descriptor.action && pending.bindingId === descriptor.bindingId
        ));
        form.closest('tr')?.toggleAttribute('data-revoking', ownAction || sameBindingRevocation);
      }
    }
  };
  // session-action-coordinator-end
  const removeBindingRows = (descriptor) => {
    for (const form of document.querySelectorAll(`form[data-ajax="${descriptor.action}"]`)) {
      const candidate = sessionActionDescriptor(form);
      if (candidate?.bindingId === descriptor.bindingId) form.closest('tr')?.remove();
    }
    const section = descriptor.action === 'revoke_loxberry_read'
      ? loxberryBindingSection : loxberryOperateBindingSection;
    if (!section.querySelector('tbody tr')) section.hidden = true;
  };
  const applySuccessfulSessionAction = (form, descriptor, data) => {
    const row = form.closest('tr[data-session-id]');
    if (descriptor.action === 'confirm_loxone_token') {
      const tokenState = row?.querySelector('[data-session-token-state]');
      if (tokenState) tokenState.textContent = label('SESSIONS.TOKEN_ACTIVE');
      form.remove();
      return;
    }
    if (descriptor.action === 'allow_loxberry_read') {
      form.remove();
      if (Array.isArray(data.loxberry_bindings)) mergeLoxberryBindings(data.loxberry_bindings);
      return;
    }
    if (descriptor.action === 'allow_loxberry_operate') {
      form.remove();
      if (Array.isArray(data.loxberry_operate_bindings)) {
        mergeLoxberryOperateBindings(data.loxberry_operate_bindings);
      }
      return;
    }
    if (descriptor.action === 'revoke_session') {
      row?.remove();
      if (!sessionList.querySelector('tr[data-session-id]')) updateSessions([]);
      return;
    }
    if (descriptor.action === 'revoke_all') {
      updateSessions([]);
      return;
    }
    removeBindingRows(descriptor);
    if (Array.isArray(data.sessions)) updateSessions(data.sessions);
  };
  const scheduleSessionPoll = (delay = 10000) => {
    window.clearTimeout(sessionPollTimer);
    sessionPollTimer = null;
    if (!document.hidden && activeSessionActions.size === 0) {
      sessionPollTimer = window.setTimeout(pollSessions, delay);
    }
  };
  const pollSessions = async ({initial = false} = {}) => {
    if ((!initial && document.hidden)
        || activeSessionActions.size > 0 || sessionPollInFlight) {
      scheduleSessionPoll();
      return;
    }
    sessionPollInFlight = true;
    const expectedSessionDataVersion = sessionDataVersion;
    try {
      const body = new URLSearchParams();
      body.set('action', 'list_sessions');
      body.set('ajax', '1');
      const result = await postAjax(body, 15000);
      if (expectedSessionDataVersion !== sessionDataVersion) return;
      if (Array.isArray(result.data.sessions)) {
        updateSessions(result.data.sessions);
        sessionsLoaded = true;
      }
      renderRemoteCleanup(result.data.remote_cleanup);
      if (Array.isArray(result.data.loxberry_bindings)) {
        updateLoxberryBindings(result.data.loxberry_bindings);
      }
      if (Array.isArray(result.data.loxberry_operate_bindings)) {
        updateLoxberryOperateBindings(result.data.loxberry_operate_bindings);
      }
    } catch {
      if (core.unloading) return;
      setSummaryBadge(sessionsSummaryBadge, label('SUMMARY.UNKNOWN'));
      approvalsSummaryBadge.hidden = true;
      if (!sessionsLoaded) {
        sessionList.replaceChildren(document.createTextNode(label('AJAX.ERROR')));
      }
      // Keep the last known table after a successful hydration; the next visible and open-section poll retries.
    } finally {
      sessionPollInFlight = false;
      sessionsSection.setAttribute('aria-busy', 'false');
      scheduleSessionPoll(expectedSessionDataVersion === sessionDataVersion ? 10000 : 0);
    }
  };
  const beginAction = (form, button) => {
    const descriptor = sessionActionDescriptor(form);
    if (!descriptor) return null;
    const token = beginSessionAction(descriptor, button);
    if (!token) return null;
    window.clearTimeout(sessionPollTimer);
    sessionPollTimer = null;
    updateSessionActionControls();
    return {token, descriptor};
  };
  const actionSucceeded = (form, action, data) => {
    applySuccessfulSessionAction(form, action.descriptor, data);
    updateSessionSummaryBadges();
  };
  const actionFailed = (action, message) => {
    sessionActionFailures.set(action.token, message);
    showSessionActionFailure();
  };
  const finishAction = (action) => {
    const refresh = finishSessionAction(action.token);
    updateSessionActionControls();
    if (refresh) scheduleSessionPoll(0);
  };
  const stopPoll = () => {
    window.clearTimeout(sessionPollTimer);
    sessionPollTimer = null;
  };
  return {pollSessions, scheduleSessionPoll, stopPoll, isSessionAction,
    beginAction, actionSucceeded, actionFailed, finishAction,
    updateSessionActionControls,
    get activeActions() { return activeSessionActions.size; },
    get hasFailures() { return sessionActionFailures.size > 0; },
    showSessionActionFailure};
};
