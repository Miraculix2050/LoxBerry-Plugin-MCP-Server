#!/usr/bin/perl

use strict;
use warnings;
use CGI;
use HTML::Template;
use IPC::Open3;
use JSON::PP qw(decode_json encode_json);
use Symbol qw(gensym);
use LoxBerry::System;
use LoxBerry::Web;
use LoxBerry::Log;

my $cgi = CGI->new;
my $q = $cgi->Vars;
my $version = LoxBerry::System::pluginversion();
my $log = LoxBerry::Log->new(name => 'admin-ui', package => $lbpplugindir, addtime => 1);
$log->LOGSTART('index.cgi called');

$ENV{LBPDATA} = $lbpdatadir;
$ENV{MCPSERVER_CONFIG} = "$lbpconfigdir/mcpserver.json";
$ENV{MCPSERVER_AUTH_STORE} = "$lbpdatadir/auth/sessions.json";
$ENV{MCPSERVER_LOXONE_TOKEN_STORE} = "$lbpdatadir/auth/loxone-tokens.json.enc";
$ENV{MCPSERVER_INSTALL_KEY} = "$lbpdatadir/auth/install.key";

sub admin_call {
    my ($action, $payload) = @_;
    my ($child_in, $child_out);
    my $child_err = gensym;
    my $pid = open3($child_in, $child_out, $child_err, "$lbpbindir/mcpserver-admin");
    print {$child_in} encode_json({action => $action, payload => ($payload // {})});
    close $child_in;
    local $/;
    my $stdout = <$child_out> // '';
    my $stderr = <$child_err> // '';
    waitpid($pid, 0);
    if ($? != 0 || $stdout eq '') {
        LOGERR("admin helper failed");
        return {ok => JSON::PP::false, error => {code => 'internal_error', message => 'Administrative action failed'}};
    }
    my $result = eval { decode_json($stdout) };
    if (!$result || ref($result) ne 'HASH') {
        LOGERR("admin helper returned invalid JSON");
        return {ok => JSON::PP::false, error => {code => 'internal_error', message => 'Administrative action failed'}};
    }
    return $result;
}

sub same_origin_post {
    return 0 if uc($ENV{REQUEST_METHOD} // '') ne 'POST';
    my $origin = $ENV{HTTP_ORIGIN} // '';
    my $host = $ENV{HTTP_HOST} // '';
    return 0 if $origin eq '' || $host eq '';
    return $origin =~ m{^https?://\Q$host\E$}i ? 1 : 0;
}

sub json_reply {
    my ($result, $status) = @_;
    print $cgi->header(-type => 'application/json', -charset => 'utf-8', -status => ($status // 200));
    print encode_json($result);
    exit;
}

my $action = $q->{action} // '';
if ($action ne '') {
    if (!same_origin_post()) {
        my $failure = {ok => JSON::PP::false, error => {code => 'forbidden', message => 'Same-origin POST required'}};
        json_reply($failure, 403) if $q->{ajax};
        print $cgi->redirect('index.cgi?notice=forbidden');
        exit;
    }

    my $result;
    if ($action eq 'save_config') {
        my $document = {
            schema_version => 1,
            server => {
                enabled => $q->{enabled} ? JSON::PP::true : JSON::PP::false,
                public_origin => $q->{public_origin} // '',
            },
            loxone => {
                endpoint => $q->{endpoint} // '',
                connection_timeout => 0 + ($q->{connection_timeout} // 10),
            },
            tools => {loxone_read_enabled => JSON::PP::true},
            limits => {
                requests_per_minute => 0 + ($q->{requests_per_minute} // 60),
                max_parallel_calls => 0 + ($q->{max_parallel_calls} // 4),
            },
        };
        $result = admin_call('save_config', $document);
    } elsif ($action eq 'test_connection') {
        $result = admin_call('test_connection', {endpoint => ($q->{endpoint} // '')});
    } elsif ($action eq 'revoke_session') {
        $result = admin_call('revoke_session', {id => ($q->{id} // '')});
    } elsif ($action eq 'revoke_all') {
        $result = admin_call('revoke_all', {});
    } elsif ($action eq 'status') {
        $result = admin_call('status', {});
    } elsif ($action eq 'diagnostic') {
        $result = admin_call('diagnostic', {});
    } else {
        $result = {ok => JSON::PP::false, error => {code => 'invalid_request', message => 'Unsupported action'}};
    }
    if ($action eq 'diagnostic' && $result->{ok}) {
        print $cgi->header(
            -type => 'application/json',
            -charset => 'utf-8',
            -attachment => 'mcpserver-diagnostic.json',
        );
        print encode_json($result->{data});
        exit;
    }
    json_reply($result, $result->{ok} ? 200 : 400) if $q->{ajax};
    my $notice = $result->{ok} ? 'success' : 'error';
    print $cgi->redirect("index.cgi?notice=$notice");
    exit;
}

my $template_text = LoxBerry::System::read_file("$lbptemplatedir/index.html");
my $template = HTML::Template->new_scalar_ref(
    \$template_text,
    global_vars => 1,
    loop_context_vars => 1,
    die_on_bad_params => 0,
);
my %L = LoxBerry::System::readlanguage($template, 'language.ini');

my $config_result = admin_call('get_config', {});
my $status_result = admin_call('status', {});
my $sessions_result = admin_call('list_sessions', {});
my $config = $config_result->{ok} ? $config_result->{data}{configuration} : {};
my $sessions = $sessions_result->{ok} ? $sessions_result->{data}{sessions} : [];
$config->{server} = {} if ref($config->{server}) ne 'HASH';
$config->{loxone} = {} if ref($config->{loxone}) ne 'HASH';
$config->{limits} = {} if ref($config->{limits}) ne 'HASH';

$template->param(
    VERSION => $version,
    ENABLED => $config->{server}{enabled} ? 1 : 0,
    PUBLIC_ORIGIN => $config->{server}{public_origin} // '',
    ENDPOINT => $config->{loxone}{endpoint} // '',
    CONNECTION_TIMEOUT => $config->{loxone}{connection_timeout} // 10,
    REQUESTS_PER_MINUTE => $config->{limits}{requests_per_minute} // 60,
    MAX_PARALLEL_CALLS => $config->{limits}{max_parallel_calls} // 4,
    SERVICE_ACTIVE => ($status_result->{ok} && $status_result->{data}{service_active}) ? 1 : 0,
    SESSIONS => $sessions,
    HAS_SESSIONS => scalar(@$sessions) ? 1 : 0,
    NOTICE => $q->{notice} // '',
    LOGLIST => LoxBerry::Web::loglist_html(),
);

our %navbar;
$navbar{10}{Name} = $L{'NAV.SETUP'};
$navbar{10}{URL} = '#setup';
$navbar{20}{Name} = $L{'NAV.STATUS'};
$navbar{20}{URL} = '#status';
$navbar{30}{Name} = $L{'NAV.SESSIONS'};
$navbar{30}{URL} = '#sessions';
$navbar{40}{Name} = $L{'NAV.DIAGNOSTICS'};
$navbar{40}{URL} = '#diagnostics';
$navbar{50}{Name} = $L{'NAV.HELP'};
$navbar{50}{URL} = '#help';

LoxBerry::Web::lbheader($L{'BASIC.TITLE'} . " V$version", '', '', 'nojqm');
print LoxBerry::Log::get_notifications_html($lbpplugindir);
print $template->output();
LoxBerry::Web::lbfooter();
exit;
