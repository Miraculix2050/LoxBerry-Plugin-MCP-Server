// Internal Admin UI registry. Feature factories keep their state in their own closures.
window.McpAdmin = Object.create(null);
window.McpAdmin.createCore = () => {
  const labels = document.getElementById('admin-labels');
  const label = (key) => {
    const value = labels.getAttribute('data-l-' + key.toLowerCase().replace(/[._]/g, '-'));
    if (value === null) throw new Error(`Missing admin label: ${key}`);
    return value;
  };
  const status = document.getElementById('ajax-status');
  const loxberryNotifications = document.getElementById('loxberry-notifications');
  const pluginLogList = document.getElementById('plugin-log-list');
  const collapseStorageKey = 'mcpserver.admin.sections.v2';
  const collapsibles = [...document.querySelectorAll('details[data-persist-collapse]')];
  // collapse-state-migration-start
  const readCollapseState = () => {
    try {
      const storage = window.localStorage;
      const current = storage.getItem(collapseStorageKey);
      if (current !== null) {
        const state = JSON.parse(current);
        return state && typeof state === 'object' && !Array.isArray(state) ? state : {};
      }
      const legacy = JSON.parse(storage.getItem('mcpserver.admin.sections.v1') || '{}');
      if (!legacy || typeof legacy !== 'object' || Array.isArray(legacy)) return {};
      const migrated = { ...legacy };
      if (typeof legacy.setup === 'boolean') migrated.configuration = legacy.setup;
      if (typeof legacy.certificate === 'boolean' || typeof legacy.help === 'boolean') {
        migrated.access = legacy.certificate === true || legacy.help === true;
      }
      return migrated;
    } catch {
      return {};
    }
  };
  // collapse-state-migration-end
  const storedCollapseState = readCollapseState();
  const persistCollapsibles = () => {
    const state = Object.fromEntries(collapsibles.map((element) => [element.id, element.open]));
    try { window.localStorage.setItem(collapseStorageKey, JSON.stringify(state)); } catch { /* Defaults remain usable. */ }
  };
  for (const element of collapsibles) {
    if (typeof storedCollapseState[element.id] === 'boolean') element.open = storedCollapseState[element.id];
    element.addEventListener('toggle', persistCollapsibles);
  }
  const openHashSection = (hash = window.location.hash, respectClosedState = false) => {
    const fragment = hash.slice(1);
    const sectionId = { setup: 'configuration', certificate: 'access' }[fragment] || fragment;
    if (respectClosedState && storedCollapseState[sectionId] === false) return;
    const target = document.getElementById(sectionId);
    if (target instanceof HTMLDetailsElement && !target.open) {
      target.open = true;
      persistCollapsibles();
    }
  };
  window.addEventListener('hashchange', () => openHashSection());
  document.addEventListener('click', (event) => {
    const anchor = event.target instanceof Element ? event.target.closest('a[href^="#"]') : null;
    if (anchor) openHashSection(anchor.hash);
  });
  openHashSection(
    window.location.hash,
    window.performance?.getEntriesByType?.('navigation')?.[0]?.type === 'reload',
  );
  let pageIsUnloading = false;
  const markPageUnloading = () => { pageIsUnloading = true; };
  window.addEventListener('beforeunload', markPageUnloading);
  window.addEventListener('pagehide', markPageUnloading);
  window.addEventListener('pageshow', () => { pageIsUnloading = false; });
  const setSummaryBadge = (badge, label, kind = '') => {
    badge.textContent = label;
    if (kind) badge.dataset.kind = kind;
    else delete badge.dataset.kind;
  };
  const expiryFormatter = new Intl.DateTimeFormat(document.documentElement.lang || undefined, {
    dateStyle: 'medium',
    timeStyle: 'medium',
  });
  const MAX_EXPIRY_EPOCH = 4102444799;
  const parseExpiry = (raw) => {
    if (!/^(?:0|[1-9][0-9]*)$/.test(raw) || raw.length > 10) return null;
    const value = Number(raw);
    return Number.isSafeInteger(value) && value <= MAX_EXPIRY_EPOCH ? value : null;
  };
  const updateExpiry = (element, raw) => {
    element.dataset.expiresAt = String(raw ?? '');
    const expiresAt = parseExpiry(element.dataset.expiresAt);
    if (expiresAt !== null) {
      const date = new Date(expiresAt * 1000);
      element.dateTime = date.toISOString();
      element.textContent = expiryFormatter.format(date);
    } else {
      element.removeAttribute('datetime');
      element.textContent = String(raw ?? '');
    }
  };
  for (const element of document.querySelectorAll('time.mcp-expiry')) {
    if (element.dataset.expiresAt) updateExpiry(element, element.dataset.expiresAt);
  }
  const hideStatusTimers = new WeakMap();
  const hideSuccess = (element, defer = () => false) => {
    window.clearTimeout(hideStatusTimers.get(element));
    const hide = () => {
      if (defer()) {
        hideStatusTimers.set(element, window.setTimeout(hide, 4000));
        return;
      }
      if (element.dataset.kind === 'success') element.hidden = true;
    };
    hideStatusTimers.set(element, window.setTimeout(hide, 4000));
  };
  const setAjaxStatus = (kind, message) => {
    window.clearTimeout(hideStatusTimers.get(status));
    status.hidden = false;
    status.dataset.kind = kind;
    status.textContent = message;
  };
  const pageNotice = document.getElementById('page-notice');
  if (pageNotice) {
    const url = new URL(window.location.href);
    url.searchParams.delete('notice');
    window.history.replaceState(null, '', url);
    if (pageNotice.dataset.kind === 'success') hideSuccess(pageNotice);
  }
  for (const button of document.querySelectorAll('button[data-copy-target]')) {
    button.addEventListener('click', async () => {
      const input = document.getElementById(button.dataset.copyTarget);
      if (!input) return;
      try {
        await navigator.clipboard.writeText(input.value);
      } catch {
        input.focus();
        input.select();
        document.execCommand('copy');
      }
      const previous = button.textContent;
      button.textContent = label('ACTION.COPIED');
      window.setTimeout(() => { button.textContent = previous; }, 2000);
    });
  }
  const postAjax = async (body, timeoutMs, suppliedResult) => {
    if (suppliedResult !== undefined) {
      if (!suppliedResult?.ok) throw new Error(label('AJAX.ERROR'));
      return suppliedResult;
    }
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch('index.cgi', {
        method: 'POST',
        body,
        signal: controller.signal,
        headers: {'X-Requested-With': 'XMLHttpRequest'},
      });
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.error?.message || label('AJAX.ERROR'));
      return result;
    } finally {
      window.clearTimeout(timeout);
    }
  };
  const updatePageAuxiliaryContent = (element, markup) => {
    // This value is generated by a LoxBerry server-side helper and was
    // previously inserted verbatim during the initial CGI render.
    element.innerHTML = typeof markup === 'string' ? markup : '';
    element.setAttribute('aria-busy', 'false');
  };
  const showPageAuxiliaryError = (element, message) => {
    element.textContent = message;
    element.classList.add('mcp-status');
    element.dataset.kind = 'error';
    element.setAttribute('aria-busy', 'false');
  };
  const loadLoxberryNotifications = async (suppliedResult) => {
    const body = new URLSearchParams();
    body.set('action', 'page_notifications');
    body.set('ajax', '1');
    try {
      const result = await postAjax(body, 15000, suppliedResult);
      if (pageIsUnloading) return;
      updatePageAuxiliaryContent(loxberryNotifications, result.data.notifications_html);
      loxberryNotifications.hidden = !loxberryNotifications.innerHTML.trim();
    } catch {
      if (pageIsUnloading) return;
      loxberryNotifications.hidden = false;
      showPageAuxiliaryError(loxberryNotifications, label('AJAX.NOTIFICATIONS_ERROR'));
    }
  };
  const loadPluginLogList = async (suppliedResult) => {
    const body = new URLSearchParams();
    body.set('action', 'page_loglist');
    body.set('ajax', '1');
    try {
      const result = await postAjax(body, 15000, suppliedResult);
      if (pageIsUnloading) return;
      updatePageAuxiliaryContent(pluginLogList, result.data.loglist_html);
    } catch {
      if (pageIsUnloading) return;
      showPageAuxiliaryError(pluginLogList, label('DIAGNOSTICS.LOGLIST_ERROR'));
    }
  };
  return {
    label, postAjax, setAjaxStatus, hideSuccess, setSummaryBadge,
    parseExpiry, updateExpiry, expiryFormatter, loadLoxberryNotifications, loadPluginLogList,
    status, get unloading() { return pageIsUnloading; },
  };
};
