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

Access and refresh tokens, arguments, results and call history exist only in the
open browser tab. The non-secret public `client_id` may be retained by origin and
scope to avoid consuming a new dynamic registration on each visit. Disconnect
and page unload attempt RFC 7009 revocation; the existing session UI remains the
reliable recovery path after a browser crash.

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
- Disconnecting, reloading or closing the page deliberately loses drafts,
  results, history and transcript data.
- Resources, prompts, sampling, arbitrary-server connections and protocol
  conformance suites remain responsibilities of external tools such as the
  official MCP Inspector.
- The explorer requires JavaScript; all existing configuration and session
  management retain their server-rendered fallback.
