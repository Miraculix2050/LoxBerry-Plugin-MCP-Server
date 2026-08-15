# Capabilities and limits

[Deutsch](capabilities.de.md)

## Supported scope

The server reads visible rooms, categories, controls and states. Optional bounded history, statistics, masked LoxBerry diagnostics and documented type-specific actions for visible Gen. 1 controls are available.

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
