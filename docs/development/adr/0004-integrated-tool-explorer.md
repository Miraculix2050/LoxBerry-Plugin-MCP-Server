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
It cannot connect to arbitrary URLs and does not add a proxy or server-side token
store.

The Explorer uses the HTTPS origin from which its page was opened for browser
requests. The configured OAuth issuer and resource remain canonical protocol
identifiers, while the LoxBerry hostname and its local IP address are accepted as
finite network aliases after the backend Host allowlist has validated them. This
keeps links, callbacks and permission selection on the address chosen by the
operator without allowing arbitrary origins.

Access tokens, arguments, results and call history exist only in memory in the
open browser tab. A strictly validated refresh token and its minimal binding data
may additionally exist in that tab's `sessionStorage`. This allows a reload to
rotate the refresh token immediately and restore the MCP connection without
persisting the credential as normal local browser data after the tab is closed.
A Web Lock tied to a random session identifier prevents a duplicated tab from
automatically replaying the same single-use refresh token. The resumable record
is removed before every rotation, so a reload that interrupts an in-flight
rotation fails closed instead of replaying a possibly consumed token. The
non-secret public `client_id` may be retained by origin and scope to avoid
consuming a new dynamic registration on each visit.

`sessionStorage` is isolated by origin and top-level browsing context, not by URL
path. The LoxBerry admin origin is therefore part of the Explorer trust boundary:
other same-origin code running in the same tab could read the refresh credential.
This design does not claim isolation from a malicious or compromised same-origin
plugin. Operators must install only trusted admin plugins; stronger isolation
would require a separate origin or a server-side browser-session architecture.

Browsers cannot reliably distinguish reload from tab close or guarantee an
unload request. The explorer therefore does not claim automatic revocation on
page unload. Explicit disconnect performs RFC 7009 revocation, Explorer OAuth
families identified by both their fixed name and exact local callback expire
after at most eight hours instead of the normal 30 days, and the existing session
UI remains the reliable recovery path after a crash or close. Startup garbage
collection also caps matching families created before this rule was installed.

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
- Reloading preserves only the Explorer sign-in. Reloading or closing still loses
  drafts, results, history and transcript data; closing also normally discards the
  tab-scoped refresh credential.
- Resources, prompts, sampling, arbitrary-server connections and protocol
  conformance suites remain responsibilities of external tools such as the
  official MCP Inspector.
- The explorer requires JavaScript; all existing configuration and session
  management retain their server-rendered fallback.
