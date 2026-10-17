(() => {
  'use strict';
  const section = document.getElementById('knx-corrections');
  if (!section) return;
  const page = document.getElementById('knx-page');
  const list = document.getElementById('knx-corrections-list');
  const values = document.getElementById('knx-corrections-values');
  const status = document.getElementById('knx-corrections-status');
  const more = document.getElementById('knx-corrections-more');
  const loading = document.getElementById('knx-corrections-loading');
  const announcement = document.getElementById('knx-corrections-announcement');
  let target = null;
  let selected = null;
  let busy = false;
  let viewStale = false;
  const knownDrafts = new Map();
  const exportSelection = new Set();
  const exportButton = document.getElementById('knx-corrections-export');
  let pendingApply = null;
  const reconcile = document.getElementById('knx-corrections-reconcile');
  const forget = document.getElementById('knx-corrections-forget');
  const pendingKey = 'mcp-knx-admin-pending-apply-v1';
  const selectionKey = 'mcp-knx-admin-draft-view-v1';
  let savedSelection = null;
  try {
    const raw = sessionStorage.getItem(selectionKey);
    const value = raw && raw.length <= 512 ? JSON.parse(raw) : null;
    if (/^[0-9a-f]{64}$/.test(value?.target) && /^[0-9a-f]{48}$/.test(value?.draft_id)
        && Number.isInteger(value.offset) && value.offset >= 0 && value.offset < 50)
      savedSelection = {target: value.target, draft_id: value.draft_id, offset: value.offset};
  } catch (_) { /* Selection is optional when browser storage is unavailable. */ }
  const rememberSelection = (draft = null, offset = 0) => {
    savedSelection = draft ? {target, draft_id: draft.draft_id, offset} : null;
    try {
      if (savedSelection) sessionStorage.setItem(selectionKey, JSON.stringify(savedSelection));
      else sessionStorage.removeItem(selectionKey);
    } catch (_) { /* Keep the live view usable without persistent selection. */ }
  };
  const updatePending = (value) => {
    // Only identities/revisions: no field values, tokens or Admin cookies.
    // Persist before sending; refuse a write when exact recovery cannot be retained.
    if (value) sessionStorage.setItem(pendingKey, JSON.stringify({arguments:value, expires:Date.now()+7*86400000}));
    else sessionStorage.removeItem(pendingKey);
    pendingApply = value; reconcile.hidden = !value; forget.hidden = !value;
  };
  try {
    const raw = sessionStorage.getItem(pendingKey);
    const retained = raw && raw.length <= 4096 ? JSON.parse(raw) : null;
    if (retained && retained.expires > Date.now() && retained.expires <= Date.now()+7*86400000
        && /^[0-9a-f]{32}$/.test(retained.arguments?.request_id)
        && /^[0-9a-f]{48}$/.test(retained.arguments?.draft_id)) {
      pendingApply = retained.arguments; reconcile.hidden = false; forget.hidden = false;
    }
  } catch (_) { /* No recovered write is ever sent automatically. */ }
  const api = async (action, payload, withProject = false) => {
    if (withProject) {
      if (!window.MCPKnxProject?.adminRequest) {
        const error = new Error('knx_project_evidence_required'); error.code = 'knx_project_evidence_required'; throw error;
      }
      return window.MCPKnxProject.adminRequest(action, payload);
    }
    const response = await fetch('knx.cgi', {method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      body: new URLSearchParams({action, payload: JSON.stringify(payload)})});
    const result = await response.json();
    if (!response.ok || !result.ok) {
      const error = new Error('correction_unavailable'); error.code = result.error?.code; throw error;
    }
    return result.data;
  };
  const cell = (row, value) => {
    const td = document.createElement('td');
    td.textContent = String(value); row.append(td);
  };
  const display = (value) => value.state === 'missing' ? section.dataset.missing
    : value.value + (value.truncated ? ' …' : '');
  const requestId = () => Array.from(crypto.getRandomValues(new Uint8Array(16)),
    (value) => value.toString(16).padStart(2, '0')).join('');
  const controls = () => {
    const blocked = busy || page.getAttribute('aria-busy') === 'true';
    section.querySelectorAll('button').forEach(control => {
      control.disabled = blocked || (viewStale
        && (values.contains(control) || control === exportButton || control === more));
    });
    values.querySelectorAll('input, select, textarea').forEach(control => {
      const removal = control.tagName === 'TEXTAREA'
        && control.closest('form')?.querySelector('select')?.value !== 'set';
      control.disabled = blocked || viewStale || removal;
    });
  };
  const mutation = async (action, extra) => {
    if (viewStale || page.getAttribute('aria-busy') === 'true') throw new Error('correction_changed');
    const id = selected.draft_id;
    let acknowledged = false;
    try {
      const result = await api(action, {target, draft_id: id, draft_revision: selected.draft_revision,
        catalog_revision: selected.catalog_revision, manual_revision: selected.manual_revision,
        request_id: requestId(), ...extra});
      acknowledged = true;
      const entry = knownDrafts.get(id);
      if (!entry || result.target !== target || result.draft_id !== id
          || !Number.isInteger(result.draft_revision)) throw new Error('correction_changed');
      entry.draft.draft_revision = result.draft_revision;
      entry.revision.textContent = String(result.draft_revision);
      await inspect(entry.draft, selected.offset);
    } catch (error) {
      error.correctionPhase = acknowledged ? 'refresh' : 'decision'; throw error;
    }
  };
  const button = (text, action) => {
    const control = document.createElement('button');
    control.type = 'button'; control.className = 'lb-button'; control.textContent = text;
    control.addEventListener('click', () => void run(action));
    return control;
  };
  const applyLocal = async (item, offset) => {
    if (viewStale || page.getAttribute('aria-busy') === 'true') throw new Error('correction_changed');
    const complete = await api('knx_correction_inspect', {target, draft_id: selected.draft_id,
      draft_revision: selected.draft_revision, offset, detail: true});
    const change = complete.changes[0];
    if (!change || change.change_id !== item.change_id || change.decision !== 'accepted'
        || complete.catalog_stale || complete.manual_stale
        || !['not_required', 'not_checked'].includes(complete.project_status))
      throw new Error('correction_changed');
    const question = `${section.dataset.confirmApply}\n${change.identity} · ${change.field} / ${change.operation}\n`
      + `${display(change.manual)} → ${display(change.proposed)}`;
    if (!await window.MCPKnx.ask(question)) return;
    updatePending({target, draft_id: selected.draft_id, draft_revision: selected.draft_revision,
      catalog_revision: selected.catalog_revision, manual_revision: selected.manual_revision,
      request_id: requestId(), approved_change_ids: [change.change_id],
      storage: change.kind === 'prefix' ? 'prefix_labels' : 'addresses', confirmed: true,
      use_project_evidence: Boolean(selected.project_binding_digest)});
    // Once sent, retain only reconciliation. Never automatically repeat an uncertain write.
    let result;
    const {use_project_evidence, ...parameters} = pendingApply;
    try { result = await api('knx_correction_apply', {...parameters, action: 'apply'}, use_project_evidence); }
    catch (error) {
      const rejected = ['knx_revision_conflict', 'knx_target_conflict', 'knx_correction_invalid',
        'knx_correction_not_accepted', 'knx_draft_unavailable', 'knx_draft_expired',
        'knx_project_evidence_required', 'knx_project_evidence_changed', 'knx_label_limit',
        'knx_correction_receipt_limit'];
      if (rejected.includes(error.code)) updatePending(null);
      throw error;
    }
    if (result.outcome !== 'applied') throw new Error('correction_uncertain');
    updatePending(null);
    await reload();
    status.textContent = section.dataset.applied;
  };
  const editor = async (container, item, offset) => {
    const complete = item.proposed?.truncated === false ? item
      : (await api('knx_correction_inspect', {target, draft_id: selected.draft_id,
        draft_revision: selected.draft_revision, offset, detail: true})).changes[0];
    if (!complete || complete.change_id !== item.change_id) throw new Error('correction_changed');
    container.textContent = '';
    const form = document.createElement('form'); form.className = 'mcp-form';
    const operationLabel = document.createElement('label');
    operationLabel.className = 'mcp-field';
    operationLabel.textContent = section.dataset.operation;
    const operation = document.createElement('select');
    for (const [value, text] of [['set', section.dataset.set],
      ...(item.destination === 'local_metadata' ? [['remove_override', section.dataset.remove]] : [])]) {
      const option = document.createElement('option'); option.value = value; option.textContent = text;
      operation.append(option);
    }
    operation.value = complete.operation; operationLabel.append(operation);
    const valueLabel = document.createElement('label'); valueLabel.className = 'mcp-field';
    valueLabel.textContent = section.dataset.valueLabel;
    const value = document.createElement('textarea'); value.rows = 3;
    value.maxLength = item.field === 'description' ? 4096 : item.field === 'label' ? 80 : 255;
    value.value = complete.proposed.state === 'missing' ? '' : complete.proposed.value;
    valueLabel.append(value);
    const toggle = () => { value.disabled = operation.value !== 'set'; };
    operation.addEventListener('change', toggle); toggle();
    const save = document.createElement('button'); save.type = 'submit'; save.className = 'lb-button';
    save.textContent = section.dataset.saveEdit;
    form.append(operationLabel, valueLabel, save);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      const edit = {operation: operation.value};
      if (edit.operation === 'set') edit.value = value.value;
      void run(() => mutation('knx_correction_edit', {change_id: item.change_id, edit}));
    });
    container.append(form); value.focus();
  };
  const run = async (operation) => {
    if (busy) return;
    busy = true; section.setAttribute('aria-busy', 'true');
    loading.hidden = false; announcement.textContent = announcement.dataset.loading;
    controls();
    try { await operation(); section.dataset.loadFailed = String(viewStale); }
    catch (error) {
      section.dataset.loadFailed = 'true'; viewStale = Boolean(selected);
      status.textContent = error.correctionPhase === 'refresh' ? section.dataset.savedRefreshFailed
        : error.correctionPhase === 'decision' ? section.dataset.decisionUnconfirmed : section.dataset.failed;
    }
    finally {
      loading.hidden = true; announcement.textContent = '';
      busy = false; section.removeAttribute('aria-busy');
      controls();
    }
  };
  const inspect = async (draft, offset = 0) => {
    rememberSelection(draft, offset);
    const data = await api('knx_correction_inspect', {target, draft_id: draft.draft_id,
      draft_revision: draft.draft_revision, offset});
    if (!selected || selected.draft_id !== data.draft.draft_id
        || selected.draft_revision !== data.draft.draft_revision) exportSelection.clear();
    selected = {...data.draft, next_offset: data.next_offset, offset}; viewStale = false;
    values.textContent = '';
    values.dataset.emptyMessage = section.dataset.noChanges;
    for (const [index, item] of data.changes.entries()) {
      const row = document.createElement('tr');
      for (const value of [item.identity, `${item.field} / ${item.operation}`, item.destination,
        display(item.imported), display(item.manual), display(item.proposed)]) cell(row, value);
      cell(row, section.dataset[item.decision || 'proposed']);
      const actions = document.createElement('td');
      if (!data.catalog_stale && !data.manual_stale) {
        if (item.decision === 'accepted' && item.destination === 'ets_export') {
          const choice = document.createElement('input'); choice.type = 'checkbox';
          choice.setAttribute('aria-label', `${section.dataset.selectExport}: ${item.identity} · ${item.field}`);
          choice.checked = exportSelection.has(item.change_id);
          choice.addEventListener('change', () => {
            if (choice.checked) exportSelection.add(item.change_id); else exportSelection.delete(item.change_id);
            exportButton.hidden = !exportSelection.size;
          });
          actions.append(choice);
        }
        if (!pendingApply && ['not_required', 'not_checked'].includes(data.project_status) && item.decision === 'accepted'
            && item.destination === 'local_metadata') {
          actions.append(button(section.dataset.applyLocal, () => applyLocal(item, offset + index)));
        }
        for (const decision of ['accepted', 'rejected', 'proposed']) {
          const text = {accepted: section.dataset.accept, rejected: section.dataset.reject,
            proposed: section.dataset.reset}[decision];
          actions.append(button(text, () => mutation('knx_correction_review',
            {decisions: [{change_id: item.change_id, decision}]})));
        }
        const edit = document.createElement('details');
        const summary = document.createElement('summary'); summary.textContent = section.dataset.edit;
        const content = document.createElement('div'); edit.append(summary, content);
        edit.addEventListener('toggle', () => {
          if (!viewStale && edit.open && !content.childElementCount) void run(() => editor(content, item, offset + index));
        });
        actions.append(edit);
      }
      row.append(actions);
      values.append(row);
    }
    status.textContent = [data.catalog_stale || data.manual_stale ? section.dataset.stale : '',
      data.project_status === 'not_checked' ? section.dataset.unchecked : ''].filter(Boolean).join(' ');
    more.hidden = data.next_offset === null;
    exportButton.hidden = !exportSelection.size || data.catalog_stale || data.manual_stale;
  };
  const renderDrafts = (data) => {
    const keepView = selected && data.target === target
      && data.drafts.some(item => item.draft_id === selected.draft_id);
    target = data.target; list.textContent = ''; knownDrafts.clear();
    if (!keepView) { selected = null; values.textContent = ''; }
    viewStale = Boolean(keepView);
    exportSelection.clear(); exportButton.hidden = true;
    values.dataset.emptyMessage = section.dataset.selectDraft;
    more.hidden = true; status.textContent = '';
    for (const draft of data.drafts) {
      const row = document.createElement('tr');
      for (const value of [draft.draft_id.slice(0, 12), draft.draft_revision,
        new Date(draft.expires_at * 1000).toLocaleString(), draft.change_count]) cell(row, value);
      knownDrafts.set(draft.draft_id, {draft, revision: row.children[1]});
      const td = document.createElement('td');
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'lb-button'; button.textContent = section.dataset.inspect;
      button.addEventListener('click', () => void run(() => inspect(draft)));
      td.append(button); row.append(td); list.append(row);
    }
    return data.drafts;
  };
  const restoreSelection = async (drafts) => {
    if (!savedSelection) return;
    const draft = savedSelection.target === target
      ? drafts.find(item => item.draft_id === savedSelection.draft_id) : null;
    if (!draft) {
      rememberSelection(); status.textContent = section.dataset.selectionUnavailable; return;
    }
    const offset = savedSelection.offset < draft.change_count ? savedSelection.offset : 0;
    try { await inspect(draft, offset); }
    catch (error) {
      if (!['knx_draft_unavailable', 'knx_draft_expired'].includes(error.code)) throw error;
      selected = null; values.textContent = ''; more.hidden = true; exportButton.hidden = true;
      viewStale = false;
      rememberSelection(); status.textContent = section.dataset.selectionUnavailable;
    }
  };
  const reload = async (restore = true) => {
    const drafts = renderDrafts(await api('knx_correction_page', target ? {target} : {}));
    if (restore) await restoreSelection(drafts);
    return drafts;
  };
  more.addEventListener('click', () => { if (selected) void run(() => inspect(selected, selected.next_offset)); });
  document.getElementById('knx-corrections-reload').addEventListener('click', () => void run(reload));
  exportButton.addEventListener('click', () => void run(async () => {
    if (!selected || !exportSelection.size || viewStale || page.getAttribute('aria-busy') === 'true') return;
    const payload = {target, draft_id:selected.draft_id, draft_revision:selected.draft_revision,
      catalog_revision:selected.catalog_revision, manual_revision:selected.manual_revision,
      approved_change_ids:[...exportSelection]};
    const withProject = Boolean(selected.project_binding_digest);
    // Keep the existing XML section's cancellation available if preview response is lost.
    document.getElementById('knx-page').dispatchEvent(new CustomEvent('knx-correction-export-start'));
    const result = await api('knx_correction_xml_preview', payload, withProject);
    document.getElementById('knx-page').dispatchEvent(new CustomEvent('knx-correction-export-preview',
      {detail:{...result, use_project_evidence:withProject}}));
  }));
  reconcile.addEventListener('click', () => void run(async () => {
    if (!pendingApply) return;
    const {use_project_evidence, ...parameters} = pendingApply;
    const result = await api('knx_correction_apply', {...parameters, action: 'reconcile'});
    status.textContent = result.outcome === 'applied' ? section.dataset.applied : section.dataset.notObserved;
    if (result.outcome === 'applied') updatePending(null);
  }));
  forget.addEventListener('click', () => void run(async () => {
    if (!pendingApply || !await window.MCPKnx.ask(section.dataset.confirmForget)) return;
    updatePending(null); await reload();
  }));
  page.addEventListener('knx-idle', controls);
  new MutationObserver(controls).observe(page, {attributes: true, attributeFilter: ['aria-busy']});
  controls();
  if (window.MCPKnx?.initialSections) {
    void run(async () => {
      const initial = (await window.MCPKnx.initialSections)?.knx_correction_page;
      if (!initial?.ok) throw new Error('correction_unavailable');
      await restoreSelection(renderDrafts(initial.data));
    });
  } else void run(reload);
})();
