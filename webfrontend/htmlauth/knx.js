(() => {
  'use strict';
  const page = document.getElementById('knx-page');
  const status = document.getElementById('knx-status');
  const form = document.getElementById('knx-record-form');
  const labels = document.getElementById('knx-taxonomy-form');
  const textarea = document.getElementById('knx-taxonomy-entries');
  const rows = document.getElementById('knx-addresses');
  const dialog = document.getElementById('knx-confirm');
  const ask = (text) => new Promise((resolve) => {
    document.getElementById('knx-confirm-message').textContent = text;
    dialog.returnValue = 'cancel';
    dialog.addEventListener('close', () => resolve(dialog.returnValue === 'continue'), {once: true});
    dialog.showModal();
    document.getElementById('knx-confirm-cancel').focus();
  });
  let state = null;
  let busy = false;
  let labelsDirty = false;
  let recordDirty = false;
  let recordRevision = null;
  let labelsRevision = null;
  const dirty = () => labelsDirty || recordDirty || draft !== null;
  let draft = null;
  let editingFields = {};
  const message = (text) => { status.textContent = text; };
  const api = async (action, payload = {}) => {
    const response = await fetch('knx.cgi', {method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      body: new URLSearchParams({action, payload: JSON.stringify(payload)})});
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error?.code || 'request_failed');
    return result.data;
  };
  const run = async (operation) => {
    if (busy) return;
    busy = true;
    page.setAttribute('aria-busy', 'true');
    page.querySelectorAll('fieldset, button, input[type=file]').forEach((e) => { e.disabled = true; });
    try { await operation(); }
    catch (error) { message(`${page.dataset.failed} (${error.message})`); }
    finally {
      busy = false;
      page.removeAttribute('aria-busy');
      if (state) page.querySelectorAll('fieldset, button, input[type=file]').forEach((e) => { e.disabled = false; });
      document.getElementById('knx-previous').disabled = !state || state.offset === 0;
      document.getElementById('knx-next').disabled = !state || state.offset + 50 >= state.total;
    }
  };
  const download = (content, name, type) => {
    const url = URL.createObjectURL(new Blob([content], {type}));
    const link = document.createElement('a');
    link.href = url; link.download = name; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const render = (data) => {
    if (state && state.target !== data.target && (dirty() || form.elements.namedItem('address').readOnly)) {
      throw new Error('knx_target_conflict');
    }
    state = data;
    if (!labelsDirty) textarea.value = data.taxonomy.map((e) => `${e.address_format === 'two_level' ? '2' : '3'}:${e.prefix}=${e.label}`).join('\n');
    rows.replaceChildren();
    for (const item of data.items) {
      const tr = document.createElement('tr');
      for (const value of [item.address, item.effective.name, item.effective.description || '']) {
        const td = document.createElement('td'); td.textContent = value; tr.append(td);
      }
      const actions = document.createElement('td');
      const edit = document.createElement('button');
      edit.type = 'button'; edit.textContent = page.dataset.edit;
      edit.addEventListener('click', async () => {
        if (recordDirty && !await ask(page.dataset.unsaved)) return;
        editingFields = {...item.overrides};
        recordRevision = state.revision;
        form.elements.namedItem('address').readOnly = true;
        for (const key of ['address', 'address_format']) form.elements.namedItem(key).value = item[key];
        for (const key of ['name', 'description']) form.elements.namedItem(key).value = item.effective[key] || '';
        form.elements.namedItem('dpts').value = (item.effective.dpts || []).join(', ');
        recordDirty = false; form.elements.namedItem('name').focus();
      });
      const remove = document.createElement('button');
      remove.type = 'button'; remove.textContent = page.dataset.delete;
      remove.addEventListener('click', async () => {
        if (!await ask(`${page.dataset.confirm} ${item.address}`)) return;
        void run(async () => {
          render(await api('knx_delete', {target: state.target, revision: state.revision,
            address_id: item.address_id, offset: Math.max(0, state.offset - (state.items.length === 1 ? 50 : 0))}));
          message(page.dataset.saved);
        });
      });
      actions.append(edit, remove); tr.append(actions); rows.append(tr);
    }
    document.getElementById('knx-count').textContent = `${data.offset + (data.total ? 1 : 0)}\u2013${Math.min(data.offset + 50, data.total)} / ${data.total}`;
  };
  labels.addEventListener('input', () => { labelsRevision ??= state.taxonomy_revision; labelsDirty = true; });
  form.addEventListener('input', () => { recordRevision ??= state.revision; recordDirty = true; });
  document.getElementById('knx-back').addEventListener('click', async (event) => {
    const href = event.currentTarget.href;
    if (busy || dirty()) event.preventDefault();
    if (busy || !dirty()) return;
    if (await ask(page.dataset.unsaved)) window.location.assign(href);
  });
  form.addEventListener('reset', (event) => {
    if (recordDirty) {
      event.preventDefault();
      void ask(page.dataset.unsaved).then((accepted) => {
        if (accepted) { recordDirty = false; form.reset(); }
      });
      return;
    }
    editingFields = {}; recordRevision = null; form.elements.namedItem('address').readOnly = false;
  });
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const input = new FormData(form);
    const fields = {...editingFields, name: input.get('name'), description: input.get('description'),
      dpts: String(input.get('dpts')).split(',').map((v) => v.trim()).filter(Boolean)};
    void run(async () => {
      render(await api('knx_put', {target: state.target, revision: recordRevision ?? state.revision,
        offset: state.offset, record: {address: input.get('address'), address_format: input.get('address_format'), fields}}));
      recordDirty = false; form.reset(); message(page.dataset.saved);
    });
  });
  labels.addEventListener('submit', (event) => {
    event.preventDefault();
    const entries = textarea.value.split(/\r?\n/).filter(Boolean).map((line) => {
      const match = /^([23]):([^=]+)=(.*)$/.exec(line);
      return match ? {address_format: match[1] === '2' ? 'two_level' : 'three_level', prefix: match[2], label: match[3]} : {};
    });
    void run(async () => {
      const data = await api('knx_taxonomy', {target: state.target, taxonomy_revision: labelsRevision ?? state.taxonomy_revision, entries, offset: state.offset});
      labelsDirty = false; labelsRevision = null; render(data); message(page.dataset.saved);
    });
  });
  for (const [id, direction] of [['knx-previous', -50], ['knx-next', 50]]) {
    document.getElementById(id).addEventListener('click', () => {
      void run(async () => { render(await api('knx_page', {offset: state.offset + direction})); });
    });
  }
  document.getElementById('knx-label-export').addEventListener('click', () => download(textarea.value, 'knx-address-labels.txt', 'text/plain;charset=utf-8'));
  document.getElementById('knx-label-import').addEventListener('change', (event) => {
    const file = event.target.files[0]; event.target.value = '';
    if (!file) return;
    void run(async () => {
      if (file.size > 64 * 1024) throw new Error('file_too_large');
      const content = new TextDecoder('utf-8', {fatal: true}).decode(await file.arrayBuffer());
      if (content.length > 16384 || content.includes('\0')) throw new Error('invalid_file');
      textarea.value = content; labelsRevision ??= state.taxonomy_revision; labelsDirty = true; message(page.dataset.unsaved);
    });
  });
  document.getElementById('knx-json-export').addEventListener('click', () => void run(async () => {
    const result = await api('knx_export', {offset: state.offset});
    download(JSON.stringify(result.document, null, 2), 'knx-metadata.json', 'application/json');
  }));
  document.getElementById('knx-json-import').addEventListener('change', (event) => {
    const file = event.target.files[0]; event.target.value = '';
    draft = null; document.getElementById('knx-json-apply').hidden = true;
    if (!file) return;
    void run(async () => {
      if (file.size > 16 * 1024 * 1024) throw new Error('file_too_large');
      const documentData = JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(await file.arrayBuffer()));
      if (documentData.schema_version !== 1 || !Array.isArray(documentData.records)) throw new Error('invalid_file');
      const preview = await api('knx_preview', {document: documentData, target: state.target});
      draft = {document: documentData, target: preview.target, revision: preview.revision};
      document.getElementById('knx-json-preview').textContent = JSON.stringify(preview, null, 2);
      document.getElementById('knx-json-apply').hidden = false;
      message(page.dataset.unsaved);
    });
  });
  document.getElementById('knx-json-apply').addEventListener('click', () => void run(async () => {
    render(await api('knx_restore', draft)); draft = null;
    document.getElementById('knx-json-apply').hidden = true;
    document.getElementById('knx-json-preview').textContent = '';
    message(page.dataset.saved);
  }));
  void run(async () => render(await api('knx_page')));
})();
