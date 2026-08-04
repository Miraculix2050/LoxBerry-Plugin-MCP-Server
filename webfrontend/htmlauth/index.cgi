#!/usr/bin/perl

use strict;
use warnings;
use CGI;
use HTML::Template;
use IPC::Open3;
use JSON::PP qw(decode_json encode_json);
use POSIX qw(strftime);
use Socket qw(AF_INET AF_INET6 inet_ntop inet_pton);
use Symbol qw(gensym);
use LoxBerry::System;
use LoxBerry::Web;
use LoxBerry::Log;

my $cgi = CGI->new;
my $q = $cgi->Vars;
# LoxBerry may initialize its process-global language before readlanguage()
# inspects the query string. Keep the documented request-local preview useful
# without changing the persisted system language.
if (($q->{lang} // '') =~ /\A(?:de|en)\z/) {
    $LoxBerry::System::lang = $q->{lang};
    $LoxBerry::Web::lang = $q->{lang};
}
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

sub miniserver_endpoint {
    my ($server) = @_;
    return if ref($server) ne 'HASH';

    my $transport = lc($server->{Transport} // '');
    return if $transport ne 'http' && $transport ne 'https';

    my $host = $server->{IPAddress} // '';
    $host =~ s/\A\s+|\s+\z//g;
    $host = lc($host);
    return if $host eq '';
    if ($host =~ /:/) {
        my $packed = inet_pton(AF_INET6, $host);
        return if !defined $packed;
        return if $transport eq 'http' && (unpack('C', $packed) & 0xfe) != 0xfc;
        $host = '[' . lc(inet_ntop(AF_INET6, $packed)) . ']';
    } else {
        my $packed = inet_pton(AF_INET, $host);
        if (defined $packed) {
            my @octets = unpack('C4', $packed);
            my $private = $octets[0] == 10
                || ($octets[0] == 172 && $octets[1] >= 16 && $octets[1] <= 31)
                || ($octets[0] == 192 && $octets[1] == 168);
            return if $transport eq 'http' && !$private;
            $host = inet_ntop(AF_INET, $packed);
        } else {
            return if $transport eq 'http'
                || length($host) > 253
                || $host =~ /\.\z/;
            my @labels = split(/\./, $host, -1);
            return if grep {
                $_ eq ''
                    || length($_) > 63
                    || $_ =~ /\A-/
                    || $_ =~ /-\z/
                    || $_ !~ /\A[a-z0-9-]+\z/
            } @labels;
        }
    }

    my $port = $transport eq 'https' ? $server->{PortHttps} : $server->{Port};
    $port = $transport eq 'https' ? 443 : 80 if !defined($port) || $port eq '';
    return if "$port" !~ /\A[0-9]{1,5}\z/ || $port < 1 || $port > 65535;
    my $default_port = $transport eq 'https' ? 443 : 80;
    return "$transport://$host" . ($port == $default_port ? '' : ":$port");
}

sub configured_miniservers {
    my ($selected_endpoint) = @_;
    my %servers = eval { LoxBerry::System::get_miniservers() };
    if ($@) {
        LOGWARN('Could not read configured Miniservers');
        return [];
    }

    my @options;
    for my $key (sort keys %servers) {
        my $server = $servers{$key};
        my $endpoint = miniserver_endpoint($server);
        next if !defined $endpoint;
        my $name = $server->{Name} // '';
        $name =~ s/\A\s+|\s+\z//g;
        $name = "Miniserver $key" if $name eq '';
        push @options, {
            endpoint => $endpoint,
            label => "$name - $endpoint",
            selected => $endpoint eq ($selected_endpoint // '') ? 1 : 0,
        };
    }
    if (($selected_endpoint // '') eq '' && @options == 1) {
        $options[0]{selected} = 1;
    }
    return \@options;
}

sub requested_endpoint {
    my ($query) = @_;
    my $selection = $query->{miniserver_endpoint} // '';
    return $selection ne '' ? $selection : ($query->{endpoint} // '');
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
                endpoint => requested_endpoint($q),
                connection_timeout => 0 + ($q->{connection_timeout} // 10),
            },
            tools => {
                loxone_read_enabled => JSON::PP::true,
                loxone_control_enabled => $q->{loxone_control_enabled} ? JSON::PP::true : JSON::PP::false,
            },
            limits => {
                requests_per_minute => 0 + ($q->{requests_per_minute} // 60),
                control_requests_per_minute => 0 + ($q->{control_requests_per_minute} // 10),
                max_parallel_calls => 0 + ($q->{max_parallel_calls} // 4),
            },
        };
        $result = admin_call('save_config', $document);
    } elsif ($action eq 'test_connection') {
        $result = admin_call('test_connection', {endpoint => requested_endpoint($q)});
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

use constant MAX_EXPIRY_EPOCH => 4_102_444_799;

sub format_expiry {
    my ($value) = @_;
    my $raw = defined($value) ? "$value" : '';
    return $raw if $raw !~ /\A(?:0|[1-9][0-9]*)\z/
        || length($raw) > 10
        || 0 + $raw > MAX_EXPIRY_EPOCH;
    my $formatted = eval {
        strftime('%Y-%m-%d %H:%M:%S %Z', localtime(0 + $raw));
    };
    return defined($formatted) && length($formatted) ? $formatted : $raw;
}

my $page_result = admin_call('page_state', {});
my $page_state = $page_result->{ok} ? $page_result->{data} : {};
my $config = $page_state->{configuration} // {};
my $sessions = $page_state->{sessions} // [];
for my $session (@$sessions) {
    next if ref($session) ne 'HASH';
    $session->{expires_display} = format_expiry($session->{expires_at});
}
$config->{server} = {} if ref($config->{server}) ne 'HASH';
$config->{loxone} = {} if ref($config->{loxone}) ne 'HASH';
$config->{tools} = {} if ref($config->{tools}) ne 'HASH';
$config->{limits} = {} if ref($config->{limits}) ne 'HASH';
my $miniservers = configured_miniservers($config->{loxone}{endpoint});
my $has_selected_miniserver = grep { $_->{selected} } @$miniservers;
my ($selected_miniserver) = grep { $_->{selected} } @$miniservers;
my $display_endpoint = $config->{loxone}{endpoint} // '';
$display_endpoint = $selected_miniserver->{endpoint}
    if $display_endpoint eq '' && $selected_miniserver;

$template->param(
    VERSION => $version,
    ENABLED => $config->{server}{enabled} ? 1 : 0,
    PUBLIC_ORIGIN => $config->{server}{public_origin} // '',
    ENDPOINT => $display_endpoint,
    MINISERVERS => $miniservers,
    MANUAL_ENDPOINT => $has_selected_miniserver ? 0 : 1,
    CONNECTION_TIMEOUT => $config->{loxone}{connection_timeout} // 10,
    LOXONE_CONTROL_ENABLED => $config->{tools}{loxone_control_enabled} ? 1 : 0,
    REQUESTS_PER_MINUTE => $config->{limits}{requests_per_minute} // 60,
    CONTROL_REQUESTS_PER_MINUTE => $config->{limits}{control_requests_per_minute} // 10,
    MAX_PARALLEL_CALLS => $config->{limits}{max_parallel_calls} // 4,
    SERVICE_ACTIVE => $page_state->{service_active} ? 1 : 0,
    SESSIONS => $sessions,
    HAS_SESSIONS => scalar(@$sessions) ? 1 : 0,
    NOTICE => ($q->{notice} // '') eq 'success' ? $L{'AJAX.SUCCESS'} :
        (($q->{notice} // '') ne '' ? $L{'AJAX.ERROR'} : ''),
    NOTICE_KIND => ($q->{notice} // '') eq 'success' ? 'success' : 'error',
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
