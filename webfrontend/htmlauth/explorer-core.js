/* LoxBerry MCP Tool Explorer. Refresh credentials remain in the server-side browser session. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.McpExplorerCore = api;
})(typeof window !== 'undefined' ? window : undefined, function () {
  'use strict';
  const adapters = typeof module === 'object' && module.exports
    ? require('./explorer-adapters.js') : window.McpExplorerAdapters;

  const PROTOCOL_VERSION = '2025-11-25';
  const MAX_CALL_HISTORY = 50;
  const MAX_TRANSCRIPT = 100;
  const EXPLORER_SESSION_MS = 8 * 60 * 60 * 1000;
  const MCP_RESOURCE_PATH = '/plugins/mcpserver/mcp';
  const EXPLORER_PATH = '/admin/plugins/mcpserver/explorer.cgi';
  const EXPLORER_SCOPE_ORDER = [
    'loxone:read', 'loxone:history', 'loxone:control', 'loxberry:read', 'loxberry:operate',
  ];
  function grantedScopes(scope) {
    if (typeof scope !== 'string' || !scope.trim()) return null;
    const values = scope.trim().split(/\s+/);
    if (values.some((value) => !EXPLORER_SCOPE_ORDER.includes(value)) ||
        new Set(values).size !== values.length) return null;
    return new Set(values);
  }
  const SECRET_NAME = /(?:password|passwd|secret|token|api[_-]?key|private[_-]?key)/i;
  const JSON_TYPES = new Set(['null', 'boolean', 'object', 'array', 'number', 'string', 'integer']);
  const REUSE_SCHEMA_KEYS = new Set([
    '$ref', '$defs', 'type', 'enum', 'const', 'anyOf', 'oneOf', 'properties', 'required',
    'additionalProperties', 'items', 'minimum', 'maximum', 'minLength', 'maxLength',
    'pattern', 'minItems', 'maxItems', 'uniqueItems', 'title', 'description', 'default',
    'examples', 'format', 'readOnly', 'writeOnly',
  ]);
  function clone(value) {
    return value === undefined ? undefined : JSON.parse(JSON.stringify(value));
  }

  function toolGroup(tool) {
    return adapters.toolGroup(tool);
  }

  function sortedToolGroups(tools) {
    return adapters.GROUPS.map((group) => {
      return {
        id: group.id,
        tools: (tools || []).filter((tool) => toolGroup(tool) === group.id).sort((left, right) => {
          const leftPosition = adapters.forTool(left)?.order ?? Number.MAX_SAFE_INTEGER;
          const rightPosition = adapters.forTool(right)?.order ?? Number.MAX_SAFE_INTEGER;
          return leftPosition - rightPosition || left.name.localeCompare(right.name);
        }),
      };
    }).filter((group) => group.tools.length);
  }

  function filteredToolGroups(tools, search, groupIds) {
    const query = String(search || '').trim().toLowerCase();
    const selectedGroups = new Set(groupIds || []);
    const matches = (tools || []).filter((tool) => {
      if (selectedGroups.size && !selectedGroups.has(toolGroup(tool))) return false;
      return !query || `${tool.name || ''} ${tool.description || ''}`.toLowerCase().includes(query);
    });
    return sortedToolGroups(matches);
  }

  function dateTimeLocalToRfc3339(value) {
    if (typeof value !== 'string' || !value) return '';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? '' : date.toISOString();
  }

  function rfc3339ToDateTimeLocal(value) {
    const date = new Date(value);
    if (typeof value !== 'string' || Number.isNaN(date.getTime())) return '';
    const pad = (number) => String(number).padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }

  function timeRange(preset, now) {
    const end = new Date(now === undefined ? Date.now() : now);
    if (Number.isNaN(end.getTime())) return null;
    const start = new Date(end.getTime());
    if (preset === 'hour') start.setTime(start.getTime() - 60 * 60 * 1000);
    else if (preset === 'day') start.setTime(start.getTime() - 24 * 60 * 60 * 1000);
    else if (preset === 'week') start.setTime(start.getTime() - 7 * 24 * 60 * 60 * 1000);
    else if (preset === 'today') start.setHours(0, 0, 0, 0);
    else return null;
    return {start: start.toISOString(), end: end.toISOString()};
  }

  function actionFields(action) {
    return adapters.actionFields(action);
  }

  function operationParameterFields() {
    return adapters.operationParameterFields();
  }

  function isAdvancedField(name) {
    return adapters.isAdvancedField(name);
  }

  function isReferenceField(name) {
    return adapters.isReferenceField(name);
  }

  function referenceCandidates(field, history) {
    return adapters.referenceCandidates(field, history);
  }

  function canonicalExplorerUrl(resource, currentOrigin, trustedLocalAlias) {
    if (typeof resource !== 'string' || typeof currentOrigin !== 'string') return null;
    try {
      const resourceUrl = new URL(resource);
      const pageOrigin = new URL(currentOrigin);
      if (
        resourceUrl.protocol !== 'https:'
        || resourceUrl.username
        || resourceUrl.password
        || resourceUrl.pathname !== MCP_RESOURCE_PATH
        || resourceUrl.search
        || resourceUrl.hash
        || pageOrigin.origin !== currentOrigin
      ) return null;
      if (resourceUrl.origin === currentOrigin) return '';
      // The metadata request reached this point only after the backend validated
      // the same-origin Host against its finite hostname/IP allowlist.
      if (trustedLocalAlias && pageOrigin.protocol === 'https:') return '';
      return `${resourceUrl.origin}${EXPLORER_PATH}`;
    } catch (_error) {
      return null;
    }
  }

  function httpsExplorerUrl(currentUrl) {
    if (typeof currentUrl !== 'string') return null;
    try {
      const page = new URL(currentUrl);
      if (
        page.protocol !== 'http:'
        || page.username
        || page.password
        || page.pathname !== EXPLORER_PATH
      ) return null;
      page.protocol = 'https:';
      if (page.port === '80') page.port = '';
      return page.href;
    } catch (_error) {
      return null;
    }
  }

  function localAuthorizationMetadata(metadata, currentOrigin) {
    let issuer;
    let local;
    try {
      issuer = new URL(metadata.issuer);
      local = new URL(currentOrigin);
    } catch (_error) {
      return null;
    }
    if (
      issuer.protocol !== 'https:'
      || issuer.pathname !== '/plugins/mcpserver/oauth'
      || issuer.search
      || issuer.hash
      || local.protocol !== 'https:'
      || local.origin !== currentOrigin
    ) return null;
    const endpoints = {
      authorization_endpoint: '/plugins/mcpserver/oauth/authorize',
      token_endpoint: '/plugins/mcpserver/oauth/token',
      registration_endpoint: '/plugins/mcpserver/oauth/register',
      revocation_endpoint: '/plugins/mcpserver/oauth/revoke',
    };
    for (const [name, path] of Object.entries(endpoints)) {
      if (metadata[name] !== `${issuer.origin}${path}`) return null;
    }
    return Object.fromEntries(
      [
        ...Object.entries(endpoints),
        ['explorer_session_endpoint', '/plugins/mcpserver/oauth/explorer-session'],
      ].map(([name, path]) => [name, `${local.origin}${path}`]),
    );
  }

  function resolveRef(schema, rootSchema) {
    let current = schema || {};
    const seen = new Set();
    while (current && typeof current.$ref === 'string' && current.$ref.startsWith('#/')) {
      if (seen.has(current.$ref)) return {};
      seen.add(current.$ref);
      current = current.$ref.slice(2).split('/').reduce((value, part) => {
        const key = part.replace(/~1/g, '/').replace(/~0/g, '~');
        return value && value[key];
      }, rootSchema);
    }
    return current || {};
  }

  function effectiveSchema(schema, rootSchema) {
    const resolved = resolveRef(schema, rootSchema);
    if (Array.isArray(resolved.type)) {
      const usefulTypes = resolved.type.filter((type) => type !== 'null');
      if (usefulTypes.length === 1) return {...resolved, type: usefulTypes[0]};
    }
    const variants = resolved.anyOf || resolved.oneOf;
    if (!Array.isArray(variants)) return resolved;
    const useful = variants
      .map((item) => resolveRef(item, rootSchema))
      .filter((item) => item.type !== 'null');
    if (useful.length !== 1) return resolved;
    const {anyOf, oneOf, ...outer} = resolved;
    return {...outer, ...useful[0]};
  }

  function schemaType(schema, rootSchema) {
    const effective = effectiveSchema(schema, rootSchema);
    if (typeof effective.type === 'string') return effective.type;
    if (effective.properties) return 'object';
    if (effective.enum && effective.enum.length) return typeof effective.enum[0];
    return undefined;
  }

  function initialValue(schema, rootSchema) {
    const effective = effectiveSchema(schema, rootSchema);
    if (Object.prototype.hasOwnProperty.call(effective, 'default')) return clone(effective.default);
    const type = schemaType(effective, rootSchema);
    if (type === 'string') return '';
    if (type === 'integer' || type === 'number') return 0;
    if (type === 'boolean') return false;
    if (type === 'array') return [];
    if (type === 'object') return {};
    return null;
  }

  function defaultArguments(schema) {
    const document = {};
    const required = new Set(schema && Array.isArray(schema.required) ? schema.required : []);
    for (const [name, property] of Object.entries((schema && schema.properties) || {})) {
      const effective = effectiveSchema(property, schema);
      if (required.has(name) || (Object.prototype.hasOwnProperty.call(effective, 'default') && effective.default !== null)) {
        document[name] = initialValue(property, schema);
      }
    }
    return document;
  }

  function valueMatchesSchema(value, schema, rootSchema) {
    const resolved = resolveRef(schema, rootSchema);
    if (Array.isArray(resolved.enum) && !resolved.enum.some((item) => Object.is(item, value))) return false;
    if (Object.prototype.hasOwnProperty.call(resolved, 'const') && !Object.is(resolved.const, value)) return false;
    const declaredTypes = Array.isArray(resolved.type) ? resolved.type : [resolved.type];
    const declaredVariants = resolved.anyOf || resolved.oneOf || [];
    if (value === null) {
      return (resolved.type === undefined && declaredVariants.length === 0) || declaredTypes.includes('null') ||
        declaredVariants.some((item) => valueMatchesSchema(value, item, rootSchema));
    }
    const effective = effectiveSchema(resolved, rootSchema);
    if (Array.isArray(effective.anyOf) || Array.isArray(effective.oneOf)) {
      const variants = effective.anyOf || effective.oneOf;
      return variants.some((item) => valueMatchesSchema(value, item, rootSchema));
    }
    const type = schemaType(effective, rootSchema);
    if (type !== undefined && !JSON_TYPES.has(type)) return false;
    if (type === 'string' && typeof value !== 'string') return false;
    if (type === 'integer' && (!Number.isInteger(value))) return false;
    if (type === 'number' && (typeof value !== 'number' || !Number.isFinite(value))) return false;
    if (type === 'boolean' && typeof value !== 'boolean') return false;
    if (type === 'array' && !Array.isArray(value)) return false;
    if (type === 'object' && (typeof value !== 'object' || Array.isArray(value))) return false;
    return true;
  }

  function validateValue(value, schema, rootSchema) {
    const errors = [];
    function visit(current, currentSchema, path) {
      const resolved = resolveRef(currentSchema, rootSchema);
      const variants = resolved.anyOf || resolved.oneOf;
      if (Array.isArray(variants)) {
        const matches = variants.filter((variant) => validateValue(current, variant, rootSchema).length === 0);
        const valid = resolved.oneOf ? matches.length === 1 : matches.length > 0;
        if (!valid) errors.push(`${path || '$'}: schema variant does not match`);
        return;
      }
      const effective = effectiveSchema(currentSchema, rootSchema);
      if (!valueMatchesSchema(current, currentSchema, rootSchema)) {
        errors.push(`${path || '$'}: type or enum does not match`);
        return;
      }
      if (typeof current === 'number') {
        if (typeof effective.minimum === 'number' && current < effective.minimum) errors.push(`${path}: below minimum`);
        if (typeof effective.maximum === 'number' && current > effective.maximum) errors.push(`${path}: above maximum`);
      }
      if (typeof current === 'string') {
        if (typeof effective.minLength === 'number' && current.length < effective.minLength) errors.push(`${path}: too short`);
        if (typeof effective.maxLength === 'number' && current.length > effective.maxLength) errors.push(`${path}: too long`);
        if (typeof effective.pattern === 'string') {
          try { if (!(new RegExp(effective.pattern)).test(current)) errors.push(`${path}: pattern does not match`); }
          catch (_error) { errors.push(`${path}: schema pattern is invalid`); }
        }
      }
      if (Array.isArray(current)) {
        if (typeof effective.minItems === 'number' && current.length < effective.minItems) errors.push(`${path}: too few items`);
        if (typeof effective.maxItems === 'number' && current.length > effective.maxItems) errors.push(`${path}: too many items`);
        if (effective.uniqueItems && new Set(current.map((item) => JSON.stringify(item))).size !== current.length) errors.push(`${path}: items must be unique`);
        if (effective.items) current.forEach((item, index) => visit(item, effective.items, `${path}[${index}]`));
      }
      if (current && typeof current === 'object' && !Array.isArray(current)) {
        const properties = effective.properties || {};
        for (const name of effective.required || []) {
          if (!Object.prototype.hasOwnProperty.call(current, name)) errors.push(`${path ? `${path}.` : ''}${name}: required`);
        }
        if (effective.additionalProperties === false) {
          for (const name of Object.keys(current)) if (!properties[name]) errors.push(`${path ? `${path}.` : ''}${name}: unknown`);
        }
        for (const [name, child] of Object.entries(current)) {
          if (properties[name]) visit(child, properties[name], path ? `${path}.${name}` : name);
        }
      }
    }
    visit(value, schema || {}, '');
    return errors;
  }

  function validateArguments(value, schema) {
    return validateValue(value, schema || {type: 'object'}, schema || {});
  }

  function isSecretSchema(name, schema, rootSchema) {
    const effective = effectiveSchema(schema, rootSchema);
    return SECRET_NAME.test(name) || effective.writeOnly === true || effective.format === 'password';
  }

  function redactArguments(value, schema) {
    function visit(current, currentSchema, rootSchema, name) {
      if (isSecretSchema(name || '', currentSchema || {}, rootSchema || {})) return '[redacted]';
      const effective = effectiveSchema(currentSchema || {}, rootSchema || {});
      if (Array.isArray(current)) return current.map((item) => visit(item, effective.items || {}, rootSchema, ''));
      if (!current || typeof current !== 'object') return clone(current);
      const result = {};
      for (const [key, child] of Object.entries(current)) {
        result[key] = visit(child, (effective.properties || {})[key] || {}, rootSchema, key);
      }
      return result;
    }
    return visit(value, schema || {}, schema || {}, '');
  }

  function summarizeArguments(value, schema) {
    if (!schema || !schema.properties || !value || typeof value !== 'object' || Array.isArray(value)) return '';
    const redacted = redactArguments(value, schema);
    function known(current, currentSchema, depth) {
      if (current === '[redacted]') return current;
      if (depth > 2) return undefined;
      const effective = effectiveSchema(currentSchema, schema);
      if (Array.isArray(current)) {
        if (!effective.items) return undefined;
        return current.slice(0, 2).map((item) => known(item, effective.items, depth + 1));
      }
      if (current && typeof current === 'object') {
        if (!effective.properties) return undefined;
        const result = {};
        for (const [key, child] of Object.entries(current).slice(0, 3)) {
          if (!Object.hasOwn(effective.properties, key)) continue;
          const safe = known(child, effective.properties[key], depth + 1);
          if (safe !== undefined) result[key] = safe;
        }
        return result;
      }
      return effective.type || effective.enum || effective.const !== undefined ? current : undefined;
    }
    const entries = Object.entries(redacted).filter(([key]) => Object.hasOwn(schema.properties, key));
    entries.sort(([leftKey, left], [rightKey, right]) => {
      const leftSchema = effectiveSchema(schema.properties[leftKey], schema);
      const rightSchema = effectiveSchema(schema.properties[rightKey], schema);
      const isDefault = (child, fieldSchema) => Object.hasOwn(fieldSchema, 'default')
        && JSON.stringify(child) === JSON.stringify(fieldSchema.default);
      return Number(isDefault(left, leftSchema)) - Number(isDefault(right, rightSchema));
    });
    const parts = [];
    for (const [key, child] of entries) {
      if (parts.length >= 3) break;
      let safe = known(child, schema.properties[key], 0);
      if (safe === undefined) continue;
      if (typeof safe === 'string' && safe !== '[redacted]' && safe.length > 24) safe = `${safe.slice(0, 23)}…`;
      const rendered = JSON.stringify(safe);
      parts.push(`${key.slice(0, 24)}=${rendered.length > 70 ? `${rendered.slice(0, 69)}…` : rendered}`);
    }
    const summary = parts.join(', ');
    return summary.length > 120 ? `${summary.slice(0, 119)}…` : summary;
  }

  function preferredTargetField(sourcePath) {
    const leaf = Array.isArray(sourcePath) && sourcePath.length
      ? String(sourcePath[sourcePath.length - 1]).toLowerCase()
      : '';
    return leaf.startsWith('next_') ? leaf.slice(5) : leaf;
  }

  function compatibleTargets(tools, value, context) {
    const result = [];
    const preferredField = preferredTargetField(context && context.sourcePath);
    let order = 0;
    for (const tool of tools || []) {
      const schema = tool.inputSchema || {type: 'object'};
      for (const [name, property] of Object.entries(schema.properties || {})) {
        let target = null;
        if (schemaSupportedForReuse(property, schema) && validateValue(value, property, schema).length === 0) {
          target = {tool: tool.name, field: name};
        } else {
          const effective = effectiveSchema(property, schema);
          if (schemaType(property, schema) === 'array' && effective.items &&
            schemaSupportedForReuse(effective.items, schema) &&
            validateValue(value, effective.items, schema).length === 0 &&
            validateValue([value], property, schema).length === 0) {
            target = {tool: tool.name, field: name, mode: 'wrap-array'};
          }
        }
        if (target) {
          target.semanticRank = preferredField && name.toLowerCase() === preferredField ? 0 : 1;
          target.toolRank = context && tool.name === context.sourceTool ? 0 : 1;
          target.order = order++;
          result.push(target);
        }
      }
    }
    result.sort((left, right) =>
      left.semanticRank - right.semanticRank || left.toolRank - right.toolRank || left.order - right.order);
    return result.map(({semanticRank: _semanticRank, toolRank: _toolRank, order: _order, ...target}) => target);
  }

  function valueForTransfer(value, mode) {
    return mode === 'wrap-array' ? [clone(value)] : clone(value);
  }

  function transferArguments(tool, field, value, mode, sourceContext, targetDraft) {
    const draft = targetDraft && typeof targetDraft === 'object' && !Array.isArray(targetDraft)
      ? clone(targetDraft)
      : sourceContext && sourceContext.tool === tool.name && sourceContext.arguments &&
      typeof sourceContext.arguments === 'object' && !Array.isArray(sourceContext.arguments)
      ? clone(sourceContext.arguments)
      : defaultArguments(tool.inputSchema || {});
    if (field !== 'cursor') delete draft.cursor;
    draft[field] = valueForTransfer(value, mode);
    return draft;
  }

  function nextPageArguments(tool, previousArguments, displayedResult) {
    if (!tool || toolIsMutating(tool) || !previousArguments ||
      typeof previousArguments !== 'object' || Array.isArray(previousArguments)) return null;
    const cursor = displayedResult && displayedResult.data && displayedResult.data.next_cursor;
    if (typeof cursor !== 'string' || cursor.length === 0) return null;
    const schema = tool.inputSchema || {type: 'object'};
    const cursorSchema = (schema.properties || {}).cursor;
    if (!cursorSchema || validateValue(cursor, cursorSchema, schema).length) return null;
    const draft = clone(previousArguments);
    draft.cursor = cursor;
    return validateArguments(draft, schema).length ? null : draft;
  }

  function schemaSupportedForReuse(schema, rootSchema, seen) {
    if (!schema || typeof schema !== 'object' || Array.isArray(schema)) return false;
    const visited = seen || new Set();
    if (visited.has(schema)) return true;
    visited.add(schema);
    if (Object.keys(schema).some((key) => !REUSE_SCHEMA_KEYS.has(key))) return false;
    if (schema.format !== undefined && schema.format !== 'date-time') return false;
    if (typeof schema.$ref === 'string') {
      if (!schema.$ref.startsWith('#/')) return false;
      const resolved = schema.$ref.slice(2).split('/').reduce((value, part) => {
        const key = part.replace(/~1/g, '/').replace(/~0/g, '~');
        return value && Object.prototype.hasOwnProperty.call(value, key) ? value[key] : undefined;
      }, rootSchema);
      return resolved !== undefined && resolved !== schema && schemaSupportedForReuse(resolved, rootSchema, visited);
    }
    const types = Array.isArray(schema.type) ? schema.type : schema.type === undefined ? [] : [schema.type];
    if (types.some((type) => !JSON_TYPES.has(type))) return false;
    for (const key of ['anyOf', 'oneOf']) {
      if (schema[key] !== undefined && (!Array.isArray(schema[key]) || !schema[key].length ||
        !schema[key].every((item) => schemaSupportedForReuse(item, rootSchema, visited)))) return false;
    }
    if (schema.items !== undefined && !schemaSupportedForReuse(schema.items, rootSchema, visited)) return false;
    if (schema.properties !== undefined && (!schema.properties || typeof schema.properties !== 'object' ||
      Array.isArray(schema.properties) || !Object.values(schema.properties).every((item) => schemaSupportedForReuse(item, rootSchema, visited)))) return false;
    if (schema.additionalProperties !== undefined && typeof schema.additionalProperties !== 'boolean') return false;
    return true;
  }

  function formatPath(parts) {
    if (!parts.length) return '$';
    return parts.reduce((text, part) => typeof part === 'number' ? `${text}[${part}]` : `${text}.${part}`, '$');
  }

  function base64Url(bytes) {
    let binary = '';
    bytes.forEach((value) => { binary += String.fromCharCode(value); });
    return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }

  function toolIsMutating(tool) {
    const annotations = tool && tool.annotations || {};
    return !(annotations.readOnlyHint === true && annotations.destructiveHint === false);
  }

  function toolMetadataLabels(tool) {
    const annotations = tool && tool.annotations || {};
    const mutating = toolIsMutating(tool);
    const contradictory = annotations.readOnlyHint === true && annotations.destructiveHint === true;
    const labels = [mutating
      ? (annotations.readOnlyHint === false ? 'toolBadgeWrite' : 'toolBadgeWritePossible')
      : 'toolBadgeReadOnly'];
    if (contradictory) return labels;
    if (annotations.readOnlyHint === false) {
      if (annotations.destructiveHint === true) labels.push('toolHintDestructive');
      if (annotations.destructiveHint === false) labels.push('toolHintAdditive');
      if (annotations.idempotentHint === true) labels.push('toolHintIdempotent');
      if (annotations.idempotentHint === false) labels.push('toolHintRepeatEffect');
    }
    if (annotations.openWorldHint === true) labels.push('toolHintOpenWorld');
    if (annotations.openWorldHint === false) labels.push('toolHintClosedWorld');
    return labels;
  }

  function toolRequiredScopes(tool) {
    return adapters.requiredScopes(tool);
  }

  function acceptOAuthPayload(data, expectedState) {
    return Boolean(
      data && data.type === 'mcp-explorer-oauth' && data.state === expectedState &&
      (typeof data.code === 'string' || typeof data.error === 'string'),
    );
  }

  function acceptOAuthMessage(origin, expectedOrigin, data, expectedState) {
    return origin === expectedOrigin && acceptOAuthPayload(data, expectedState);
  }

  function clearSensitiveState(state) {
    state.oauth = null;
    state.tools = [];
    state.selectedTool = null;
    state.toolSearch = '';
    state.toolGroups = [];
    state.arguments = {};
    state.history = [];
    state.transcript = [];
    state.lastResult = null;
    state.hasResult = false;
    state.lastResultContext = null;
    state.nextPageRequest = null;
    state.transferValue = undefined;
    state.transferPath = '';
    state.transferRecipe = null;
    state.drafts = {};
  }

  function mcpFailure(response, fallback) {
    const protocolError = response && response.error;
    if (protocolError && typeof protocolError === 'object') {
      return {
        message: typeof protocolError.message === 'string' ? protocolError.message : fallback,
        result: {error: clone(protocolError)},
      };
    }
    const message = typeof protocolError === 'string' ? protocolError : fallback;
    return {message, result: {error: message}};
  }

  return {
    PROTOCOL_VERSION,
    MAX_CALL_HISTORY,
    MAX_TRANSCRIPT,
    EXPLORER_SESSION_MS,
    EXPLORER_SCOPE_ORDER,
    grantedScopes,
    clone,
    resolveRef,
    effectiveSchema,
    schemaType,
    initialValue,
    defaultArguments,
    valueMatchesSchema,
    validateValue,
    validateArguments,
    redactArguments,
    summarizeArguments,
    compatibleTargets,
    toolGroup,
    sortedToolGroups,
    filteredToolGroups,
    dateTimeLocalToRfc3339,
    rfc3339ToDateTimeLocal,
    timeRange,
    actionFields,
    operationParameterFields,
    isAdvancedField,
    isReferenceField,
    referenceCandidates,
    valueForTransfer,
    transferArguments,
    nextPageArguments,
    schemaSupportedForReuse,
    formatPath,
    base64Url,
    toolIsMutating,
    toolMetadataLabels,
    toolRequiredScopes,
    acceptOAuthPayload,
    acceptOAuthMessage,
    mcpFailure,
    clearSensitiveState,
    canonicalExplorerUrl,
    httpsExplorerUrl,
    localAuthorizationMetadata,
  };
});
