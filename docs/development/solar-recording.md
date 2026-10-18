# Local solar recording and native PV forecasts

Local Admin source management uses the existing authenticated same-origin POST
boundary. `event_history.solar_enabled` defaults to false; `solar_sources` defaults
to an empty list. Each of at most 16 sources selects an exact visible control and
state (or a whole `PvProductionForecast`), quantity/unit, 60–1800-second sampling
period, documentation reference and explicit source confirmation. Admin source
contracts are recorded declarations, not caller-supplied MCP decoder rules or
physical calibration. Select actual independent weather, never irradiance derived
from the assessed PV output. The native current absolute-irradiance channel is
distinct from the raw structured-weather radiation-class field.

The existing service-owned history stream supplies samples. No new connection per
source, external provider request, database or service is introduced. Local ticks
sample the current connected stream cache, including unchanged states; reconnects
start with an empty cache. A source error blocks scalar capture when its error
state is advertised. PVPF snapshots require all ten documented states and at least
two quiet seconds after an update; this is a practical settled-cache snapshot,
not a protocol guarantee of atomic native updates. Reception timestamps establish
local observations, not continuous physical measurement timestamps. Sampling
cannot reconstruct a pre-existing history.

The shared SQLite schema migrates V8 to V9 transactionally, preserving scalar and
weather tables and adding `solar_samples` with source/fingerprint/time and retention
indices. Fingerprints bind installation, configuration, exact references and
presentation generation. Queries use one bounded indexed source/range read.
Retention, oldest-prefix size eviction and complete deletion cover all three
datasets. Existing configured 16–1024 MiB bounds remain unchanged. For Hotswap,
take a WAL-consistent SQLite backup first; rollback restores matching code and
database together. Older V8-only code must not be installed against a V9 store.

Native PVPF semantics use Structure File 17.1, PDF page 115. Energy states `period`,
`today`, `tomorrow`, `after` are predicted kWh; time states use seconds since 2009.
`ready=0`, energy -1 and error flags mean unavailable predictions; zero timestamps
are unavailable. The error bitmask uses bit 0 InternetError and bit 1
WeatherServiceError. Unsupported bits stay invalid. Forecast energy requires
current readiness/error/time companions. Source prediction freshness remains
separate from cache freshness and must be assessed from prediction/cycle times.
No control write, source repair, hourly PV forecast or plant model is introduced.
