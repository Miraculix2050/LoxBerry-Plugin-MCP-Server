# State-reference response measurements

Issue #313 evaluates `loxone_describe_control(view="state_refs")` against
`history_targets` for state-reference discovery before a separate value read.

## Method and decision

Measurements use the complete structured tool envelope serialized with
`json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8")`.
Both responses use identical normalized control data, fixed `observed_at` and
`trace_id`, and a connected runtime. Fixtures have a 36-character control UUID,
name `Fixture`, no room/category assignment, `state-N` names, and 36-character
state UUIDs. Statistic fixtures advertise 128 normalized series with IDs/titles
`series-N` / `Series N` and format `W`. These are synthetic fixtures, not a
physical installation or performance benchmark.

The approved decision rule requires both simple cases to save at least 25%
and both statistics-rich cases to save at least 1 KiB, together with lossless
reference selection and value-read argument construction. The proposed six-field
projection was measured before implementation; final implementation tests
reproduce the same sizes and exercise the complete Describe-to-GetStates flow.

| Fixture | States | Statistics | history_targets bytes | state_refs bytes | Saved bytes | Saved % | Value reads |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Switch | 1 | 0 | 533 | 332 | 201 | 37.71 | 1 |
| Dimmer | 5 | 0 | 793 | 592 | 201 | 25.35 | 1 |
| State-rich | 100 | 0 | 7,058 | 6,857 | 201 | 2.85 | 1 |
| State-rich | 101 | 0 | 7,125 | 6,924 | 201 | 2.82 | 2 |
| State-rich | 256 | 0 | 17,510 | 17,309 | 201 | 1.15 | 3 |
| Statistics-rich Switch | 1 | 128 | 13,752 | 332 | 13,420 | 97.59 | 1 |
| Statistics-rich Dimmer | 5 | 128 | 14,012 | 592 | 13,420 | 95.78 | 1 |
| Statistics-truncated Dimmer | 5 | 128 | 14,011 | 592 | 13,419 | 95.77 | 1 |

Decision: implement `state_refs`. Both size gates pass, and the controlled
client workflow preserves every selected unique UUID through batches of at
most 100. The simple Dimmer is close to the relative threshold: these figures
do not promise the same reduction for different names, state counts, or metadata.
Savings for state-rich controls without statistics are small because the
reference list itself dominates. A truncated statistic list does not truncate
state references; its history-specific flag is intentionally absent from this view.

For all rows the initial name-discovery call and description call remain the
same. Selecting all unique states then requires the value-read calls shown;
the new view does not reduce call count. Alias names sharing a UUID remain in
the description; a client deduplicates UUIDs before reading. Empty selections
need no value-read call. No values or related-control references are added to
the description, and no reference pagination or additional truncation is introduced.

## Freshness and evidence limits

`state_refs` loads the current user-filtered structure for each description,
inside the existing authenticated/rate-limited call slot. This can add a
Miniserver structure read compared with cached `history_targets`; the byte
measurement above is not a latency, token, CPU, or total-network-cost claim.
Refresh failure returns an error without cached fallback. `stale` indicates
a disconnected event stream; description `observed_at` is not a value timestamp.
Only the complete normalized references of the requested control are returned,
not a complete physical/configuration inventory. Values retain their own
freshness/observation evidence through `loxone_get_states`.

Earlier read-only measurements on six live MCP-Test controls in #263 reported
approximately 320 bytes (10.6-46.9%) saved by a prototype versus `history_targets`.
Those samples contained live room/category context and come from one authorized
runtime. They are supplementary evidence, not live acceptance of this implementation.
No target deployment or live control writes were performed for #313.

Reproduce the fixture measurements and client workflow with:

```text
python -m pytest -q -s tests/test_state_refs.py
```
