# Energy & solar: agreed intermediate delivery

The owner approved completing the usable intermediate PR series separately from
the original numerical-comparison and full PV-planning goals. This changes the
delivery boundary, not the qualification of available data.

| Package | Delivered capability | Evidence boundary |
| --- | --- | --- |
| 1–4: #486, #492, #494, #495 | Native energy reading, bounded semantics, Energy Manager context, confirmed weather/installation profile | Missing native meanings remain explicit. |
| 5: #496 | Opt-in local weather reception recording | No backfill; point, reception and reported-update times are separate. |
| 6: #505 | Qualitative comparable-day class analysis | Native classes 0–3 use an explicit owner assumption; no numerical irradiation-energy or normalized-yield qualification. |
| 7: #506 | Confirmed load flexibility and observed complete-cycle evidence | Owner constraints do not prove native lock clearance. |
| 8: #507 | Conditional retrospective export-absorption examples sharing one budget | Unknown historical native locks block admissibility; no measured self-consumption, savings or operation permission. |
| 9: local irradiance guidance | Opt-in fixed-source discovery, bounded W/m² sampled future windows and configuration explanations | Weather guidance only; no irradiance-energy conversion, PV yield, surplus or admissible schedule. |

Package 9 must complete normal review, exact-head CI and scoped target/browser
acceptance before merge. Source fixtures establish adapter behavior; genuine
source availability, installed software behavior and physical plant validation
are separate evidence. No general compatibility claim follows from one source.

## Follow-ups and later delivery

- [#509: qualified historical irradiation energy and numerical comparable days](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/issues/509)
  tracks the original 15% irradiation-energy method and resulting yield/deviation
  assessment. The explicit numerical runtime is delivered; usable results
  still require qualified historical inputs. Lux and forecasts cannot replace
  observations.
- [#510: qualified local PV-yield forecasts and full future load planning](https://github.com/Miraculix2050/LoxBerry-Plugin-MCP-Server/issues/510)
  tracks PV-output/plant-model evidence, baseload, storage, competing loads and
  current native constraints. Until then, future outputs remain sampled weather
  guidance with explicit missing evidence and configuration suggestions.

This is the historical intermediate boundary, not current tracker status.
The later #439/#509 technical closeout follows the owner-revised
[acceptance criteria](solar-history-acceptance.en.md); other issues retain their own
gates. Future Config MCP imports require a separately authorized integration; no device scheduling or
operation is introduced. Independent performance/resource measurements remain
outside this delivery and are not claimed as passing or used as its merge gate.
