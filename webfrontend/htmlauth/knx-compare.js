(() => {
  'use strict';
  const page = document.getElementById('knx-page');
  const ui = document.getElementById('knx-compare-section');
  const core = window.MCPKnx;
  const mode = document.getElementById('knx-compare-mode');
  const inputs = {left: null, right: null};
  let frame = null;
  const node = (tag, text) => {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    return element;
  };
  const matches = (value, state = core.snapshot()) => value && state
    && value.target === state.target && value.revision === state.revision
    && value.taxonomy_revision === state.taxonomy_revision;
  const stale = () => [inputs.right, mode.value === 'file' ? inputs.left : null, frame]
    .some(value => value && !matches(value));
  const controls = () => {
    document.getElementById('knx-compare-left-controls').hidden = mode.value !== 'file';
    document.getElementById('knx-compare-run').disabled = !core.snapshot() || stale()
      || !inputs.right || (mode.value === 'file' && !inputs.left);
    document.getElementById('knx-compare-previous').disabled = !frame || stale() || frame.offset === 0;
    document.getElementById('knx-compare-next').disabled = !frame || stale() || !frame.has_more;
    document.getElementById('knx-compare-stale').textContent = stale() ? ui.dataset.stale : '';
  };
  const labels = () => ({name: page.dataset.name, description: page.dataset.description,
    dpts: page.dataset.dpts, central: page.dataset.central,
    unfiltered: page.dataset.unfiltered, security: page.dataset.security});
  const fields = (source, keys) => {
    const list = node('dl');
    for (const key of keys) {
      let value = page.dataset.unknown;
      if (Object.hasOwn(source, key)) {
        const raw = source[key];
        value = raw === '' || (Array.isArray(raw) && raw.length === 0) ? page.dataset.empty
          : Array.isArray(raw) ? raw.join(', ') : String(raw);
      }
      list.append(node('dt', labels()[key] || key), node('dd', value));
    }
    if (!keys.length) list.append(node('p', page.dataset.unknown));
    return list;
  };
  const render = () => {
    const rows = document.getElementById('knx-compare-rows'); rows.replaceChildren();
    const summary = document.getElementById('knx-compare-summary');
    const count = document.getElementById('knx-compare-count');
    const scope = document.getElementById('knx-compare-scope');
    summary.textContent = ''; count.textContent = ''; scope.textContent = '';
    if (!frame) { controls(); return; }
    const tokens = {};
    for (const [kind, values] of Object.entries(frame.counts))
      for (const [key, value] of Object.entries(values)) tokens[`${kind}_${key}`] = value;
    summary.textContent = ui.dataset.summary.replace(/\{(\w+)\}/g, (_all, key) => tokens[key]);
    const completeness = value => value.completeness === 'complete' ? ui.dataset.complete
      : value.completeness === 'partial' ? ui.dataset.partial : ui.dataset.catalog;
    scope.textContent = `${ui.dataset.before}: ${completeness(frame.left)} ${ui.dataset.after}: ${completeness(frame.right)} `
      + (frame.manual_scope === 'not_part_of_files' ? ui.dataset.fileOnly : ui.dataset.catalog);
    if (!frame.total) summary.textContent += ` ${ui.dataset.empty}`;
    for (const item of frame.rows) {
      const tr = node('tr');
      const identity = item.kind === 'address'
        ? (item.after_address || item.before_address)
        : `${ui.dataset.group}: ${item.prefix} (${item.address_format === 'two_level' ? '1/123' : '1/2/3'})`;
      tr.append(node('td', identity), node('td', ui.dataset[item.change]));
      const keys = item.changed_fields.length ? item.changed_fields
        : Array.from(new Set([...Object.keys(item.before), ...Object.keys(item.after)])).sort();
      for (const [source, title] of [[item.before, ui.dataset.before], [item.after, ui.dataset.after]]) {
        const td = node('td');
        td.append(node('p', source.name || page.dataset.unknown));
        const details = node('details'); details.append(node('summary', title), fields(source, keys));
        td.append(details); tr.append(td);
      }
      const manual = node('td');
      if (Object.keys(item.manual).length) {
        const details = node('details'); details.append(node('summary', ui.dataset.manual),
          fields(item.manual, Object.keys(item.manual))); manual.append(details);
      } else manual.textContent = page.dataset.unknown;
      tr.append(manual);
      rows.append(tr);
    }
    count.textContent = `${frame.total ? frame.offset + 1 : 0}\u2013${frame.offset + frame.rows.length} / ${frame.total}`;
    controls();
  };
  const encode = async file => {
    if (!file || !file.size || file.size > 16 * 1024 * 1024) throw new Error('knx_file_limit');
    const bytes = new Uint8Array(await file.arrayBuffer()); let binary = '';
    for (let i = 0; i < bytes.length; i += 0x8000)
      binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    return btoa(binary);
  };
  for (const side of ['left', 'right']) {
    const prefix = `knx-compare-${side}-`;
    const load = document.getElementById(prefix + 'load');
    load.addEventListener('click', () => void core.run(async () => {
      const state = core.snapshot();
      const response = await core.api('knx_compare_load', {target: state.target, side,
        file: await encode(document.getElementById(prefix + 'file').files[0]),
        file_format: document.getElementById(prefix + 'format').value,
        encoding: document.getElementById(prefix + 'encoding').value,
        address_format: document.getElementById(prefix + 'style').value || null,
        complete_export: document.getElementById(prefix + 'complete').checked});
      if (!matches(response) || core.snapshot().target !== state.target
          || core.snapshot().revision !== state.revision
          || core.snapshot().taxonomy_revision !== state.taxonomy_revision) throw new Error('knx_revision_conflict');
      inputs[side] = response; frame = null;
      const tokens = {...response, file_format: response.file_format.toUpperCase(),
        duplicates: response.merged_duplicates, scope: response.complete_export ? ui.dataset.complete : ui.dataset.partial};
      document.getElementById(prefix + 'info').textContent = ui.dataset.info.replace(/\{(\w+)\}/g, (_all, key) => tokens[key]);
      render();
    }));
    for (const suffix of ['file', 'format', 'encoding', 'style', 'complete'])
      document.getElementById(prefix + suffix).addEventListener('change', () => {
        inputs[side] = null; frame = null;
        document.getElementById(prefix + 'info').textContent = ''; render();
      });
  }
  const compare = offset => void core.run(async () => {
    if (stale() || !inputs.right || (mode.value === 'file' && !inputs.left))
      throw new Error('knx_revision_conflict');
    const state = core.snapshot();
    const response = await core.api('knx_compare_page', {target: state.target, revision: state.revision,
      taxonomy_revision: state.taxonomy_revision,
      left_id: mode.value === 'file' ? inputs.left.draft_id : 'current',
      right_id: inputs.right.draft_id, offset});
    if (!matches(response) || core.snapshot().target !== state.target
        || core.snapshot().revision !== state.revision
          || core.snapshot().taxonomy_revision !== state.taxonomy_revision) throw new Error('knx_revision_conflict');
    frame = response; render();
  });
  document.getElementById('knx-compare-run').addEventListener('click', () => compare(0));
  document.getElementById('knx-compare-previous').addEventListener('click', () => compare(Math.max(0, frame.offset - 50)));
  document.getElementById('knx-compare-next').addEventListener('click', () => compare(frame.offset + 50));
  mode.addEventListener('change', () => { frame = null; render(); });
  document.getElementById('knx-compare-clear').addEventListener('click', () => void core.run(async () => {
    await core.api('knx_compare_discard', {target: core.snapshot().target});
    for (const side of ['left', 'right']) {
      inputs[side] = null; document.getElementById(`knx-compare-${side}-info`).textContent = '';
      document.getElementById(`knx-compare-${side}-file`).value = '';
    }
    frame = null; render(); core.message(ui.dataset.cleared);
  }));
  page.addEventListener('knx-state', controls); page.addEventListener('knx-idle', controls);
  controls();
})();
