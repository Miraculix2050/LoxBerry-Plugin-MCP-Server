# Capabilities and limits

[Deutsch](capabilities.de.md)

## Supported scope

The server reads visible rooms, categories, controls and states. Optional bounded history, statistics, masked LoxBerry diagnostics and documented type-specific actions for visible Gen. 1 controls are available.

`loxone_get_structure_overview` returns a bounded initial map of the rooms,
categories and control types visible to the signed-in Loxone user. It contains
no current states, history, hidden-object counts or Config-project data; use the
targeted discovery tools for details. Each breakdown contains at most 50 items,
and the complete result envelope is limited to 64 KiB with explicit completeness
metadata.

For initial orientation, this replaces separate calls to `loxone_list_rooms`,
`loxone_list_categories`, and an unfiltered `loxone_find_controls` request just
to learn their aggregate distribution. For example, a client can make one
overview call to see that its authorized visible structure has 18 controls in
four rooms and three categories, then use `loxone_find_controls` only for the
chosen room, category, or type. It does not replace those targeted calls when a
client needs individual controls, descriptions, or current states.

## Limits

- Exactly one Miniserver target is supported.
- External or cloud-hosted MCP access is outside supported operation.
- Gen. 2/Compact remains experimental until independent compatibility evidence exists.
- Unconfirmed control actions are not promised as hardware verified.
- No arbitrary commands, Loxone Config management or general LoxBerry system administration.

## Hardware-confirmed control

Only these Gen. 1 actions were confirmed on explicitly authorized harmless test
fixtures: `Switch.on`, `Switch.off`, `Dimmer.set_level`, `Dimmer.off`,
`TimedSwitch.on`, `TimedSwitch.off`, `LightControllerV2.set_mood`,
`Jalousie.open`, `Jalousie.set_position`, `Jalousie.enable_auto` and
`ColorPickerV2.set_color_hsv`. That evidence does not transfer to other
controls, actions or installations.

The current mapping of platforms, clients and evidence status is in the [support matrix](../development/support-matrix.md).
