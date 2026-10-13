(() => {
  'use strict';
  for (const prefix of ['knx-read', 'knx-drafts', 'knx-write']) {
    const section = document.getElementById(`${prefix}-delegation`);
    if (!section) continue;
    const actionPrefix = prefix.replace('-', '_');
    const form = document.getElementById(`${prefix}-enable-form`);
    const enabled = document.getElementById(`${prefix}-enabled`);
    const rows = document.getElementById(`${prefix}-bindings`);
    const status = document.getElementById(`${prefix}-status`);
    const loading = document.getElementById(`${prefix}-loading`);
    const announcement = document.getElementById(`${prefix}-announcement`);
    const badge = document.getElementById(`${prefix}-badge`);
    let state = null;
    let busy = false;
    let backgroundBusy = false;
    let dirty = false;
    let editRevision = null;
    let timer = null;
    const queued = [];
    let bindingsFingerprint = null;
    const page = document.getElementById('knx-page');
    const controls = () => {
      const blocked = queued.length > 0 || (busy && !backgroundBusy) || page.getAttribute('aria-busy') === 'true';
      section.querySelectorAll('button, input').forEach(control => { control.disabled = blocked || !state; });
      document.getElementById(`${prefix}-reload`).disabled = blocked;
    };
    new MutationObserver(controls).observe(page, {attributes: true, attributeFilter: ['aria-busy']});
    page.addEventListener('knx-idle', controls);
    const ask = (message) => new Promise((resolve) => {
      const dialog = document.getElementById('knx-confirm');
      document.getElementById('knx-confirm-message').textContent = message;
      if (dialog.open) { resolve(false); return; }
      dialog.returnValue = 'cancel';
      dialog.addEventListener('close', () => resolve(dialog.returnValue === 'continue'), {once: true});
      dialog.showModal();
      document.getElementById('knx-confirm-cancel').focus();
    });
    const api = async (action, payload = {}, background = false) => {
      if (action === `${actionPrefix}_page` && !background) {
        loading.hidden = false;
        announcement.textContent = announcement.dataset.loading;
        status.textContent = section.dataset.loading;
      }
      const response = await fetch('knx.cgi', {
        method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
        body: new URLSearchParams({action, payload: JSON.stringify(payload)})
      });
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error('delegation_unavailable');
      return result.data;
    };
    const render = (data, background = false) => {
      state = data;
      badge.textContent = data.enabled ? section.dataset.enabled : section.dataset.disabled;
      badge.dataset.kind = data.enabled ? 'success' : 'inactive';
      if (!background || !dirty) {
        enabled.checked = data.enabled;
        dirty = false; editRevision = null;
      }
      const fingerprint = JSON.stringify(data.bindings);
      if (fingerprint === bindingsFingerprint) return;
      bindingsFingerprint = fingerprint;
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
              policy_revision: state.policy_revision, binding: item.binding}), true);
          }));
          actions.append(button);
        }
        row.append(actions); rows.append(row);
      }
    };
    const schedule = (delay = 10000) => {
      window.clearTimeout(timer);
      if (!document.hidden) timer = window.setTimeout(() => void refresh(true), delay);
    };
    const run = async (operation, background = false) => {
      if (busy) {
        if (!background) { queued.push(operation); controls(); }
        return;
      }
      if (background && page.getAttribute('aria-busy') === 'true') { schedule(); return; }
      const focused = !background && section.contains(document.activeElement) ? document.activeElement : null;
      busy = true;
      backgroundBusy = background;
      controls();
      if (!background) {
        section.setAttribute('aria-busy', 'true');
        section.querySelectorAll('button, input').forEach((control) => { control.disabled = true; });
      }
      try { await operation(); status.textContent = ''; section.dataset.loadFailed = 'false'; }
      catch (_) {
        badge.textContent = section.dataset.unknown; delete badge.dataset.kind;
        status.textContent = section.dataset.failed; section.dataset.loadFailed = 'true';
      }
      finally {
        loading.hidden = true;
        announcement.textContent = '';
        busy = false; section.removeAttribute('aria-busy');
        controls();
        if (focused) window.requestAnimationFrame(() => {
          if (focused.isConnected && !focused.disabled && document.activeElement === document.body)
            focused.focus({preventScroll: true});
        });
        schedule();
        if (queued.length) void run(queued.shift());
      }
    };
    const refresh = (background = false) => run(async () =>
      render(await api(`${actionPrefix}_page`, state ? {target: state.target} : {}, background), background), background);
    enabled.addEventListener('change', () => {
      if (!dirty) editRevision = state?.policy_revision;
      dirty = true;
    });
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      if (!state) return;
      const value = enabled.checked;
      const target = state.target;
      const revision = editRevision ?? state.policy_revision;
      void run(async () => {
        if (value && !await ask(section.dataset.confirmEnable)) {
          enabled.checked = state.enabled; dirty = false; editRevision = null; return;
        }
        render(await api(`${actionPrefix}_enable`, {target,
          policy_revision: revision, enabled: value}));
      });
    });
    document.getElementById(`${prefix}-reload`).addEventListener('click', () => {
      void refresh();
    });
    document.addEventListener('visibilitychange', () => {
      window.clearTimeout(timer);
      if (!document.hidden) schedule(0);
    });
    if (window.MCPKnx?.initialSections) {
      void run(async () => {
        loading.hidden = false;
        announcement.textContent = announcement.dataset.loading;
        const initial = (await window.MCPKnx.initialSections)?.[`${actionPrefix}_page`];
        if (!initial?.ok) throw new Error('delegation_unavailable');
        render(initial.data);
      });
    } else void refresh();
  }
})();
