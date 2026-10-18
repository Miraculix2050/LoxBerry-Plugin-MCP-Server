Load core rules first.

For static Modbus review, call `loxone_analyze_project` with `scope="modbus"`
(analysis version 1). Omitted selection runs `inventory`,
`configured_register_mappings`, `direct_consumers`, `configured_polling` and
`evidence_gaps`; explicit selections must be unique and belong to that scope.
Separate facts, review candidates and evidence gaps. Inspect per-check status,
coverage, limitations, omissions and every cursor before describing completeness.
Mappings compare only exact raw commands `3`/`4` and explicit lexical addresses
under uniquely observed transport/device ancestry in one model source. Shared
sensor/actor registers can be intentional read/write combinations. Raw polling
units remain unknown; configuration proves neither bus load nor current values.
Direct signal edges and distinct consumers have separate counts; references and
unresolved connectors do not establish direct signal use. Missing direct consumers
never prove non-use. Register width, overlaps, device addressing, scaling and byte
order require independent device documentation and are not evaluated here.
Search/describe metadata keeps `semantics="unresolved"` and bounded ancestors;
analysis reports its own prerequisites and completeness without strengthening
that metadata into physical topology or installation coverage.
Search/describe also expose exact `ModbusAActor` raw configuration, including
`RepeatRate`, `Channel` and `ModbusCoilQuantity`. `configured_write` is a configured
direction, not an allowed operation. These fields have unresolved semantics and
do not establish unit identity, timing or register width. Actors remain unsupported
by the sensor-only V1 analyzer. No live actor writes or hardware support are implied.
