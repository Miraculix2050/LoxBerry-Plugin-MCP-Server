(() => {
  'use strict';
  const ui = document.getElementById('knx-import-section');
  const page = document.getElementById('knx-page');
  const core = window.MCPKnx;
  const fileInput = document.getElementById('knx-ets-file');
  const fileFormat = document.getElementById('knx-ets-file-format');
  const encoding = document.getElementById('knx-ets-encoding');
  const addressFormat = document.getElementById('knx-ets-format');
  const complete = document.getElementById('knx-ets-complete');
  const mode = document.getElementById('knx-ets-mode');
  const orphanPolicy = document.getElementById('knx-ets-orphan-policy');
  let frame = null;
  let settingsDirty = false;
  let taxonomyRevision = null;
  let choices = {};
  const labels = new Set();
  const element = (tag, value) => {
    const node = document.createElement(tag);
    if (value !== undefined) node.textContent = value;
    return node;
  };
  const value = (fields, key) => {
    if (!Object.hasOwn(fields, key)) return page.dataset.unknown;
    const data = fields[key];
    if (data === '' || (Array.isArray(data) && !data.length)) return page.dataset.empty;
    if (typeof data === 'boolean') return data ? ui.dataset.yes : ui.dataset.no;
    return Array.isArray(data) ? data.join(', ') : String(data);
  };
  const fieldLabels = () => ({name: page.dataset.name, description: page.dataset.description,
    dpts: page.dataset.dpts, central: ui.dataset.central, unfiltered: ui.dataset.unfiltered,
    security: ui.dataset.security});
  const fields = (data, keys = Object.keys(data)) => {
    const list = element('dl');
    for (const key of keys) list.append(element('dt', fieldLabels()[key] || key), element('dd', value(data, key)));
    return list;
  };
  const details = (title, data, keys) => {
    const block = element('details'); block.append(element('summary', title), fields(data, keys));
    return block;
  };
  const stale = () => frame && (settingsDirty || !core.snapshot()
    || frame.target !== core.snapshot().target || frame.revision !== core.snapshot().revision
    || taxonomyRevision !== core.snapshot().taxonomy_revision);
  const controls = () => {
    document.getElementById('knx-ets-apply').disabled = !frame || stale() || frame.conflict_count > 0
      || frame.name_policy_required || frame.invalid_labels?.length > 0;
    document.getElementById('knx-ets-previous').disabled = !frame || stale() || frame.offset === 0;
    document.getElementById('knx-ets-next').disabled = !frame || stale() || !frame.has_more;
    document.getElementById('knx-conflict-previous').disabled = !frame || stale() || frame.conflict_offset === 0;
    document.getElementById('knx-conflict-next').disabled = !frame || stale() || !frame.has_more_conflicts;
    mode.querySelector('[value="replace"]').disabled = !frame || !frame.complete_export;
    document.getElementById('knx-ets-stale').textContent = stale() ? ui.dataset.stale : '';
    const state = core.snapshot();
    if (state) document.getElementById('knx-target').textContent = `${ui.dataset.target}: ${state.target_display || ''}`;
  };
  const render = () => {
    document.getElementById('knx-ets-preview').hidden = !frame;
    if (!frame) { controls(); return; }
    const tokens = {addresses: frame.addresses, groups: frame.groups_count, additions: frame.additions,
      updates: frame.updates, duplicates: frame.merged_duplicates, conflicts: frame.conflict_count,
      removals: frame.removals, preserved: frame.preserved_overrides,
      encoding: frame.encoding, style: frame.address_format === 'three_level' ? '1/2/3' : '1/123',
      file_format: `${(frame.file_format || 'xml').toUpperCase()}${frame.layout ? ` ${frame.layout}` : ''}`};
    document.getElementById('knx-ets-summary').textContent = ui.dataset.summary.replace(/\{(\w+)\}/g, (_all, key) => tokens[key])
      + ` ${frame.complete_export ? ui.dataset.complete : ui.dataset.partial}`;
    mode.value = frame.mode; orphanPolicy.value = frame.orphan_name_policy || '';
    document.getElementById('knx-orphan-policy').hidden = frame.mode !== 'replace' || !frame.nameless_overrides;
    const conflicts = document.getElementById('knx-ets-conflicts'); conflicts.replaceChildren();
    for (const conflict of frame.conflicts) {
      const group = element('fieldset'); group.append(element('legend', conflict.candidates[0].address));
      for (const candidate of conflict.candidates) {
        const label = element('label'); const input = element('input');
        input.type = 'radio'; input.name = conflict.identity; input.value = String(candidate.index);
        input.checked = choices[conflict.identity] === candidate.index;
        input.addEventListener('change', () => {
          void refresh(frame.offset, {...choices, [conflict.identity]: candidate.index}, labels, 0);
        });
        label.append(input, element('span', `${ui.dataset.select}: ${value(candidate.fields, 'name')}`));
        group.append(label, fields(candidate.fields));
        const source = candidate.source.attributes || candidate.source;
        group.append(details(ui.dataset.additional, source));
      }
      conflicts.append(group);
    }
    const changes = document.getElementById('knx-ets-changes'); changes.replaceChildren();
    for (const change of frame.changes) {
      const entry = element('details');
      entry.append(element('summary', `${change.address}: ${ui.dataset[change.kind]}`));
      const keys = [...new Set([...Object.keys(change.old_imported), ...Object.keys(change.new_imported)])];
      entry.append(details(ui.dataset.before, change.old_imported, keys), details(ui.dataset.after, change.new_imported, keys),
        details(ui.dataset.overrides, change.overrides));
      changes.append(entry);
    }
    const groups = document.getElementById('knx-ets-groups'); groups.replaceChildren();
    for (const group of frame.groups) {
      const label = element('label'); const input = element('input');
      input.type = 'checkbox'; input.checked = labels.has(group.identity);
      input.addEventListener('change', () => {
        const selected = new Set(labels);
        if (input.checked) selected.add(group.identity); else selected.delete(group.identity);
        void refresh(frame.offset, choices, selected);
      });
      label.append(input, element('span', `${ui.dataset.label}: ${group.prefix} \u2014 ${group.fields.name}`));
      if ([...group.fields.name].length > 80) label.append(element('span', ui.dataset.labelTooLong));
      groups.append(label);
    }
    document.getElementById('knx-ets-page').textContent = `${Math.floor(frame.offset / 50) + 1}`;
    document.getElementById('knx-conflict-page').textContent = `${Math.floor(frame.conflict_offset / 5) + 1} / ${Math.max(1, Math.ceil(frame.conflict_count / 5))}`;
    controls();
  };
  const accept = (result, selectedChoices) => {
    frame = result; choices = {...selectedChoices};
    labels.clear(); result.selected_groups.forEach((identity) => labels.add(identity));
    core.setImportDirty(true); render();
  };
  const refresh = async (offset, selectedChoices = choices, selectedLabels = labels, conflictOffset = frame.conflict_offset) => {
    const request = {target: frame.target, draft_id: frame.draft_id, offset,
      choices: selectedChoices, selected_groups: [...selectedLabels], conflict_offset: conflictOffset,
      mode: mode.value, orphan_name_policy: orphanPolicy.value || null};
    await core.run(async () => accept(await core.api('knx_import_preview', request), selectedChoices));
    render();
  };
  const encoded = async (file) => {
    if (!file || !file.size || file.size > 16 * 1024 * 1024) throw new Error('knx_file_limit');
    const bytes = new Uint8Array(await file.arrayBuffer()); let binary = '';
    for (let offset = 0; offset < bytes.length; offset += 0x8000) binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
    return btoa(binary);
  };
  document.getElementById('knx-ets-load').addEventListener('click', () => void core.run(async () => {
    const payload = {target: core.snapshot().target, file: await encoded(fileInput.files[0]),
      encoding: encoding.value, file_format: fileFormat.value,
      complete_export: complete.checked, address_format: addressFormat.value || null};
    const result = await core.api('knx_import_load', payload);
    settingsDirty = false; taxonomyRevision = core.snapshot().taxonomy_revision;
    accept(result, {}); core.message(ui.dataset.review);
  }));
  for (const control of [fileInput, fileFormat, encoding, complete, addressFormat]) control.addEventListener('change', () => {
    settingsDirty = true; controls();
  });
  document.getElementById('knx-ets-previous').addEventListener('click', () => void refresh(frame.offset - 50));
  document.getElementById('knx-ets-next').addEventListener('click', () => void refresh(frame.offset + 50));
  document.getElementById('knx-conflict-previous').addEventListener('click', () => void refresh(frame.offset, choices, labels, frame.conflict_offset - 5));
  document.getElementById('knx-conflict-next').addEventListener('click', () => void refresh(frame.offset, choices, labels, frame.conflict_offset + 5));
  mode.addEventListener('change', () => {
    if (mode.value === 'replace' && !orphanPolicy.value) orphanPolicy.value = 'retain_import_name';
    void refresh(0);
  });
  orphanPolicy.addEventListener('change', () => void refresh(frame.offset));
  document.getElementById('knx-ets-apply').addEventListener('click', () => void core.run(async () => {
    if (!frame || stale() || frame.conflict_count || frame.name_policy_required
      || frame.invalid_labels?.length) throw new Error('knx_preview_changed');
    const result = await core.api('knx_import_apply', {target: frame.target,
      draft_id: frame.draft_id, preview_token: frame.preview_token});
    frame = null; core.setImportDirty(false); core.render(result); render();
    core.message(result.draft_cleanup_pending ? ui.dataset.cleanupPending : page.dataset.saved);
  }));
  document.getElementById('knx-ets-discard').addEventListener('click', () => void core.run(async () => {
    await core.api('knx_import_discard', {target: frame.target, draft_id: frame.draft_id});
    frame = null; core.setImportDirty(false); render(); core.message(ui.dataset.discarded);
  }));
  page.addEventListener('knx-state', controls); page.addEventListener('knx-idle', controls);
})();
