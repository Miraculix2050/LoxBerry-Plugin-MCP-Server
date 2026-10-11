#!/usr/bin/perl
use strict;
use warnings;
use CGI;
use LoxBerry::System;

my $cgi = CGI->new;
print $cgi->header(
    -type => 'text/html', -charset => 'utf-8',
    -Cache_Control => 'no-store',
    -Content_Security_Policy => "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
    -X_Frame_Options => 'DENY', -Referrer_Policy => 'no-referrer',
    -X_Content_Type_Options => 'nosniff',
);
print LoxBerry::System::read_file("$lbptemplatedir/message-approval.html");
