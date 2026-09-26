/* Fixed-origin MCP transport and sanitized protocol recording. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.McpExplorerClient = api;
})(typeof window !== 'undefined' ? window : undefined, function () {
  'use strict';
  function create({core, state, explorerState, label, accessToken, fetchWithTimeout, addTranscript}) {
    function parseMcpBody(text, contentType) {
      if (!text) return null;
      if (contentType.includes('text/event-stream')) {
        const payloads = text.split(/\r?\n/).filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trim()).filter(Boolean);
        return payloads.length ? JSON.parse(payloads[payloads.length - 1]) : null;
      }
      return JSON.parse(text);
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
      const oauth = state.oauth;
      const selected = method === 'tools/call' ? state.tools.find((tool) => tool.name === params.name) : null;
      const safeParams = selected ? {...params, arguments: core.redactArguments(params.arguments, selected.inputSchema)} : core.clone(params);
      const request = {jsonrpc: '2.0', method, params: params || {}};
      if (!notification) request.id = explorerState.nextRequestId();
      const safeRequest = {...request, params: safeParams || {}};
      const started = performance.now();
      let response;
      let status = 0;
      try {
        const token = await accessToken();
        if (state.oauth !== oauth || Date.now() >= oauth.resumeUntil) {
          const error = new Error(label('tokenExpired'));
          error.sessionCleared = true;
          throw error;
        }
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
        if (state.oauth !== oauth || Date.now() >= oauth.resumeUntil) {
          const error = new Error(label('tokenExpired'));
          error.sessionCleared = true;
          throw error;
        }
        response = parseMcpBody(text, http.headers.get('content-type') || '');
        addTranscript(method, safeRequest, safeMcpResponse(response, selected), status, Math.round(performance.now() - started));
        if (!http.ok || (response && response.error)) {
          const failure = core.mcpFailure(response, http.ok ? 'MCP protocol error' : `${http.status} ${http.statusText}`);
          const error = new Error(failure.message);
          error.mcpResult = failure.result;
          throw error;
        }
        return response ? response.result : null;
      } catch (error) {
        if (state.oauth !== oauth && error) error.sessionCleared = true;
        if (!(error && error.sessionCleared === true) &&
          (!state.transcript.length || state.transcript[state.transcript.length - 1].request !== safeRequest)) {
          addTranscript(method, safeRequest, response || {error: error instanceof Error ? error.message : 'request failed'}, status, Math.round(performance.now() - started));
        }
        throw error;
      }
    }

    async function listTools() {
      const listed = await mcpRequest('tools/list', {}, false);
      return Array.isArray(listed && listed.tools) ? listed.tools : [];
    }

    async function initialize() {
      const initialized = await mcpRequest('initialize', {
        protocolVersion: core.PROTOCOL_VERSION,
        capabilities: {},
        clientInfo: {name: 'LoxBerry MCP Tool Explorer', version: '1.0'},
      }, false);
      if (!initialized || initialized.protocolVersion !== core.PROTOCOL_VERSION) throw new Error('Unsupported MCP protocol version');
      await mcpRequest('notifications/initialized', {}, true);
      return listTools();
    }

    function callTool(name, args) {
      return mcpRequest('tools/call', {name, arguments: args}, false);
    }

    return {initialize, listTools, callTool};
  }
  return {create};
});
