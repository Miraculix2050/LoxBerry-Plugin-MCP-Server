# Native EFM Rest and display-unit observations

Reviewed 2026-10-19; exact observed firmware: **17.2.8.28**. This is a bounded
read-only follow-up to #534, not a general aggregation or compatibility claim.

## Independent source chain for Cpwr's display unit

The official [Structure File 17.1](https://www.loxone.com/dede/wp-content/uploads/sites/2/2021/10/1701_Structure-File.pdf)
defines `details.actualFormat` on physical p.64 as the display format for current
values, explicitly illustrating current consumed power. Physical p.67 identifies
native `get/actual.Cpwr` as power of loads. The
[EFM KB](https://www.loxone.com/dede/kb/energieflussmonitor/) independently labels
the block output Cpwr as consumption power. This provides a consumption-specific
display-format applicability chain, rather than borrowing a neighboring field's
unit or deriving a unit from equal numbers.

Fresh caller-authorized reads on 2026-10-19 separately corroborated that chain:
three native actual requests were bracketed by exact EFM/meter reads; native
Cpwr matched the explicitly referenced consumption meter in at least one
adjacent read in every round. The same EFM's normalized `actualFormat` was
retained and unchanged before/after. Five participant references and their
firmware-bound state UUID joins were resolved; all 30 adjacent meter/participant
comparisons were equal. These sequential software observations do not establish
physical simultaneity, a universal Cpwr inclusion formula or source calibration.

Rule `native_efm_actual_semantics_17_2_8_28.v2` therefore extends the existing
exact W/kW display-format rule to Cpwr, with
`unit_origin=configured_display_format`. It retains the original bounded format
allowlist, before/after metadata checks and source requests. Metadata instability
or rejection drops unit/origin; no numeric conversion is performed. Native result
schema remains v2 and transport rule remains v1. The v1 semantic version remains
readable for retained earlier results. Signs and physical boundaries stay unknown.

## Rest sources remain separate

The current structure advertised a participant referencing a meter displayed as
Rest, with an explicit firmware-verified EFM state reference. Its meter/state
values agreed in all six adjacent comparisons and included negative, zero and
positive values. Its display name is not used to invent a residual-role decoder.

In contrast, native `get/actual.Rest` was **missing in all three responses**.
It is neither zero nor a copy of the participant state. Existing native decoding
and missing-field handling are retained; no synthesized field or residual formula
is introduced. The documented remaining-top-group-power block function remains
known independently of that native omission.

Cached production aggregate values also differed from the explicitly referenced
production participant in one adjacent read. This is cached-state evidence, not
a positive native production specimen or proof of a calculation formula. Never
alias an aggregate to one participant or reconstruct a balance from this example.

## Acquisition and limitations

The exclusive queue reservation was checked, used for bounded reads and released.
Current canonical HTTP-MCP schemas, core/energy/states guidance, firmware-bound
references and installed decoder source were inspected. Two additional
same-family fresh runtime snapshots inspected only the exact EFM's normalized
display format because full MCP descriptions did not expose that string. Other
raw formats were not retained by the installed normalized EFM model.

The inventory's optional project-object request returned `unauthenticated`; its
envelope was preserved and that request was not retried or bypassed. Its cause
is unverified. The later canonical state/native comparisons and authorized format
snapshots succeeded independently. No project-derived claim depends on the
failed request. Installed code/configuration hashes and service PID remained
unchanged. The target was not deployed to, restarted, controlled or reconfigured;
recording was not activated.

Complete canonical result envelopes, warnings, software observation/receipt times,
trace IDs, firmware, exact references, preservation hashes and source applicability
are retained privately. Public material contains no household values, identities,
screenshots or private configuration. Local replay of retained numeric results is
separate from live acceptance of newly installed code; this change makes no such
deployment claim. Rounding, asynchronous updates, tolerances and possible
unmetered loads preclude forced zero balances or fault/consumer conclusions from
a residual alone. Period units/currency/calendar/reset/lifetime contracts and
physical measurement timestamps remain outside this accepted extension.
