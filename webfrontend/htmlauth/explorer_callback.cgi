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
  if (window.opener && window.opener !== window) {
    window.opener.postMessage(payload, window.location.origin);
    window.close();
  } else {
    document.body.textContent = 'The authorization window can be closed. / Das Autorisierungsfenster kann geschlossen werden.';
  }
})();
</script></body></html>
HTML
exit;
