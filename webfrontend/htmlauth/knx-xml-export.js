/* Explicit experimental correction download; catalog and project remain unchanged. */
(() => {
  'use strict';
  const page = document.getElementById('knx-page');
  const ui = document.getElementById('knx-xml-section');
  const core = window.MCPKnx;
  const project = window.MCPKnxProject;
  const rows = document.getElementById('knx-xml-rows');
  const previewArea = document.getElementById('knx-xml-result');
  const confirm = document.getElementById('knx-xml-confirm');
  let source = null, preview = null;
  const node = (tag, value) => {
    const result = document.createElement(tag);
    if (value !== undefined) result.textContent = value;
    return result;
  };
  const controls = () => {
    const current = core.snapshot(), live = project.snapshot();
    const valid = current && source && live && live.binding === source.binding
      && current.target === source.target && current.revision === source.revision;
    document.getElementById('knx-xml-preview').disabled = !valid;
    document.getElementById('knx-xml-download').disabled = !valid || !preview || !confirm.checked;
  };
  const invalidate = () => { preview = null; previewArea.replaceChildren(); confirm.checked = false; controls(); };
  const valueControl = (item, field) => {
    const wrapper = node('div'), select = node('select'), manual = node(field === 'name' ? 'input' : 'textarea');
    select.dataset.field = field;
    select.setAttribute('aria-label', field === 'name' ? page.dataset.name : page.dataset.description);
    manual.setAttribute('aria-label', `${ui.dataset.manual}: ${field === 'name' ? page.dataset.name : page.dataset.description}`);
    manual.maxLength = field === 'name' ? 255 : 4096; manual.hidden = true;
    for (const [value, label] of [['keep', ui.dataset.keep], ['manual', ui.dataset.manual]]) {
      const option = node('option', label); option.value = value; select.append(option);
    }
    item.project_objects.forEach((object, index) => {
      const value = field === 'name' ? object.loxone_name : object.project_description;
      const complete = field === 'name' ? object.name_complete : !object.truncated_fields.includes('description');
      if (typeof value !== 'string' || !value.trim() || !complete) return;
      const option = node('option', `${ui.dataset.loxone}: ${value} (${object.project_node_id})`);
      option.value = `object:${index}`; select.append(option);
    });
    select.addEventListener('change', () => { manual.hidden = select.value !== 'manual'; invalidate(); });
    manual.addEventListener('input', invalidate);
    wrapper.append(select, manual); return wrapper;
  };
  const renderChoices = () => {
    source = project.snapshot(); rows.replaceChildren(); invalidate();
    if (!source) return;
    for (const item of source.items) {
      if (!item.local_metadata || !Object.keys(item.local_metadata.imported).length) continue;
      const tr = node('tr'); tr.dataset.address = item.address_id;
      const selected = node('input'); selected.type = 'checkbox';
      selected.setAttribute('aria-label', `${ui.dataset.select}: ${item.local_metadata.address}`);
      selected.addEventListener('change', invalidate);
      const first = node('td'); first.append(selected, node('span', item.local_metadata.address)); tr.append(first);
      const imported = node('td'); imported.append(node('p', item.local_metadata.imported.name ?? page.dataset.unknown),
        node('p', item.local_metadata.imported.description ?? page.dataset.unknown)); tr.append(imported);
      for (const field of ['name', 'description']) {
        const cell = node('td'); cell.append(valueControl(item, field)); tr.append(cell);
      }
      rows.append(tr);
    }
    controls();
  };
  const choices = () => [...rows.querySelectorAll('tr')].filter(tr => tr.querySelector('input[type="checkbox"]').checked)
    .map(tr => {
      const item = source.items.find(item => item.address_id === Number(tr.dataset.address));
      const fields = {};
      for (const select of tr.querySelectorAll('select')) {
        if (select.value === 'keep') continue;
        const field = select.dataset.field;
        fields[field] = select.value === 'manual' ? select.nextElementSibling.value
          : item.project_objects[Number(select.value.split(':')[1])][field === 'name' ? 'loxone_name' : 'project_description'];
      }
      return {address_id: item.address_id, fields};
    });
  document.getElementById('knx-xml-preview').addEventListener('click', () => void core.run(async () => {
    const expectedSource = source;
    const binding = expectedSource.binding;
    const selected = choices();
    await project.validate(binding);
    if (source !== expectedSource || !project.snapshot() || project.snapshot().binding !== binding)
      throw new Error('knx_revision_conflict');
    const result = await core.api('knx_xml_preview', {target: expectedSource.target, revision: expectedSource.revision,
      choices: selected, project_binding: binding});
    if (!project.snapshot() || project.snapshot().binding !== binding
        || core.snapshot().target !== result.target || core.snapshot().revision !== result.revision)
      throw new Error('knx_revision_conflict');
    invalidate(); preview = result;
    previewArea.append(node('p', `${result.rows.length} ${ui.dataset.select} · ${result.bytes} bytes`));
    for (const row of result.rows) {
      const change = node('p', row.address);
      change.append(node('span', ` · ${row.before.Name ?? page.dataset.unknown} → ${row.after.Name ?? page.dataset.unknown}`),
        node('span', ` · ${row.before.Description ?? page.dataset.unknown} → ${row.after.Description ?? page.dataset.unknown}`));
      previewArea.append(change);
    }
    const preserved = node('pre', JSON.stringify({root: result.root_attributes,
      comments: result.document_comments, outer_comments: result.outer_comments,
      groups: result.groups, addresses: result.rows}, null, 2));
    preserved.tabIndex = 0; preserved.setAttribute('role', 'region');
    preserved.setAttribute('aria-label', ui.dataset.metadata);
    const details = node('details'); details.append(node('summary', ui.dataset.metadata), preserved);
    previewArea.append(details); controls();
  }));
  confirm.addEventListener('change', controls);
  document.getElementById('knx-xml-download').addEventListener('click', () => void core.run(async () => {
    if (!preview || !confirm.checked) throw new Error('knx_export_confirmation_required');
    const expected = preview;
    await project.validate(expected.project_binding);
    if (preview !== expected || !confirm.checked) throw new Error('knx_revision_conflict');
    const result = await core.api('knx_xml_download', {target: expected.target, revision: expected.revision,
      draft_id: expected.draft_id, project_binding: expected.project_binding, confirmed_experimental: true});
    if (preview !== expected || !project.snapshot() || project.snapshot().binding !== expected.project_binding
        || core.snapshot().target !== result.target || core.snapshot().revision !== result.revision)
      throw new Error('knx_revision_conflict');
    const url = URL.createObjectURL(new Blob([result.content], {type: 'application/xml;charset=utf-8'}));
    const link = node('a'); link.href = url; link.download = result.filename;
    link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }));
  document.getElementById('knx-xml-clear').addEventListener('click', () => void core.run(async () => {
    await core.api('knx_xml_discard', {target: core.snapshot().target}); renderChoices();
  }));
  page.addEventListener('knx-project-state', renderChoices);
  page.addEventListener('knx-state', () => { invalidate(); controls(); });
  page.addEventListener('knx-idle', controls);
  renderChoices();
})();
