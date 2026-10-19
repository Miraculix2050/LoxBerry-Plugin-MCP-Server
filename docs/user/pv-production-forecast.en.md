# Native PV forecasts and solar recording

Describe the visible `PvProductionForecast` control and read its named states with
semantics. `period`, `today`, `tomorrow` and `after` are forecasts in kWh.
`ready=0`, prediction values of -1 or error flags mean no available prediction.
Prediction time and cycle bounds are separate from reception time; a newly read
state does not guarantee a newly issued forecast.

In Admin, open “Solar observations and PV forecasts”, load sources, review and
confirm installation association, units and the source contract. Add sources to
the selection, optionally enable recording, then select “Save and apply solar
recording”. Selection alone does not start recording. Loxone history must be
enabled. Concurrent changes require reloading. Stored data remains after source
removal until shared retention or complete deletion.
Saved selection, disabling and source removal remain available while the
Miniserver is offline; new sources and enabling require current visibility.

Only selected current irradiance/temperature states or settled PV-forecast
snapshots are recorded, at a default 60-second interval. State samples are not
continuous physical measurements; a disconnect does not continue an old stream's
cache. Forecasts remain forecasts and do not create retrospective history.
Irradiance derived from the PV production being assessed is not an independent
weather baseline. PVPF replaces neither observed radiation history nor storage
accounting.

The shared SQLite history format extends to V9. Before a file Hotswap, take a
consistent database backup; reverting to V8 requires restoring matching program
files and the database backup together.
