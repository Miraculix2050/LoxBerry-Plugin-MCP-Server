# Read-only MCP prompt templates

Clients supporting MCP prompts can select a task through `prompts/list` and
retrieve it with parameters through `prompts/get`. Eight analysis recipes join
the two [KNX recipes](knx-mcp.en.md). Retrieval performs no data query, analysis
or change and grants no permission. It returns one text message for the subsequent
AI workflow. Existing tools remain usable in clients without prompt support.

| Name | Purpose | Parameters besides `language` and `detail` |
| --- | --- | --- |
| `lighting_naming_review` | Review visible light names and source-proven moods | optional `room_uuid`, `focus=all\|names\|moods` (default `all`) |
| `presence_light_association` | Explain explicit project connections between presence and lights | optional `room_uuid` |
| `current_state_summary` | Summarize actual temperatures or proven operating states | optional `focus=temperature\|operating_state` (default `temperature`), `room_uuid` or `control_uuid` |
| `temperature_history_summary` | Analyze temperature samples in an interval | exactly one `binding_id` or `control_uuid`; required `start`, `end`, `timezone` |
| `solar_daily_report` | Report available energy components for one local day | required `date`, `timezone`; optional production `binding_id` |
| `comparable_day_review` | Select qualitative radiation-class peers | required `reference_date`, `start`, `end`, `timezone` |
| `consumer_pv_comparison` | Compare consumer/PV timing or rank energy consumption | required `start`, `end`, `timezone`; optional `focus=overlap\|ranking` (default `overlap`), `consumer_binding_id` |
| `energy_period_report` | Build a qualified calendar week/month report | required `period=week\|month`, contained `date`, `timezone` |

All parameters are strings. `language=en|de` selects the answer language (default
`en`); `detail=summary|findings` selects depth (default `summary`). The technical
recipe message remains English. `summary` prefers compact overviews; `findings`
requests required bounded continuation pages. An arbitrary page cutoff never
proves completeness. Responses retain the 50-record upper bound.

Identifiers must come from current authorized discovery or a currently confirmed
profile. UUID selectors allow 1–128 ASCII letters, digits, underscores and
hyphens; binding IDs allow at most 64. `control_uuid` also retains the existing
contract for runtime child-control IDs of at most 128 characters: a UUID prefix
and an unchanged opaque suffix such as `…/AI1`. This key is not a file path or
evidence of a parent object; it remains unchanged JSON data. Validation proves
syntax only, never existence, visibility or role. Names, free-form instructions, paths and URLs are
not selectors. Missing or ambiguous targets are resolved in the subsequent
workflow. Selecting a temperature control still requires selecting an advertised
actual-temperature series there; a profile binding must be confirmed and usable.

Dates use `YYYY-MM-DD`. `start`/`end` are RFC3339 instants with seconds and an
offset or `Z`; the half-open interval touches at most 31 local days. `timezone`
explicitly specifies an IANA timezone. Weeks start Monday; months start on day one.
Day/period boundaries follow that timezone, including 23-/25-hour days. Running
periods remain incomplete; future periods produce no historical report. Larger
source sets must be processed separately within existing analysis limits.

Example `prompts/get` MCP parameter object:

```json
{
  "name": "solar_daily_report",
  "arguments": {
    "date": "2026-10-17",
    "timezone": "Europe/Berlin",
    "language": "en",
    "detail": "summary"
  }
}
```

For a temperature report use `temperature_history_summary`, for example with
`binding_id="room_temperature"`, `start="2026-10-17T00:00:00+02:00"`,
`end="2026-10-18T00:00:00+02:00"`, `timezone="Europe/Berlin"` and `language="en"`.
Replace the example binding ID with an actually confirmed binding.

## Evidence and limitations

Recipes load `core` and only the relevant skill modules unless already loaded for
this server revision. Missing modules, capabilities, sources, profiles or rights
yield a qualified partial or unavailable answer. Actual reads recheck existing
permissions. A Loxone login grants no LoxBerry rights; retrieval confirms neither
measurement-boundary comparability nor permission for writes.

- Light names and source moods prove neither complete scene inventory nor
  physical circuits, scene roles or professional lighting design (#441).
  Presence associations require explicit project paths; room membership is insufficient.
  With `room_uuid`, first discover visible room controls and map their exact UUIDs
  to project objects; project search has no room filter. Preserve ambiguous
  mappings and cross-room endpoints.
- Temperature means are sample means, not time-weighted means. Actual/setpoint
  temperatures, freshness and coverage remain separate.
- Solar reports remain component reports. Native EFM calendar views describe
  running periods and cannot fill historical gaps. Unsupported self-consumption,
  storage or residual-load components remain unknown.
- Comparable days use only the existing qualitative radiation-class method.
  Explicitly choose a common local hour window before calling it. Preserve the
  class assumption, warnings, gaps and DST exclusions. The separately implemented
  numeric comparison method and its outstanding acceptance gates in #439 are
  outside this qualitative recipe; it supplies no causal explanations.
- Consumer/PV overlap proves no exact solar attribution. Rankings require explicit
  human confirmation of comparable boundaries and excluded parent/child overlap;
  selecting the recipe is not confirmation.
- Load-shifting and prospective planning are outside these recipes. The separate
  conditional workflows from #440 and [PVPF future planning](pv-planning.en.md)
  retain their own prerequisites.

[Analysis support and limitations](analysis-support.en.md) remain authoritative.
Mapping recipes to existing scenarios extends no earlier acceptance or
compatibility claim. Automated SDK/wire tests establish the protocol contract,
not universal chat-client support or new hardware acceptance. Each expansion is
at most 4 KiB UTF-8; the complete catalog is at most 16 KiB.
