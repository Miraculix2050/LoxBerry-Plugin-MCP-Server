(() => {
  'use strict';
  const page = document.getElementById('knx-page');
  // Keep row nodes (and their input state/listeners) intact when sorting small tables.
  const tables = (() => {
    const key = 'mcp-knx-table-order-v1', orders = new Map(), handlers = new Map();
    const collator = new Intl.Collator(document.documentElement.lang || undefined, {numeric:true, sensitivity:'base'});
    let retained = {};
    try { const raw = sessionStorage.getItem(key); if (raw?.length < 4096) retained = JSON.parse(raw); }
    catch (_) { /* Sorting remains usable without browser storage. */ }
    const persist = () => {
      try { sessionStorage.setItem(key, JSON.stringify(Object.fromEntries(orders))); }
      catch (_) { /* Preferences are optional. */ }
    };
    const get = id => orders.get(id) || null;
    const local = (body) => {
      const order = get(body.id);
      if (!order || handlers.has(body.id)) return;
      const rows = [...body.rows];
      const value = row => {
        const cell = row.cells[order.column];
        if (cell?.dataset.sortValue !== undefined) return cell.dataset.sortValue;
        const control = cell?.querySelector('input,textarea,select');
        return control?.type === 'checkbox' ? Number(control.checked) : control?.value ?? cell?.textContent ?? '';
      };
      const sorted = [...rows].sort((a,b) => (order.direction === 'ascending' ? 1 : -1)
        * collator.compare(String(value(a)), String(value(b))));
      if (sorted.some((row,index) => row !== rows[index])) body.append(...sorted);
    };
    for (const body of page.querySelectorAll('table tbody[id]')) {
      const headings = body.closest('table').querySelectorAll('thead th');
      const prior = retained?.[body.id];
      if (Number.isInteger(prior?.column) && prior.column >= 0 && prior.column < headings.length
          && !headings[prior.column].hasAttribute('data-knx-unsortable')
          && ['ascending','descending'].includes(prior.direction)) orders.set(body.id, prior);
      const sync = () => headings.forEach((heading,index) => {
        const active = get(body.id)?.column === index;
        if (active) heading.setAttribute('aria-sort', get(body.id).direction);
        else heading.removeAttribute('aria-sort');
        const control = heading.querySelector('button');
        if (control) control.setAttribute('aria-label', `${page.dataset.sortBy} ${control.textContent.trim()}, `
          + (active && get(body.id).direction === 'ascending' ? page.dataset.sortDescending : page.dataset.sortAscending));
      });
      headings.forEach((heading,column) => {
        if (heading.hasAttribute('data-knx-unsortable')) return;
        const control = document.createElement('button');
        control.type = 'button'; control.className = 'mcp-knx-sort';
        control.textContent = heading.textContent;
        heading.replaceChildren(control);
        control.addEventListener('click', async () => {
          if (page.getAttribute('aria-busy') === 'true'
              || body.closest('[aria-busy="true"]')) return;
          const previous = get(body.id);
          orders.set(body.id, {column, direction:previous?.column === column
            && previous.direction === 'ascending' ? 'descending' : 'ascending'});
          sync(); persist();
          if (handlers.has(body.id)) {
            let applied = false;
            try { applied = await handlers.get(body.id)() !== false; }
            catch (_) { /* The owning section reports its read error. */ }
            if (!applied) {
              if (previous) orders.set(body.id,previous); else orders.delete(body.id);
              sync(); persist();
            }
          } else local(body);
        });
      });
      sync();
      new MutationObserver(() => local(body)).observe(body, {childList:true,subtree:true,characterData:true});
    }
    return Object.freeze({get, bind:(id, handler) => handlers.set(id, handler),
      selection:(id,fields) => { const order=get(id); return order
        ? {field:fields[order.column],direction:order.direction} : null; }});
  })();
  let resolveInitialSections;
  let initialGroupPage = null;
  const initialSections = new Promise(resolve => { resolveInitialSections = resolve; });
  const collapseStorageKey = 'mcpserver.knx.sections.v1';
  const collapsibles = [...page.querySelectorAll('details[data-persist-collapse]')];
  let storedCollapseState = {};
  try {
    const value = JSON.parse(window.localStorage.getItem(collapseStorageKey) || '{}');
    if (value && typeof value === 'object' && !Array.isArray(value)) storedCollapseState = value;
  } catch { /* Defaults remain usable when browser storage is unavailable. */ }
  const persistCollapsibles = () => {
    const state = Object.fromEntries(collapsibles.map((element) => [element.id, element.open]));
    try { window.localStorage.setItem(collapseStorageKey, JSON.stringify(state)); }
    catch { /* Toggling remains usable without browser storage. */ }
  };
  for (const element of collapsibles) {
    if (typeof storedCollapseState[element.id] === 'boolean') element.open = storedCollapseState[element.id];
    element.addEventListener('toggle', persistCollapsibles);
  }
  // Empty presentation stays outside tbody so counts and row consumers remain exact.
  const emptyNotes = new Map();
  const updateEmptyTables = () => {
    for (const body of page.querySelectorAll('tbody[data-empty-message]')) {
      const wrapper = body.closest('.mcp-table-wrap');
      if (!wrapper) continue;
      let note = emptyNotes.get(body);
      if (!note) {
        note = document.createElement('p'); note.className = 'mcp-help mcp-knx-empty-note';
        wrapper.after(note); emptyNotes.set(body, note);
      }
      const card = body.closest('.mcp-card');
      const suppressed = body.closest('[aria-busy="true"], [data-load-failed="true"]')
        || card?.querySelector('.mcp-status[data-kind="error"]');
      const empty = body.children.length === 0 && !suppressed;
      wrapper.dataset.empty = String(empty); note.hidden = !empty;
      if (note.textContent !== body.dataset.emptyMessage) note.textContent = body.dataset.emptyMessage;
    }
  };
  new MutationObserver(updateEmptyTables).observe(page, {subtree: true, childList: true,
    attributes: true, attributeFilter: ['aria-busy', 'data-load-failed', 'data-empty-message', 'data-kind']});
  updateEmptyTables();
  const status = document.getElementById('knx-status');
  const form = document.getElementById('knx-record-form');
  const editor = document.getElementById('knx-editor-section');
  const editorTitle = document.getElementById('knx-editor-title');
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
  let groupDirty = false;
  const dirty = () => labelsDirty || recordDirty || groupDirty || draft !== null || importDirty;
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
      errorStorage: ['knx_storage_failed', 'knx_draft_storage_failed'],
      errorQuery: ['knx_query_invalid'],
      errorExport: ['knx_export_source_unavailable', 'knx_export_selection_invalid', 'knx_export_confirmation_required'],
      errorComparison: ['knx_comparison_invalid', 'knx_comparison_conflicts', 'knx_comparison_no_import']
    };
    const entry = Object.entries(categories).find(([, codes]) => codes.includes(code));
    return entry ? page.dataset[entry[0]] : page.dataset.failed;
  };
  const api = async (action, payload = {}) => {
    if (['knx_page','knx_put','knx_delete','knx_restore','knx_taxonomy','knx_export'].includes(action))
      payload = {...payload, sort:tables.selection('knx-addresses',
        ['address','main_group','middle_group','imported_name','manual_name','description','sources'])};
    const hints = action === 'knx_page' ? [...page.querySelectorAll('[data-knx-catalog-loading]')] : [];
    const loading = (active) => {
      if (hints.length) {
        const announcement = document.getElementById('knx-catalog-announcement');
        announcement.textContent = active ? announcement.dataset.loading : '';
      }
      hints.forEach((hint) => {
        hint.hidden = !active;
        if (active) hint.closest('.mcp-card').setAttribute('aria-busy', 'true');
        else hint.closest('.mcp-card').removeAttribute('aria-busy');
      });
    };
    loading(true);
    try {
      const response = await fetch('knx.cgi', {method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
        body: new URLSearchParams({action, payload: JSON.stringify(payload)})});
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.error?.code || 'request_failed');
      return result.data;
    } finally { loading(false); }
  };
  const run = async (operation) => {
    if (busy) return;
    busy = true;
    page.setAttribute('aria-busy', 'true');
    page.querySelectorAll('fieldset, button, input, select, textarea').forEach((e) => { e.disabled = true; });
    try { await operation(); page.dataset.loadFailed = 'false'; }
    catch (error) { page.dataset.loadFailed = 'true'; message(`${explanation(error.message)} (${error.message})`); }
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
  const fieldLabels = () => ({name: page.dataset.name, description: page.dataset.description,
    dpts: page.dataset.dpts, central: page.dataset.central, unfiltered: page.dataset.unfiltered,
    security: page.dataset.security});
  const display = (value) => value === '' || (Array.isArray(value) && !value.length)
    ? page.dataset.empty : Array.isArray(value) ? value.join(', ') : String(value);
  const sourceDetails = (item) => {
    const details = document.createElement('details');
    details.className = 'mcp-knx-sources';
    const summary = document.createElement('summary');
    summary.textContent = page.dataset.sources; details.append(summary);
    if (item.deviations?.length) {
      const line = document.createElement('p');
      line.textContent = `${page.dataset.deviations}: ${item.deviations.map(k => fieldLabels()[k]).join(', ')}`;
      details.append(line);
    }
    const stamp = item.import_info?.imported_at;
    const provenance = document.createElement('p');
    provenance.textContent = `${page.dataset.importSource}: ${item.import_info?.file_format || page.dataset.unknown}`
      + (typeof stamp === 'number' ? ` · ${new Date(stamp * 1000).toLocaleString(document.documentElement.lang)}` : '')
      + (item.import_info?.digest ? ` · ${item.import_info.digest.slice(0, 12)}` : '');
    details.append(provenance);
    for (const [label, values, key] of [[page.dataset.importSource, item.imported, 'imported'],
      [page.dataset.manualSource, item.overrides, 'manual']]) {
      const title = document.createElement('h4'); title.textContent = label; details.append(title);
      const list = document.createElement('dl');
      for (const field of Object.keys(fieldLabels())) {
        const term = document.createElement('dt'), description = document.createElement('dd');
        term.textContent = fieldLabels()[field];
        description.textContent = Object.hasOwn(values, field) ? display(values[field]) : page.dataset.unknown;
        list.append(term, description);
      }
      details.append(list);
      for (const dpt of item.dpt_details?.[key]?.items || []) {
        const line = document.createElement('p');
        line.textContent = `${dpt.raw}${dpt.normalized ? ` → ${dpt.normalized}` : ''}: `
          + (dpt.status === 'invalid_format' ? page.dataset.dptInvalid : page.dataset.dptValid);
        if (dpt.normalized) line.textContent += ` (${page.dataset.dptMain}: ${dpt.main}; `
          + `${page.dataset.dptSubtype}: ${dpt.subtype ?? page.dataset.dptNoSubtype})`;
        details.append(line);
      }
    }
    const limitation = document.createElement('p'); limitation.textContent = page.dataset.dptAssociation;
    details.append(limitation); return details;
  };
  const render = (data) => {
    if (state && state.target !== data.target && (dirty() || form.elements.namedItem('address').readOnly)) {
      throw new Error('knx_target_conflict');
    }
    state = data;
    const badge = document.getElementById('knx-address-badge');
    badge.textContent = String(data.total);
    badge.hidden = false;
    const labelBadge = document.getElementById('knx-label-badge');
    labelBadge.textContent = String(new Set([...data.taxonomy, ...(data.imported_labels || [])]
      .map(e => `${e.address_format}:${e.prefix}`)).size);
    labelBadge.hidden = false;
    const filters = data.filters || {query: '', source: 'all', deviations_only: false};
    document.getElementById('knx-search-query').value = filters.query;
    document.getElementById('knx-search-source').value = filters.source;
    document.getElementById('knx-search-deviations').checked = filters.deviations_only;
    if (!labelsDirty) textarea.value = data.taxonomy.map((e) => `${e.address_format === 'two_level' ? '2' : '3'}:${e.prefix}=${e.label}`).join('\n');
    document.getElementById('knx-imported-labels').textContent = (data.imported_labels || [])
      .map((e) => `${e.address_format === 'two_level' ? '2' : '3'}:${e.prefix}=${e.label}`).join('\n');
    rows.replaceChildren();
    for (const item of data.items) {
      const tr = document.createElement('tr');
      const groupText = (level) => {
        const group = (item.imported_groups || []).find(entry => entry.level === level);
        const format = item.import_info?.address_format || item.address_format;
        if (!group && level === 'middle' && format === 'two_level') return '—';
        return group ? `${group.prefix} — ${group.fields.name}` : page.dataset.unknown;
      };
      for (const value of [item.address, groupText('main'), groupText('middle'), item.imported.name || '', item.overrides.name || '', item.effective.description || '']) {
        const td = document.createElement('td'); td.textContent = value; tr.append(td);
      }
      const sources = document.createElement('td'); sources.append(sourceDetails(item)); tr.append(sources);
      const actions = document.createElement('td');
      const edit = document.createElement('button');
      edit.type = 'button'; edit.className = 'lb-button'; edit.textContent = page.dataset.edit;
      edit.addEventListener('click', async () => {
        if (recordDirty && !await ask(page.dataset.unsaved)) return;
        editingFields = {...item.overrides};
        editingImport = {...item.imported}; touched.clear();
        recordRevision = state.revision;
        form.elements.namedItem('address').readOnly = true;
        for (const key of ['address', 'address_format']) form.elements.namedItem(key).value = item[key];
        for (const key of ['name', 'description']) form.elements.namedItem(key).value = item.effective[key] || '';
        form.elements.namedItem('dpts').value = (item.effective.dpts || []).join(', ');
        editorTitle.textContent = editor.dataset.editTitle.replace('{address}', item.address);
        recordDirty = false; form.elements.namedItem('name').focus();
        renderEditorSources();
      });
      const remove = document.createElement('button');
      remove.type = 'button'; remove.className = 'lb-button'; remove.textContent = page.dataset.delete;
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
    message('');
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
    editorTitle.textContent = editor.dataset.newTitle;
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
      void run(async () => { render(await api('knx_page', {offset: state.offset + direction,
        target: state.target, query_revision: state.revision, filters: state.filters || {}})); });
    });
  }
  document.getElementById('knx-search-form').addEventListener('submit', (event) => {
    event.preventDefault();
    const filters = {query: document.getElementById('knx-search-query').value,
      source: document.getElementById('knx-search-source').value,
      deviations_only: document.getElementById('knx-search-deviations').checked};
    void run(async () => {render(await api('knx_page', {offset: 0, target: state.target, filters}));});
  });
  document.getElementById('knx-search-clear').addEventListener('click', () => {
    void run(async () => {render(await api('knx_page', {offset: 0, target: state.target, filters: {}}));});
  });
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
    const result = await api('knx_export', {offset: state.offset, target: state.target,
      filters: state.filters || {}, query_revision: state.revision});
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
  tables.bind('knx-addresses', async () => {
    let applied = false;
    if (state) await run(async () => {
      render(await api('knx_page', {target:state.target,query_revision:state.revision,filters:state.filters,offset:0}));
      applied = true;
    });
    return applied;
  });
  const groupSection = document.getElementById('knx-group-management');
  if (groupSection) {
    const groupRows = document.getElementById('knx-group-rows');
    const groupForm = document.getElementById('knx-group-form');
    const groupFormat = document.getElementById('knx-group-format');
    const groupPrefix = document.getElementById('knx-group-prefix');
    const groupLabel = document.getElementById('knx-group-label');
    const groupStatus = document.getElementById('knx-group-status');
    let groupData = null, groupBase = null, groupStale = true, groupQuery = '';
    let requested = false;
    const groupControls = () => {
      const blocked = busy || !state;
      groupForm.querySelector('fieldset').disabled = blocked || groupStale || !groupData || groupData.target !== state?.target;
      groupRows.querySelectorAll('button').forEach(control => {control.disabled = blocked || groupStale;});
      document.getElementById('knx-group-previous').disabled = blocked || groupStale || !groupData?.offset;
      document.getElementById('knx-group-next').disabled = blocked || groupStale || !groupData
        || groupData.offset + 50 >= groupData.total;
      groupFormat.disabled = blocked || groupPrefix.readOnly;
    };
    const groupRun = async operation => {
      if (busy) return false;
      let applied = false;
      groupSection.setAttribute('aria-busy','true');
      groupStatus.textContent = groupSection.dataset.loading;
      try {
        await run(async () => {
          try {await operation();applied=true;groupSection.dataset.loadFailed='false';}
          catch(error){groupStale=true;groupSection.dataset.loadFailed='true';
            groupStatus.textContent=error.groupSaved ? groupSection.dataset.savedRefreshFailed : groupSection.dataset.stale;
            if(error.groupSaved){message(groupSection.dataset.savedRefreshFailed);applied=true;}
            else throw error;}
        });
      } finally {groupSection.removeAttribute('aria-busy');groupControls();}
      return applied;
    };
    const groupEdit = item => {
      if (groupDirty) {groupStatus.textContent=groupSection.dataset.conflict;return;}
      groupBase = {target:groupData.target,taxonomy_revision:groupData.taxonomy_revision,
        entries:groupData.taxonomy.map(entry=>({...entry}))};
      groupFormat.value = item.address_format; groupPrefix.value = item.prefix;
      groupPrefix.readOnly = true; groupLabel.value = item.manual_label || '';
      document.getElementById('knx-group-source').textContent =
        `${groupSection.dataset.imported}: ${item.imported_name ?? page.dataset.unknown}`;
      groupControls();groupLabel.focus();
    };
    const loadGroups = async (offset=0, query=groupQuery) => {
      if (!state) return;
      const payload = {target:state.target,offset,query,
        sort:tables.selection('knx-group-rows',['prefix','format','imported_name','manual_label','address_count'])};
      if (offset && groupData) Object.assign(payload,{query_revision:groupData.revision,
        taxonomy_revision:groupData.taxonomy_revision});
      const retained = initialGroupPage; initialGroupPage = null;
      const data = retained?.ok && !offset && !query
        && retained.data.target === state.target && retained.data.revision === state.revision
        && retained.data.taxonomy_revision === state.taxonomy_revision
        && JSON.stringify(retained.sort) === JSON.stringify(payload.sort) ? retained.data
        : await api('knx_groups_page',payload);
      if (data.target !== state.target) throw new Error('knx_target_conflict');
      groupData = data;groupQuery=query;groupStale=false;requested=true;
      groupRows.replaceChildren();
      for (const item of data.groups) {
        const row=document.createElement('tr');row.dataset.level=item.level;
        for (const value of [`${item.prefix} · ${item.level === 'main' ? groupSection.dataset.main : groupSection.dataset.middle}`,
          item.address_format === 'three_level' ? '1/2/3':'1/123',item.imported_name ?? '—',
          item.manual_label ?? '—',item.address_count]) {
          const cell=document.createElement('td');cell.textContent=String(value);row.append(cell);
        }
        const actions=document.createElement('td'), edit=document.createElement('button');
        edit.type='button';edit.className='lb-button';edit.textContent=groupSection.dataset.edit;
        edit.addEventListener('click',()=>groupEdit(item));actions.append(edit);
        if (item.manual_label !== null) {
          const remove=document.createElement('button');remove.type='button';remove.className='lb-button';
          remove.textContent=groupSection.dataset.remove;
          remove.addEventListener('click',async()=>{
            if(busy || groupStale)return;
            if(groupDirty || labelsDirty){groupStatus.textContent=groupSection.dataset.conflict;return;}
            const baseline={target:groupData.target,taxonomy_revision:groupData.taxonomy_revision,
              entries:groupData.taxonomy.filter(entry=>!(entry.address_format===item.address_format && entry.prefix===item.prefix))};
            if(!await ask(`${groupSection.dataset.removeConfirm}\n${item.prefix}: ${item.manual_label}`))return;
            await groupRun(async()=>{
              render(await api('knx_taxonomy',baseline));
              message(page.dataset.saved);
              try{await loadGroups(0);}catch(error){error.groupSaved=true;throw error;}
            });
          });actions.append(remove);
        }
        row.append(actions);groupRows.append(row);
      }
      document.getElementById('knx-group-count').textContent = data.total
        ? `${data.offset+1}–${Math.min(data.offset+50,data.total)} / ${data.total}`:'0';
      groupStatus.textContent='';groupControls();
    };
    for (const field of [groupFormat,groupPrefix,groupLabel]) field.addEventListener('input',()=>{
      if (!groupBase && groupData) groupBase={target:groupData.target,taxonomy_revision:groupData.taxonomy_revision,
        entries:groupData.taxonomy.map(entry=>({...entry}))};
      groupDirty=true;
    });
    groupFormat.addEventListener('change',()=>{
      groupPrefix.pattern = groupFormat.value === 'two_level'
        ? '(?:0|[1-9]|[12][0-9]|3[01])':'(?:0|[1-9]|[12][0-9]|3[01])(?:/[0-7])?';
    });
    groupForm.addEventListener('reset',event=>{
      if(groupDirty){
        event.preventDefault();
        void ask(page.dataset.unsaved).then(accepted=>{
          if(accepted){groupDirty=false;groupForm.reset();}
        });return;
      }
      groupDirty=false;groupBase=null;groupPrefix.readOnly=false;
      document.getElementById('knx-group-source').textContent='';
      queueMicrotask(()=>{groupFormat.dispatchEvent(new Event('change'));groupControls();});
    });
    groupForm.addEventListener('submit',event=>{
      event.preventDefault();
      void groupRun(async()=>{
        if(labelsDirty){groupStatus.textContent=groupSection.dataset.conflict;return;}
        if(!groupBase || groupBase.target!==state.target)throw new Error('knx_target_conflict');
        const entry={address_format:groupFormat.value,prefix:groupPrefix.value,label:groupLabel.value.trim()};
        const parts=entry.prefix.split('/');
        if(parts.length>(entry.address_format==='two_level'?1:2))throw new Error('knx_field_invalid');
        const entries=groupBase.entries.filter(saved=>!(saved.address_format===entry.address_format && saved.prefix===entry.prefix));
        entries.push(entry);
        const data=await api('knx_taxonomy',{target:groupBase.target,taxonomy_revision:groupBase.taxonomy_revision,entries});
        groupDirty=false;groupForm.reset();render(data);message(page.dataset.saved);
        try{await loadGroups(0);}catch(error){error.groupSaved=true;throw error;}
      });
    });
    for (const [key,delta] of [['previous',-50],['next',50]])
      document.getElementById(`knx-group-${key}`).addEventListener('click',()=>void groupRun(()=>loadGroups(groupData.offset+delta)));
    document.getElementById('knx-group-search').addEventListener('submit',event=>{
      event.preventDefault();void groupRun(()=>loadGroups(0,document.getElementById('knx-group-query').value));
    });
    document.getElementById('knx-group-refresh').addEventListener('click',()=>void groupRun(()=>loadGroups(0)));
    tables.bind('knx-group-rows',()=>groupRun(()=>loadGroups(0)));
    const lazyGroups = () => {
      groupControls();
      if(groupSection.open && state && !busy && !requested){requested=true;void groupRun(()=>loadGroups(0));}
    };
    groupSection.addEventListener('toggle',lazyGroups);
    page.addEventListener('knx-idle',lazyGroups);
    page.addEventListener('knx-state',()=>{
      if(groupData && (groupData.target!==state?.target || groupData.revision!==state?.revision
          || groupData.taxonomy_revision!==state?.taxonomy_revision)){
        groupStale=true;groupStatus.textContent=groupSection.dataset.stale;
      }
      groupControls();
    });
  }
  window.MCPKnx = Object.freeze({api, run, ask, render, tables, initialSections, snapshot: () => state,
    setImportDirty: (value) => { importDirty = value; }, message});
  void run(async () => {
    try {
      const payload = {include_sections: true};
      try {
        const raw = sessionStorage.getItem('mcp-knx-admin-draft-view-v1');
        const selection = raw && raw.length <= 512 ? JSON.parse(raw) : null;
        if (/^[0-9a-f]{64}$/.test(selection?.target) && /^[0-9a-f]{48}$/.test(selection?.draft_id)
            && Number.isInteger(selection.offset) && selection.offset >= 0 && selection.offset < 50)
          payload.initial_correction = {target:selection.target,draft_id:selection.draft_id,offset:selection.offset,
            sort:tables.selection('knx-corrections-values',
              ['address','field','destination','imported','manual','proposed','decision'])};
      } catch (_) { /* A saved selection is optional; no values are stored here. */ }
      if (document.getElementById('knx-group-management')?.open)
        payload.initial_groups = {sort:tables.selection('knx-group-rows',
          ['prefix','format','imported_name','manual_label','address_count'])};
      const data = await api('knx_page', payload);
      initialGroupPage = data.sections?.knx_groups_page
        ? {...data.sections.knx_groups_page,sort:payload.initial_groups?.sort} : null;
      render(data);
      resolveInitialSections(data.sections || null);
    } catch (error) {
      resolveInitialSections(null);
      throw error;
    }
  });
})();
