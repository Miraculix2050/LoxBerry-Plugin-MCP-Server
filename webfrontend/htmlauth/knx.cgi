#!/usr/bin/perl

use strict;
use warnings;
use Time::HiRes qw(clock_gettime CLOCK_MONOTONIC);
our $knx_compile_started;
BEGIN { $knx_compile_started = Time::HiRes::clock_gettime(Time::HiRes::CLOCK_MONOTONIC()); }
use CGI;
use Digest::SHA qw(sha256_hex);
use IPC::Open3;
use IO::Handle;
use IO::Select;
use JSON::PP qw(encode_json decode_json);
use Symbol qw(gensym);
use LoxBerry::System;

# JSON::XS is an optional platform accelerator; JSON::PP remains the fallback.
my $knx_fast_json;
my $knx_decoder_initialized = 0;
sub decode_helper_json {
    my ($raw) = @_;
    if (!$knx_decoder_initialized) {
        $knx_fast_json = eval { require JSON::XS; JSON::XS->new->utf8->max_depth(512) };
        $knx_decoder_initialized = 1;
    }
    if ($knx_fast_json && $raw !~ /[^\x00-\x7f]/) {
        my $result = eval { $knx_fast_json->decode($raw) };
        return $result unless $@;
    }
    return decode_json($raw);
}
my $knx_helper_response_bytes = 0;
my %knx_timing = (cgi_compile_ms => (clock_gettime(CLOCK_MONOTONIC) - $knx_compile_started) * 1000);
my $knx_setup_started = clock_gettime(CLOCK_MONOTONIC);
require "$lbpbindir/lib/MCPServer/RequestSecurity.pm";

$CGI::POST_MAX = 64 * 1024 * 1024;
$CGI::DISABLE_UPLOADS = 1;
my $cgi = CGI->new;
my $q = $cgi->Vars;
if (($q->{lang} // '') =~ /\A(?:de|en)\z/) {
    $LoxBerry::System::lang = $q->{lang};
}
$ENV{MCPSERVER_KNX_ADMIN} = "1";
$ENV{LBPDATA} = $lbpdatadir;
$ENV{MCPSERVER_CONFIG} = "$lbpconfigdir/mcpserver.json";
$ENV{MCPSERVER_AUTH_STORE} = "$lbpdatadir/auth/sessions.json";
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
$knx_timing{cgi_setup_ms} = (clock_gettime(CLOCK_MONOTONIC) - $knx_setup_started) * 1000;
sub read_helper_pipes {
    my ($output, $error) = @_;
    my $selector = IO::Select->new($output, $error);
    my $output_fd = fileno($output);
    my ($raw, $diagnostics) = ('', '');
    while ($selector->count) {
        for my $pipe ($selector->can_read) {
            my $buffer = '';
            my $count = sysread($pipe, $buffer, 65536);
            die "KNX helper read failed\n" unless defined($count);
            if (!$count) { $selector->remove($pipe); close $pipe; next; }
            if (fileno($pipe) == $output_fd) {
                $raw .= $buffer;
                die "KNX helper response limit\n" if length($raw) > 24 * 1024 * 1024;
            } else {
                $diagnostics .= $buffer;
                die "KNX helper diagnostics limit\n" if length($diagnostics) > 8192;
            }
        }
    }
    return ($raw, $diagnostics);
}
sub timing_header {
    return () unless ($q->{action} // '') =~ /\A(?:knx_page|knx_read_page|knx_project_page)\z/;
    return (-Server_Timing => join(', ', map {
        sprintf('%s;dur=%.3f', $_, $knx_timing{$_})
    } sort grep { /\A[a-z_]{1,64}\z/ && defined($knx_timing{$_})
        && $knx_timing{$_} =~ /\A\d+(?:\.\d+)?\z/ && $knx_timing{$_} <= 60000 } keys %knx_timing));
}
sub headers {
    return (
        -Cache_Control => 'no-store',
        -Pragma => 'no-cache',
        -Content_Security_Policy => "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'",
        -Referrer_Policy => 'no-referrer',
        -X_Content_Type_Options => 'nosniff',
        -X_Frame_Options => 'DENY',
        timing_header(),
        ($knx_helper_response_bytes ? (-X_KNX_Helper_Response_Bytes => $knx_helper_response_bytes) : ()) ,
        (defined($session_cookie) ? (-cookie => $session_cookie) : ()),
    );
}

if (($q->{action} // '') ne '') {
    my $result;
    if (!MCPServer::RequestSecurity::same_origin_post()) {
        $result = {ok => JSON::PP::false, error => {code => 'forbidden'}};
    } elsif ($cgi->cgi_error || ($q->{action} // '') !~ /\A(?:knx_page|knx_groups_page|knx_put|knx_delete|knx_export|knx_restore|knx_taxonomy|knx_preview|knx_import_load|knx_import_preview|knx_import_apply|knx_import_discard|knx_compare_load|knx_compare_page|knx_compare_discard|knx_xml_preview|knx_xml_download|knx_xml_discard|knx_read_page|knx_read_enable|knx_read_grant|knx_read_revoke|knx_drafts_page|knx_drafts_enable|knx_drafts_grant|knx_drafts_revoke|knx_write_page|knx_write_enable|knx_write_grant|knx_write_revoke|knx_correction_page|knx_correction_inspect|knx_correction_review|knx_correction_edit|knx_correction_manage|knx_correction_apply|knx_correction_xml_preview|knx_correction_xml_download|knx_project_page)\z/) {
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
                my $spawn_started = clock_gettime(CLOCK_MONOTONIC);
                $pid = open3($input, $output, $error, "$lbpbindir/mcpserver-admin");
                $knx_timing{cgi_spawn_ms} = (clock_gettime(CLOCK_MONOTONIC) - $spawn_started) * 1000;
                my $input_started = clock_gettime(CLOCK_MONOTONIC);
                print {$input} encode_json({action => $q->{action}, payload => $payload});
                close $input;
                $knx_timing{cgi_input_ms} = (clock_gettime(CLOCK_MONOTONIC) - $input_started) * 1000;
                local $/;
                my $read_started = clock_gettime(CLOCK_MONOTONIC);
                my ($raw, $diagnostics) = read_helper_pipes($output, $error);
                $knx_helper_response_bytes = length($raw);
                $knx_timing{cgi_helper_read_ms} = (clock_gettime(CLOCK_MONOTONIC) - $read_started) * 1000;
                my $wait_started = clock_gettime(CLOCK_MONOTONIC);
                waitpid($pid, 0);
                $knx_timing{cgi_wait_ms} = (clock_gettime(CLOCK_MONOTONIC) - $wait_started) * 1000;
                if ($diagnostics =~ /(?:\A|\n)mcpserver_admin_timing=(\{[^\r\n]{1,4096}\})/) {
                    my $measured = eval { decode_json($1) };
                    my %allowed = map { $_ => 1 } qw(process_bootstrap_ms module_import_ms module_definitions_ms helper_total_ms
                        helper_input_ms helper_dispatch_ms helper_serialize_ms
                        forward_config_ms forward_proof_ms forward_send_ms forward_headers_ms
                        forward_read_ms forward_decode_ms
                        bridge_handler_ms bridge_key_ms bridge_access_ms bridge_execute_ms
                        bridge_slot_ms bridge_prepare_ms bridge_runner_ms bridge_finish_ms);
                    if (ref($measured) eq 'HASH') {
                        for my $key (keys %allowed) {
                            $knx_timing{$key} = $measured->{$key} if defined($measured->{$key})
                                && $measured->{$key} =~ /\A\d+(?:\.\d+)?\z/;
                        }
                    }
                }
                $pid = undef;
                alarm 0;
                die "KNX helper response limit\n" if length($raw) > 24 * 1024 * 1024;
                my $decode_started = clock_gettime(CLOCK_MONOTONIC);
                $result = decode_helper_json($raw);
                $knx_timing{cgi_decode_ms} = (clock_gettime(CLOCK_MONOTONIC) - $decode_started) * 1000;
                1;
            };
            alarm 0;
            if (defined($pid)) {
                kill 'KILL', $pid;
                waitpid($pid, 0);
            }
            $result = {ok => JSON::PP::false, error => {code => 'internal_error'}}
                if ref($result) ne 'HASH';
            my $quiet_read = $result->{ok}
                && $q->{action} =~ /\A(?:knx_page|knx_read_page|knx_drafts_page|knx_project_page)\z/;
            if (!$quiet_read) {
                require LoxBerry::Log;
                my $log = LoxBerry::Log->new(name => 'admin-ui', package => $lbpplugindir, addtime => 1);
                my $outcome = $result->{ok} ? 'completed' : 'rejected';
                my $mode = '';
                if ($q->{action} eq 'knx_correction_apply') {
                    $mode = ($payload->{action} // '') =~ /\A(?:apply|reconcile)\z/
                        ? ' mode=' . $payload->{action} : ' mode=invalid';
                    $outcome = 'uncertain' if ($result->{error}{code} // '') =~ /\A(?:persistence_uncertain|write_outcome_uncertain|internal_error)\z/;
                    $outcome = 'uncertain' if ($payload->{action} // '') eq 'apply'
                        && ($result->{error}{code} // '') eq 'knx_storage_failed';
                    $outcome = $result->{data}{outcome} if $result->{ok}
                        && ($result->{data}{outcome} // '') =~ /\A(?:applied|not_observed)\z/;
                }
                $log->INF('action=' . $q->{action} . $mode . ' outcome=' . $outcome) if $log;
            }
        }
    }
    my $status = (($result->{error}{code} // '') eq 'forbidden') ? '403 Forbidden' : '200 OK';
    my $encode_started = clock_gettime(CLOCK_MONOTONIC);
    my $response_json = encode_json($result);
    $knx_timing{cgi_encode_ms} = (clock_gettime(CLOCK_MONOTONIC) - $encode_started) * 1000;
    $knx_timing{cgi_total_ms} = (clock_gettime(CLOCK_MONOTONIC) - $knx_compile_started) * 1000;
    print $cgi->header(-status => $status, -type => 'application/json', -charset => 'utf-8', headers());
    print $response_json;
    exit;
}
require HTML::Template;
require LoxBerry::Web;
if (($q->{lang} // '') =~ /\A(?:de|en)\z/) {
    $LoxBerry::Web::lang = $q->{lang};
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
