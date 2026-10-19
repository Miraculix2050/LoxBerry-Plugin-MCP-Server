# Native EFM Rest and display-unit contract

Scope: exact EFM firmware **17.2.8.28**, semantic rule
`native_efm_actual_semantics_17_2_8_28.v2`.

## Cpwr display-unit applicability

The official [Structure File 17.1](https://www.loxone.com/dede/wp-content/uploads/sites/2/2021/10/1701_Structure-File.pdf)
defines `details.actualFormat` on physical p.64 as the display format for current
values, explicitly illustrating consumed power. Physical p.67 identifies native
`get/actual.Cpwr` as power of loads. The
[EFM KB](https://www.loxone.com/dede/kb/energieflussmonitor/) independently labels
Cpwr as consumption power. This consumption-specific source chain supports the
declared display unit; equal values or neighboring fields do not establish it.

The existing strict stable-format W/kW rule covers Gpwr/Ppwr/Spwr/Cpwr and reports
`unit_origin=configured_display_format`. Metadata instability or rejection leaves
unit/origin unknown. Raw numbers are unchanged. This declares neither calibration
nor conversion, physical simultaneity or a universal aggregate inclusion formula.
Native result schema remains v2; retained semantic-rule v1 results remain readable.

## Rest without a unit

Return an available Rest value unchanged, with no assigned unit. Preserve its
source and delivery status. A present native `get/actual.Rest` retains its raw
number with `unit=null` and `unit_origin=null`; an omitted native field stays
missing rather than becoming zero or a calculated residual.

An explicitly identified Rest meter can be read separately through the existing
cached-state workflow: use its exact current control reference and `actual`,
without `native_result_view`. Report that raw value without a unit and identify
it as the meter value. It does not replace a missing native EFM field. The display
name alone does not establish a Rest role or binding.

Rest's documented block function is remaining top-group power. Residuals can
include unmetered loads, tolerances and asynchronous measurements. Do not force
zero balance, clamp signs or infer a fault or unmetered load from a residual alone.
Cached aggregates and individual participants also remain distinct sources.

## Evidence boundaries

Scoped read-only observations support the tested bindings; native Rest was not
delivered in that evidence. Detailed acquisition records remain in the private
evidence store. This contract makes no new deployment or general compatibility
claim. Native aggregate inclusion, physical sampling times, historical settings
and period unit/currency/calendar/reset/lifetime contracts remain independently
qualified in the [semantic matrix](efm-semantic-matrix.v1.md).
