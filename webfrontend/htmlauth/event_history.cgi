#!/usr/bin/perl

use strict;
use warnings;
use CGI;
use HTML::Template;
use IPC::Open3;
use JSON::PP qw(encode_json decode_json);
use Symbol qw(gensym);
use Time::HiRes qw(clock_gettime CLOCK_MONOTONIC);
use LoxBerry::System;
use LoxBerry::Web;
use LoxBerry::Log;

my $cgi = CGI->new;
my $q = $cgi->Vars;
my $request_id = sprintf('%x-%x', $$, int(clock_gettime(CLOCK_MONOTONIC) * 1_000_000));
if (($q->{lang} // '') =~ /\A(?:de|en)\z/) {
    $LoxBerry::System::lang = $q->{lang};
    $LoxBerry::Web::lang = $q->{lang};
}
my $version = LoxBerry::System::pluginversion();
$ENV{LBPDATA} = $lbpdatadir;
$ENV{MCPSERVER_CONFIG} = "$lbpconfigdir/mcpserver.json";
$ENV{MCPSERVER_AUTH_STORE} = "$lbpdatadir/auth/sessions.json";
$ENV{MCPSERVER_EVENT_HISTORY_STORE} = "$lbpdatadir/event-history/state-events.sqlite3";

sub headers {
    return (
        -Cache_Control => 'no-store',
        -Pragma => 'no-cache',
        -Content_Security_Policy => "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'",
        -Referrer_Policy => 'no-referrer',
        -X_Content_Type_Options => 'nosniff',
        -X_Frame_Options => 'DENY',
    );
}

sub reply {
    my ($result, $status) = @_;
    print $cgi->header(-type => 'application/json', -charset => 'utf-8',
        -status => $status, headers());
    print encode_json($result);
    exit;
}

sub admin_call {
    my ($action, $payload) = @_;
    my ($input, $output);
    my $error = gensym;
    my $pid = open3($input, $output, $error, "$lbpbindir/mcpserver-admin");
    print {$input} encode_json({action => $action, payload => $payload});
    close $input;
    local $/;
    my $raw = <$output> // '';
    my $ignored = <$error>;
    waitpid($pid, 0);
    my $result = eval { decode_json($raw) };
    return ref($result) eq 'HASH' ? $result
        : {ok => JSON::PP::false, error => {code => 'internal_error', message => 'Admin helper unavailable'}};
}

my %actions = map { $_ => 1 } qw(
    event_history_overview event_history_local_overview event_history_quick_summary event_history_source_revision event_history_runtime_status event_history_discover
    event_history_discover_states
    event_history_prepare_selector event_history_selector_catalog event_history_selector_facets
    event_history_selector_query event_history_selector_states
    event_history_save_policy event_history_add_source event_history_remove_source
    event_history_purge_source clear_event_history
);
if (($q->{action} // '') ne '') {
    my $origin = $ENV{HTTP_ORIGIN} // '';
    my $host = $ENV{HTTP_HOST} // '';
    reply({ok => JSON::PP::false,
        error => {code => 'forbidden', message => 'Same-origin POST required'}}, 403)
        if uc($ENV{REQUEST_METHOD} // '') ne 'POST'
        || $origin eq '' || $host eq ''
        || $origin !~ m{^https?://\Q$host\E$}i;
    my $action = $q->{action};
    reply({ok => JSON::PP::false,
        error => {code => 'invalid_request', message => 'Unsupported action'}}, 400)
        if !$actions{$action};
    my $payload = {};
    if ($action eq 'event_history_discover') {
        $payload = {query => ($q->{query} // '')};
    } elsif ($action eq 'event_history_discover_states') {
        $payload = {control_uuid => ($q->{control_uuid} // ''),
            query => ($q->{query} // '')};
    } elsif ($action =~ /\Aevent_history_selector_(?:catalog|facets|query|states)\z/) {
        my $decode_list = sub {
            my ($name) = @_;
            my $raw = $q->{$name} // '[]';
            return undef if length($raw) > 65536;
            my $decoded = eval { decode_json($raw) };
            return ref($decoded) eq 'ARRAY' ? $decoded : undef;
        };
        $payload = {
            generation => ($q->{generation} // ''),
            query => ($q->{query} // ''),
            offset => ($q->{offset} // '') =~ /\A[0-9]+\z/ ? 0 + $q->{offset} : 0,
            control_uuid => ($q->{control_uuid} // ''),
            room => $decode_list->('room'),
            category => $decode_list->('category'),
            type => $decode_list->('type'),
        };
    } elsif ($action eq 'event_history_save_policy') {
        $payload = {
            retention_days => ($q->{retention_days} // '') =~ /\A[0-9]+\z/
                ? 0 + $q->{retention_days} : '',
            maximum_mib => ($q->{maximum_mib} // '') =~ /\A[0-9]+\z/
                ? 0 + $q->{maximum_mib} : '',
        };
    } elsif ($action =~ /\Aevent_history_(?:add|remove|purge)_source\z/) {
        $payload = {control_uuid => ($q->{control_uuid} // ''),
            state_uuid => ($q->{state_uuid} // ''),
            confirm => ($q->{confirm} // '') eq '1' ? JSON::PP::true : JSON::PP::false};
    } elsif ($action eq 'clear_event_history') {
        $payload = {confirm => ($q->{confirm} // '') eq '1'
            ? JSON::PP::true : JSON::PP::false};
    }
    my $started = clock_gettime(CLOCK_MONOTONIC);
    my $result = admin_call($action, $payload);
    if ($action =~ /\A(?:event_history_(?:save_policy|add_source|remove_source|purge_source)|clear_event_history)\z/) {
        my $log = LoxBerry::Log->new(name => 'admin-ui', package => $lbpplugindir,
            addtime => 1);
        $log->INF(sprintf(
            'component=event_history_admin request_id=%s action=%s outcome=%s duration_ms=%.1f',
            $request_id, $action, ($result->{ok} ? 'completed' : 'rejected'),
            (clock_gettime(CLOCK_MONOTONIC) - $started) * 1000,
        )) if $log;
    }
    reply($result, $result->{ok} ? 200 : 400);
}

my $template_text = LoxBerry::System::read_file("$lbptemplatedir/event-history.html");
my $template = HTML::Template->new_scalar_ref(\$template_text,
    global_vars => 1, die_on_bad_params => 0);
my %L = LoxBerry::System::readlanguage($template, 'language.ini');
$template->param(VERSION => $version);
our %navbar;
$navbar{10}{Name} = $L{'EVENT_HISTORY.BACK'};
$navbar{10}{URL} = 'index.cgi';
print "Cache-Control: no-store\nPragma: no-cache\n";
print "Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'\n";
print "Referrer-Policy: no-referrer\nX-Content-Type-Options: nosniff\nX-Frame-Options: DENY\n";
LoxBerry::Web::lbheader($L{'EVENT_HISTORY.TITLE'} . " V$version", 'nopanels', '', 'nojqm');
print $template->output();
LoxBerry::Web::lbfooter();
