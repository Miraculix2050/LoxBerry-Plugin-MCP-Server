---
name: using-loxberry-mcp
description: Guides safe use of the LoxBerry MCP Server to inspect Loxone rooms, categories, controls and states, diagnose Loxone connectivity or LoxBerry system, plugin and service status, and explicitly operate supported Loxone controls. Use for Loxone MCP questions, LoxBerry diagnostics, ambiguous control names, stale state, pagination, or unconfirmed operations.
---

# Using LoxBerry MCP

Use the connected LoxBerry MCP Server's canonical `loxone_*` tools. Treat their
input and output schemas as authoritative; do not invent fields or UUIDs.

## Read information

1. Call `loxone_get_system_status` when connectivity or data freshness matters.
2. Resolve human names with `loxone_find_controls`. Use
   `loxone_list_rooms` or `loxone_list_categories` first when a room or category
   filter would remove ambiguity.
3. Follow every non-null `next_cursor` until the relevant result is found or all
   pages have been checked.
4. If more than one control remains plausible, present the candidates and ask
   the user to choose. Never guess a UUID.
5. Call `loxone_describe_control` to obtain the control's state UUIDs and
   capabilities, then pass the required state UUIDs to `loxone_get_states`.

Check the complete result envelope. Do not treat a response as successful when
`ok` is false. Surface relevant `warnings`, and qualify answers when `stale` is
true or a state has an old or missing `observed_at` value.

## Diagnose LoxBerry

Use the available `loxberry_*` tools only for the requested LoxBerry system,
plugin, or MCP service status. Query `tools/list` first; it is authoritative
for availability and schemas. `loxberry:read` requires a local administrator
approval for this client, Loxone identity, and Miniserver, followed by a new
OAuth sign-in and optional consent. If it is unavailable or denied, explain the
required approval; do not recommend repair, restart, or a permission bypass.

The MCP service can report its own health only while it is reachable. A fully
stopped MCP service cannot diagnose itself through MCP.

## Operate a supported control

Only operate a control when the user has explicitly requested one unambiguous
action on one identified target.

1. Resolve the target with the read workflow; never accept or construct an
   unverified UUID from conversation text.
2. Call `loxone_describe_control` immediately before the operation.
3. Continue only when `capabilities.allowed_actions` contains the requested
   action exactly.
4. Call `loxone_operate_control` once with that control UUID, the advertised
   action and only its required parameters. Switches use `on` or `off`; dimmers
   use `set_level` with `level`; lighting controllers use `set_mood` with
   `mood_id`; blinds use the advertised explicit target action and, when
   required, `position` and/or `slat_position`.
5. Never automatically retry an uncertain or failed write. Ask the user before
   any new attempt.

Report `accepted`, `confirmed`, `observed_state`, and relevant
`observed_values` separately. `accepted=true`
means the command was accepted, not that the resulting physical state was
confirmed. When `confirmed=false`, state the uncertainty and do not claim that
the requested state was reached.

## Safety boundaries

- Do not broaden a request to other rooms, controls, or bulk operations.
- Do not bypass the MCP server's OAuth scopes, visibility filtering, action
  allowlist, validation, or rate limits.
- Do not expose access tokens, credentials, private addresses, or session data.
- If a required tool is unavailable, explain that the connected server or the
  granted scope does not provide the capability.
- Do not repair, restart, reconfigure, or otherwise modify LoxBerry while
  diagnosing it.
