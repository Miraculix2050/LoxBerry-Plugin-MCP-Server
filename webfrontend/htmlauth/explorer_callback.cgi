#!/usr/bin/perl

use strict;
use warnings;
use CGI;

my $cgi = CGI->new;
print $cgi->header(
    -type => 'text/html',
    -charset => 'utf-8',
    -Cache_Control => 'no-store',
    -Pragma => 'no-cache',
    -Content_Security_Policy => "default-src 'none'; script-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'",
    -Referrer_Policy => 'no-referrer',
    -X_Content_Type_Options => 'nosniff',
    -X_Frame_Options => 'DENY',
);
print <<'HTML';
<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MCP OAuth callback</title></head>
<body><p>Completing authorization …</p><script>
(() => {
  const parameters = new URLSearchParams(window.location.search);
  const payload = {
    type: 'mcp-explorer-oauth',
    code: parameters.get('code'),
    state: parameters.get('state'),
    error: parameters.get('error'),
    errorDescription: parameters.get('error_description'),
  };
  window.history.replaceState(null, '', window.location.pathname);
  // The direct opener message is the normal completion path. BroadcastChannel is
  // a same-origin fallback for browsers that detach a popup's opener during the
  // authentication navigation.
  try {
    const channel = new BroadcastChannel('mcp-explorer-oauth');
    channel.postMessage(payload);
    window.setTimeout(() => channel.close(), 100);
  } catch (_error) { /* BroadcastChannel is optional. */ }
  if (window.opener && window.opener !== window) {
    window.opener.postMessage(payload, window.location.origin);
    window.setTimeout(() => window.close(), 100);
  } else {
    document.body.textContent = 'The authorization window can be closed. / Das Autorisierungsfenster kann geschlossen werden.';
  }
})();
</script></body></html>
HTML
exit;
