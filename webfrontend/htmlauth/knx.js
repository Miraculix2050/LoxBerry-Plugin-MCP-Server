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
  let importDirty = false;
  const dirty = () => labelsDirty || recordDirty || draft !== null || importDirty;
  let draft = null;
  let editingFields = {};
  let editingImport = {};
  const touched = new Set();
  const message = (text) => { status.textContent = text; };
  const explanation = (code) => {
    const categories = {
      errorFormat: ['knx_xml_format_unsupported', 'knx_import_format_unsupported', 'knx_format_invalid'],
      errorHierarchy: ['knx_free_hierarchy_unsupported', 'knx_mixed_format_unsupported'],
      errorEncoding: ['knx_encoding_invalid', 'knx_encoding_unsupported'],
      errorFile: ['knx_file_limit', 'knx_xml_structure_limit', 'knx_address_limit', 'knx_group_limit'],
      errorUnsafe: ['knx_xml_unsafe'],
      errorXml: ['knx_xml_invalid', 'knx_xml_element_unsupported', 'knx_xml_text_unsupported'],
      errorCsv: ['knx_csv_invalid', 'knx_csv_header_unsupported', 'knx_csv_row_invalid', 'knx_csv_structure_limit'],
      errorStale: ['knx_revision_conflict', 'knx_target_conflict', 'knx_preview_changed',
        'knx_draft_expired', 'knx_session_missing'],
      errorLabels: ['knx_label_limit', 'knx_label_selection_invalid'],
      errorStorage: ['knx_storage_failed', 'knx_draft_storage_failed']
    };
    const entry = Object.entries(categories).find(([, codes]) => codes.includes(code));
    return entry ? page.dataset[entry[0]] : page.dataset.failed;
  };
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
    page.querySelectorAll('fieldset, button, input, select, textarea').forEach((e) => { e.disabled = true; });
    try { await operation(); }
    catch (error) { message(`${explanation(error.message)} (${error.message})`); }
    finally {
      busy = false;
      page.removeAttribute('aria-busy');
      if (state) page.querySelectorAll('fieldset, button, input, select, textarea').forEach((e) => { e.disabled = false; });
      document.getElementById('knx-previous').disabled = !state || state.offset === 0;
      document.getElementById('knx-next').disabled = !state || state.offset + 50 >= state.total;
      if (state) renderEditorSources();
      page.dispatchEvent(new CustomEvent('knx-idle'));
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
    document.getElementById('knx-imported-labels').textContent = (data.imported_labels || [])
      .map((e) => `${e.address_format === 'two_level' ? '2' : '3'}:${e.prefix}=${e.label}`).join('\n');
    rows.replaceChildren();
    for (const item of data.items) {
      const tr = document.createElement('tr');
      for (const value of [item.address, item.imported.name || '', item.overrides.name || '', item.effective.description || '']) {
        const td = document.createElement('td'); td.textContent = value; tr.append(td);
      }
      const actions = document.createElement('td');
      const edit = document.createElement('button');
      edit.type = 'button'; edit.textContent = page.dataset.edit;
      edit.addEventListener('click', async () => {
        if (recordDirty && !await ask(page.dataset.unsaved)) return;
        editingFields = {...item.overrides};
        editingImport = {...item.imported}; touched.clear();
        recordRevision = state.revision;
        form.elements.namedItem('address').readOnly = true;
        for (const key of ['address', 'address_format']) form.elements.namedItem(key).value = item[key];
        for (const key of ['name', 'description']) form.elements.namedItem(key).value = item.effective[key] || '';
        form.elements.namedItem('dpts').value = (item.effective.dpts || []).join(', ');
        recordDirty = false; form.elements.namedItem('name').focus();
        renderEditorSources();
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
    page.dispatchEvent(new CustomEvent('knx-state'));
  };
  const renderEditorSources = () => {
    const details = document.getElementById('knx-editor-sources');
    details.hidden = Object.keys(editingImport).length === 0;
    details.textContent = '';
    for (const key of ['name', 'description', 'dpts']) {
      const line = document.createElement('p');
      const value = Object.hasOwn(editingImport, key) ? editingImport[key] : page.dataset.unknown;
      const display = value === '' || (Array.isArray(value) && !value.length) ? page.dataset.empty : Array.isArray(value) ? value.join(', ') : value;
      const override = Object.hasOwn(editingFields, key) || touched.has(key);
      line.textContent = `${page.dataset.importSource} ${page.dataset[key]}: ${display} (${override ? page.dataset.override : page.dataset.inherited})`;
      details.append(line);
      const button = document.querySelector(`[data-knx-use-import="${key}"]`);
      button.hidden = Object.keys(editingImport).length === 0;
      button.disabled = !override || (key === 'name' && !editingImport.name);
    }
  };
  labels.addEventListener('input', () => { labelsRevision ??= state.taxonomy_revision; labelsDirty = true; });
  form.addEventListener('input', (event) => {
    recordRevision ??= state.revision; recordDirty = true;
    if (['name', 'description', 'dpts'].includes(event.target.name)) touched.add(event.target.name);
    renderEditorSources();
  });
  document.querySelectorAll('[data-knx-use-import]').forEach((button) => {
    button.addEventListener('click', () => {
      const key = button.dataset.knxUseImport;
      delete editingFields[key]; touched.delete(key);
      const value = editingImport[key];
      form.elements.namedItem(key).value = Array.isArray(value) ? value.join(', ') : value || '';
      recordRevision ??= state.revision; recordDirty = true;
      renderEditorSources(); message(page.dataset.unsaved);
    });
  });
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
    editingFields = {}; editingImport = {}; touched.clear(); recordRevision = null;
    form.elements.namedItem('address').readOnly = false; renderEditorSources();
  });
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const input = new FormData(form);
    const fields = {...editingFields};
    if (!Object.keys(editingImport).length || touched.has('name')) fields.name = input.get('name');
    if (touched.has('description')) fields.description = input.get('description');
    if (touched.has('dpts')) fields.dpts = String(input.get('dpts')).split(',').map((v) => v.trim()).filter(Boolean);
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
  window.MCPKnx = Object.freeze({api, run, ask, render, snapshot: () => state,
    setImportDirty: (value) => { importDirty = value; }, message});
  void run(async () => render(await api('knx_page')));
})();
