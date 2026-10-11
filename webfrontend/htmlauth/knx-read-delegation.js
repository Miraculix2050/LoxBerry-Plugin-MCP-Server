(() => {
  'use strict';
  for (const prefix of ['knx-read', 'knx-drafts']) {
    const section = document.getElementById(`${prefix}-delegation`);
    if (!section) continue;
    const actionPrefix = prefix.replace('-', '_');
    const form = document.getElementById(`${prefix}-enable-form`);
    const enabled = document.getElementById(`${prefix}-enabled`);
    const rows = document.getElementById(`${prefix}-bindings`);
    const status = document.getElementById(`${prefix}-status`);
    let state = null;
    let busy = false;
    const ask = (message) => new Promise((resolve) => {
      const dialog = document.getElementById('knx-confirm');
      document.getElementById('knx-confirm-message').textContent = message;
      if (dialog.open) { resolve(false); return; }
      dialog.returnValue = 'cancel';
      dialog.addEventListener('close', () => resolve(dialog.returnValue === 'continue'), {once: true});
      dialog.showModal();
      document.getElementById('knx-confirm-cancel').focus();
    });
    const api = async (action, payload = {}) => {
      const response = await fetch('knx.cgi', {
        method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
        body: new URLSearchParams({action, payload: JSON.stringify(payload)})
      });
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error('delegation_unavailable');
      return result.data;
    };
    const render = (data) => {
      state = data;
      enabled.checked = data.enabled;
      rows.textContent = '';
      for (const item of data.bindings) {
        const row = document.createElement('tr');
        const client = document.createElement('td');
        client.textContent = item.client_name || item.client || section.dataset.unavailable;
        row.append(client);
        const identity = document.createElement('td');
        const details = document.createElement('details');
        const summary = document.createElement('summary');
        summary.textContent = item.binding.slice(0, 12);
        const text = document.createElement('p');
        text.textContent = [item.client, item.identity, item.miniserver, item.binding].filter(Boolean).join(' / ');
        details.append(summary, text); identity.append(details); row.append(identity);
        const approval = document.createElement('td');
        approval.textContent = item.approved ? section.dataset.approved : section.dataset.pending;
        row.append(approval);
        const actions = document.createElement('td');
        for (const [action, available] of [['grant', item.eligible && !item.approved], ['revoke', item.retained]]) {
          if (!available) continue;
          const button = document.createElement('button');
          button.type = 'button'; button.className = 'lb-button'; button.textContent = section.dataset[action];
          button.addEventListener('click', () => void run(async () => {
            const question = action === 'grant' ? section.dataset.confirmGrant : section.dataset.confirmRevoke;
            if (!await ask(`${question}\n${client.textContent}\n${item.binding}`)) return;
            render(await api(`${actionPrefix}_${action}`, {target: state.target,
              policy_revision: state.policy_revision, binding: item.binding}));
          }));
          actions.append(button);
        }
        row.append(actions); rows.append(row);
      }
    };
    const run = async (operation) => {
      if (busy) return;
      busy = true;
      section.setAttribute('aria-busy', 'true');
      section.querySelectorAll('button, input').forEach((control) => { control.disabled = true; });
      try { await operation(); status.textContent = ''; }
      catch (_) { status.textContent = section.dataset.failed; }
      finally {
        busy = false; section.removeAttribute('aria-busy');
        section.querySelectorAll('button, input').forEach((control) => { control.disabled = !state; });
        document.getElementById(`${prefix}-reload`).disabled = false;
      }
    };
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      const value = enabled.checked;
      void run(async () => {
        if (value && !await ask(section.dataset.confirmEnable)) { enabled.checked = state.enabled; return; }
        render(await api(`${actionPrefix}_enable`, {target: state.target,
          policy_revision: state.policy_revision, enabled: value}));
      });
    });
    document.getElementById(`${prefix}-reload`).addEventListener('click', () => {
      void run(async () => render(await api(`${actionPrefix}_page`, state ? {target: state.target} : {})));
    });
    void run(async () => render(await api(`${actionPrefix}_page`)));
  }
})();
