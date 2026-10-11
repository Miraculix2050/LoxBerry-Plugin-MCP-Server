(() => {
  'use strict';
  const section = document.getElementById('knx-corrections');
  if (!section) return;
  const list = document.getElementById('knx-corrections-list');
  const values = document.getElementById('knx-corrections-values');
  const status = document.getElementById('knx-corrections-status');
  const more = document.getElementById('knx-corrections-more');
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
  const run = async (operation) => {
    if (busy) return;
    busy = true; section.setAttribute('aria-busy', 'true');
    section.querySelectorAll('button').forEach((button) => { button.disabled = true; });
    try { await operation(); }
    catch (_) { status.textContent = section.dataset.failed; selected = null; values.textContent = ''; more.hidden = true; }
    finally {
      busy = false; section.removeAttribute('aria-busy');
      section.querySelectorAll('button').forEach((button) => { button.disabled = false; });
    }
  };
  const inspect = async (draft, offset = 0) => {
    const data = await api('knx_correction_inspect', {target, draft_id: draft.draft_id,
      draft_revision: draft.draft_revision, offset});
    selected = {...data.draft, next_offset: data.next_offset};
    values.textContent = '';
    for (const item of data.changes) {
      const row = document.createElement('tr');
      for (const value of [item.identity, `${item.field} / ${item.operation}`, item.destination,
        display(item.imported), display(item.manual), display(item.proposed)]) cell(row, value);
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
  };
  more.addEventListener('click', () => { if (selected) void run(() => inspect(selected, selected.next_offset)); });
  document.getElementById('knx-corrections-reload').addEventListener('click', () => void run(reload));
  void run(reload);
})();
