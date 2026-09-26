# Configuration

[Deutsch](configuration.de.md)

## Basic settings

In **Status & operation**, **Service operation and autostart** shows the saved operating permission. It is enabled after a new installation, while MCP and MQTT health are separately disabled. Applying the enabled permission starts the service immediately and at the next system boot. Disabling it stops the service immediately and prevents it from starting at the next system boot; this choice is preserved across upgrades. The **Start**, **Stop** and **Restart** status actions are available only while this permission is enabled and affect only the current runtime state, never the boot behavior.

## MCP configuration

Admin section headings show the last successfully loaded, saved MCP and MQTT settings, the current session count, and the number of pending approval actions. The session list refreshes every ten seconds while the page is visible, even when its section is closed. The HTTPS badge reflects certificate, origin, and hostname checks; loading or missing data has a neutral label. Editing a form does not change a badge until the save succeeds.

Under **Connection**, configure one local HTTPS origin and exactly one Miniserver target. Selecting a Miniserver stored in LoxBerry does not reuse its credentials. On first setup, the origin is suggested from the LoxBerry hostname and HTTPS port; verify it matches the browser's certificate address. **Test connection** uses the currently selected or manually entered target without saving the configuration. Only **Enable MCP endpoint access** releases MCP and OAuth access. Permissions and local event-history enablement remain visible; rate, runtime, structure, and cache settings are under **Advanced settings**. Their values are saved even while that section is closed.

### Authentication recovery

The advanced limits include an initial and maximum delay for one lazy Miniserver authentication recovery probe. Defaults are 15 minutes and 24 hours. After the Miniserver confirms that the source IP is blocked, the service makes no further login attempts until the delay has elapsed and a real tool or runtime request needs a connection. A repeated block doubles the delay up to the configured maximum. These limits are plugin policy, not a claimed Miniserver block duration; changing them does not itself start a login attempt.

## Local event history

The main Admin UI shows enablement, the configured active-source count, the current SQLite database plus WAL file size, and links to **Local event history** in configuration and under **Help and developer tools**. The separate view shows local measurements first and loads the control selector in the background. It checks visible controls afresh on every page open; saved control names stay hidden until then. Filter the bounded list by name or UUID and by room, category, and type; each filter group accepts at most 100 selected values. **Load controls** forces a new discovery. Then select an advertised state of that control; the source limit is 64 active pairs.

For short state lists, the dropdown is enough; longer lists also show a text filter. State inputs are disabled while loading. The Miniserver structure does not reliably identify value types: a visible state can produce values that cannot be recorded. The recorder supports scalar values only and reports unsupported values in its runtime status. **Start recording** shows progress and then updates the source overview. An enabled source alone does not prove that any event was captured.

While the tab is visible, the page regularly checks a local change marker. If another browser adds or stops a source, deletes its retained data, or clears the entire history, the page reloads the authorized source overview. After a failed visibility check, it retries with bounded spacing. If another tab changes the control generation, the page reloads the selector and retains a control/state pair that remains visible. With verified visibility and an unchanged marker, no further Miniserver structure request is made. **Refresh overview** is disabled while loading and then shows a success message for five seconds; errors remain visible.

The overview separates configured retention and maximum size from the measured file size and retained evidence. Event timestamps show the oldest and newest stored change, not a complete history. Recent capture intervals are shown separately; a gap remains a gap even after a source is re-added. Counts on this page include only currently visible sources, and hidden-source historical details are withheld. For configured sources whose visibility cannot be verified, the view shows only their saved identifiers and offers confirmed removal. A database's storage bytes cannot be attributed precisely to an individual source. When the store, Miniserver structure, or running recorder cannot be checked, the affected information is marked unavailable or unknown.

**Stop recording** retains stored evidence under the global limits. **Delete retained data** is a separate confirmed action available only for an inactive visible source. **Delete all history** has its own confirmation and clears events and coverage while keeping configured source selections. After an uncertain deletion result, inspect the refreshed overview before attempting another operation.

## Emergency-stop signal (Virtual Status)

The optional **Emergency-stop signal (Virtual Status)** is in the **MCP
configuration** section. Select only a visible Virtual Status configured as
digital on the selected Miniserver. The default, **No virtual status selected**,
allows all MCP tool calls.

The page shows the saved selection immediately. Use **Load available signals**
when you want to query the configured Miniserver for the current choices; a
temporary discovery failure never clears the saved value.

The Admin UI also shows the signal used by the running service, including its
name and UUID, and its state. The states match MQTT publication:
`not_configured`, `clear`, `active`, and `unknown`. A selection that has not
yet been saved remains separate and is identified as a change not yet adopted
by the service. If the service is unavailable, the page does not invent a state.

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
