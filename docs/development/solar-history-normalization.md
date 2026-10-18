# Local solar observation normalization

The numerical comparable-day adapter uses `solar_history.normalize_hours` to
prepare complete hours without transport, authorization or database dependencies.
This module does not register a source or enable recording. Its internal
`ObservationContract` must come from a source adapter with a documented quantity,
unit, time axis, installation association and source generation. An MCP analysis
caller cannot submit this contract as evidence.

Observed interval radiation energy accepts Wh/m² or MJ/m²; isolated electrical
energy accepts Wh or kWh. Only exact complete hourly intervals are used. A
temperature source supplies a Celsius observation at the exact hour start.
Missing observations never become zero or shrink the common comparison window.

Observed irradiance samples accept W/m² with an explicit sampling period. The
bounded trapezoidal model integrates adjacent samples, clipping segments at hour
boundaries. It never extrapolates or bridges a gap exceeding twice the sampling
period or 60 minutes, whichever is smaller. Results identify themselves as
estimated Wh/m² with method `bounded_trapezoidal_irradiance.v1`. This is a declared
integration approximation, not measured interval energy or physical calibration.
Forecast points are not accepted observations.

Each request normalizes at most 100,000 points and 744 hour positions under the
existing analysis deadline. Sorting is followed by a monotonic segment traversal;
source data is not loaded or scanned afresh for each comparison day. Duplicate
positions, overlapping energy intervals, nonfinite values and invalid units are
rejected. Source/installation changes are handled by the adapter before combining
hours, never by averaging across generations.

## Source selection and practical evidence

Prefer available native hourly statistics and existing local observations.
Qualification needs a source contract, an explicit installation association and
a representative real sample; it does not require a general hardware survey.
An irradiance signal calculated from the PV production being assessed is a
circular comparison baseline and must not be used to assess that production.
Lux, radiation classes, forecast energy and arbitrary display formats cannot
establish independent observed irradiance.

This normalization foundation is independently tested. It does not complete
#509/#439, establish an installed source or prove real historical coverage.
