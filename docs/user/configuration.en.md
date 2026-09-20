# Configuration

[Deutsch](configuration.de.md)

## Basic settings

The **Enable service** switch is the saved operating permission. It is enabled after a new installation, while MCP and MQTT health are separately disabled. Enabling it starts the service immediately and at the next system boot. Disabling it stops the service immediately and prevents it from starting at the next system boot; this choice is preserved across upgrades. The **Start**, **Stop** and **Restart** status actions are available only while this permission is enabled and affect only the current runtime state, never the boot behavior.

## MCP configuration

Configure one local HTTPS origin and exactly one Miniserver target. Selecting a Miniserver stored in LoxBerry does not reuse its credentials. On first setup, the origin is suggested from the LoxBerry hostname and HTTPS port; verify it matches the browser's certificate address. Only **Enable MCP access** releases MCP and OAuth access.

## Emergency-stop signal (Virtual Status)

The optional **Emergency-stop signal (Virtual Status)** is in the **MCP
configuration** section. Select only a visible Virtual Status configured as
digital on the selected Miniserver. The default, **No virtual status selected**,
allows all MCP tool calls.

When a signal is selected, value `1` permits MCP tool calls and value `0` blocks
them. An as-yet unknown value during service startup or loss of the Miniserver
connection also blocks calls fail closed. Set the Virtual Status back to `1`, or
remove the selection and save the configuration, to permit tool calls again. The
block applies only to tool calls; OAuth, tool discovery and the HTTP health
endpoint remain reachable.

## MQTT configuration (health)

MQTT health is disabled by default. By default, the plugin reads host, port, and credentials at runtime from the LoxBerry MQTT gateway. For a custom broker, disable **Use LoxBerry MQTT gateway** and enter its host, port, username, and password. Custom-broker connections always use TLS with normal certificate and hostname validation. The password is stored separately with encryption, is never displayed again, and is never included in diagnostics or logs. Use **Clear saved MQTT password** to remove it deliberately. The default root topic is `mcpserver` and the default heartbeat interval is 60 seconds. Retained topics are `mcpserver/health/heartbeat`, `mcpserver/health/system_state` and `mcpserver/health/substate`. A controlled stop publishes `inactive` and `dead`; an unexpected process or connection loss publishes the retained fallback `unknown`. The timestamp uses Loxone epoch seconds.

When MQTT health is disabled, its root topic changes, or its configured broker endpoint or transport changes, the plugin removes all four retained plugin topics at the previous destination before starting the replacement service. This is best effort: if the previous broker is unavailable, the new configuration remains active and the Admin UI reports that old retained values may remain. Changing only broker credentials at the same endpoint and root does not remove topics because the replacement service remains authoritative for that same topic tree.

When MQTT health is enabled, the plugin additionally publishes the retained
emergency-stop state with QoS 1 under `<root>/emergency_stop/status`. This topic
has its own Last Will and is independent of the `health/*` topics: it publishes
`not_configured` when no signal is selected, `clear` when the configured signal
is `1`, `active` when it is `0`, and `unknown` when a configured signal is
unavailable or the MQTT connection is lost. `active` and configured `unknown`
block MCP tool calls.

## Certificate

Use an MCP client address covered by the LoxBerry web-server certificate. Certificate diagnostics show whether the configured origin matches. Reissuing a local certificate requires SecurePIN and confirmation; externally issued certificates are not changed.

To let an endpoint accept the local certificate, install its CA certificate, `cacert.cer`, on that endpoint. Download it in LoxBerry from `https://<LoxBerry-hostname>/admin/system/services.php`.

### Windows

1. Double-click the downloaded `cacert.cer` file.
2. Select **Install Certificate…**.
3. Select **Place all certificates in the following store**, then choose **Trusted Root Certification Authorities**.
4. Complete the installation, then open the HTTPS origin again.

### Android

1. Download `cacert.cer` to the device through the LoxBerry system services page.
2. Open **Settings** and search for **Install a certificate**. Depending on the device, it may be under **Security & privacy** → **More security settings** → **Encryption & credentials**.
3. Choose **CA certificate**, then select the downloaded `cacert.cer` file. Confirm the security prompt; a screen lock may be required.
4. Open the HTTPS origin again.

Install a CA certificate only from your own trusted LoxBerry: it allows the device to accept certificates issued by that CA. Menu names can differ between Android versions and device manufacturers.

## Feature switches

Read access, history/statistics and LoxBerry diagnostics are globally available. The client must still request the matching scope and the user must approve it; LoxBerry diagnostics also require local approval.

Next: [Permissions](permissions.en.md).
