# Local weather history

Weather recording is independently **off by default**. In Admin â†’ Configuration,
enable Loxone history, load the current weather sources, select the fields to
record, save the source, then explicitly save the weather-recording activation.
Scalar event recording can remain off. Disabling recording preserves retained
data. Removing a source stops its recording; complete history deletion also
deletes weather data. Retention and the size limit are shared with event history.

The existing recorder and SQLite database store only the configured fields.
Current source values and forecasts retain separate modes. Receipt of a value
does not prove an actual measurement. Unknown units and radiation encoding stay
unknown. The recorder does not reconstruct earlier weather or fill interruptions.

Use `loxone_get_weather(mode="history", history_options=...)` with an exact
currently visible `state_uuid`, `stored_mode`, and offset-aware `start`/`end`.
The period is at most 31 days on the **local reception axis**, with an exclusive
end in the past. Activated `loxone:read` and `loxone:history` are required on every
page. The configured recorder source must still match; recording itself can be off.

Default pages show delivery/point metadata and capture phases; numeric raw values
require `include_raw=true`. Up to 96 point rows and 128 capture phases are returned.
The complete response is bounded at 64 KiB; use a smaller page if necessary.
Follow `next_cursor` unchanged. Clear, retention, source/field/format changes or
another caller invalidate its scope; restart at page one.

`received_at`, `point_at` and `reported_update_at` are independent Unix UTC seconds.
Future forecast points remain forecasts in a query about past receptions. The
reported update is not proven forecast issuance. Capture readiness is distinct
from delivered-point coverage and establishes no provider cadence or continuous
observation. Actual mode projects the first point and rejects future point times.
Newly received older points carry `point_predates_capture=true`; they do not
establish capture coverage before recording start. Invalid or oversized deliveries create an
explicit interruption; no successful partial completeness is claimed.

Only the current installation/source/field/metadata fingerprint is read. Older
generations remain subject to retention and deletion but are not silently mixed.
Selected-field formats and weather-type texts are provenance, not unit proof;
station/provider/location changes cannot all be detected. This stage does not
select comparable days or establish a PV forecast.

The shared SQLite schema becomes v8 through an atomic, repeatable migration.
Before a Hotswap, take a WAL-consistent v7 backup with the existing deployment/
native upgrade helper. Older code rejects v8: a code rollback alone is insufficient.
Save the current v8 database before restoring the v7 snapshot; that restores its
earlier data state, while subsequent records remain in the separate v8 backup.
Hotswap evidence does not establish native installation or upgrade compatibility.
