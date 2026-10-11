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
    'coverage', 'coverage-data', 'rows', 'count', 'next', 'origin-warning', 'origin-link']
    .map((key) => [key, document.getElementById(`knx-project-${key}`)]));
  const channel = typeof BroadcastChannel === 'function' ? new BroadcastChannel('mcp-explorer-session') : null;
  let frame = null;
  let busy = false;
  let generation = 0;
  let expiryTimer = null;
  const message = (text) => { elements.status.textContent = text; };
  const display = (fields, key) => Object.hasOwn(fields || {}, key)
    ? (fields[key] === '' ? page.dataset.empty : String(fields[key])) : page.dataset.unknown;
  const clearResult = () => {
    generation++;
    frame = null;
    elements.rows.replaceChildren();
    elements.summary.textContent = '';
    elements.count.textContent = '';
    elements['coverage-data'].textContent = '';
    elements.coverage.hidden = true;
  };
  const controls = () => {
    const blocked = busy || page.getAttribute('aria-busy') === 'true';
    elements.connect.disabled = blocked || Boolean(state.oauth);
    elements.disconnect.disabled = blocked || !state.oauth;
    elements.run.disabled = blocked || !state.oauth || !knx.snapshot();
    elements.next.disabled = blocked || !state.oauth || !frame?.cursor;
  };
  const clearSession = () => {
    window.clearTimeout(expiryTimer);
    explorerState.clear();
    clearResult();
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
    revokeAndClear: clearSession,
    requestedScopes: ['loxone:read'], clientName: 'LoxBerry KNX project comparison'});
  const mcp = window.McpExplorerClient.create({core, state, explorerState, label,
    accessToken: auth.accessToken, fetchWithTimeout: auth.fetchWithTimeout,
    addTranscript: () => { /* This page does not retain transport payloads. */ }});
  const run = async (operation) => {
    if (busy || page.getAttribute('aria-busy') === 'true') return;
    busy = true; controls(); message(label('working'));
    try { await operation(); }
    catch (error) {
      if (error?.httpStatus === 401 || error?.sessionCleared === true) clearSession();
      clearResult(); originWarning(error);
      message(`${label('error')}: ${error instanceof Error ? error.message : label('error')}`);
    } finally { busy = false; controls(); }
  };
  const relation = (value) => label({common: 'common', import_only: 'importOnly',
    observed_project_only: 'observedProjectOnly'}[value] || 'limited');
  const appendText = (parent, tag, value) => {
    const node = document.createElement(tag); node.textContent = value; parent.append(node); return node;
  };
  const render = (envelope, summary, count) => {
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
  const compare = async (cursor = null) => {
    const saved = knx.snapshot();
    if (!saved) throw new Error(label('targetChanged'));
    const binding = {target: saved.target, revision: saved.revision};
    const expectedSession = state.oauth;
    const request = ++generation;
    const priorCount = cursor ? frame?.count || 0 : 0;
    const result = await mcp.callTool('loxone_analyze_project', {scope: 'knx',
      analyses: ['ets_project_comparison'], limit: 50, ...(cursor ? {cursor} : {})});
    if (request !== generation || state.oauth !== expectedSession) return;
    const envelope = result?.structuredContent;
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
    const count = priorCount + envelope.data.findings.length;
    frame = {...binding, cursor: envelope.data.next_cursor, count};
    render(envelope, summary, count);
  };
  elements.run.addEventListener('click', () => void run(() => compare()));
  elements.next.addEventListener('click', () => void run(() => compare(frame?.cursor)));
  elements.connect.addEventListener('click', () => {
    if (busy || page.getAttribute('aria-busy') === 'true') return;
    const popup = window.location.protocol === 'https:' ? auth.openAuthorizationPopup() : null;
    void run(async () => {
      const request = generation;
      const session = await auth.authorize(popup);
      if (request !== generation) return;
      explorerState.setSession(session);
      const tools = await mcp.initialize();
      if (request !== generation || state.oauth !== session) return;
      explorerState.setTools(tools);
      scheduleExpiry(); message(label('connected'));
    });
  });
  elements.disconnect.addEventListener('click', () => void run(async () => {
    const oauth = state.oauth;
    clearSession();
    if (oauth) await auth.explorerSession(oauth.metadata, {action: 'revoke'});
    if (channel) channel.postMessage('logout');
    message(label('disconnected'));
  }));
  page.addEventListener('knx-state', () => {
    const current = knx.snapshot();
    if (frame && (!current || frame.target !== current.target || frame.revision !== current.revision)) {
      clearResult(); message(label('targetChanged'));
    }
    controls();
  });
  page.addEventListener('knx-idle', controls);
  controls();
  const restore = async () => {
    const request = generation;
    try {
      const discovery = await auth.discover();
      if (request !== generation) return;
      explorerState.setSession({metadata: discovery.authorizationMetadata,
        resource: discovery.resourceMetadata.resource, scope: 'loxone:read', accessToken: '', expiresAt: 0});
      await auth.refreshAccessToken();
      if (request !== generation) return;
      const session = state.oauth;
      const tools = await mcp.initialize();
      if (request !== generation || state.oauth !== session) return;
      explorerState.setTools(tools);
      scheduleExpiry(); message(label('connected'));
    } catch (error) { if (request === generation) { clearSession(); originWarning(error); } }
  };
  if (page.getAttribute('aria-busy') === 'true') {
    page.addEventListener('knx-idle', () => void run(restore), {once: true});
  } else void run(restore);
})();
