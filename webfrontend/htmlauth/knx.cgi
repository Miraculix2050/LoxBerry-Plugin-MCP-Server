#!/usr/bin/perl

use strict;
use warnings;
use CGI;
use Digest::SHA qw(sha256_hex);
use HTML::Template;
use HTTP::Tiny;
use IPC::Open3;
use IO::Handle;
use JSON::PP qw(encode_json decode_json);
use Symbol qw(gensym);
use Time::HiRes qw(clock_gettime CLOCK_MONOTONIC);
use LoxBerry::System;
use LoxBerry::Web;
use LoxBerry::Log;

require "$lbpbindir/lib/MCPServer/RequestSecurity.pm";

$CGI::POST_MAX = 64 * 1024 * 1024;
$CGI::DISABLE_UPLOADS = 1;
my $cgi = CGI->new;
my $q = $cgi->Vars;
if (($q->{lang} // '') =~ /\A(?:de|en)\z/) {
    $LoxBerry::System::lang = $q->{lang};
    $LoxBerry::Web::lang = $q->{lang};
}
$ENV{MCPSERVER_KNX_ADMIN} = "1";
$ENV{LBPDATA} = $lbpdatadir;
$ENV{MCPSERVER_CONFIG} = "$lbpconfigdir/mcpserver.json";
my $session_token = $cgi->cookie('mcp_knx_admin') // '';
my $session_cookie;
if ($session_token !~ /\A[0-9a-f]{64}\z/ && ($ENV{REQUEST_METHOD} // '') eq 'GET') {
    open my $random, '<:raw', '/dev/urandom' or die "KNX session unavailable";
    my $bytes = '';
    read($random, $bytes, 32) == 32 or die "KNX session unavailable";
    close $random;
    $session_token = unpack('H*', $bytes);
    $session_cookie = $cgi->cookie(
        -name => 'mcp_knx_admin', -value => $session_token,
        -path => ($ENV{SCRIPT_NAME} // '/admin/plugins/mcpserver/knx.cgi'),
        -secure => (MCPServer::RequestSecurity::request_scheme(\%ENV) // '') eq 'https',
        -httponly => 1, -samesite => 'Strict',
    );
}
$ENV{MCPSERVER_KNX_ADMIN_SESSION} = $session_token =~ /\A[0-9a-f]{64}\z/
    ? sha256_hex($session_token . ':' . ($ENV{REMOTE_USER} // '')) : '';
sub headers {
    return (
        -Cache_Control => 'no-store',
        -Pragma => 'no-cache',
        -Content_Security_Policy => "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'",
        -Referrer_Policy => 'no-referrer',
        -X_Content_Type_Options => 'nosniff',
        -X_Frame_Options => 'DENY',
        (defined($session_cookie) ? (-cookie => $session_cookie) : ()),
    );
}

if (($q->{action} // '') ne '') {
    my $result;
    if (!MCPServer::RequestSecurity::same_origin_post()) {
        $result = {ok => JSON::PP::false, error => {code => 'forbidden'}};
    } elsif ($cgi->cgi_error || ($q->{action} // '') !~ /\A(?:knx_page|knx_put|knx_delete|knx_export|knx_restore|knx_taxonomy|knx_preview|knx_import_load|knx_import_preview|knx_import_apply|knx_import_discard|knx_compare_load|knx_compare_page|knx_compare_discard|knx_xml_preview|knx_xml_download|knx_xml_discard)\z/) {
        $result = {ok => JSON::PP::false, error => {code => 'invalid_request'}};
    } else {
        my $payload = eval { decode_json($q->{payload} // '{}') };
        if (ref($payload) ne 'HASH') {
            $result = {ok => JSON::PP::false, error => {code => 'invalid_request'}};
        } else {
            my ($input, $output);
            my $error = gensym;
            my $pid;
            my $completed = eval {
                local $SIG{ALRM} = sub { die "KNX helper timeout\n"; };
                alarm 60;
                $pid = open3($input, $output, $error, "$lbpbindir/mcpserver-admin");
                print {$input} encode_json({action => $q->{action}, payload => $payload});
                close $input;
                local $/;
                my $raw = <$output> // '';
                my $diagnostics = <$error> // '';
                waitpid($pid, 0);
                $pid = undef;
                alarm 0;
                die "KNX helper response limit\n" if length($raw) > 24 * 1024 * 1024;
                $result = decode_json($raw);
                1;
            };
            alarm 0;
            if (defined($pid)) {
                kill 'KILL', $pid;
                waitpid($pid, 0);
            }
            $result = {ok => JSON::PP::false, error => {code => 'internal_error'}}
                if ref($result) ne 'HASH';
            if ($q->{action} ne 'knx_page') {
                my $log = LoxBerry::Log->new(name => 'admin-ui', package => $lbpplugindir, addtime => 1);
                $log->INF('action=' . $q->{action} . ' outcome=' . ($result->{ok} ? 'completed' : 'rejected')) if $log;
            }
        }
    }
    my $status = (($result->{error}{code} // '') eq 'forbidden') ? '403 Forbidden' : '200 OK';
    print $cgi->header(-status => $status, -type => 'application/json', -charset => 'utf-8', headers());
    print encode_json($result);
    exit;
}
my $version = LoxBerry::System::pluginversion();
my $template_text = LoxBerry::System::read_file("$lbptemplatedir/knx.html");
my $template = HTML::Template->new_scalar_ref(\$template_text, global_vars => 1, die_on_bad_params => 0);
my %L = LoxBerry::System::readlanguage($template, 'language.ini');
$template->param(VERSION => $version);
print "Set-Cookie: $session_cookie\n" if defined($session_cookie);
print "Cache-Control: no-store\nPragma: no-cache\n";
print "Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'\n";
print "Referrer-Policy: no-referrer\nX-Content-Type-Options: nosniff\nX-Frame-Options: DENY\n";
LoxBerry::Web::lbheader($L{'KNX.TITLE'} . " V$version", 'nopanels', '', 'nojqm');
print $template->output();
LoxBerry::Web::lbfooter();
