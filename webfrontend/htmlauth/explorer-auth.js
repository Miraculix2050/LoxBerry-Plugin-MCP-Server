/* OAuth and server-side Explorer session boundary. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.McpExplorerAuth = api;
})(typeof window !== 'undefined' ? window : undefined, function () {
  'use strict';
  function create({core, state, explorerState, label, clearOriginWarning, renderConnection, revokeAndClear}) {
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
      return registration.client_id;
    }

    function waitForAuthorization(popup, expectedState) {
      return new Promise((resolve, reject) => {
        let finished = false;
        const authorizationChannel = typeof BroadcastChannel === 'function'
          ? new BroadcastChannel('mcp-explorer-oauth')
          : null;
        const finish = (callback) => {
          if (finished) return;
          finished = true;
          window.clearInterval(closedTimer);
          window.clearTimeout(timeout);
          window.removeEventListener('message', onMessage);
          authorizationChannel?.close();
          callback();
        };
        const onMessage = (event) => {
          if (!core.acceptOAuthMessage(event.origin, window.location.origin, event.data, expectedState)) return;
          finish(() => event.data.error ? reject(new Error(event.data.errorDescription || event.data.error)) : resolve(event.data.code));
        };
        const onChannelMessage = (event) => {
          if (!core.acceptOAuthPayload(event.data, expectedState)) return;
          finish(() => event.data.error ? reject(new Error(event.data.errorDescription || event.data.error)) : resolve(event.data.code));
        };
        window.addEventListener('message', onMessage);
        if (authorizationChannel) authorizationChannel.onmessage = onChannelMessage;
        const closedTimer = window.setInterval(() => {
          if (popup.closed) finish(() => reject(new Error(label('authCancelled'))));
        }, 500);
        const timeout = window.setTimeout(() => {
          try { popup.close(); } catch (_error) { /* already gone */ }
          finish(() => reject(new Error(label('authCancelled'))));
        }, 5 * 60 * 1000);
      });
    }

    async function explorerSession(metadata, body) {
      return fetchJson(metadata.explorer_session_endpoint, {
        method: 'POST', cache: 'no-store', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
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
      const token = await explorerSession(discovered.authorizationMetadata, {
        action: 'complete', client_id: clientId, code, redirect_uri: redirectUri,
        code_verifier: verifier, resource: discovered.resourceMetadata.resource,
      });
      if (!token.access_token) throw new Error('Explorer session response is incomplete');
      return {
        metadata: discovered.authorizationMetadata,
        resource: discovered.resourceMetadata.resource,
        scope: typeof token.scope === 'string' ? token.scope : '',
        accessToken: token.access_token,
        expiresAt: Date.now() + Math.max(0, Number(token.expires_in || 0) - 15) * 1000,
        resumeUntil: Number(token.expires_at || resumeUntil) * 1000,
      };
    }

    async function refreshAccessToken() {
      const oauth = state.oauth;
      if (!oauth) throw new Error(label('tokenExpired'));
      const token = await explorerSession(oauth.metadata, {action: 'access'});
      if (state.oauth !== oauth) {
        const error = new Error(label('tokenExpired'));
        error.sessionCleared = true;
        throw error;
      }
      if (!token.access_token) throw new Error('Explorer session response is incomplete');
      explorerState.updateToken(token);
      renderConnection();
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

    return {discover, authorize, refreshAccessToken, accessToken,
      explorerSession, openAuthorizationPopup, fetchWithTimeout};
  }
  return {create};
});
