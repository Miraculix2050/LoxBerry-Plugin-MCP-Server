# Data for numerical solar-day comparisons

Numerical comparisons need historical radiation energy and temperature, plus
independent PV-yield data. Suitable local sources are checked for units, time
meaning and installation association first. A documented contract and a real data
sample suffice; general hardware qualification is not required.

Direct hourly radiation energy in Wh/m² or MJ/m² is preferred. For observed W/m²
values, the plugin may estimate energy using trapezoidal integration. Gaps longer
than twice the sampling period, capped at 60 minutes, are not bridged; values
outside available observations are not extrapolated. Calculated energy remains
explicitly estimated. Incomplete hours are excluded instead of filled with zero.

Radiation calculated from the PV production being assessed is not an independent
weather baseline. Forecasts, lux and radiation classes cannot replace observed
radiation energy either. Without a suitable local source, numerical comparison
remains unavailable. The existing qualitative class method remains usable. The
internal hourly normalization alone enables neither a source nor recording;
#509 and #439 remain open until full acceptance.
