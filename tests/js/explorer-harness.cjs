/* Deterministic browser boundary for the shipped static Explorer page. */
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM, VirtualConsole} = require('jsdom');

const ROOT = path.resolve(__dirname, '../..');
const TEMPLATE = fs.readFileSync(path.join(ROOT, 'templates/explorer.html'), 'utf8');
const scriptUrls = [...TEMPLATE.matchAll(/<script defer src="([^"]+)"/g)]
  .map((match) => match[1]);
assert.ok(scriptUrls.every((url) =>
  /^explorer(?:-[^"?]+)?\.js\?v=<TMPL_VAR VERSION ESCAPE=HTML>(?:-[\w-]+)?$/.test(url)),
'Every Explorer script needs the template-derived cache version');
const SCRIPT_NAMES = scriptUrls.map((url) => url.split('?')[0]);
const ORIGIN = 'https://loxberry.test';
const MCP_PATH = '/plugins/mcpserver/mcp';
const SESSION_PATH = '/plugins/mcpserver/oauth/explorer-session';
const START = Date.UTC(2026, 8, 27, 12);

const readTool = {
  name: 'future_read', description: 'Future read-only tool',
  annotations: {readOnlyHint: true, destructiveHint: false},
  inputSchema: {type: 'object', properties: {
    query: {type: 'string'}, optional: {type: 'string'},
    password: {type: 'string', format: 'password'},
  }, required: ['query']},
};
const secondTool = {
  name: 'another_read', description: 'Another read-only tool',
  annotations: {readOnlyHint: true, destructiveHint: false},
  inputSchema: {type: 'object', properties: {name: {type: 'string'}}},
};
const writeTool = {
  name: 'loxone_operate_control', description: 'Operate one control',
  inputSchema: {type: 'object', properties: {
    control_uuid: {type: 'string'}, action: {type: 'string', enum: ['on', 'off']},
  }, required: ['control_uuid', 'action']},
};

function createHarness(options = {}) {
  const errors = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', (error) => errors.push(error));
  const dom = new JSDOM(TEMPLATE, {
    url: `${ORIGIN}/plugins/mcpserver/explorer.cgi`, runScripts: 'outside-only',
    virtualConsole,
  });
  const {window} = dom;
  const {document} = window;
  let now = START;
  let nextTimer = 1;
  const timers = new Map();
  const NativeDate = window.Date;
  window.Date = class extends NativeDate {
    constructor(...args) { super(...(args.length ? args : [now])); }
    static now() { return now; }
  };
  window.setTimeout = (callback, delay = 0) => {
    const id = nextTimer++;
    timers.set(id, {callback, due: now + Number(delay)});
    return id;
  };
  window.clearTimeout = (id) => timers.delete(id);
  window.matchMedia = () => ({matches: false, addEventListener() {}, removeEventListener() {}});
  window.HTMLElement.prototype.scrollIntoView = function () {};
  window.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  window.HTMLDialogElement.prototype.close = function (value = '') {
    this.open = false;
    this.returnValue = value;
    this.dispatchEvent(new window.Event('close'));
  };
  const channels = options.channelBus || new Set();
  const ownChannels = new Set();
  window.BroadcastChannel = class {
    constructor(name) { this.name = name; channels.add(this); ownChannels.add(this); }
    postMessage(message) { [...channels].filter((peer) => peer !== this && peer.name === this.name)
      .forEach((peer) => peer.onmessage?.({data: message})); }
    close() { channels.delete(this); ownChannels.delete(this); }
  };

  const requests = [];
  const tools = options.tools || [readTool, secondTool, writeTool];
  let scope = options.scope === undefined ? 'loxone:read loxone:control' : options.scope;
  let sessionExpiresAt = START + (options.sessionMs || 600000);
  let pendingCall = null;
  let pendingLogout = null;
  const response = (body, status = 200) => ({
    ok: status < 400, status, statusText: status < 400 ? 'OK' : 'Error',
    headers: {get: (name) => name.toLowerCase() === 'content-type' ? 'application/json' : null},
    json: async () => body,
    text: async () => JSON.stringify(body),
  });
  window.fetch = async (url, init = {}) => {
    const pathname = new URL(url, ORIGIN).pathname;
    const body = init.body ? JSON.parse(init.body) : null;
    requests.push({pathname, body, headers: init.headers || {}, credentials: init.credentials});
    if (pathname === '/.well-known/oauth-protected-resource/plugins/mcpserver/mcp') {
      return response({resource: `${ORIGIN}${MCP_PATH}`,
        authorization_servers: [`${ORIGIN}/plugins/mcpserver/oauth`]});
    }
    if (pathname === '/.well-known/oauth-authorization-server/plugins/mcpserver/oauth') {
      const issuer = `${ORIGIN}/plugins/mcpserver/oauth`;
      return response({issuer, authorization_endpoint: `${issuer}/authorize`,
        token_endpoint: `${issuer}/token`, registration_endpoint: `${issuer}/register`,
        revocation_endpoint: `${issuer}/revoke`});
    }
    if (pathname === SESSION_PATH) {
      if (body.action === 'logout') {
        if (options.deferLogout) {
          return new Promise((resolve) => { pendingLogout = () => resolve(response({})); });
        }
        return response({});
      }
      if (options.restoreFailure) return response({error: 'expired'}, 401);
      return response({access_token: 'synthetic-token', scope,
        expires_in: 300, expires_at: Math.floor(sessionExpiresAt / 1000)});
    }
    if (pathname === MCP_PATH) {
      assert.equal(init.headers.Authorization, 'Bearer synthetic-token');
      const result = body.method === 'initialize'
        ? {protocolVersion: window.McpExplorerCore.PROTOCOL_VERSION}
        : body.method === 'tools/list' ? {tools}
          : body.method === 'tools/call' ? {structuredContent: {items: [{name: 'result'}]}} : {};
      if (body.method === 'tools/call' && options.deferCall) {
        return new Promise((resolve) => { pendingCall = () => resolve(response({jsonrpc: '2.0', id: body.id, result})); });
      }
      return response({jsonrpc: '2.0', id: body.id, result});
    }
    throw new Error(`Unexpected request: ${pathname}`);
  };
  for (const name of SCRIPT_NAMES) {
    window.eval(fs.readFileSync(path.join(ROOT, 'webfrontend/htmlauth', name), 'utf8'));
  }

  async function waitFor(predicate) {
    for (let i = 0; i < 50; i++) {
      await new Promise((resolve) => setImmediate(resolve));
      if (predicate()) return;
    }
    throw new Error(`Explorer did not reach expected state: ${document.querySelector('#explorer-status')?.textContent}`);
  }
  async function ready() {
    await waitFor(() => options.restoreFailure
      ? requests.some((item) => item.pathname === SESSION_PATH)
      : Boolean(document.querySelector('#explorer-tools button.mcp-explorer-tool')));
    assert.deepEqual(errors, []);
  }
  function advance(ms) {
    now += ms;
    for (const [id, timer] of [...timers]) {
      if (timer.due <= now) { timers.delete(id); timer.callback(); }
    }
  }
  const byId = (id) => document.getElementById(`explorer-${id}`);
  const calls = () => requests.filter((item) => item.body?.method === 'tools/call');
  async function click(element) { element.click(); await new Promise((resolve) => setImmediate(resolve)); }
  return {window, document, requests, tools, ready, waitFor, advance, byId, calls,
    click, setScope: (value) => { scope = value; },
    resolveCall: () => { assert.ok(pendingCall); pendingCall(); pendingCall = null; },
    resolveLogout: () => { assert.ok(pendingLogout); pendingLogout(); pendingLogout = null; },
    close: () => {
      for (const channel of [...ownChannels]) channel.close();
      dom.window.close();
    }};
}

module.exports = {createHarness, readTool, secondTool, writeTool, SCRIPT_NAMES};
