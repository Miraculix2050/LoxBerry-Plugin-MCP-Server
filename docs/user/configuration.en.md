# Configuration

[Deutsch](configuration.de.md)

## Basic settings

Configure one local HTTPS origin and exactly one Miniserver target. Selecting a Miniserver stored in LoxBerry does not reuse its credentials. On first setup, the origin is suggested from the LoxBerry hostname and HTTPS port; verify it matches the browser's certificate address. The first save of a complete, valid setup enables the server.

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
