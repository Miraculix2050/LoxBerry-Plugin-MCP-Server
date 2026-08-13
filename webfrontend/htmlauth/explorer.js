/* LoxBerry MCP Tool Explorer. Refresh credentials may resume only within the same tab. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.McpExplorerCore = api;
})(typeof window !== 'undefined' ? window : undefined, function () {
  'use strict';

  const PROTOCOL_VERSION = '2025-11-25';
  const MAX_CALL_HISTORY = 50;
  const MAX_TRANSCRIPT = 100;
  const REVOCATION_TIMEOUT_MS = 5000;
  const EXPLORER_SESSION_MS = 8 * 60 * 60 * 1000;
  const EXPLORER_CLIENT_REGISTRATION_MS = EXPLORER_SESSION_MS;
  const MCP_RESOURCE_PATH = '/plugins/mcpserver/mcp';
  const EXPLORER_PATH = '/admin/plugins/mcpserver/explorer.cgi';
  const OPAQUE_VALUE = /^[A-Za-z0-9_-]{32,512}$/;
  const EXPLORER_SCOPE_ORDER = [
    'loxone:read', 'loxone:history', 'loxone:control', 'loxberry:read', 'loxberry:operate',
  ];
  const SECRET_NAME = /(?:password|passwd|secret|token|api[_-]?key|private[_-]?key)/i;
  const JSON_TYPES = new Set(['null', 'boolean', 'object', 'array', 'number', 'string', 'integer']);
  const REUSE_SCHEMA_KEYS = new Set([
    '$ref', '$defs', 'type', 'enum', 'const', 'anyOf', 'oneOf', 'properties', 'required',
    'additionalProperties', 'items', 'minimum', 'maximum', 'minLength', 'maxLength',
    'pattern', 'minItems', 'maxItems', 'uniqueItems', 'title', 'description', 'default',
    'examples', 'readOnly', 'writeOnly',
  ]);
  const TOOL_GROUPS = [
    {id: 'loxoneRead', names: [
      'loxone_get_skill_guide', 'loxone_get_system_status', 'loxone_list_rooms',
      'loxone_list_categories', 'loxone_find_controls', 'loxone_describe_control',
      'loxone_get_control_notes', 'loxone_get_states',
    ]},
    {id: 'loxoneHistory', names: ['loxone_get_statistics', 'loxone_get_control_history']},
    {id: 'loxoneControl', names: ['loxone_operate_control']},
    {id: 'loxberryRead', names: [
      'loxberry_get_system_status', 'loxberry_get_plugin_status', 'loxberry_get_service_health',
    ]},
    {id: 'loxberryOperate', names: ['loxberry_clear_statistics_cache']},
  ];

  function clone(value) {
    return value === undefined ? undefined : JSON.parse(JSON.stringify(value));
  }

  function toolGroup(tool) {
    const name = tool && tool.name || '';
    if (name === 'loxone_get_statistics' || name === 'loxone_get_control_history') return 'loxoneHistory';
    if (name.startsWith('loxone_')) return toolIsMutating(tool) ? 'loxoneControl' : 'loxoneRead';
    if (name === 'loxberry_clear_statistics_cache') return 'loxberryOperate';
    return 'loxberryRead';
  }

  function sortedToolGroups(tools) {
    return TOOL_GROUPS.map((group) => {
      const positions = new Map(group.names.map((name, index) => [name, index]));
      return {
        id: group.id,
        tools: (tools || []).filter((tool) => toolGroup(tool) === group.id).sort((left, right) => {
          const leftPosition = positions.has(left.name) ? positions.get(left.name) : Number.MAX_SAFE_INTEGER;
          const rightPosition = positions.has(right.name) ? positions.get(right.name) : Number.MAX_SAFE_INTEGER;
          return leftPosition - rightPosition || left.name.localeCompare(right.name);
        }),
      };
    }).filter((group) => group.tools.length);
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

  function statisticsTransfer(sourceTool, displayedResult, path, value, now) {
    if (sourceTool !== 'loxone_describe_control' || !Array.isArray(path) || path.length !== 4 ||
      path[0] !== 'data' || path[1] !== 'capabilities' || path[2] !== 'statistics' ||
      !value || typeof value !== 'object' || Array.isArray(value) || typeof value.series_id !== 'string' ||
      !displayedResult || !displayedResult.data || typeof displayedResult.data.uuid !== 'string') return null;
    const end = new Date(now === undefined ? Date.now() : now);
    if (Number.isNaN(end.getTime())) return null;
    const start = new Date(end.getTime() - 24 * 60 * 60 * 1000);
    return {
      tool: 'loxone_get_statistics',
      arguments: {
        control_uuid: displayedResult.data.uuid,
        series_id: value.series_id,
        start: start.toISOString(),
        end: end.toISOString(),
        granularity: 'raw',
      },
    };
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
      Object.entries(endpoints).map(([name, path]) => [name, `${local.origin}${path}`]),
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
    return useful.length === 1 ? useful[0] : resolved;
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

  function acceptOAuthMessage(origin, expectedOrigin, data, expectedState) {
    return origin === expectedOrigin && data && data.type === 'mcp-explorer-oauth' && data.state === expectedState;
  }

  function authorizationCodeTokenFields(clientId, code, redirectUri, verifier, resource) {
    return {
      grant_type: 'authorization_code', client_id: clientId, code,
      redirect_uri: redirectUri, code_verifier: verifier, resource,
    };
  }

  function refreshTokenFields(clientId, refreshToken, resource) {
    return {
      grant_type: 'refresh_token', client_id: clientId,
      refresh_token: refreshToken, resource,
    };
  }

  function resumableSession(oauth) {
    return {
      version: 1,
      sessionId: oauth.sessionId,
      clientId: oauth.clientId,
      scope: oauth.scope,
      refreshToken: oauth.refreshToken,
      resource: oauth.resource,
      resumeUntil: oauth.resumeUntil,
    };
  }

  function validExplorerScope(value) {
    if (typeof value !== 'string') return false;
    const scopes = value.split(/\s+/).filter(Boolean);
    if (!scopes.length || scopes.length !== new Set(scopes).size) return false;
    if (scopes.join(' ') !== EXPLORER_SCOPE_ORDER.filter((scope) => scopes.includes(scope)).join(' ')) return false;
    if (scopes[0] !== 'loxone:read') return false;
    return !scopes.includes('loxberry:operate') || scopes.includes('loxone:history');
  }

  function validateResumableSession(value, expectedResource, now) {
    if (!value || typeof value !== 'object' || Array.isArray(value) || value.version !== 1) return null;
    if (!OPAQUE_VALUE.test(value.sessionId || '') || !OPAQUE_VALUE.test(value.clientId || '') ||
      !OPAQUE_VALUE.test(value.refreshToken || '')) return null;
    if (!validExplorerScope(value.scope) || value.resource !== expectedResource) return null;
    if (!Number.isSafeInteger(value.resumeUntil) || value.resumeUntil <= now ||
      value.resumeUntil > now + EXPLORER_SESSION_MS) return null;
    return resumableSession(value);
  }

  function clientRegistration(clientId, registeredAt) {
    return {version: 2, clientId, registeredAt};
  }

  function validateClientRegistration(value, now) {
    if (!value || typeof value !== 'object' || Array.isArray(value) || value.version !== 2) return null;
    if (!/^[A-Za-z0-9_-]{43}$/.test(value.clientId || '')) return null;
    if (!Number.isSafeInteger(value.registeredAt) || value.registeredAt > now ||
      value.registeredAt <= now - EXPLORER_CLIENT_REGISTRATION_MS) return null;
    return clientRegistration(value.clientId, value.registeredAt);
  }

  async function rotateRefreshToken(oauth, exchange, clearResume, saveResume, now) {
    if (oauth.resumeEnabled) clearResume();
    const token = await exchange(refreshTokenFields(oauth.clientId, oauth.refreshToken, oauth.resource));
    if (!token.access_token || !token.refresh_token) throw new Error('OAuth token response is incomplete');
    oauth.accessToken = token.access_token;
    oauth.refreshToken = token.refresh_token;
    oauth.scope = token.scope || oauth.scope;
    oauth.expiresAt = now + Math.max(0, Number(token.expires_in || 0) - 15) * 1000;
    return !oauth.resumeEnabled || saveResume(oauth);
  }

  function clearSensitiveState(state) {
    state.oauth = null;
    state.tools = [];
    state.selectedTool = null;
    state.arguments = {};
    state.history = [];
    state.transcript = [];
    state.lastResult = null;
    state.lastResultContext = null;
    state.nextPageRequest = null;
    state.transferValue = undefined;
    state.transferPath = '';
    state.transferRecipe = null;
    state.drafts = {};
  }

  async function revokeThenClear(oauth, revoke, clear) {
    try {
      if (oauth && oauth.refreshToken) await revoke(oauth);
    } catch (_error) {
      // Server-side session management remains available if best-effort revocation fails.
    } finally {
      clear();
    }
  }

  async function revokeOAuthGrant(fetcher, oauth, timeoutMs) {
    return fetcher(oauth.metadata.revocation_endpoint, {
      method: 'POST', cache: 'no-store',
      headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      body: new URLSearchParams({token: oauth.refreshToken, token_type_hint: 'refresh_token', client_id: oauth.clientId}),
      keepalive: true,
    }, timeoutMs);
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

  return {
    PROTOCOL_VERSION,
    MAX_CALL_HISTORY,
    MAX_TRANSCRIPT,
    REVOCATION_TIMEOUT_MS,
    EXPLORER_SESSION_MS,
    EXPLORER_CLIENT_REGISTRATION_MS,
    EXPLORER_SCOPE_ORDER,
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
    compatibleTargets,
    toolGroup,
    sortedToolGroups,
    dateTimeLocalToRfc3339,
    rfc3339ToDateTimeLocal,
    statisticsTransfer,
    valueForTransfer,
    transferArguments,
    nextPageArguments,
    schemaSupportedForReuse,
    formatPath,
    base64Url,
    toolIsMutating,
    acceptOAuthMessage,
    authorizationCodeTokenFields,
    refreshTokenFields,
    resumableSession,
    validExplorerScope,
    validateResumableSession,
    clientRegistration,
    validateClientRegistration,
    rotateRefreshToken,
    clearSensitiveState,
    revokeThenClear,
    revokeOAuthGrant,
    fieldControlId,
    canonicalExplorerUrl,
    httpsExplorerUrl,
    localAuthorizationMetadata,
    createFieldLabel,
    createOptionalToggle,
  };
});

(function () {
  'use strict';
  if (typeof window === 'undefined' || typeof document === 'undefined') return;

  const core = window.McpExplorerCore;
  const page = document.getElementById('mcp-explorer');
  if (!page) return;

  const elements = {
    status: document.getElementById('explorer-status'),
    connect: document.getElementById('explorer-connect'),
    disconnect: document.getElementById('explorer-disconnect'),
    originWarning: document.getElementById('explorer-origin-warning'),
    originLink: document.getElementById('explorer-origin-link'),
    sessionExpiry: document.getElementById('explorer-session-expiry'),
    sessionExpiryTime: document.getElementById('explorer-session-expiry-time'),
    tools: document.getElementById('explorer-tools'),
    history: document.getElementById('explorer-history'),
    summary: document.getElementById('explorer-tool-summary'),
    form: document.getElementById('explorer-form'),
    formTab: document.getElementById('explorer-form-tab'),
    formPanel: document.getElementById('explorer-form-panel'),
    jsonTab: document.getElementById('explorer-json-tab'),
    jsonPanel: document.getElementById('explorer-json-panel'),
    json: document.getElementById('explorer-json'),
    schemaWarning: document.getElementById('explorer-schema-warning'),
    validation: document.getElementById('explorer-validation'),
    run: document.getElementById('explorer-run'),
    resetDraft: document.getElementById('explorer-reset-draft'),
    copy: document.getElementById('explorer-copy'),
    nextPage: document.getElementById('explorer-next-page'),
    resultContext: document.getElementById('explorer-result-context'),
    historyArguments: document.getElementById('explorer-history-arguments'),
    restoreHistory: document.getElementById('explorer-restore-history'),
    resultTree: document.getElementById('explorer-result-tree'),
    resultRaw: document.getElementById('explorer-result-raw'),
    transcript: document.getElementById('explorer-transcript'),
    confirm: document.getElementById('explorer-confirm'),
    confirmTool: document.getElementById('explorer-confirm-tool'),
    confirmArguments: document.getElementById('explorer-confirm-arguments'),
    transfer: document.getElementById('explorer-transfer'),
    transferSource: document.getElementById('explorer-transfer-source'),
    transferContext: document.getElementById('explorer-transfer-context'),
    transferTool: document.getElementById('explorer-transfer-tool'),
    transferField: document.getElementById('explorer-transfer-field'),
    transferEmpty: document.getElementById('explorer-transfer-empty'),
    transferApply: document.getElementById('explorer-transfer-apply'),
  };

  const label = (name) => page.dataset[name] || name;
  const state = {
    oauth: null,
    tools: [],
    selectedTool: null,
    arguments: {},
    history: [],
    transcript: [],
    lastResult: null,
    lastResultContext: null,
    nextPageRequest: null,
    transferValue: undefined,
    transferPath: '',
    transferRecipe: null,
    drafts: {},
    nextId: 1,
    busy: false,
    sessionLockId: null,
    releaseSessionLock: null,
  };

  function setStatus(text, kind) {
    elements.status.textContent = text;
    elements.status.dataset.kind = kind || '';
  }

  function setBusy(busy) {
    state.busy = busy;
    elements.connect.disabled = busy || Boolean(state.oauth);
    elements.disconnect.disabled = busy || !state.oauth;
    elements.run.disabled = busy || !state.oauth || !state.selectedTool;
    elements.nextPage.disabled = busy || !state.nextPageRequest;
    elements.connect.setAttribute('aria-busy', busy ? 'true' : 'false');
  }

  function showError(error, fallback) {
    const message = error instanceof Error && error.message ? error.message : fallback;
    setStatus(message, 'error');
  }

  function clearOriginWarning() {
    elements.originWarning.hidden = true;
    elements.originLink.removeAttribute('href');
  }

  function showConnectionError(error, fallback) {
    if (error instanceof Error && typeof error.canonicalUrl === 'string') {
      elements.originLink.href = error.canonicalUrl;
      elements.originWarning.hidden = false;
      setStatus(fallback, 'error');
      return;
    }
    clearOriginWarning();
    showError(error, fallback);
  }

  async function sha256(value) {
    return new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value)));
  }

  function randomUrlSafe(length) {
    const bytes = new Uint8Array(length);
    crypto.getRandomValues(bytes);
    return core.base64Url(bytes);
  }

  async function fetchWithTimeout(url, options, timeoutMs) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      return await fetch(url, {...options, signal: controller.signal});
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') throw new Error(label('timeout'));
      throw error;
    } finally {
      window.clearTimeout(timeout);
    }
  }

  async function fetchJson(url, options) {
    const response = await fetchWithTimeout(url, options, 15000);
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = body.error_description || body.error || `${response.status} ${response.statusText}`;
      throw new Error(detail);
    }
    return body;
  }

  function clientStorageKey() {
    return `mcp-explorer-client:${window.location.origin}`;
  }

  function sessionStorageKey() {
    return `mcp-explorer-session:${window.location.origin}`;
  }

  function clearStoredSession() {
    try { window.sessionStorage.removeItem(sessionStorageKey()); } catch (_error) { /* optional */ }
  }

  function readStoredSession(expectedResource) {
    try {
      const serialized = window.sessionStorage.getItem(sessionStorageKey());
      if (!serialized) return null;
      const session = core.validateResumableSession(
        JSON.parse(serialized),
        expectedResource,
        Date.now(),
      );
      if (!session) clearStoredSession();
      return session;
    } catch (_error) {
      clearStoredSession();
      return null;
    }
  }

  function saveStoredSession(oauth) {
    try {
      window.sessionStorage.setItem(
        sessionStorageKey(),
        JSON.stringify(core.resumableSession(oauth)),
      );
      return true;
    } catch (_error) {
      // Never leave a rotated, replay-invalid refresh token behind.
      clearStoredSession();
      return false;
    }
  }

  async function acquireSessionOwnership(sessionId) {
    if (state.sessionLockId === sessionId) return true;
    if (!navigator.locks || typeof navigator.locks.request !== 'function') return false;
    return new Promise((resolve) => {
      navigator.locks.request(
        `mcp-explorer-session:${sessionId}`,
        {mode: 'exclusive', ifAvailable: true},
        (lock) => {
          if (!lock) {
            resolve(false);
            return undefined;
          }
          state.sessionLockId = sessionId;
          return new Promise((release) => {
            state.releaseSessionLock = () => {
              state.sessionLockId = null;
              state.releaseSessionLock = null;
              release();
            };
            resolve(true);
          });
        },
      ).catch(() => resolve(false));
    });
  }

  function releaseSessionOwnership() {
    if (state.releaseSessionLock) state.releaseSessionLock();
  }

  function readClientId() {
    const key = clientStorageKey();
    // Older releases retained this identifier beyond the server-side DCR lifetime.
    try { window.localStorage.removeItem(key); } catch (_error) { /* migration only */ }
    try {
      const serialized = window.sessionStorage.getItem(key);
      if (!serialized) return null;
      const registration = core.validateClientRegistration(JSON.parse(serialized), Date.now());
      if (registration) return registration.clientId;
      window.sessionStorage.removeItem(key);
    } catch (_error) {
      try { window.sessionStorage.removeItem(key); } catch (_ignored) { /* optional */ }
    }
    return null;
  }

  function saveClientId(clientId) {
    try {
      window.sessionStorage.setItem(
        clientStorageKey(),
        JSON.stringify(core.clientRegistration(clientId, Date.now())),
      );
    } catch (_error) { /* optional */ }
  }

  async function discover() {
    if (window.location.protocol !== 'https:') {
      const error = new Error(label('originMismatch'));
      error.canonicalUrl = core.httpsExplorerUrl(window.location.href);
      throw error;
    }
    const resourceMetadata = await fetchJson('/.well-known/oauth-protected-resource/plugins/mcpserver/mcp', {cache: 'no-store'});
    const issuer = Array.isArray(resourceMetadata.authorization_servers) ? resourceMetadata.authorization_servers[0] : null;
    const canonicalUrl = core.canonicalExplorerUrl(
      resourceMetadata.resource,
      window.location.origin,
      true,
    );
    if (canonicalUrl === null) throw new Error('OAuth resource metadata is invalid');
    if (canonicalUrl) {
      const error = new Error(label('originMismatch'));
      error.canonicalUrl = canonicalUrl;
      throw error;
    }
    if (!issuer) throw new Error('OAuth resource metadata has no authorization server');
    const issuerUrl = new URL(issuer);
    const resourceUrl = new URL(resourceMetadata.resource);
    if (
      issuerUrl.protocol !== 'https:'
      || issuerUrl.origin !== resourceUrl.origin
      || issuerUrl.pathname !== '/plugins/mcpserver/oauth'
    ) throw new Error('OAuth issuer is not the local plugin issuer');
    const metadataPath = `/.well-known/oauth-authorization-server${issuerUrl.pathname}`;
    const authorizationMetadata = await fetchJson(metadataPath, {cache: 'no-store'});
    if (authorizationMetadata.issuer !== issuer) throw new Error('OAuth issuer metadata does not match');
    const localEndpoints = core.localAuthorizationMetadata(
      authorizationMetadata,
      window.location.origin,
    );
    if (!localEndpoints) throw new Error('OAuth endpoints do not match the local plugin endpoint');
    clearOriginWarning();
    return {
      resourceMetadata,
      authorizationMetadata: {...authorizationMetadata, ...localEndpoints},
    };
  }

  async function registerClient(metadata, registrationScope, redirectUri) {
    const cached = readClientId();
    if (cached) return cached;
    const registration = await fetchJson(metadata.registration_endpoint, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      cache: 'no-store',
      body: JSON.stringify({
        client_name: 'LoxBerry MCP Tool Explorer',
        redirect_uris: [redirectUri],
        grant_types: ['authorization_code', 'refresh_token'],
        response_types: ['code'],
        token_endpoint_auth_method: 'none',
        scope: registrationScope,
      }),
    });
    if (!registration.client_id) throw new Error('OAuth client registration returned no client_id');
    saveClientId(registration.client_id);
    return registration.client_id;
  }

  function waitForAuthorization(popup, expectedState) {
    return new Promise((resolve, reject) => {
      let finished = false;
      const finish = (callback) => {
        if (finished) return;
        finished = true;
        window.clearInterval(closedTimer);
        window.clearTimeout(timeout);
        window.removeEventListener('message', onMessage);
        callback();
      };
      const onMessage = (event) => {
        if (!core.acceptOAuthMessage(event.origin, window.location.origin, event.data, expectedState)) return;
        finish(() => event.data.error ? reject(new Error(event.data.errorDescription || event.data.error)) : resolve(event.data.code));
      };
      window.addEventListener('message', onMessage);
      const closedTimer = window.setInterval(() => {
        if (popup.closed) finish(() => reject(new Error(label('authCancelled'))));
      }, 500);
      const timeout = window.setTimeout(() => {
        try { popup.close(); } catch (_error) { /* already gone */ }
        finish(() => reject(new Error(label('authCancelled'))));
      }, 5 * 60 * 1000);
    });
  }

  async function exchangeToken(metadata, fields) {
    const body = new URLSearchParams(fields);
    return fetchJson(metadata.token_endpoint, {
      method: 'POST',
      headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      cache: 'no-store',
      body,
    });
  }

  function openAuthorizationPopup() {
    return window.open(
      '',
      'mcp-explorer-oauth',
      'popup=yes,width=680,height=900,resizable=yes,scrollbars=yes',
    );
  }

  async function authorize(popup) {
    const resumeUntil = Date.now() + core.EXPLORER_SESSION_MS;
    const discovered = await discover();
    if (!popup) throw new Error(label('popupBlocked'));
    const supported = new Set(discovered.resourceMetadata.scopes_supported || []);
    if (!supported.has('loxone:read')) throw new Error(label('error'));
    if (!supported.has('loxone:history')) supported.delete('loxberry:operate');
    const scope = core.EXPLORER_SCOPE_ORDER.filter((item) => supported.has(item)).join(' ');
    const registrationScope = scope;
    const redirectUri = new URL('explorer_callback.cgi', window.location.href).href;
    const clientId = await registerClient(discovered.authorizationMetadata, registrationScope, redirectUri);
    const verifier = randomUrlSafe(64);
    const challenge = core.base64Url(await sha256(verifier));
    const oauthState = randomUrlSafe(32);
    const authorizationUrl = new URL(discovered.authorizationMetadata.authorization_endpoint);
    authorizationUrl.search = new URLSearchParams({
      response_type: 'code', client_id: clientId, redirect_uri: redirectUri,
      code_challenge: challenge, code_challenge_method: 'S256', state: oauthState,
      scope, resource: discovered.resourceMetadata.resource,
    }).toString();
    popup.location.replace(authorizationUrl.href);
    const code = await waitForAuthorization(popup, oauthState);
    if (!code) throw new Error(label('authCancelled'));
    const token = await exchangeToken(
      discovered.authorizationMetadata,
      core.authorizationCodeTokenFields(clientId, code, redirectUri, verifier, discovered.resourceMetadata.resource),
    );
    if (!token.access_token || !token.refresh_token) throw new Error('OAuth token response is incomplete');
    return {
      metadata: discovered.authorizationMetadata,
      resource: discovered.resourceMetadata.resource,
      sessionId: randomUrlSafe(32),
      clientId,
      scope: token.scope || scope,
      accessToken: token.access_token,
      refreshToken: token.refresh_token,
      expiresAt: Date.now() + Math.max(0, Number(token.expires_in || 0) - 15) * 1000,
      resumeUntil,
      resumeEnabled: false,
    };
  }

  async function refreshAccessToken() {
    if (!state.oauth || !state.oauth.refreshToken) throw new Error(label('tokenExpired'));
    const saved = await core.rotateRefreshToken(
      state.oauth,
      (fields) => exchangeToken(state.oauth.metadata, fields),
      clearStoredSession,
      saveStoredSession,
      Date.now(),
    );
    if (!saved) {
      state.oauth.resumeEnabled = false;
      releaseSessionOwnership();
    }
  }

  async function accessToken() {
    if (!state.oauth) throw new Error(label('disconnected'));
    if (Date.now() >= state.oauth.expiresAt) {
      try { await refreshAccessToken(); } catch (_error) {
        await revokeAndClear();
        const error = new Error(label('tokenExpired'));
        error.sessionCleared = true;
        throw error;
      }
    }
    return state.oauth.accessToken;
  }

  function parseMcpBody(text, contentType) {
    if (!text) return null;
    if (contentType.includes('text/event-stream')) {
      const payloads = text.split(/\r?\n/).filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trim()).filter(Boolean);
      return payloads.length ? JSON.parse(payloads[payloads.length - 1]) : null;
    }
    return JSON.parse(text);
  }

  function addTranscript(method, request, response, status, duration) {
    const entry = {method, request, response, status, duration, at: new Date().toISOString()};
    state.transcript.push(entry);
    if (state.transcript.length > core.MAX_TRANSCRIPT) {
      state.transcript.splice(0, state.transcript.length - core.MAX_TRANSCRIPT);
      elements.transcript.firstElementChild?.remove();
    }
    elements.transcript.append(transcriptEntry(entry));
  }

  function safeMcpResponse(response, tool) {
    const safe = core.clone(response);
    if (!safe || !tool || !safe.result) return safe;
    if (safe.result.structuredContent !== undefined) {
      safe.result.structuredContent = core.redactArguments(safe.result.structuredContent, tool.outputSchema || {});
      if (safe.result.content !== undefined) safe.result.content = '[omitted; structuredContent shown]';
    }
    return safe;
  }

  async function mcpRequest(method, params, notification) {
    const selected = method === 'tools/call' ? state.tools.find((tool) => tool.name === params.name) : null;
    const safeParams = selected ? {...params, arguments: core.redactArguments(params.arguments, selected.inputSchema)} : core.clone(params);
    const request = {jsonrpc: '2.0', method, params: params || {}};
    if (!notification) request.id = state.nextId++;
    const safeRequest = {...request, params: safeParams || {}};
    const started = performance.now();
    let response;
    let status = 0;
    try {
      const token = await accessToken();
      const http = await fetchWithTimeout('/plugins/mcpserver/mcp', {
        method: 'POST',
        cache: 'no-store',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
          'Accept': 'application/json, text/event-stream',
          'MCP-Protocol-Version': core.PROTOCOL_VERSION,
        },
        body: JSON.stringify(request),
      }, 70000);
      status = http.status;
      const text = await http.text();
      response = parseMcpBody(text, http.headers.get('content-type') || '');
      addTranscript(method, safeRequest, safeMcpResponse(response, selected), status, Math.round(performance.now() - started));
      if (!http.ok) throw new Error(response && response.error && response.error.message ? response.error.message : `${http.status} ${http.statusText}`);
      if (response && response.error) throw new Error(response.error.message || 'MCP protocol error');
      return response ? response.result : null;
    } catch (error) {
      if (!(error && error.sessionCleared === true) &&
        (!state.transcript.length || state.transcript[state.transcript.length - 1].request !== safeRequest)) {
        addTranscript(method, safeRequest, response || {error: error instanceof Error ? error.message : 'request failed'}, status, Math.round(performance.now() - started));
      }
      throw error;
    }
  }

  async function initializeMcp() {
    const initialized = await mcpRequest('initialize', {
      protocolVersion: core.PROTOCOL_VERSION,
      capabilities: {},
      clientInfo: {name: 'LoxBerry MCP Tool Explorer', version: '1.0'},
    }, false);
    if (!initialized || initialized.protocolVersion !== core.PROTOCOL_VERSION) throw new Error('Unsupported MCP protocol version');
    await mcpRequest('notifications/initialized', {}, true);
    const listed = await mcpRequest('tools/list', {}, false);
    state.tools = Array.isArray(listed && listed.tools) ? listed.tools : [];
  }

  async function revokeAndClear() {
    const oauth = state.oauth;
    await core.revokeThenClear(oauth, async (current) => {
      await core.revokeOAuthGrant(fetchWithTimeout, current, core.REVOCATION_TIMEOUT_MS);
    }, () => {
      clearStoredSession();
      releaseSessionOwnership();
      core.clearSensitiveState(state);
      elements.json.value = '{}';
      elements.confirmTool.textContent = '';
      elements.confirmArguments.textContent = '';
      elements.transferSource.textContent = '';
      elements.transferTool.replaceChildren();
      elements.transferField.replaceChildren();
      elements.transferEmpty.hidden = false;
      elements.transferApply.disabled = true;
      if (elements.transfer.open) elements.transfer.close();
      renderAll();
    });
  }

  function renderConnection() {
    const connected = Boolean(state.oauth);
    elements.connect.disabled = connected;
    elements.disconnect.disabled = !connected;
    elements.run.disabled = !connected || !state.selectedTool;
    elements.sessionExpiry.hidden = !connected;
    if (connected) {
      const expiry = new Date(state.oauth.resumeUntil);
      elements.sessionExpiryTime.dateTime = expiry.toISOString();
      elements.sessionExpiryTime.textContent = expiry.toLocaleString();
    } else {
      elements.sessionExpiryTime.removeAttribute('datetime');
      elements.sessionExpiryTime.textContent = '';
    }
    setStatus(connected ? label('connected') : label('disconnected'), connected ? 'success' : '');
  }

  function element(tag, options, children) {
    const node = document.createElement(tag);
    for (const [name, value] of Object.entries(options || {})) {
      if (name === 'className') node.className = value;
      else if (name === 'text') node.textContent = value;
      else node.setAttribute(name, value);
    }
    for (const child of children || []) node.append(child);
    return node;
  }

  function renderTools() {
    elements.tools.replaceChildren();
    if (!state.tools.length) {
      elements.tools.append(element('p', {className: 'mcp-explorer-muted', text: label('noTools')}));
      return;
    }
    core.sortedToolGroups(state.tools).forEach((group) => {
      elements.tools.append(element('h3', {className: 'mcp-explorer-tool-group', text: label(`toolGroup${group.id[0].toUpperCase()}${group.id.slice(1)}`)}));
      group.tools.forEach((tool) => {
      const button = element('button', {type: 'button', className: 'mcp-explorer-tool', 'aria-current': String(state.selectedTool && state.selectedTool.name === tool.name)});
      button.append(element('strong', {text: tool.name}));
      if (core.toolIsMutating(tool)) button.append(element('span', {className: 'mcp-explorer-badge', 'data-kind': 'danger', text: 'write'}));
      else button.append(element('span', {className: 'mcp-explorer-badge', text: 'read-only'}));
      button.addEventListener('click', () => selectTool(tool.name));
      elements.tools.append(button);
      });
    });
  }

  function draftFor(tool) {
    if (!tool) return {arguments: {}, json: '{}'};
    if (!state.drafts[tool.name]) {
      const argumentsValue = core.defaultArguments(tool.inputSchema || {});
      state.drafts[tool.name] = {arguments: argumentsValue, json: JSON.stringify(argumentsValue, null, 2)};
    }
    return state.drafts[tool.name];
  }

  function saveCurrentDraft() {
    if (!state.selectedTool) return;
    state.drafts[state.selectedTool.name] = {
      arguments: core.clone(state.arguments),
      json: elements.json.value,
    };
  }

  function selectTool(name, draft) {
    saveCurrentDraft();
    state.selectedTool = state.tools.find((tool) => tool.name === name) || null;
    if (state.selectedTool && draft !== undefined) {
      state.drafts[state.selectedTool.name] = {arguments: core.clone(draft), json: JSON.stringify(draft, null, 2)};
    }
    const saved = draftFor(state.selectedTool);
    state.arguments = core.clone(saved.arguments);
    elements.json.value = saved.json;
    renderTools();
    renderSelectedTool();
  }

  function setDraftField(name, included, value) {
    if (included) state.arguments[name] = value;
    else delete state.arguments[name];
    elements.json.value = JSON.stringify(state.arguments, null, 2);
    saveCurrentDraft();
    validateDraft(false);
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
      const optional = core.createOptionalToggle(document, name, include, fieldIndex, label('optional'));
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
        if (input.value !== '') setDraftField(name, true, JSON.parse(input.value));
      });
    } else if (type === 'boolean') {
      input = element('input', {type: 'checkbox'});
      input.checked = Boolean(state.arguments[name]);
      input.addEventListener('change', () => setDraftField(name, true, input.checked));
    } else if (type === 'integer' || type === 'number') {
      input = element('input', {type: 'number'});
      if (typeof effective.minimum === 'number') input.min = String(effective.minimum);
      if (typeof effective.maximum === 'number') input.max = String(effective.maximum);
      input.step = type === 'integer' ? '1' : 'any';
      input.value = state.arguments[name] === undefined ? '' : String(state.arguments[name]);
      input.addEventListener('input', () => setDraftField(name, true, input.value === '' ? 0 : Number(input.value)));
    } else if (type === 'array' || type === 'object') {
      input = element('textarea', {rows: '4', spellcheck: 'false', 'aria-label': type === 'array' ? label('arrayHelp') : label('objectHelp')});
      input.value = JSON.stringify(state.arguments[name] === undefined ? core.initialValue(property, rootSchema) : state.arguments[name], null, 2);
      input.addEventListener('change', () => {
        try { setDraftField(name, true, JSON.parse(input.value)); input.setCustomValidity(''); }
        catch (_error) { input.setCustomValidity(label('invalidJson')); input.reportValidity(); }
      });
    } else if (type === 'string' && effective.format === 'date-time') {
      input = element('input', {type: 'datetime-local'});
      input.value = core.rfc3339ToDateTimeLocal(state.arguments[name]);
      input.addEventListener('change', () => setDraftField(name, true, core.dateTimeLocalToRfc3339(input.value)));
    } else {
      input = element('input', {type: 'text'});
      input.value = state.arguments[name] === undefined ? '' : String(state.arguments[name]);
      input.addEventListener('input', () => setDraftField(name, true, input.value));
    }
    const fieldLabel = core.createFieldLabel(document, name, input, fieldIndex);
    input.disabled = !included;
    wrapper.append(fieldLabel);
    const helpKey = {
      cursor: 'helpCursor', limit: 'helpLimit', query: 'helpQuery', room_uuid: 'helpRoomUuid',
      category_uuid: 'helpCategoryUuid', control_type: 'helpControlType',
      control_uuid: 'helpControlUuid', state_uuids: 'helpStateUuids', action: 'helpAction',
    }[name];
    const description = helpKey ? label(helpKey) : effective.description;
    if (description) wrapper.append(element('span', {className: 'mcp-explorer-muted', text: description}));
    wrapper.append(input);
    if (include) include.addEventListener('change', () => {
      input.disabled = !include.checked;
      setDraftField(name, include.checked, include.checked ? core.initialValue(property, rootSchema) : undefined);
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
    elements.summary.append(element('p', {text: state.selectedTool.description || ''}));
    const annotations = state.selectedTool.annotations || {};
    elements.summary.append(element('code', {text: JSON.stringify(annotations)}));
    const schema = state.selectedTool.inputSchema || {type: 'object'};
    const required = new Set(schema.required || []);
    let supported = true;
    let fieldIndex = 0;
    for (const [name, property] of Object.entries(schema.properties || {})) {
      const rendered = renderField(name, property, required.has(name), schema, fieldIndex++);
      supported = rendered.supported && supported;
      elements.form.append(rendered.wrapper);
    }
    if (!Object.keys(schema.properties || {}).length) elements.form.append(element('p', {className: 'mcp-explorer-muted', text: '{}'}));
    elements.schemaWarning.hidden = supported;
    elements.run.disabled = !state.oauth;
    elements.resetDraft.disabled = !state.oauth;
  }

  function validateDraft(show) {
    if (!state.selectedTool) return false;
    let parsed;
    try { parsed = JSON.parse(elements.json.value); }
    catch (_error) {
      if (show) { elements.validation.textContent = label('invalidJson'); elements.validation.hidden = false; }
      return false;
    }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      if (show) { elements.validation.textContent = label('invalidArguments'); elements.validation.hidden = false; }
      return false;
    }
    const errors = core.validateArguments(parsed, state.selectedTool.inputSchema || {type: 'object'});
    if (errors.length) {
      if (show) { elements.validation.textContent = `${label('invalidArguments')} ${errors.join('; ')}`; elements.validation.hidden = false; }
      return false;
    }
    state.arguments = parsed;
    saveCurrentDraft();
    elements.validation.hidden = true;
    return true;
  }

  function confirmMutation(tool, args) {
    if (!core.toolIsMutating(tool)) return Promise.resolve(true);
    elements.confirmTool.textContent = tool.name;
    elements.confirmArguments.textContent = JSON.stringify(core.redactArguments(args, tool.inputSchema), null, 2);
    if (typeof elements.confirm.showModal !== 'function') {
      return Promise.resolve(window.confirm(`${tool.name}\n\n${elements.confirmArguments.textContent}`));
    }
    elements.confirm.showModal();
    return new Promise((resolve) => elements.confirm.addEventListener('close', () => resolve(elements.confirm.returnValue === 'confirm'), {once: true}));
  }

  function displayValue(result) {
    if (result && result.structuredContent !== undefined) return result.structuredContent;
    if (result && result.content !== undefined) return result.content;
    return result;
  }

  function renderTreeNode(value, path) {
    const list = element('ul');
    if (value && typeof value === 'object') {
      const entries = Array.isArray(value) ? value.map((item, index) => [index, item]) : Object.entries(value);
      entries.forEach(([key, child]) => {
        const childPath = [...path, key];
        const item = element('li');
        const choose = element('button', {type: 'button', className: 'mcp-explorer-value', text: `${String(key)}: ${child && typeof child === 'object' ? (Array.isArray(child) ? '[…]' : '{…}') : JSON.stringify(child)}`});
        choose.title = label('selectValue');
        choose.addEventListener('click', () => openTransfer(child, childPath));
        item.append(choose);
        if (child && typeof child === 'object') item.append(renderTreeNode(child, childPath));
        list.append(item);
      });
    } else {
      const item = element('li');
      const choose = element('button', {type: 'button', className: 'mcp-explorer-value', text: JSON.stringify(value)});
      choose.addEventListener('click', () => openTransfer(value, path));
      item.append(choose);
      list.append(item);
    }
    return list;
  }

  function renderResult(result, context) {
    state.lastResult = result;
    state.lastResultContext = context ? core.clone(context) : null;
    const displayed = displayValue(result);
    const sourceTool = context && state.tools.find((tool) => tool.name === context.tool);
    const nextArguments = sourceTool
      ? core.nextPageArguments(sourceTool, context.arguments, displayed)
      : null;
    state.nextPageRequest = nextArguments ? {tool: sourceTool.name, arguments: nextArguments} : null;
    elements.nextPage.hidden = !state.nextPageRequest;
    elements.nextPage.disabled = state.busy || !state.nextPageRequest;
    const historySource = context && context.history === true;
    elements.resultContext.textContent = historySource
      ? `${label('resultFromHistory')}: ${context.tool}`
      : context ? `${label('resultCurrentCall')}: ${context.tool}` : '';
    elements.resultContext.hidden = !context;
    elements.restoreHistory.hidden = !historySource;
    elements.historyArguments.hidden = !historySource;
    elements.historyArguments.replaceChildren();
    if (historySource) {
      const historyTool = state.tools.find((tool) => tool.name === context.tool);
      const argumentsValue = core.redactArguments(context.arguments || {}, historyTool && historyTool.inputSchema);
      elements.historyArguments.append(
        element('strong', {text: label('historyArguments')}),
        element('pre', {className: 'mcp-explorer-pre', text: JSON.stringify(argumentsValue, null, 2)}),
      );
    }
    elements.resultRaw.textContent = JSON.stringify(result, null, 2);
    elements.resultTree.replaceChildren(renderTreeNode(displayed, []));
    elements.copy.disabled = false;
  }

  function transcriptEntry(entry) {
    const details = element('details');
    details.append(element('summary', {text: `${entry.method} — ${entry.status} — ${entry.duration} ms`}));
    details.addEventListener('toggle', () => {
      if (!details.open) return;
      details.append(element('p', {text: `${label('status')}: ${entry.status}; ${label('duration')}: ${entry.duration} ms`}));
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
      const button = element('button', {type: 'button', text: `${entry.tool} — ${entry.duration} ms — ${entry.ok ? 'OK' : 'ERROR'}`});
      button.addEventListener('click', () => {
        renderResult(entry.result, {tool: entry.tool, arguments: entry.arguments, history: true});
      });
      elements.history.append(button);
    });
  }

  async function runSelectedTool() {
    if (!validateDraft(true) || !state.selectedTool) return;
    const requiredMutationScope = state.selectedTool.name === 'loxberry_clear_statistics_cache'
      ? 'loxberry:operate'
      : 'loxone:control';
    if (core.toolIsMutating(state.selectedTool) && !(state.oauth && state.oauth.scope.split(/\s+/).includes(requiredMutationScope))) {
      showError(new Error(label(requiredMutationScope === 'loxberry:operate' ? 'operateRequired' : 'controlRequired')), label('error'));
      return;
    }
    if (!(await confirmMutation(state.selectedTool, state.arguments))) return;
    const tool = state.selectedTool;
    const args = core.clone(state.arguments);
    setBusy(true);
    setStatus(label('working'), 'working');
    const started = performance.now();
    let result;
    let ok = false;
    let sessionCleared = false;
    try {
      result = await mcpRequest('tools/call', {name: tool.name, arguments: args}, false);
      ok = !(result && result.isError);
      renderResult(result, {tool: tool.name, arguments: args});
      const outputErrors = result && result.structuredContent !== undefined && tool.outputSchema
        ? core.validateArguments(result.structuredContent, tool.outputSchema)
        : [];
      if (outputErrors.length) {
        ok = false;
        elements.validation.textContent = `${label('invalidOutput')} ${outputErrors.join('; ')}`;
        elements.validation.hidden = false;
      }
      setStatus(ok ? label('ready') : label('error'), ok ? 'success' : 'error');
    } catch (error) {
      sessionCleared = Boolean(error && error.sessionCleared === true);
      if (!sessionCleared) {
        result = {error: error instanceof Error ? error.message : label('error')};
        renderResult(result, {tool: tool.name, arguments: args});
      }
      showError(error, label('error'));
    } finally {
      if (!sessionCleared) {
        state.history.push({tool: tool.name, arguments: args, result, ok, duration: Math.round(performance.now() - started)});
        if (state.history.length > core.MAX_CALL_HISTORY) state.history.splice(0, state.history.length - core.MAX_CALL_HISTORY);
        renderHistory();
      }
      setBusy(false);
    }
  }

  function openTransfer(value, path) {
    state.transferValue = core.clone(value);
    state.transferPath = core.formatPath(path);
    elements.transferSource.textContent = `${state.transferPath} = ${JSON.stringify(value)}`;
    const recipe = core.statisticsTransfer(
      state.lastResultContext && state.lastResultContext.tool,
      displayValue(state.lastResult),
      path,
      value,
    );
    state.transferRecipe = recipe;
    elements.transferContext.textContent = recipe
      ? `${label('statisticsTransferContext')}: loxone_get_statistics (5 ${label('fields')})`
      : `${label('transferContext')}: ${state.lastResultContext ? state.lastResultContext.tool : '—'}`;
    elements.transferTool.closest('label').hidden = Boolean(recipe);
    elements.transferField.closest('label').hidden = Boolean(recipe);
    if (recipe) {
      elements.transferTool.replaceChildren(element('option', {value: recipe.tool, text: recipe.tool}));
      elements.transferField.replaceChildren();
      elements.transferEmpty.hidden = true;
      elements.transferApply.disabled = false;
      if (typeof elements.transfer.showModal === 'function') elements.transfer.showModal();
      return;
    }
    const targets = core.compatibleTargets(state.tools, value, {
      sourcePath: path,
      sourceTool: state.lastResultContext && state.lastResultContext.tool,
    });
    elements.transferTool.replaceChildren();
    [...new Set(targets.map((item) => item.tool))].forEach((name) => elements.transferTool.append(element('option', {value: name, text: name})));
    const updateFields = () => {
      elements.transferField.replaceChildren();
      targets.filter((item) => item.tool === elements.transferTool.value).forEach((item) => {
        const text = item.mode === 'wrap-array' ? `${item.field} (${label('asList')})` : item.field;
        elements.transferField.append(element('option', {value: item.field, text, 'data-mode': item.mode || 'direct'}));
      });
      const empty = !elements.transferField.options.length;
      elements.transferEmpty.hidden = !empty;
      elements.transferApply.disabled = empty;
    };
    elements.transferTool.onchange = updateFields;
    updateFields();
    if (typeof elements.transfer.showModal === 'function') elements.transfer.showModal();
  }

  function applyTransfer() {
    if (state.transferRecipe) {
      const tool = state.tools.find((item) => item.name === state.transferRecipe.tool);
      if (!tool) return;
      const existing = draftFor(tool).arguments;
      const draft = {...core.clone(existing), ...state.transferRecipe.arguments};
      delete draft.cursor;
      selectTool(tool.name, draft);
      window.scrollTo({top: elements.summary.getBoundingClientRect().top + window.scrollY - 16, behavior: 'smooth'});
      return;
    }
    const tool = state.tools.find((item) => item.name === elements.transferTool.value);
    if (!tool || !elements.transferField.value) return;
    const selected = elements.transferField.options[elements.transferField.selectedIndex];
    const draft = core.transferArguments(
      tool,
      elements.transferField.value,
      state.transferValue,
      selected.dataset.mode,
      state.lastResultContext,
      draftFor(tool).arguments,
    );
    selectTool(tool.name, draft);
    window.scrollTo({top: elements.summary.getBoundingClientRect().top + window.scrollY - 16, behavior: 'smooth'});
  }

  function renderAll() {
    renderConnection();
    renderTools();
    renderSelectedTool();
    renderHistory();
    renderTranscript();
    if (!state.lastResult) {
      elements.resultTree.replaceChildren(element('p', {className: 'mcp-explorer-muted', text: label('emptyResult')}));
      elements.resultRaw.textContent = '{}';
      elements.copy.disabled = true;
      elements.nextPage.hidden = true;
      elements.nextPage.disabled = true;
    }
  }

  function selectTab(jsonMode, focusPanel = true) {
    elements.formTab.setAttribute('aria-selected', String(!jsonMode));
    elements.jsonTab.setAttribute('aria-selected', String(jsonMode));
    elements.formTab.tabIndex = jsonMode ? -1 : 0;
    elements.jsonTab.tabIndex = jsonMode ? 0 : -1;
    elements.formPanel.hidden = jsonMode;
    elements.jsonPanel.hidden = !jsonMode;
    if (focusPanel) (jsonMode ? elements.json : elements.form.querySelector('input,select,textarea'))?.focus();
  }

  function handleTabKey(event) {
    const tabs = [elements.formTab, elements.jsonTab];
    const current = tabs.indexOf(event.currentTarget);
    let target = null;
    if (event.key === 'ArrowLeft') target = tabs[(current - 1 + tabs.length) % tabs.length];
    if (event.key === 'ArrowRight') target = tabs[(current + 1) % tabs.length];
    if (event.key === 'Home') target = tabs[0];
    if (event.key === 'End') target = tabs[tabs.length - 1];
    if (!target) return;
    event.preventDefault();
    selectTab(target === elements.jsonTab, false);
    target.focus();
  }

  elements.connect.addEventListener('click', async () => {
    const insecureOrigin = window.location.protocol !== 'https:';
    // A blank window retains the click's transient user activation in Firefox.
    // HTTP is rejected without opening a window and offers the HTTPS link below.
    const authorizationPopup = insecureOrigin ? null : openAuthorizationPopup();
    setBusy(true);
    setStatus(label('working'), 'working');
    try {
      state.oauth = await authorize(authorizationPopup);
      state.oauth.resumeEnabled = await acquireSessionOwnership(state.oauth.sessionId);
      if (state.oauth.resumeEnabled && !saveStoredSession(state.oauth)) {
        state.oauth.resumeEnabled = false;
        releaseSessionOwnership();
      }
      await initializeMcp();
      renderAll();
      if (state.tools.length) selectTool(state.tools[0].name);
      setStatus(label('connected'), 'success');
    } catch (error) {
      try { authorizationPopup?.close(); } catch (_closeError) { /* already gone */ }
      if (state.oauth) await revokeAndClear();
      else core.clearSensitiveState(state);
      showConnectionError(error, label('error'));
      renderAll();
    } finally { setBusy(false); }
  });
  elements.disconnect.addEventListener('click', async () => {
    setBusy(true);
    await revokeAndClear();
    setBusy(false);
    setStatus(label('disconnected'), '');
  });
  elements.run.addEventListener('click', runSelectedTool);
  elements.resetDraft.addEventListener('click', () => {
    if (!state.selectedTool) return;
    const defaults = core.defaultArguments(state.selectedTool.inputSchema || {});
    selectTool(state.selectedTool.name, defaults);
  });
  elements.formTab.addEventListener('click', () => selectTab(false));
  elements.jsonTab.addEventListener('click', () => selectTab(true));
  elements.formTab.addEventListener('keydown', handleTabKey);
  elements.jsonTab.addEventListener('keydown', handleTabKey);
  elements.json.addEventListener('input', saveCurrentDraft);
  elements.json.addEventListener('change', () => { if (validateDraft(true)) renderSelectedTool(); });
  elements.copy.addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(JSON.stringify(state.lastResult, null, 2)); setStatus(label('copied'), 'success'); }
    catch (error) { showError(error, label('error')); }
  });
  elements.nextPage.addEventListener('click', async () => {
    if (!state.nextPageRequest) return;
    const request = core.clone(state.nextPageRequest);
    selectTool(request.tool, request.arguments);
    await runSelectedTool();
  });
  elements.transfer.addEventListener('close', () => { if (elements.transfer.returnValue === 'apply') applyTransfer(); });
  elements.restoreHistory.addEventListener('click', () => {
    const context = state.lastResultContext;
    if (!context || !context.history || !window.confirm(label('restoreHistoryConfirm'))) return;
    selectTool(context.tool, context.arguments);
  });

  selectTab(false, false);
  renderAll();
  (async () => {
    let stored = null;
    let ownershipConflict = false;
    let refreshed = false;
    try {
      const discovered = await discover();
      stored = readStoredSession(discovered.resourceMetadata.resource);
      if (stored) {
        setBusy(true);
        setStatus(label('restoringSession'), 'working');
        if (!(await acquireSessionOwnership(stored.sessionId))) {
          clearStoredSession();
          stored = null;
          ownershipConflict = true;
        }
      }
      if (!stored) return;
      state.oauth = {
        ...stored,
        metadata: discovered.authorizationMetadata,
        accessToken: '',
        expiresAt: 0,
        resumeEnabled: true,
      };
      await refreshAccessToken();
      refreshed = true;
      await initializeMcp();
      renderAll();
      if (state.tools.length) selectTool(state.tools[0].name);
      setStatus(label('connected'), 'success');
    } catch (_error) {
      const refreshFailed = Boolean(state.oauth) && !refreshed;
      const canonicalOriginMismatch = _error instanceof Error
        && typeof _error.canonicalUrl === 'string';
      if (refreshFailed) {
        await revokeAndClear();
      } else {
        if (canonicalOriginMismatch && stored) clearStoredSession();
        core.clearSensitiveState(state);
        releaseSessionOwnership();
      }
      renderAll();
      if (canonicalOriginMismatch) {
        showConnectionError(_error, label('error'));
      } else if (stored) {
        showError(
          new Error(refreshFailed ? label('tokenExpired') : label('restoreFailed')),
          label('error'),
        );
      }
      else {
        showConnectionError(_error, label('error'));
      }
    } finally {
      setBusy(false);
      if (ownershipConflict) showError(new Error(label('sessionOtherTab')), label('error'));
    }
  })();
})();
