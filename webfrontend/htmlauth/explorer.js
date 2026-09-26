(function () {
  'use strict';
  if (typeof window === 'undefined' || typeof document === 'undefined') return;

  const core = window.McpExplorerCore;
  const viewHelpers = window.McpExplorerViews;
  const adapters = window.McpExplorerAdapters;
  const page = document.getElementById('mcp-explorer');
  if (!page) return;

  const elements = {
    status: document.getElementById('explorer-status'),
    connect: document.getElementById('explorer-connect'),
    disconnect: document.getElementById('explorer-disconnect'),
    originWarning: document.getElementById('explorer-origin-warning'),
    originLink: document.getElementById('explorer-origin-link'),
    sessionExpiry: document.getElementById('explorer-session-expiry'),
    sessionExpiryTime: document.getElementById('explorer-session-expiry-time'),
    accessScopes: document.getElementById('explorer-access-scopes'),
    scopeList: document.getElementById('explorer-scope-list'),
    scopeUnavailable: document.getElementById('explorer-scope-unavailable'),
    connectionPanel: document.getElementById('explorer-connection-panel'),
    connectionBadge: document.getElementById('explorer-connection-badge'),
    toolsPanel: document.getElementById('explorer-tools-panel'),
    historyPanel: document.getElementById('explorer-history-panel'),
    selectedTool: document.getElementById('explorer-selected-tool'),
    requestSelection: document.getElementById('explorer-request-selection'),
    toolSearch: document.getElementById('explorer-tool-search'),
    toolFilters: document.getElementById('explorer-tool-filters'),
    toolFilterCount: document.getElementById('explorer-tool-filter-count'),
    tools: document.getElementById('explorer-tools'),
    history: document.getElementById('explorer-history'),
    summary: document.getElementById('explorer-tool-summary'),
    request: document.getElementById('explorer-request'),
    result: document.getElementById('explorer-result'),
    form: document.getElementById('explorer-form'),
    formTab: document.getElementById('explorer-form-tab'),
    formPanel: document.getElementById('explorer-form-panel'),
    jsonTab: document.getElementById('explorer-json-tab'),
    jsonPanel: document.getElementById('explorer-json-panel'),
    json: document.getElementById('explorer-json'),
    schemaWarning: document.getElementById('explorer-schema-warning'),
    validation: document.getElementById('explorer-validation'),
    callFeedback: document.getElementById('explorer-call-feedback'),
    run: document.getElementById('explorer-run'),
    resetDraft: document.getElementById('explorer-reset-draft'),
    copy: document.getElementById('explorer-copy'),
    nextPage: document.getElementById('explorer-next-page'),
    resultContext: document.getElementById('explorer-result-context'),
    historyArguments: document.getElementById('explorer-history-arguments'),
    historyArgumentsValue: document.getElementById('explorer-history-arguments-value'),
    restoreHistory: document.getElementById('explorer-restore-history'),
    resultTree: document.getElementById('explorer-result-tree'),
    rawDetails: document.getElementById('explorer-raw-details'),
    resultRaw: document.getElementById('explorer-result-raw'),
    transcript: document.getElementById('explorer-transcript'),
    confirm: document.getElementById('explorer-confirm'),
    confirmTool: document.getElementById('explorer-confirm-tool'),
    confirmArguments: document.getElementById('explorer-confirm-arguments'),
    transfer: document.getElementById('explorer-transfer'),
    transferSource: document.getElementById('explorer-transfer-source'),
    transferContext: document.getElementById('explorer-transfer-context'),
    transferTool: document.getElementById('explorer-transfer-tool'),
    transferField: document.getElementById('explorer-transfer-field'),
    transferEmpty: document.getElementById('explorer-transfer-empty'),
    transferApply: document.getElementById('explorer-transfer-apply'),
  };

  const label = (name) => page.dataset[name] || name;
  const explorerState = window.McpExplorerState.create(core);
  const state = explorerState.data;
  const logoutChannel = typeof BroadcastChannel === 'function'
    ? new BroadcastChannel('mcp-explorer-session') : null;
  const narrowViewport = window.matchMedia('(max-width: 52rem)');
  let sessionExpiryTimer = null;
  function persistDisclosure(element, key) {
    try {
      const saved = window.localStorage.getItem(key);
      if (saved === 'true' || saved === 'false') element.open = saved === 'true';
    } catch (_error) { /* Browser storage may be unavailable. */ }
    element.addEventListener('toggle', () => {
      try { window.localStorage.setItem(key, String(element.open)); }
      catch (_error) { /* The disclosure still works for this tab. */ }
    });
  }
  persistDisclosure(elements.connectionPanel, 'mcp-explorer-connection-open-v1');
  persistDisclosure(elements.accessScopes, 'mcp-explorer-scopes-open-v1');
  if (logoutChannel) logoutChannel.onmessage = (event) => {
    if (event.data !== 'logout') return;
    clearExplorerState();
    setBusy(false);
    renderAll();
    setStatus(label('disconnected'), '');
  };

  function setStatus(text, kind) {
    elements.status.textContent = text;
    elements.status.dataset.kind = kind || '';
  }

  function setCallFeedback(text, kind) {
    elements.callFeedback.textContent = text;
    elements.callFeedback.dataset.kind = kind || '';
    elements.callFeedback.hidden = !text;
  }

  function setBusy(busy) {
    explorerState.setBusy(busy);
    elements.connect.disabled = busy || Boolean(state.oauth);
    elements.disconnect.disabled = busy || !state.oauth;
    elements.run.disabled = busy || !state.oauth || !state.selectedTool;
    elements.nextPage.disabled = busy || !state.nextPageRequest;
    elements.connect.setAttribute('aria-busy', busy ? 'true' : 'false');
  }

  function scrollBehavior() {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth';
  }

  function revealRequest(focus, force) {
    elements.request.open = true;
    if (!force && !narrowViewport.matches) return;
    if (focus) elements.request.focus({preventScroll: true});
    elements.request.scrollIntoView({behavior: scrollBehavior(), block: 'start'});
  }

  function revealResult() {
    elements.result.open = true;
    elements.result.focus({preventScroll: true});
    elements.result.scrollIntoView({behavior: scrollBehavior(), block: 'start'});
  }

  function syncResponsivePanels(event) {
    if (!narrowViewport.matches) {
      elements.toolsPanel.open = true;
      elements.historyPanel.open = true;
      return;
    }
    if (!event || event.matches) {
      elements.toolsPanel.open = false;
      elements.historyPanel.open = false;
    }
  }

  function showError(error, fallback) {
    const message = error instanceof Error && error.message ? error.message : fallback;
    setStatus(message, 'error');
  }

  function clearOriginWarning() {
    elements.originWarning.hidden = true;
    elements.originLink.removeAttribute('href');
  }

  function showConnectionError(error, fallback) {
    if (error instanceof Error && typeof error.canonicalUrl === 'string') {
      elements.originLink.href = error.canonicalUrl;
      elements.originWarning.hidden = false;
      setStatus(fallback, 'error');
      return;
    }
    clearOriginWarning();
    showError(error, fallback);
  }

  const auth = window.McpExplorerAuth.create({core, state, explorerState, label, clearOriginWarning,
    renderConnection: () => { views.renderConnection(); scheduleSessionExpiry(); }, revokeAndClear});
  const {discover, authorize, refreshAccessToken, accessToken,
    explorerSession, openAuthorizationPopup, fetchWithTimeout} = auth;

  function addTranscript(method, request, response, status, duration) {
    const entry = {method, request, response, status, duration, at: new Date().toISOString()};
    if (explorerState.appendTranscript(entry)) {
      elements.transcript.firstElementChild?.remove();
    }
    elements.transcript.append(transcriptEntry(entry));
  }

  const mcp = window.McpExplorerClient.create({core, state, explorerState, label, accessToken,
    fetchWithTimeout, addTranscript});
  const {initialize: initializeMcp, callTool} = mcp;

  async function revokeAndClear() {
    const oauth = state.oauth;
    clearExplorerState();
    renderAll();
    setStatus(label('disconnected'), '');
    if (logoutChannel) logoutChannel.postMessage('logout');
    try { if (oauth) await explorerSession(oauth.metadata, {action: 'logout'}); }
    catch (_error) { /* Server-side expiry remains the fail-safe. */ }
    setBusy(false);
  }

  function clearExplorerState() {
    explorerState.clear();
    viewHelpers.clearSensitiveDom(elements);
  }

  function expireSession() {
    clearExplorerState();
    setBusy(false);
    renderAll();
    setStatus(label('disconnected'), '');
    if (logoutChannel) logoutChannel.postMessage('logout');
  }

  function scheduleSessionExpiry() {
    if (sessionExpiryTimer !== null) window.clearTimeout(sessionExpiryTimer);
    sessionExpiryTimer = null;
    const oauth = state.oauth;
    if (!oauth || !Number.isFinite(oauth.resumeUntil)) return;
    sessionExpiryTimer = window.setTimeout(() => {
      if (state.oauth === oauth && Date.now() >= oauth.resumeUntil) expireSession();
    }, Math.max(0, oauth.resumeUntil - Date.now()));
  }

  const views = window.McpExplorerViews.create({core, state,
    adapters, elements, label, narrowViewport, element,
    actions: {selectTool, revealRequest, setAction, setDraftField,
      validateDraft, applyRange, showResult: renderResult, openTransfer, revealResult}});
  const {renderConnection, renderTools, renderSelectedTool, renderResult: renderResultView,
    transcriptEntry, renderTranscript, renderHistory, displayValue} = views;

  function renderResult(result, context) {
    const displayed = explorerState.setResult(result, context);
    renderResultView(result, context, displayed);
  }

  function applyRange(range) {
    explorerState.setArguments({...state.arguments, ...range});
    elements.json.value = JSON.stringify(state.arguments, null, 2);
    saveCurrentDraft();
    validateDraft(false);
    renderSelectedTool();
  }

  function element(tag, options, children) {
    const node = document.createElement(tag);
    for (const [name, value] of Object.entries(options || {})) {
      if (name === 'className') node.className = value;
      else if (name === 'text') node.textContent = value;
      else node.setAttribute(name, value);
    }
    for (const child of children || []) node.append(child);
    return node;
  }

  function draftFor(tool) { return explorerState.draftFor(tool); }

  function saveCurrentDraft() { explorerState.saveDraft(elements.json.value); }

  function selectTool(name, draft) {
    elements.json.value = explorerState.selectTool(name, draft, elements.json.value);
    renderTools();
    renderSelectedTool();
    if (state.selectedTool) elements.request.open = true;
  }

  function setDraftField(name, included, value) {
    explorerState.setField(name, included, value);
    elements.json.value = JSON.stringify(state.arguments, null, 2);
    saveCurrentDraft();
    validateDraft(false);
  }

  function setAction(value) {
    const next = adapters.changeAction(state.arguments, value);
    explorerState.setArguments(next);
    elements.json.value = JSON.stringify(next, null, 2);
    saveCurrentDraft();
    validateDraft(false);
    renderSelectedTool();
  }

  function validateDraft(show) {
    if (!state.selectedTool) return false;
    let parsed;
    try { parsed = JSON.parse(elements.json.value); }
    catch (_error) {
      if (show) { elements.validation.textContent = label('invalidJson'); elements.validation.hidden = false; }
      return false;
    }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      if (show) { elements.validation.textContent = label('invalidArguments'); elements.validation.hidden = false; }
      return false;
    }
    const errors = core.validateArguments(parsed, state.selectedTool.inputSchema || {type: 'object'});
    if (errors.length) {
      if (show) { elements.validation.textContent = `${label('invalidArguments')} ${errors.join('; ')}`; elements.validation.hidden = false; }
      return false;
    }
    explorerState.setArguments(parsed);
    saveCurrentDraft();
    elements.validation.hidden = true;
    return true;
  }

  function confirmMutation(tool, args) {
    if (!core.toolIsMutating(tool)) return Promise.resolve(true);
    elements.confirmTool.textContent = tool.name;
    elements.confirmArguments.textContent = JSON.stringify(core.redactArguments(args, tool.inputSchema), null, 2);
    if (typeof elements.confirm.showModal !== 'function') {
      return Promise.resolve(window.confirm(`${tool.name}\n\n${elements.confirmArguments.textContent}`));
    }
    elements.confirm.showModal();
    return new Promise((resolve) => elements.confirm.addEventListener('close', () => resolve(elements.confirm.returnValue === 'confirm'), {once: true}));
  }

  async function runSelectedTool() {
    if (!validateDraft(true) || !state.selectedTool) return;
    const oauth = state.oauth;
    const requiredMutationScope = adapters.requiredMutationScope(state.selectedTool);
    const granted = state.oauth && core.grantedScopes(state.oauth.scope);
    if (core.toolIsMutating(state.selectedTool) && requiredMutationScope &&
        !(granted && granted.has(requiredMutationScope))) {
      setCallFeedback(label(requiredMutationScope === 'loxberry:operate' ? 'operateRequired' : 'controlRequired'), 'error');
      return;
    }
    if (!(await confirmMutation(state.selectedTool, state.arguments))) return;
    if (state.oauth !== oauth || Date.now() >= oauth.resumeUntil) {
      renderAll();
      return;
    }
    const tool = state.selectedTool;
    const args = core.clone(state.arguments);
    setBusy(true);
    setCallFeedback(label('working'), 'working');
    const started = performance.now();
    let result;
    let ok = false;
    let sessionCleared = false;
    try {
      result = await callTool(tool.name, args);
      ok = !(result && result.isError);
      renderResult(result, {tool: tool.name, arguments: args});
      const outputErrors = result && result.structuredContent !== undefined && tool.outputSchema
        ? core.validateArguments(result.structuredContent, tool.outputSchema)
        : [];
      if (outputErrors.length) {
        ok = false;
        elements.validation.textContent = `${label('invalidOutput')} ${outputErrors.join('; ')}`;
        elements.validation.hidden = false;
      }
      setCallFeedback(`${label(ok ? 'callCompleted' : 'error')} · ${Math.round(performance.now() - started)} ms`, ok ? 'success' : 'error');
    } catch (error) {
      sessionCleared = Boolean(error && error.sessionCleared === true) || state.oauth !== oauth;
      if (!sessionCleared) {
        result = error && error.mcpResult
          ? core.clone(error.mcpResult)
          : {error: error instanceof Error ? error.message : label('error')};
        renderResult(result, {tool: tool.name, arguments: args});
      }
      if (!sessionCleared) setCallFeedback(`${label('error')} · ${Math.round(performance.now() - started)} ms`, 'error');
    } finally {
      if (!sessionCleared) {
        explorerState.appendHistory({tool: tool.name, arguments: args, result, ok, at: Date.now(), duration: Math.round(performance.now() - started)});
        renderHistory();
      }
      if (state.oauth === oauth) setBusy(false);
    }
  }

  function openTransfer(value, path) {
    explorerState.setTransfer(value, path, null);
    elements.transferSource.textContent = `${state.transferPath} = ${JSON.stringify(value)}`;
    const recipe = adapters.transferRecipe(
      state.lastResultContext && state.lastResultContext.tool,
      displayValue(state.lastResult),
      path,
      value,
      state.tools,
    );
    explorerState.setTransfer(value, path, recipe);
    elements.transferContext.textContent = recipe
      ? `${label(recipe.contextLabel)}: ${recipe.tool} (${Object.keys(recipe.arguments).length} ${label('fields')})`
      : `${label('transferContext')}: ${state.lastResultContext ? state.lastResultContext.tool : '—'}`;
    elements.transferTool.closest('label').hidden = Boolean(recipe);
    elements.transferField.closest('label').hidden = Boolean(recipe);
    if (recipe) {
      elements.transferTool.replaceChildren(element('option', {value: recipe.tool, text: recipe.tool}));
      elements.transferField.replaceChildren();
      elements.transferEmpty.hidden = true;
      elements.transferApply.disabled = false;
      if (typeof elements.transfer.showModal === 'function') elements.transfer.showModal();
      return;
    }
    const targets = core.compatibleTargets(state.tools, value, {
      sourcePath: path,
      sourceTool: state.lastResultContext && state.lastResultContext.tool,
    });
    elements.transferTool.replaceChildren();
    [...new Set(targets.map((item) => item.tool))].forEach((name) => elements.transferTool.append(element('option', {value: name, text: name})));
    const updateFields = () => {
      elements.transferField.replaceChildren();
      targets.filter((item) => item.tool === elements.transferTool.value).forEach((item) => {
        const text = item.mode === 'wrap-array' ? `${item.field} (${label('asList')})` : item.field;
        elements.transferField.append(element('option', {value: item.field, text, 'data-mode': item.mode || 'direct'}));
      });
      const empty = !elements.transferField.options.length;
      elements.transferEmpty.hidden = !empty;
      elements.transferApply.disabled = empty;
    };
    elements.transferTool.onchange = updateFields;
    updateFields();
    if (typeof elements.transfer.showModal === 'function') elements.transfer.showModal();
  }

  function applyTransfer() {
    if (state.transferRecipe) {
      const tool = state.tools.find((item) => item.name === state.transferRecipe.tool);
      if (!tool) return;
      const existing = draftFor(tool).arguments;
      const draft = {...core.clone(existing), ...state.transferRecipe.arguments};
      delete draft.cursor;
      selectTool(tool.name, draft);
      revealRequest(true, true);
      return;
    }
    const tool = state.tools.find((item) => item.name === elements.transferTool.value);
    if (!tool || !elements.transferField.value) return;
    const selected = elements.transferField.options[elements.transferField.selectedIndex];
    const draft = core.transferArguments(
      tool,
      elements.transferField.value,
      state.transferValue,
      selected.dataset.mode,
      state.lastResultContext,
      draftFor(tool).arguments,
    );
    selectTool(tool.name, draft);
    revealRequest(true, true);
  }

  function renderAll() {
    if (state.oauth && state.oauth.resumeUntil <= Date.now()) {
      expireSession();
      return;
    }
    renderConnection();
    scheduleSessionExpiry();
    renderTools();
    renderSelectedTool();
    renderHistory();
    renderTranscript();
    if (!state.hasResult) {
      elements.resultTree.replaceChildren(element('p', {className: 'mcp-explorer-muted', text: label('emptyResult')}));
      elements.resultRaw.textContent = '';
      elements.rawDetails.open = false;
      elements.copy.disabled = true;
      elements.nextPage.hidden = true;
      elements.nextPage.disabled = true;
    }
  }

  function selectTab(jsonMode, focusPanel = true) {
    elements.formTab.setAttribute('aria-selected', String(!jsonMode));
    elements.jsonTab.setAttribute('aria-selected', String(jsonMode));
    elements.formTab.tabIndex = jsonMode ? -1 : 0;
    elements.jsonTab.tabIndex = jsonMode ? 0 : -1;
    elements.formPanel.hidden = jsonMode;
    elements.jsonPanel.hidden = !jsonMode;
    if (focusPanel) (jsonMode ? elements.json : elements.form.querySelector('input,select,textarea'))?.focus();
  }

  function handleTabKey(event) {
    const tabs = [elements.formTab, elements.jsonTab];
    const current = tabs.indexOf(event.currentTarget);
    let target = null;
    if (event.key === 'ArrowLeft') target = tabs[(current - 1 + tabs.length) % tabs.length];
    if (event.key === 'ArrowRight') target = tabs[(current + 1) % tabs.length];
    if (event.key === 'Home') target = tabs[0];
    if (event.key === 'End') target = tabs[tabs.length - 1];
    if (!target) return;
    event.preventDefault();
    selectTab(target === elements.jsonTab, false);
    target.focus();
  }

  elements.connect.addEventListener('click', async () => {
    const insecureOrigin = window.location.protocol !== 'https:';
    // A blank window retains the click's transient user activation in Firefox.
    // HTTP is rejected without opening a window and offers the HTTPS link below.
    const authorizationPopup = insecureOrigin ? null : openAuthorizationPopup();
    setBusy(true);
    setStatus(label('working'), 'working');
    try {
      explorerState.setSession(await authorize(authorizationPopup));
      explorerState.setTools(await initializeMcp());
      renderAll();
      if (state.tools.length) selectTool(state.tools[0].name);
      setStatus(label('connected'), 'success');
    } catch (error) {
      try { authorizationPopup?.close(); } catch (_closeError) { /* already gone */ }
      if (state.oauth) await revokeAndClear();
      else clearExplorerState();
      showConnectionError(error, label('error'));
      renderAll();
    } finally { setBusy(false); }
  });
  elements.disconnect.addEventListener('click', async () => {
    setBusy(true);
    await revokeAndClear();
    setBusy(false);
    setStatus(label('disconnected'), '');
  });
  elements.toolSearch.addEventListener('input', () => {
    explorerState.setSearch(elements.toolSearch.value);
    renderTools();
  });
  elements.toolFilters.addEventListener('change', (event) => {
    const input = event.target;
    if (!input.matches('input[data-tool-group]')) return;
    const group = input.dataset.toolGroup;
    if (group === 'all') explorerState.setGroups([]);
    else if (input.checked) explorerState.setGroups([...state.toolGroups, group]);
    else explorerState.setGroups(state.toolGroups.filter((selected) => selected !== group));
    renderTools();
  });
  elements.run.addEventListener('click', runSelectedTool);
  elements.resetDraft.addEventListener('click', () => {
    if (!state.selectedTool) return;
    const defaults = core.defaultArguments(state.selectedTool.inputSchema || {});
    selectTool(state.selectedTool.name, defaults);
  });
  elements.formTab.addEventListener('click', () => selectTab(false));
  elements.jsonTab.addEventListener('click', () => selectTab(true));
  elements.formTab.addEventListener('keydown', handleTabKey);
  elements.jsonTab.addEventListener('keydown', handleTabKey);
  elements.json.addEventListener('input', saveCurrentDraft);
  elements.json.addEventListener('change', () => { if (validateDraft(true)) renderSelectedTool(); });
  elements.copy.addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(JSON.stringify(state.lastResult, null, 2)); setStatus(label('copied'), 'success'); }
    catch (error) { showError(error, label('error')); }
  });
  elements.rawDetails.addEventListener('toggle', () => {
    if (elements.rawDetails.open && state.hasResult && !elements.resultRaw.textContent) {
      elements.resultRaw.textContent = JSON.stringify(state.lastResult, null, 2);
    }
  });
  elements.nextPage.addEventListener('click', async () => {
    if (!state.nextPageRequest) return;
    const request = core.clone(state.nextPageRequest);
    selectTool(request.tool, request.arguments);
    await runSelectedTool();
  });
  elements.transfer.addEventListener('close', () => { if (elements.transfer.returnValue === 'apply') applyTransfer(); });
  elements.restoreHistory.addEventListener('click', () => {
    const context = state.lastResultContext;
    if (!context || !context.history || !window.confirm(label('restoreHistoryConfirm'))) return;
    selectTool(context.tool, context.arguments);
    revealRequest(true, false);
  });

  syncResponsivePanels();
  narrowViewport.addEventListener('change', syncResponsivePanels);
  selectTab(false, false);
  renderAll();
  (async () => {
    try {
      const discovered = await discover();
      setBusy(true);
      setStatus(label('restoringSession'), 'working');
      explorerState.setSession({
        metadata: discovered.authorizationMetadata,
        resource: discovered.resourceMetadata.resource,
        scope: 'loxone:read', accessToken: '', expiresAt: 0,
      });
      await refreshAccessToken();
      explorerState.setTools(await initializeMcp());
      renderAll();
      if (state.tools.length) selectTool(state.tools[0].name);
      setStatus(label('connected'), 'success');
    } catch (_error) {
      const canonicalOriginMismatch = _error instanceof Error
        && typeof _error.canonicalUrl === 'string';
      clearExplorerState();
      renderAll();
      setStatus(label('disconnected'), '');
      if (canonicalOriginMismatch) {
        showConnectionError(_error, label('error'));
      }
    } finally {
      setBusy(false);
    }
  })();
})();
