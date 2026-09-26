/* Bounded Tool Explorer views. State changes are delegated to the app and state module. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.McpExplorerViews = api;
})(typeof window !== 'undefined' ? window : undefined, function () {
  'use strict';
  function createResultInspector(document, value, labels, onTransfer) {
    const BATCH_SIZE = 100;
    const INITIAL_LIMIT = 200;
    const SHALLOW_LIMIT = 10;
    const keys = new WeakMap();
    let initialCount = 0;
    const node = (tag, className, text) => {
      const result = document.createElement(tag);
      if (className) result.className = className;
      if (text !== undefined) result.textContent = text;
      return result;
    };
    const entries = (item) => {
      if (Array.isArray(item)) return item.length;
      if (!keys.has(item)) keys.set(item, Object.keys(item));
      return keys.get(item).length;
    };
    const childAt = (item, index) => {
      const key = Array.isArray(item) ? index : keys.get(item)[index];
      return [key, item[key]];
    };
    const structured = (item) => item !== null && typeof item === 'object';
    const summary = (item) => Array.isArray(item) ? `[${entries(item)}]` : `{${entries(item)}}`;
    const clippedText = (value, limit) => {
      if (typeof value !== 'string') return '';
      let preview = '';
      let length = 0;
      let truncated = false;
      let inspected = 0;
      for (const char of value) {
        if (inspected++ >= limit + 256) { truncated = !!preview; break; }
        if (!preview && /\s/u.test(char)) continue;
        if (length === limit) { truncated = true; break; }
        preview += char;
        length += 1;
      }
      preview = preview.trimEnd();
      return preview ? preview + (truncated ? '…' : '') : '';
    };
    const relationPreview = (source, target) => {
      const from = clippedText(source, 37);
      const to = clippedText(target, 37);
      return from && to ? `${from} \u2192 ${to}` : undefined;
    };
    const arrayItemPreview = (item) => {
      if (!structured(item) || Array.isArray(item)) return '';
      const own = (field) => Object.prototype.hasOwnProperty.call(item, field) ? item[field] : undefined;
      function* candidates() {
        for (const field of ['name', 'title', 'label', 'control_name', 'state_name', 'what']) yield own(field);
        const control = own('control');
        yield structured(control) && !Array.isArray(control) &&
          Object.prototype.hasOwnProperty.call(control, 'name') ? control.name : undefined;
        for (const field of ['weather_type_text', 'type', 'block_type', 'component', 'finding_type', 'strategy']) yield own(field);
        yield relationPreview(own('source'), own('target'));
        yield relationPreview(own('source_project_node_id'), own('target_project_node_id'));
        for (const field of ['code', 'model_source_id', 'classification', 'kind',
          'interpretation', 'state_uuid', 'id', 'uuid', 'observed_at', 'at']) yield own(field);
        // Keep timestamp last so a descriptive label or identifier wins when available.
        yield own('timestamp');
      }
      for (const value of candidates()) {
        if (typeof value === 'string') {
          const preview = clippedText(value, 80);
          if (preview) return ` ${JSON.stringify(preview)}`;
        }
        if (typeof value === 'number' && Number.isFinite(value)) return ` ${value}`;
        if (typeof value === 'boolean') return ` ${value}`;
      }
      return '';
    };

    function renderList(item, path, depth, initial) {
      const list = node('ul');
      const count = entries(item);
      let rendered = 0;
      const more = node('button', 'mcp-explorer-tree-more', labels.moreResults);
      const moreRow = node('li', 'mcp-explorer-tree-more-row');
      moreRow.append(more);
      more.type = 'button';
      const addBatch = (initialBatch) => {
        const limit = Math.min(count, rendered + BATCH_SIZE);
        while (rendered < limit && (!initialBatch || initialCount < INITIAL_LIMIT)) {
          const [key, child] = childAt(item, rendered);
          rendered += 1;
          if (initialBatch) initialCount += 1;
          list.append(renderEntry(key, child, [...path, key], depth + 1,
            initialBatch && !Array.isArray(item), Array.isArray(item)));
        }
        if (rendered < count) list.append(moreRow);
        else moreRow.remove();
        more.textContent = `${labels.moreResults} (${count - rendered})`;
      };
      more.addEventListener('click', () => { moreRow.remove(); addBatch(false); });
      addBatch(initial);
      return list;
    }

    function renderEntry(key, item, path, depth, initial, arrayChild) {
      const row = node('li', 'mcp-explorer-tree-entry');
      const controls = node('div', 'mcp-explorer-tree-row');
      row.append(controls);
      if (!structured(item) || entries(item) === 0) {
        const choose = node('button', 'mcp-explorer-value',
          `${String(key)}: ${structured(item) ? summary(item) : item === null ? '-' : JSON.stringify(item)}`);
        choose.type = 'button';
        choose.title = labels.selectValue;
        choose.addEventListener('click', () => onTransfer(item, path));
        controls.append(choose);
        return row;
      }
      const disclosure = node('button', 'mcp-explorer-tree-toggle');
      disclosure.type = 'button';
      disclosure.setAttribute('aria-expanded', 'false');
      const caption = `${String(key)} ${summary(item)}${arrayChild ? arrayItemPreview(item) : ''}`;
      const updateDisclosure = (open) => {
        disclosure.textContent = `${open ? '▾' : '▸'} ${caption}`;
        disclosure.setAttribute('aria-expanded', String(open));
        disclosure.setAttribute('aria-label', `${open ? labels.collapseResult : labels.expandResult}: ${caption}`);
      };
      updateDisclosure(false);
      disclosure.addEventListener('click', () => {
        const open = disclosure.getAttribute('aria-expanded') !== 'true';
        if (open && row.children.length === 1) row.append(renderList(item, path, depth, false));
        if (row.children.length > 1) row.children[1].hidden = !open;
        updateDisclosure(open);
      });
      const choose = node('button', 'mcp-explorer-value mcp-explorer-tree-select', '↗');
      choose.type = 'button';
      choose.title = labels.selectValue;
      choose.setAttribute('aria-label', `${labels.selectValue}: ${String(key)}`);
      choose.addEventListener('click', () => onTransfer(item, path));
      controls.append(disclosure, choose);
      if (initial && depth === 1 && !Array.isArray(item) && entries(item) <= SHALLOW_LIMIT &&
          INITIAL_LIMIT - initialCount >= entries(item)) {
        row.append(renderList(item, path, depth, true));
        updateDisclosure(true);
      }
      return row;
    }

    if (structured(value)) {
      if (entries(value) === 0) return node('p', 'mcp-explorer-muted', summary(value));
      return renderList(value, [], 0, true);
    }
    const list = node('ul');
    list.append(renderEntry('$', value, [], 0, true));
    return list;
  }

  function clearSensitiveDom(elements) {
    elements.json.value = '{}';
    elements.confirmTool.textContent = '';
    elements.confirmArguments.textContent = '';
    if (elements.confirm.open) elements.confirm.close('cancel');
    elements.transferSource.textContent = '';
    elements.transferContext.textContent = '';
    elements.transferTool.replaceChildren();
    elements.transferField.replaceChildren();
    elements.transferEmpty.hidden = false;
    elements.transferApply.disabled = true;
    if (elements.transfer.open) elements.transfer.close();
    elements.resultContext.textContent = '';
    elements.resultContext.hidden = true;
    elements.historyArgumentsValue.textContent = '';
    elements.historyArguments.hidden = true;
    elements.historyArguments.open = false;
    elements.resultTree.replaceChildren();
    elements.resultRaw.textContent = '';
    elements.rawDetails.open = false;
    elements.restoreHistory.hidden = true;
    elements.validation.textContent = '';
    elements.validation.hidden = true;
    elements.callFeedback.textContent = '';
    elements.callFeedback.hidden = true;
  }

  function fieldControlId(index) {
    return `explorer-field-${index}`;
  }

  function createFieldLabel(documentObject, name, input, index) {
    input.id = fieldControlId(index);
    const strong = documentObject.createElement('strong');
    strong.textContent = name;
    const fieldLabel = documentObject.createElement('label');
    fieldLabel.setAttribute('for', input.id);
    fieldLabel.append(strong);
    return fieldLabel;
  }

  function createOptionalToggle(documentObject, name, input, index, optionalText) {
    input.id = `explorer-include-${index}`;
    const toggleLabel = documentObject.createElement('label');
    toggleLabel.setAttribute('for', input.id);
    toggleLabel.append(input, documentObject.createTextNode(` ${optionalText}: ${name}`));
    return toggleLabel;
  }

  function create({core, state, adapters, elements, label,
    narrowViewport, element, actions}) {
    function renderConnection() {
      const connected = Boolean(state.oauth && state.oauth.resumeUntil > Date.now());
      elements.connect.disabled = state.busy || connected;
      elements.disconnect.disabled = state.busy || !connected;
      elements.run.disabled = state.busy || !connected || !state.selectedTool;
      elements.connectionBadge.textContent = label(connected ? 'connected' : 'disconnected');
      elements.connectionBadge.dataset.kind = connected ? 'success' : 'inactive';
      elements.sessionExpiry.hidden = !connected;
      elements.accessScopes.hidden = !connected;
      elements.scopeList.replaceChildren();
      if (connected) {
        const expiry = new Date(state.oauth.resumeUntil);
        elements.sessionExpiryTime.dateTime = expiry.toISOString();
        elements.sessionExpiryTime.textContent = expiry.toLocaleString();
        const granted = core.grantedScopes(state.oauth.scope);
        elements.scopeUnavailable.hidden = granted !== null;
        if (granted !== null) {
          for (const scope of core.EXPLORER_SCOPE_ORDER) {
            const isGranted = granted.has(scope);
            const item = element('li', {className: 'mcp-explorer-scope'}, [
              element('code', {text: scope}),
              element('span', {text: label(isGranted ? 'scopeGranted' : 'scopeNotGranted')}),
            ]);
            elements.scopeList.append(item);
          }
        }
      } else {
        elements.scopeUnavailable.hidden = true;
        elements.sessionExpiryTime.removeAttribute('datetime');
        elements.sessionExpiryTime.textContent = '';
      }
    }

    function renderTools() {
      elements.tools.replaceChildren();
      if (elements.toolSearch.value !== state.toolSearch) elements.toolSearch.value = state.toolSearch;
      elements.toolFilters.querySelectorAll('input[data-tool-group]').forEach((input) => {
        input.checked = input.dataset.toolGroup === 'all'
          ? state.toolGroups.length === 0 : state.toolGroups.includes(input.dataset.toolGroup);
      });
      elements.toolFilterCount.textContent = state.toolGroups.length
        ? `(${state.toolGroups.length})` : `(${label('filterAll')})`;
      elements.selectedTool.textContent = state.selectedTool ? `— ${state.selectedTool.name}` : '';
      elements.selectedTool.hidden = !state.selectedTool;
      elements.requestSelection.textContent = state.selectedTool ? `— ${state.selectedTool.name}` : '';
      elements.requestSelection.hidden = !state.selectedTool;
      if (!state.tools.length) {
        elements.tools.append(element('p', {className: 'mcp-explorer-muted', text: label('noTools')}));
        return;
      }
      const groups = core.filteredToolGroups(state.tools, state.toolSearch, state.toolGroups);
      if (!groups.length) {
        elements.tools.append(element('p', {className: 'mcp-explorer-muted', role: 'status', text: label('noMatchingTools')}));
        return;
      }
      groups.forEach((group) => {
        elements.tools.append(element('h3', {className: 'mcp-explorer-tool-group', text: label(`toolGroup${group.id[0].toUpperCase()}${group.id.slice(1)}`)}));
        group.tools.forEach((tool) => {
        const button = element('button', {type: 'button', className: 'mcp-explorer-tool', 'aria-current': String(state.selectedTool && state.selectedTool.name === tool.name)});
        button.append(element('strong', {text: tool.name}));
        const accessLabel = core.toolMetadataLabels(tool)[0];
        button.append(element('span', {className: 'mcp-explorer-badge',
          'data-kind': core.toolIsMutating(tool) ? 'danger' : 'read', text: label(accessLabel)}));
        button.addEventListener('click', () => {
          actions.selectTool(tool.name);
          if (narrowViewport.matches) {
            elements.toolsPanel.open = false;
            actions.revealRequest(true, false);
          } else {
            elements.tools.querySelector('[aria-current="true"]')?.focus();
          }
        });
        elements.tools.append(button);
        });
      });
    }

    function renderField(name, property, required, rootSchema, fieldIndex) {
      const effective = core.effectiveSchema(property, rootSchema);
      const type = core.schemaType(effective, rootSchema);
      const wrapper = element('div', {className: 'mcp-explorer-field'});
      const booleanWithDefault = !required && type === 'boolean' &&
        typeof effective.default === 'boolean';
      const included = booleanWithDefault || required ||
        Object.prototype.hasOwnProperty.call(state.arguments, name);
      let include = null;
      if (!required && !booleanWithDefault) {
        include = element('input', {type: 'checkbox'});
        include.checked = included;
        const optional = createOptionalToggle(document, name, include, fieldIndex, label('optional'));
        wrapper.append(optional);
      }
      let input;
      if (Array.isArray(effective.enum)) {
        input = element('select');
        if (!effective.enum.some((value) => Object.is(state.arguments[name], value))) {
          const placeholder = element('option', {value: '', text: '—'});
          placeholder.selected = true;
          placeholder.disabled = required;
          input.append(placeholder);
        }
        effective.enum.forEach((value) => {
          const option = element('option', {value: JSON.stringify(value), text: String(value)});
          option.selected = Object.is(state.arguments[name], value);
          input.append(option);
        });
        input.addEventListener('change', () => {
          if (input.value !== '') {
            const value = JSON.parse(input.value);
            if (adapters.hasActionFields(state.selectedTool) && name === 'action') actions.setAction(value);
            else actions.setDraftField(name, true, value);
          }
        });
      } else if (type === 'boolean') {
        input = element('input', {type: 'checkbox'});
        input.checked = Boolean(state.arguments[name]);
        input.addEventListener('change', () => actions.setDraftField(name, true, input.checked));
      } else if (type === 'integer' || type === 'number') {
        input = element('input', {type: 'number'});
        if (typeof effective.minimum === 'number') input.min = String(effective.minimum);
        if (typeof effective.maximum === 'number') input.max = String(effective.maximum);
        input.step = type === 'integer' ? '1' : 'any';
        input.value = state.arguments[name] === undefined ? '' : String(state.arguments[name]);
        input.addEventListener('input', () => actions.setDraftField(name, true, input.value === '' ? 0 : Number(input.value)));
      } else if (type === 'array' || type === 'object') {
        input = element('textarea', {rows: '4', spellcheck: 'false', 'aria-label': type === 'array' ? label('arrayHelp') : label('objectHelp')});
        input.value = JSON.stringify(state.arguments[name] === undefined ? core.initialValue(property, rootSchema) : state.arguments[name], null, 2);
        input.addEventListener('change', () => {
          try { actions.setDraftField(name, true, JSON.parse(input.value)); input.setCustomValidity(''); }
          catch (_error) { input.setCustomValidity(label('invalidJson')); input.reportValidity(); }
        });
      } else if (type === 'string' && effective.format === 'date-time') {
        input = element('input', {type: 'datetime-local'});
        input.value = core.rfc3339ToDateTimeLocal(state.arguments[name]);
        input.addEventListener('change', () => actions.setDraftField(name, true, core.dateTimeLocalToRfc3339(input.value)));
      } else {
        input = element('input', {type: 'text'});
        input.value = state.arguments[name] === undefined ? '' : String(state.arguments[name]);
        input.addEventListener('input', () => actions.setDraftField(name, true, input.value));
      }
      const fieldLabel = createFieldLabel(document, name, input, fieldIndex);
      input.disabled = !included;
      wrapper.append(fieldLabel);
      const helpKey = adapters.fieldHelpKey(name);
      const description = helpKey ? label(helpKey) : effective.description;
      if (description) wrapper.append(element('span', {className: 'mcp-explorer-muted', text: description}));
      wrapper.append(input);
      if (core.isReferenceField(name)) {
        const candidates = core.referenceCandidates(name, state.history);
        if (candidates.length) {
          const select = element('select', {'aria-label': `${label('referenceSelect')}: ${name}`});
          select.append(element('option', {value: '', text: label('referenceSelect')}));
          candidates.forEach((candidate) => select.append(element('option', {value: candidate.value, text: candidate.label})));
          select.addEventListener('change', () => {
            if (select.value) {
              actions.setDraftField(name, true, select.value);
              renderSelectedTool();
              document.getElementById(fieldControlId(fieldIndex))?.focus();
            }
          });
          wrapper.append(select);
        }
      }
      if (name === 'start' && rootSchema.properties && rootSchema.properties.end) {
        const rangeActions = element('div', {className: 'mcp-explorer-actions'});
        [['hour', 'rangeHour'], ['day', 'rangeDay'], ['week', 'rangeWeek'], ['today', 'rangeToday']].forEach(([preset, text]) => {
          const button = element('button', {type: 'button', text: label(text)});
          button.addEventListener('click', () => {
            const range = core.timeRange(preset);
            if (!range) return;
            actions.applyRange(range);
          });
          rangeActions.append(button);
        });
        wrapper.append(rangeActions);
      }
      if (include) include.addEventListener('change', () => {
        input.disabled = !include.checked;
        actions.setDraftField(name, include.checked, include.checked ? core.initialValue(property, rootSchema) : undefined);
        if (include.checked) { renderSelectedTool(); document.getElementById(input.id)?.focus(); }
      });
      return {wrapper, supported: ['string', 'integer', 'number', 'boolean', 'array', 'object'].includes(type)};
    }

    function renderSelectedTool() {
      elements.form.replaceChildren();
      elements.summary.replaceChildren();
      elements.validation.hidden = true;
      if (!state.selectedTool) {
        elements.summary.append(element('p', {className: 'mcp-explorer-muted', text: label('noTools')}));
        elements.run.disabled = true;
        return;
      }
      elements.summary.append(element('h2', {text: state.selectedTool.name}));
      const description = state.selectedTool.description || '';
      if (description.length > 180) {
        const excerpt = description.slice(0, 100).replace(/\s+\S*$/, '').trimEnd();
        const descriptionDetails = element('details', {className: 'mcp-explorer-description'});
        descriptionDetails.append(element('summary', {text: `${label('toolDescription')}: ${excerpt}…`}));
        descriptionDetails.append(element('p', {text: description}));
        elements.summary.append(descriptionDetails);
      } else {
        elements.summary.append(element('p', {text: description}));
      }
      const badges = element('div', {className: 'mcp-explorer-metadata'});
      core.toolMetadataLabels(state.selectedTool).forEach((key, index) => {
        badges.append(element('span', {className: 'mcp-explorer-badge',
          'data-kind': index === 0 && core.toolIsMutating(state.selectedTool) ? 'danger' : 'read',
          text: label(key)}));
      });
      elements.summary.append(badges);
      const scopes = element('p', {className: 'mcp-explorer-required-scopes'});
      scopes.append(element('span', {text: `${label('toolRequiredScopes')}:`}));
      const requiredScopes = core.toolRequiredScopes(state.selectedTool);
      if (requiredScopes) {
        requiredScopes.forEach((scope) => scopes.append(element('code', {text: scope})));
      } else {
        scopes.append(element('span', {text: label('toolScopesUnknown')}));
      }
      elements.summary.append(scopes);
      const technical = element('details', {className: 'mcp-explorer-technical'});
      technical.append(element('summary', {text: label('toolTechnicalMetadata')}));
      technical.append(element('p', {className: 'mcp-explorer-hint-notice', text: label('toolHintsNotice')}));
      technical.append(element('pre', {className: 'mcp-explorer-pre',
        text: JSON.stringify(state.selectedTool.annotations || {}, null, 2)}));
      elements.summary.append(technical);
      const schema = state.selectedTool.inputSchema || {type: 'object'};
      const required = new Set(schema.required || []);
      let supported = true;
      let fieldIndex = 0;
      const advanced = element('details', {className: 'mcp-explorer-stack'});
      advanced.append(element('summary', {text: label('advancedOptions')}));
      for (const [name, property] of Object.entries(schema.properties || {})) {
        if (!adapters.fieldVisible(state.selectedTool, name, state.arguments)) continue;
        const rendered = renderField(name, property, required.has(name), schema, fieldIndex++);
        supported = rendered.supported && supported;
        if (core.isAdvancedField(name)) advanced.append(rendered.wrapper);
        else elements.form.append(rendered.wrapper);
      }
      if (advanced.childElementCount > 1) elements.form.append(advanced);
      if (!Object.keys(schema.properties || {}).length) elements.form.append(element('p', {className: 'mcp-explorer-muted', text: '{}'}));
      elements.schemaWarning.hidden = supported;
      elements.run.disabled = !state.oauth;
      elements.resetDraft.disabled = !state.oauth;
    }

    function displayValue(result) {
      if (result && result.structuredContent !== undefined) return result.structuredContent;
      if (result && result.content !== undefined) return result.content;
      return result;
    }

    function renderResult(result, context, displayed) {
      elements.result.open = true;
      elements.nextPage.hidden = !state.nextPageRequest;
      elements.nextPage.disabled = state.busy || !state.nextPageRequest;
      const historySource = context && context.history === true;
      elements.resultContext.textContent = historySource
        ? `${label('resultFromHistory')}: ${context.tool}`
        : context ? `${label('resultCurrentCall')}: ${context.tool}` : '';
      elements.resultContext.hidden = !context;
      elements.restoreHistory.hidden = !historySource;
      elements.historyArguments.hidden = !historySource;
      elements.historyArguments.open = false;
      elements.historyArgumentsValue.textContent = '';
      if (historySource) {
        const historyTool = state.tools.find((tool) => tool.name === context.tool);
        const argumentsValue = core.redactArguments(context.arguments || {}, historyTool && historyTool.inputSchema);
        elements.historyArgumentsValue.textContent = JSON.stringify(argumentsValue, null, 2);
      }
      elements.rawDetails.open = false;
      elements.resultRaw.textContent = '';
      elements.resultTree.replaceChildren(createResultInspector(document, displayed, {
        selectValue: label('selectValue'),
        expandResult: label('expandResult'),
        collapseResult: label('collapseResult'),
        moreResults: label('moreResults'),
      }, actions.openTransfer));
      elements.copy.disabled = false;
    }

    function transcriptEntry(entry) {
      const details = element('details');
      details.append(element('summary', {text: `${entry.method} — ${entry.status} — ${entry.duration} ms`}));
      details.addEventListener('toggle', () => {
        if (!details.open) return;
        details.append(element('div', {className: 'mcp-explorer-protocol-meta'}, [
          element('p', {text: `${label('dateTime')}: ${new Date(entry.at).toLocaleString()}`}),
          element('p', {text: `${label('status')}: ${entry.status}; ${label('duration')}: ${entry.duration} ms`}),
        ]));
        details.append(element('strong', {text: label('request')}));
        details.append(element('pre', {className: 'mcp-explorer-pre', text: JSON.stringify(entry.request, null, 2)}));
        details.append(element('strong', {text: label('response')}));
        details.append(element('pre', {className: 'mcp-explorer-pre', text: JSON.stringify(entry.response, null, 2)}));
      }, {once: true});
      return details;
    }

    function renderTranscript() {
      const fragment = document.createDocumentFragment();
      state.transcript.forEach((entry) => fragment.append(transcriptEntry(entry)));
      elements.transcript.replaceChildren(fragment);
    }

    function renderHistory() {
      elements.history.replaceChildren();
      if (!state.history.length) {
        elements.history.append(element('p', {className: 'mcp-explorer-muted', text: label('emptyHistory')}));
        return;
      }
      [...state.history].reverse().forEach((entry) => {
        const tool = state.tools.find((candidate) => candidate.name === entry.tool);
        const summary = core.summarizeArguments(entry.arguments, tool && tool.inputSchema);
        const button = element('button', {type: 'button'}, [
          element('strong', {text: entry.tool}),
          ...(summary ? [element('span', {className: 'mcp-explorer-history-arguments', text: summary})] : []),
          element('span', {className: 'mcp-explorer-muted', text: `${new Date(entry.at).toLocaleTimeString()} · ${entry.duration} ms · ${entry.ok ? 'OK' : 'ERROR'}`}),
        ]);
        button.addEventListener('click', () => {
          actions.showResult(entry.result, {tool: entry.tool, arguments: entry.arguments, history: true});
          if (narrowViewport.matches) {
            elements.historyPanel.open = false;
            actions.revealResult();
          }
        });
        elements.history.append(button);
      });
    }

      return {renderConnection, renderTools, renderSelectedTool, renderResult,
        transcriptEntry, renderTranscript, renderHistory, displayValue};
  }
  return {create, createResultInspector, clearSensitiveDom, fieldControlId,
    createFieldLabel, createOptionalToggle};
});
