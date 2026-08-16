# Configuration

[Deutsch](configuration.de.md)

## Basic settings

The **Enable service** switch controls only the systemd runtime. After a new installation the service is active, while MCP and MQTT health are separately disabled. Disabling it stops the service and prevents it from starting at the next system boot.

## MCP configuration

Configure one local HTTPS origin and exactly one Miniserver target. Selecting a Miniserver stored in LoxBerry does not reuse its credentials. On first setup, the origin is suggested from the LoxBerry hostname and HTTPS port; verify it matches the browser's certificate address. Only **Enable MCP access** releases MCP and OAuth access.

## MQTT configuration (health)

MQTT health is disabled by default. By default, the plugin reads host, port, and credentials at runtime from the LoxBerry MQTT gateway. For a custom broker, disable **Use LoxBerry MQTT gateway** and enter its host, port, username, and password. The password is stored separately with encryption, is never displayed again, and is never included in diagnostics or logs. The default root topic is `mcpserver` and the default heartbeat interval is 60 seconds. Retained topics are `mcpserver/health/heartbeat`, `mcpserver/health/system_state` and `mcpserver/health/substate`. The timestamp uses Loxone epoch seconds.

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
