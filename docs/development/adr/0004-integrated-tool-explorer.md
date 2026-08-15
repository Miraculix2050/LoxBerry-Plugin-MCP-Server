# ADR 0004: Integrated MCP Tool Explorer

- **Status:** Accepted
- **Date:** 2026-08-04

## Context

Maintainers need a small browser surface for discovering, calling and validating
the plugin's MCP tools without depending on an AI client. The official MCP
Inspector remains the reference for broad protocol debugging, but embedding it
would add a separate React, Mantine and Node runtime to the LoxBerry package.

The LoxBerry admin login does not grant Loxone permissions. Any integrated
explorer therefore has to act as a normal public MCP OAuth client rather than
calling runtime adapters or administrative helpers directly.

## Decision

The plugin ships a separate `htmlauth` Tool Explorer for its own fixed MCP
endpoint. It uses OAuth discovery, dynamic client registration, Authorization
Code with PKCE, Streamable HTTP initialization, `tools/list` and `tools/call`.
It cannot connect to arbitrary URLs. A plugin-owned, encrypted server-side
Explorer session retains the refresh credential so new Explorer tabs can reuse
one OAuth client and family for at most eight hours.

The Explorer uses the HTTPS origin from which its page was opened for browser
requests. The configured OAuth issuer and resource remain canonical protocol
identifiers, while the LoxBerry hostname and its local IP address are accepted as
finite network aliases after the backend Host allowlist has validated them. This
keeps links, callbacks and permission selection on the address chosen by the
operator without allowing arbitrary origins.

Access tokens, arguments, results and call history exist only in memory in the
open browser tab. The browser never persists OAuth credentials in
`sessionStorage` or `localStorage`. The encrypted server-side Explorer session
retains the client id, OAuth family, refresh credential and current token state.
The visible transcript, rendered result panels and unsent drafts remain
tab-scoped and are never shared with another tab.

Refresh-token rotation is serialized by the server per Explorer session. A new
tab restores a short-lived access token through the private session endpoint and
does not receive a refresh credential. Browser Web Locks are therefore not used
for OAuth refresh coordination.

The refresh credential is not available to scripts running in the Explorer's
origin. The browser session identifier is delivered only in a `Secure`,
`HttpOnly`, `SameSite=Strict` cookie. Session requests require the canonical
Origin, JSON content type and an explicitly parsed request body. The same-origin
policy and a strict Content Security Policy remain important boundaries for the
access token held in tab memory.

Dynamic client registrations that have not entered an authorization flow expire
after one hour. With the public rate limit of 16 registrations per five minutes,
at most 192 unused clients can remain concurrently—below the persistent capacity
of 256. Clients referenced by an authorization code or token family remain
governed by their respective OAuth lifetime.

Browsers cannot reliably distinguish reload from tab close or guarantee an
unload request. The explorer therefore does not claim automatic revocation on
page unload. Explicit disconnect performs RFC 7009 revocation and deletes the
shared Explorer session for every tab. Explorer OAuth families identified by
both their fixed name and exact local callback expire after at most eight hours
instead of the normal 30 days; session cleanup also deletes their encrypted
Explorer session.

Input schemas produce a small accessible form for the schema subset used by the
published tools. A synchronized raw JSON editor remains authoritative for shapes
the form does not support. The server performs final input validation. Structured
results are checked against their advertised output schema and can be inspected
as a tree or raw JSON.

Result reuse is explicit: a user selects one result path and one compatible
top-level parameter of a new tool call. The explorer never infers or executes a
workflow automatically. Calls are kept in a bounded in-memory history. The MCP
transcript contains methods, sanitized JSON-RPC bodies, status and duration but
never authorization headers, OAuth values or secret-shaped arguments.

Read access is the default. Control scope is requested only after an explicit
selection and only when advertised by the server. A state-changing tool requires
that scope and a separate confirmation immediately before every call. Existing
server-side visibility checks, rate limits, audit logging and control defaults
remain authoritative.

## Consequences

- No new production dependency, service, port, configuration key or MCP contract
  is introduced.
- Reloading or opening a second tab preserves the Explorer sign-in while its
  eight-hour session remains valid. Drafts, results, history and transcript data
  remain tab-scoped.
- Resources, prompts, sampling, arbitrary-server connections and protocol
  conformance suites remain responsibilities of external tools such as the
  official MCP Inspector.
- The explorer requires JavaScript; all existing configuration and session
  management retain their server-rendered fallback.
