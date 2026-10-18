/* Explicit read-only project comparison, using the shared local OAuth boundary. */
(() => {
  'use strict';
  const page = document.getElementById('knx-page');
  const ui = document.getElementById('knx-project-section');
  const knx = window.MCPKnx;
  if (!ui || !knx) return;
  const core = window.McpExplorerCore;
  const explorerState = window.McpExplorerState.create(core);
  const state = explorerState.data;
  const label = (key) => ui.dataset[key] || key;
  const elements = Object.fromEntries(['connect', 'disconnect', 'run', 'status', 'summary',
    'coverage', 'coverage-data', 'rows', 'count', 'next', 'previous', 'origin-warning', 'origin-link',
    'connection-badge', 'session-expiry', 'session-expiry-time', 'access-scopes',
    'scope-unavailable', 'scope-list', 'loading', 'announcement']
    .map((key) => [key, document.getElementById(`knx-project-${key}`)]));
  const channel = typeof BroadcastChannel === 'function' ? new BroadcastChannel('mcp-explorer-session') : null;
  let frame = null;
  let busy = false;
  let restoring = true;
  let generation = 0;
  let expiryTimer = null;
  const pages = new Map();
  let trail = [0];
  const viewKey = 'mcp-knx-project-view-v1';
  const sortFields = ['address','relation','loxone_names','imported_name','manual_name','observation'];
  const sortOrder = () => knx.tables?.selection('knx-project-rows', sortFields) || null;
  let savedView = null;
  let restoringPage = null;
  try {
    const raw = sessionStorage.getItem(viewKey);
    const value = raw?.length < 16384 ? JSON.parse(raw) : null;
    if (/^[0-9a-f]{64}$/.test(value?.target) && Number.isInteger(value.offset)
        && value.offset >= 0 && value.offset <= 65536) {
      savedView = {target:value.target,offset:value.offset,
        revision:Number.isSafeInteger(value.revision) && value.revision >= 0 ? value.revision : null};
      if (Array.isArray(value.trail) && value.trail.length <= 1400
          && value.trail.every(n=>Number.isInteger(n)&&n>=0&&n<=65536)) trail = value.trail;
    }
  } catch (_) { /* Reload preferences are optional; data is never stored here. */ }
  const rememberView = () => {
    try {
      if (frame) sessionStorage.setItem(viewKey, JSON.stringify({target:frame.target,revision:frame.revision,offset:frame.offset,trail}));
      else sessionStorage.removeItem(viewKey);
    } catch (_) { /* Continue without browser persistence. */ }
  };
  const message = (text, kind) => {
    elements.status.textContent = text;
    elements.status.dataset.kind = kind || (state.oauth ? 'success' : 'inactive');
  };
  const display = (fields, key) => Object.hasOwn(fields || {}, key)
    ? (fields[key] === '' ? page.dataset.empty : String(fields[key])) : page.dataset.unknown;
  const clearResult = () => {
    generation++;
    frame = null;
    pages.clear();
    page.dispatchEvent(new CustomEvent('knx-project-state'));
    elements.rows.replaceChildren();
    elements.rows.dataset.emptyMessage = label('notRun');
    elements.summary.textContent = '';
    elements.count.textContent = '';
    elements['coverage-data'].textContent = '';
    elements.coverage.hidden = true;
  };
  const controls = () => {
    const connected = Boolean(state.oauth && state.oauth.resumeUntil > Date.now());
    elements.loading.hidden = !busy && !restoring;
    elements.loading.textContent = label(restoring ? 'restoringSession' : 'working');
    const announcement = elements.loading.hidden ? '' : elements.loading.textContent;
    if (elements.announcement.textContent !== announcement) elements.announcement.textContent = announcement;
    elements['connection-badge'].hidden = restoring && !connected;
    elements['connection-badge'].textContent = label(connected ? 'connected' : 'disconnected');
    elements['connection-badge'].dataset.kind = connected ? 'success' : 'inactive';
    elements['session-expiry'].hidden = !connected;
    elements['access-scopes'].hidden = !connected;
    elements['scope-list'].replaceChildren();
    elements['scope-unavailable'].hidden = true;
    const time = elements['session-expiry-time'];
    time.textContent = '';
    time.removeAttribute('datetime');
    if (connected) {
      const expiry = new Date(state.oauth.resumeUntil);
      time.dateTime = expiry.toISOString();
      time.textContent = expiry.toLocaleString(document.documentElement.lang || undefined);
      const granted = core.grantedScopes(state.oauth.scope);
      elements['scope-unavailable'].hidden = granted !== null;
      if (granted !== null) for (const scope of core.EXPLORER_SCOPE_ORDER) {
        const item = document.createElement('li');
        item.className = 'mcp-explorer-scope';
        const name = document.createElement('code');
        name.textContent = scope;
        const status = document.createElement('span');
        status.textContent = label(granted.has(scope) ? 'scopeGranted' : 'scopeNotGranted');
        item.append(name, status);
        elements['scope-list'].append(item);
      }
    }
    const blocked = busy || page.getAttribute('aria-busy') === 'true';
    elements.connect.disabled = blocked || Boolean(state.oauth);
    elements.disconnect.disabled = blocked || !state.oauth;
    elements.run.disabled = blocked || !state.oauth || !knx.snapshot();
    elements.next.disabled = blocked || !state.oauth || frame?.nextOffset == null;
    elements.previous.disabled = blocked || !state.oauth || !frame?.offset;
  };
  const clearSession = () => {
    restoringPage = null;
    restoring = false;
    window.clearTimeout(expiryTimer);
    explorerState.clear();
    clearResult();
    savedView = null; rememberView();
    message(label('disconnected'));
    controls();
  };
  if (channel) channel.onmessage = (event) => { if (event.data === 'logout') clearSession(); };
  const scheduleExpiry = () => {
    window.clearTimeout(expiryTimer);
    const oauth = state.oauth;
    if (!oauth) return;
    expiryTimer = window.setTimeout(() => { if (state.oauth === oauth) clearSession(); },
      Math.max(0, Math.min(oauth.resumeUntil - Date.now(), 2147483647)));
  };
  const originWarning = (error) => {
    if (typeof error?.canonicalUrl !== 'string') return;
    const url = new URL(error.canonicalUrl);
    url.pathname = url.pathname.replace(/explorer\.cgi$/, 'knx.cgi');
    elements['origin-link'].href = url.href;
    elements['origin-warning'].hidden = false;
  };
  const auth = window.McpExplorerAuth.create({core, state, explorerState, label,
    clearOriginWarning: () => { elements['origin-warning'].hidden = true; },
    renderConnection: () => { scheduleExpiry(); controls(); },
    revokeAndClear: clearSession});
  const run = async (operation, {independent = false} = {}) => {
    if (busy || (!independent && page.getAttribute('aria-busy') === 'true')) return;
    busy = true; ui.setAttribute('aria-busy', 'true');
    controls(); message(label(restoring ? 'restoringSession' : 'working'), 'working');
    try { await operation(); }
    catch (error) {
      if (error?.httpStatus === 401 || error?.sessionCleared === true) clearSession();
      const retainedView = Boolean(frame);
      if (frame) { frame.stale = true; pages.clear(); page.dispatchEvent(new CustomEvent('knx-project-state')); }
      originWarning(error);
      message(retainedView ? label('refreshFailed')
        : `${label('error')}: ${error instanceof Error ? error.message : label('error')}`, 'error');
    } finally { busy = false; ui.removeAttribute('aria-busy'); controls(); }
  };
  const relation = (value) => label({common: 'common', import_only: 'importOnly',
    observed_project_only: 'observedProjectOnly'}[value] || 'limited');
  const appendText = (parent, tag, value) => {
    const node = document.createElement(tag); node.textContent = value; parent.append(node); return node;
  };
  const render = (envelope, summary, count) => {
    elements.rows.dataset.emptyMessage = ui.dataset.noMatches;
    const data = envelope.data;
    elements.rows.replaceChildren();
    for (const finding of data.findings) {
      const item = finding.comparison;
      if (!item) continue;
      const tr = document.createElement('tr');
      appendText(tr, 'td', finding.group_address);
      appendText(tr, 'td', relation(item.relation));
      const names = document.createElement('td');
      for (const object of item.project_objects) {
        const details = document.createElement('details');
        appendText(details, 'summary', object.loxone_name || page.dataset.unknown);
        appendText(details, 'p', `${object.original_address || page.dataset.unknown} · ${object.project_node_id}`);
        appendText(details, 'p', `${page.dataset.description}: ${object.project_description ?? page.dataset.unknown}`);
        if (!object.name_complete || object.truncated_fields.length) appendText(details, 'p', label('namesUnknown'));
        names.append(details);
      }
      if (!item.project_objects.length) appendText(names, 'span', page.dataset.unknown);
      if (item.project_objects_omitted) appendText(names, 'p', `${label('omitted')}: ${item.project_objects_omitted}`);
      tr.append(names);
      const metadata = item.local_metadata;
      const imported = document.createElement('td');
      appendText(imported, 'span', display(metadata?.imported, 'name'));
      if (metadata) {
        const details = document.createElement('details');
        appendText(details, 'summary', page.dataset.sources);
        appendText(details, 'p', `${page.dataset.description}: ${display(metadata.imported, 'description')}`);
        appendText(details, 'p', `${page.dataset.importSource}: ${metadata.import_info.file_format || page.dataset.unknown}`);
        if (metadata.import_info.imported_at) appendText(details, 'p', new Date(metadata.import_info.imported_at * 1000).toLocaleString(document.documentElement.lang || undefined));
        imported.append(details);
      }
      tr.append(imported);
      const manual = document.createElement('td');
      appendText(manual, 'span', display(metadata?.manual, 'name'));
      if (metadata && Object.hasOwn(metadata.manual, 'description')) appendText(manual, 'p', `${page.dataset.description}: ${display(metadata.manual, 'description')}`);
      tr.append(manual);
      const observation = document.createElement('td');
      if (item.names_differ) appendText(observation, 'p', label('namesDiffer'));
      else if (item.name_comparison === 'compared' && item.project_names_complete) appendText(observation, 'p', label('namesSame'));
      if (item.name_comparison === 'unknown' || !item.project_names_complete) appendText(observation, 'p', label('namesUnknown'));
      if (item.ambiguous_names) appendText(observation, 'p', label('ambiguous'));
      tr.append(observation); elements.rows.append(tr);
    }
    const counts = summary.counts;
    const scope = summary.import_info.complete_export;
    elements.summary.textContent = `${label('common')}: ${counts.common} · ${label('importOnly')}: ${counts.import_only}`
      + ` · ${label('observedProjectOnly')}: ${counts.observed_project_only} · ${label('namesDiffer')}: ${counts.name_deviations}`
      + ` · ${label('latestDocument')}: ${scope === true ? label('complete') : scope === false ? label('partial') : page.dataset.unknown}`;
    if (summary.source_limits) {
      const limits = summary.source_limits;
      elements.summary.textContent += ` · ${label('sourceLimits')}: `
        + [limits.unsupported_source_objects, limits.invalid_or_missing_address,
          limits.ambiguous_source_objects, limits.source_groups_omitted,
          limits.diagnostic_groups_omitted, limits.incomplete_project_names].join(' / ');
    }
    const total = counts.common + counts.import_only + counts.observed_project_only;
    elements.count.textContent = `${count - data.findings.length + (data.findings.length ? 1 : 0)}–${count} / ${total}`;
    elements['coverage-data'].textContent = JSON.stringify({project_fingerprint: data.project_fingerprint,
      model_version: data.model_version, observed_at: envelope.observed_at, stale: envelope.stale,
      comparison: summary, source_coverage: data.coverage_by_source_type,
      source_diagnostics: data.source_diagnostics, analysis_truncated: data.analysis_truncated,
      truncation_reasons: data.truncation_reasons, page_truncated: data.page_truncated}, null, 2);
    elements.coverage.hidden = false;
    message(`${label('connected')} · ${label('limited')}`);
  };
  const compare = async (offset = 0, refresh = false) => {
    const saved = knx.snapshot();
    if (!saved) throw new Error(label('targetChanged'));
    const binding = {target: saved.target, revision: saved.revision};
    const expectedSession = state.oauth;
    if (!expectedSession || expectedSession.resumeUntil <= Date.now()) {
      const error = new Error(label('disconnected')); error.sessionCleared = true; throw error;
    }
    const request = ++generation;
    const sort = sortOrder();
    if (refresh) { pages.clear(); if (!offset) trail = [0]; }
    const cached = pages.get(offset);
    const retained = cached && Date.now() - cached.loadedAt < 60000
      && cached.target === binding.target && cached.revision === binding.revision
      && cached.session === expectedSession && cached.sortKey === JSON.stringify(sort) ? cached : null;
    const pending = restoringPage; restoringPage = null;
    const prepared = pending && pending.target === binding.target && pending.revision === binding.revision
      && pending.offset === offset && pending.session === expectedSession
      && pending.sortKey === JSON.stringify(sort) ? pending : null;
    let loaded = prepared ? await prepared.result : null;
    if (loaded && !(Date.now() - loaded.completedAt >= 0 && Date.now() - loaded.completedAt < 60000))
      loaded = null;
    if (loaded?.error) throw loaded.error;
    const envelope = retained
      ? retained.envelope : loaded ? loaded.envelope : await window.MCPKnxProject.adminRequest('knx_project_page',
        {...binding, offset, sort});
    if (request !== generation || state.oauth !== expectedSession) return;
    if (!envelope?.ok) {
      if (envelope?.data?.error === 'unauthenticated') clearSession();
      throw new Error(envelope?.data?.message || label('error'));
    }
    const summary = envelope.data.summaries.ets_project_comparison;
    const current = knx.snapshot();
    if (!current || current.target !== binding.target || current.revision !== binding.revision
      || summary.target_binding !== binding.target || summary.knx_revision !== binding.revision) {
      throw new Error(label('targetChanged'));
    }
    if (offset && !envelope.data.findings.length) { trail=[0]; return compare(0, true); }
    if (frame && frame.fingerprint !== envelope.data.project_fingerprint) { pages.clear(); trail = [0]; }
    // Keep a bounded set of already authorized pages only in this live tab.
    if (!retained) {
      const bytes = JSON.stringify(envelope).length * 2;
      while (pages.size && (pages.size >= 20 || [...pages.values()].reduce((sum,item)=>sum+item.bytes,0)+bytes > 8*1024*1024))
        pages.delete(pages.keys().next().value);
      pages.set(offset, {envelope, bytes, loadedAt:loaded?.completedAt || Date.now(), ...binding,
        session:expectedSession,sortKey:JSON.stringify(sort)});
    }
    trail = [...new Set([...trail,offset])].sort((a,b)=>a-b);
    const count = offset + envelope.data.findings.length;
    frame = {...binding, offset, sort, nextOffset:envelope.data.next_cursor ? count : null, count,
      fingerprint: envelope.data.project_fingerprint, modelVersion: envelope.data.model_version,
      evidence: envelope.data.findings.map(item => item.comparison).filter(Boolean),
      stale: envelope.stale, session: expectedSession, generation};
    render(envelope, summary, count);
    rememberView();
    page.dispatchEvent(new CustomEvent('knx-project-state'));
    return true;
  };
  const exportSnapshot = () => {
    if (!frame || frame.stale || !state.oauth || state.oauth !== frame.session) return null;
    return {binding: JSON.stringify({fingerprint: frame.fingerprint, modelVersion: frame.modelVersion,
      generation: frame.generation, target: frame.target, revision: frame.revision}),
      target: frame.target, revision: frame.revision, items: frame.evidence};
  };
  window.MCPKnxProject = Object.freeze({snapshot: exportSnapshot,
    adminRequest: async (action, payload) => {
      if (!['knx_project_page', 'knx_correction_apply', 'knx_correction_xml_preview', 'knx_correction_xml_download'].includes(action))
        throw new Error('knx_correction_invalid');
      const unavailable = () => {const error = new Error('knx_project_evidence_required');
        error.code = 'knx_project_evidence_required'; return error;};
      const session = state.oauth;
      if (!session) throw unavailable();
      let token;
      try { token = await auth.accessToken(); } catch (_) { throw unavailable(); }
      if (state.oauth !== session || Date.now() >= session.resumeUntil) throw unavailable();
      // Preserve Apache Admin authentication. The separate Loxone token is a
      // header only; the helper forwards it to the fixed loopback service.
      const response = await auth.fetchWithTimeout('knx.cgi', {method:'POST', credentials:'same-origin',
        headers:{'Content-Type':'application/x-www-form-urlencoded', 'X-Loxone-Authorization':`Bearer ${token}`},
        body:new URLSearchParams({action, payload:JSON.stringify(payload)})}, 60000);
      if (response.status === 401) {
        const error = new Error('HTTP 401'); error.httpStatus = 401; throw error;
      }
      const result = await response.json();
      if (!response.ok || !result.ok) {
        const error = new Error('correction_unavailable'); error.code = result.error?.code; throw error;
      }
      if (state.oauth !== session) {
        const error = new Error('write_outcome_uncertain'); error.code = 'write_outcome_uncertain'; throw error;
      }
      return result.data;
    }, validate: async binding => {
    const snapshot = exportSnapshot();
    if (!snapshot || snapshot.binding !== binding) throw new Error('knx_revision_conflict');
    const expected = frame;
    try {
      const envelope = await window.MCPKnxProject.adminRequest('knx_project_page',
        {target:expected.target,revision:expected.revision,offset:expected.offset,sort:expected.sort});
      if (envelope?.data?.error === 'unauthenticated') clearSession();
      const current = knx.snapshot();
      if (!envelope?.ok || envelope.stale || !current
          || current.target !== expected.target || current.revision !== expected.revision || state.oauth !== expected.session || frame !== expected
          || envelope.data.project_fingerprint !== expected.fingerprint
          || envelope.data.model_version !== expected.modelVersion
          || envelope.data.summaries?.ets_project_comparison?.knx_revision !== expected.revision
          || envelope.data.summaries?.ets_project_comparison?.target_binding !== expected.target
          || JSON.stringify(envelope.data.findings.map(item => item.comparison).filter(Boolean))
             !== JSON.stringify(expected.evidence)) throw new Error('knx_revision_conflict');
    } catch (error) {
      if (error?.httpStatus === 401 || error?.sessionCleared === true) clearSession();
      throw error;
    }
    return snapshot;
  }});
  elements.run.addEventListener('click', () => void run(() => compare(0, true)));
  elements.next.addEventListener('click', () => { if (frame?.nextOffset != null) void run(() => compare(frame.nextOffset)); });
  elements.previous.addEventListener('click', () => { if (frame?.offset) {
    const prior = trail.filter(offset => offset < frame.offset).sort((a,b)=>b-a)[0];
    void run(() => compare(prior ?? Math.max(0,frame.offset-50)));
  }});
  knx.tables?.bind('knx-project-rows', async () => {
    if (!frame) return true;
    let applied = false; trail=[0];
    await run(async () => { applied = await compare(0, true) === true; });
    return applied;
  });
  const restoreView = () => {
    const current = knx.snapshot();
    if (!savedView || busy || restoring || !state.oauth || !current
        || page.getAttribute('aria-busy') === 'true') return;
    const retained = savedView; savedView = null;
    if (retained.target !== current.target) { rememberView(); return; }
    void run(() => compare(retained.offset, true));
  };
  elements.connect.addEventListener('click', () => {
    if (busy || page.getAttribute('aria-busy') === 'true') return;
    const popup = window.location.protocol === 'https:' ? auth.openAuthorizationPopup() : null;
    void run(async () => {
      const request = generation;
      const session = await auth.authorize(popup);
      if (request !== generation) return;
      explorerState.setSession(session);
      scheduleExpiry(); message(label('connected'));
    });
  });
  elements.disconnect.addEventListener('click', () => void run(async () => {
    const oauth = state.oauth;
    clearSession();
    if (channel) channel.postMessage('logout');
    if (oauth) await auth.explorerSession(oauth.metadata, {action: 'logout'});
    message(label('disconnected'));
  }));
  page.addEventListener('knx-state', () => {
    const current = knx.snapshot();
    if (frame && (!current || frame.target !== current.target || frame.revision !== current.revision)) {
      clearResult(); message(label('targetChanged'), 'warning');
    }
    controls();
    restoreView();
  });
  page.addEventListener('knx-idle', () => { controls(); restoreView(); });
  controls();
  message(label('restoringSession'), 'working');
  const restore = async () => {
    const request = generation;
    try {
      const discovery = await auth.discover();
      if (request !== generation) return;
      explorerState.setSession({metadata: discovery.authorizationMetadata,
        resource: discovery.resourceMetadata.resource, scope: 'loxone:read', accessToken: '', expiresAt: 0});
      await auth.refreshAccessToken();
      if (request !== generation) return;
      scheduleExpiry(); message(label('connected'));
      if (savedView && savedView.revision !== null && !knx.snapshot()) {
        const hint = {...savedView}, sort = sortOrder();
        restoringPage = {...hint,session:state.oauth,sortKey:JSON.stringify(sort),
          result:window.MCPKnxProject.adminRequest('knx_project_page',
            {target:hint.target,revision:hint.revision,offset:hint.offset,sort})
            .then(envelope=>({envelope,completedAt:Date.now()}),
              error=>({error,completedAt:Date.now()}))};
      }
    } catch (error) { if (request === generation) { clearSession(); originWarning(error); } }
    finally { restoring = false; controls(); }
  };
  // Session discovery does not depend on the local catalog. User actions still do.
  void run(restore, {independent: true}).then(restoreView);
})();
