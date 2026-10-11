(() => {
  'use strict';
  const section = document.getElementById('knx-corrections');
  if (!section) return;
  const list = document.getElementById('knx-corrections-list');
  const values = document.getElementById('knx-corrections-values');
  const status = document.getElementById('knx-corrections-status');
  const more = document.getElementById('knx-corrections-more');
  const loading = document.getElementById('knx-corrections-loading');
  const announcement = document.getElementById('knx-corrections-announcement');
  let target = null;
  let selected = null;
  let busy = false;
  const api = async (action, payload) => {
    const response = await fetch('knx.cgi', {method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      body: new URLSearchParams({action, payload: JSON.stringify(payload)})});
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error('correction_unavailable');
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
  const mutation = async (action, extra) => {
    const id = selected.draft_id;
    await api(action, {target, draft_id: id, draft_revision: selected.draft_revision,
      catalog_revision: selected.catalog_revision, manual_revision: selected.manual_revision,
      request_id: requestId(), ...extra});
    const drafts = await reload();
    const updated = drafts.find((draft) => draft.draft_id === id);
    if (updated) await inspect(updated);
  };
  const button = (text, action) => {
    const control = document.createElement('button');
    control.type = 'button'; control.className = 'lb-button'; control.textContent = text;
    control.addEventListener('click', () => void run(action));
    return control;
  };
  const editor = async (container, item, offset) => {
    const data = await api('knx_correction_inspect', {target, draft_id: selected.draft_id,
      draft_revision: selected.draft_revision, offset, detail: true});
    const complete = data.changes[0];
    if (!complete || complete.change_id !== item.change_id) throw new Error('correction_changed');
    container.textContent = '';
    const form = document.createElement('form');
    const operationLabel = document.createElement('label');
    operationLabel.textContent = section.dataset.operation;
    const operation = document.createElement('select');
    for (const [value, text] of [['set', section.dataset.set],
      ...(item.destination === 'local_metadata' ? [['remove_override', section.dataset.remove]] : [])]) {
      const option = document.createElement('option'); option.value = value; option.textContent = text;
      operation.append(option);
    }
    operation.value = complete.operation; operationLabel.append(operation);
    const valueLabel = document.createElement('label'); valueLabel.textContent = section.dataset.proposed;
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
    section.querySelectorAll('button').forEach((button) => { button.disabled = true; });
    try { await operation(); }
    catch (_) { status.textContent = section.dataset.failed; selected = null; values.textContent = ''; more.hidden = true; }
    finally {
      loading.hidden = true; announcement.textContent = '';
      busy = false; section.removeAttribute('aria-busy');
      section.querySelectorAll('button').forEach((button) => { button.disabled = false; });
    }
  };
  const inspect = async (draft, offset = 0) => {
    const data = await api('knx_correction_inspect', {target, draft_id: draft.draft_id,
      draft_revision: draft.draft_revision, offset});
    selected = {...data.draft, next_offset: data.next_offset};
    values.textContent = '';
    for (const [index, item] of data.changes.entries()) {
      const row = document.createElement('tr');
      for (const value of [item.identity, `${item.field} / ${item.operation}`, item.destination,
        display(item.imported), display(item.manual), display(item.proposed)]) cell(row, value);
      cell(row, section.dataset[item.decision || 'proposed']);
      const actions = document.createElement('td');
      if (!data.catalog_stale && !data.manual_stale) {
        for (const decision of ['accepted', 'rejected', 'proposed']) {
          actions.append(button(section.dataset[decision], () => mutation('knx_correction_review',
            {decisions: [{change_id: item.change_id, decision}]})));
        }
        const edit = document.createElement('details');
        const summary = document.createElement('summary'); summary.textContent = section.dataset.edit;
        const content = document.createElement('div'); edit.append(summary, content);
        edit.addEventListener('toggle', () => {
          if (edit.open && !content.childElementCount) void run(() => editor(content, item, offset + index));
        });
        actions.append(edit);
      }
      row.append(actions);
      values.append(row);
    }
    status.textContent = [data.catalog_stale || data.manual_stale ? section.dataset.stale : '',
      data.project_status === 'not_checked' ? section.dataset.unchecked : ''].filter(Boolean).join(' ');
    more.hidden = data.next_offset === null;
  };
  const reload = async () => {
    const data = await api('knx_correction_page', target ? {target} : {});
    target = data.target; selected = null; list.textContent = ''; values.textContent = '';
    more.hidden = true; status.textContent = '';
    for (const draft of data.drafts) {
      const row = document.createElement('tr');
      for (const value of [draft.draft_id.slice(0, 12), draft.draft_revision,
        new Date(draft.expires_at * 1000).toLocaleString(), draft.change_count]) cell(row, value);
      const td = document.createElement('td');
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'lb-button'; button.textContent = section.dataset.inspect;
      button.addEventListener('click', () => void run(() => inspect(draft)));
      td.append(button); row.append(td); list.append(row);
    }
    return data.drafts;
  };
  more.addEventListener('click', () => { if (selected) void run(() => inspect(selected, selected.next_offset)); });
  document.getElementById('knx-corrections-reload').addEventListener('click', () => void run(reload));
  void run(reload);
})();
