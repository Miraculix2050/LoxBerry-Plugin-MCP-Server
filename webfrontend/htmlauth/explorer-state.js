/* Tab-local Explorer state and explicit transitions. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.McpExplorerState = api;
})(typeof window !== 'undefined' ? window : undefined, function () {
  'use strict';

  function create(core) {
    const data = {
      oauth: null, tools: [], selectedTool: null, toolSearch: '', toolGroups: [],
      arguments: {}, history: [], transcript: [], lastResult: null, hasResult: false,
      lastResultContext: null, nextPageRequest: null, transferValue: undefined,
      transferPath: '', transferRecipe: null, drafts: {}, nextId: 1, busy: false,
    };

    function clear() { core.clearSensitiveState(data); }
    function setSession(oauth) { data.oauth = oauth; }
    function updateToken(token) {
      if (!data.oauth) return;
      data.oauth.accessToken = token.access_token;
      data.oauth.scope = typeof token.scope === 'string' ? token.scope : '';
      data.oauth.expiresAt = Date.now() + Math.max(0, Number(token.expires_in || 0) - 15) * 1000;
      data.oauth.resumeUntil = Number(token.expires_at || 0) * 1000;
    }
    function setTools(tools) { data.tools = Array.isArray(tools) ? tools : []; }
    function nextRequestId() { return data.nextId++; }
    function setBusy(busy) { data.busy = busy; }
    function setSearch(search) { data.toolSearch = search; }
    function setGroups(groups) { data.toolGroups = groups; }
    function draftFor(tool) {
      if (!tool) return {arguments: {}, json: '{}'};
      if (!data.drafts[tool.name]) {
        const value = core.defaultArguments(tool.inputSchema || {});
        data.drafts[tool.name] = {arguments: value, json: JSON.stringify(value, null, 2)};
      }
      return data.drafts[tool.name];
    }
    function saveDraft(json) {
      if (!data.selectedTool) return;
      data.drafts[data.selectedTool.name] = {
        arguments: core.clone(data.arguments), json,
      };
    }
    function selectTool(name, draft, currentJson) {
      saveDraft(currentJson);
      data.selectedTool = data.tools.find((tool) => tool.name === name) || null;
      if (data.selectedTool && draft !== undefined) {
        data.drafts[data.selectedTool.name] = {
          arguments: core.clone(draft), json: JSON.stringify(draft, null, 2),
        };
      }
      const saved = draftFor(data.selectedTool);
      data.arguments = core.clone(saved.arguments);
      return saved.json;
    }
    function setArguments(value) { data.arguments = value; }
    function setField(name, included, value) {
      if (included) data.arguments[name] = value;
      else delete data.arguments[name];
    }
    function setResult(result, context) {
      data.lastResult = result;
      data.hasResult = true;
      data.lastResultContext = context ? core.clone(context) : null;
      const displayed = result && result.structuredContent !== undefined
        ? result.structuredContent : result && result.content !== undefined
          ? result.content : result;
      const tool = context && data.tools.find((item) => item.name === context.tool);
      const next = tool ? core.nextPageArguments(tool, context.arguments, displayed) : null;
      data.nextPageRequest = next ? {tool: tool.name, arguments: next} : null;
      return displayed;
    }
    function appendHistory(entry) {
      data.history.push(entry);
      if (data.history.length > core.MAX_CALL_HISTORY) {
        data.history.splice(0, data.history.length - core.MAX_CALL_HISTORY);
      }
    }
    function appendTranscript(entry) {
      data.transcript.push(entry);
      if (data.transcript.length > core.MAX_TRANSCRIPT) {
        data.transcript.splice(0, data.transcript.length - core.MAX_TRANSCRIPT);
        return true;
      }
      return false;
    }
    function setTransfer(value, path, recipe) {
      data.transferValue = core.clone(value);
      data.transferPath = core.formatPath(path);
      data.transferRecipe = recipe;
    }
    return {data, clear, setSession, updateToken, setTools, nextRequestId,
      setBusy, setSearch, setGroups, draftFor, saveDraft, selectTool,
      setArguments, setField, setResult, appendHistory, appendTranscript, setTransfer};
  }
  return {create};
});
