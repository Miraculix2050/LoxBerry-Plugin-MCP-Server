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
my $admin_log;

sub admin_logger {
    return $admin_log if $admin_log;
    $admin_log = LoxBerry::Log->new(
        name => 'admin-ui', package => $lbpplugindir, addtime => 1, loglevel => 7,
    );
    $admin_log->LOGSTART('Administrative action');
    return $admin_log;
}

END {
    $admin_log->LOGEND('Administrative action finished') if $admin_log;
}

$ENV{LBPDATA} = $lbpdatadir;
$ENV{MCPSERVER_CONFIG} = "$lbpconfigdir/mcpserver.json";
$ENV{MCPSERVER_AUTH_STORE} = "$lbpdatadir/auth/sessions.json";
$ENV{MCPSERVER_LOXONE_TOKEN_STORE} = "$lbpdatadir/auth/loxone-tokens.json.enc";
$ENV{MCPSERVER_INSTALL_KEY} = "$lbpdatadir/auth/install.key";
$ENV{MCPSERVER_WEB_CERT} = "$lbhomedir/data/system/LoxBerryCA/certs/wwwcert.pem";
$ENV{MCPSERVER_CA_CERT} = "$lbhomedir/data/system/LoxBerryCA/cacert.pem";
$ENV{MCPSERVER_CERT_HELPER} = '/usr/local/sbin/loxberry-mcpserver-renew-web-certificate';
$ENV{MCPSERVER_CERT_STATUS} = "$lbpdatadir/certificate-renewal.json";

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

sub enabled_value {
    my ($value) = @_;
    return defined($value) && "$value" =~ /\A(?:1|true|yes|on)\z/i ? 1 : 0;
}

my $general_config_cache;
my $general_config_loaded = 0;

sub stored_general_config {
    return $general_config_cache if $general_config_loaded;
    $general_config_loaded = 1;
    my $path = "$lbhomedir/config/system/general.json";
    if (!-f $path || !-r $path) {
        LOGWARN('Could not read stored LoxBerry configuration');
        $general_config_cache = {};
        return $general_config_cache;
    }
    open my $handle, '<:raw', $path or do {
        LOGWARN('Could not open stored LoxBerry configuration');
        $general_config_cache = {};
        return $general_config_cache;
    };
    local $/;
    my $raw = <$handle> // '';
    close $handle;
    if (length($raw) > 1024 * 1024) {
        LOGWARN('Stored LoxBerry configuration is unexpectedly large');
        $general_config_cache = {};
        return $general_config_cache;
    }
    my $document = eval { decode_json($raw) };
    if ($@ || ref($document) ne 'HASH') {
        LOGWARN('Stored LoxBerry configuration is invalid');
        $general_config_cache = {};
        return $general_config_cache;
    }
    $general_config_cache = $document;
    return $general_config_cache;
}

sub stored_miniservers {
    my $document = stored_general_config();
    if (ref($document->{Miniserver}) ne 'HASH') {
        LOGWARN('Stored Miniserver configuration is invalid');
        return {};
    }

    my %servers;
    for my $key (keys %{$document->{Miniserver}}) {
        my $stored = $document->{Miniserver}{$key};
        next if ref($stored) ne 'HASH';
        # get_miniservers() resolves CloudDNS here. Rendering the page must stay local.
        next if enabled_value($stored->{Useclouddns});
        my $prefer_https = enabled_value($stored->{Preferhttps});
        $servers{$key} = {
            Name => $stored->{Name},
            IPAddress => $stored->{Ipaddress},
            Transport => $prefer_https ? 'https' : 'http',
            Port => $stored->{Port},
            PortHttps => $stored->{Porthttps},
        };
    }
    return \%servers;
}

sub local_mcp_url {
    my ($host, $sslport) = @_;
    $host //= '';
    $host =~ s/\A\s+|\s+\z//g;
    return '' if $host eq '';
    my $packed6 = inet_pton(AF_INET6, $host);
    if (defined $packed6) {
        $host = '[' . lc(inet_ntop(AF_INET6, $packed6)) . ']';
    } else {
        my $packed4 = inet_pton(AF_INET, $host);
        if (defined $packed4) {
            $host = inet_ntop(AF_INET, $packed4);
        } else {
            $host = lc($host);
            return '' if length($host) > 253 || $host !~ /\A[A-Za-z0-9.-]+\z/;
        }
    }
    $sslport = 443 if !defined($sslport) || "$sslport" !~ /\A[0-9]{1,5}\z/
        || $sslport < 1 || $sslport > 65535;
    my $authority = $host . ($sslport == 443 ? '' : ":$sslport");
    return "https://$authority/plugins/mcpserver/mcp";
}

sub configured_miniservers {
    my ($selected_endpoint) = @_;
    my $servers = stored_miniservers();

    my @options;
    for my $key (sort keys %$servers) {
        my $server = $servers->{$key};
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

my $template_text = LoxBerry::System::read_file("$lbptemplatedir/index.html");
my $template = HTML::Template->new_scalar_ref(
    \$template_text,
    global_vars => 1,
    loop_context_vars => 1,
    die_on_bad_params => 0,
);
my %L = LoxBerry::System::readlanguage($template, 'language.ini');

sub localize_admin_error {
    my ($result) = @_;
    return if $result->{ok} || ref($result->{error}) ne 'HASH';
    my %messages = (
        securepin_invalid => $L{'CERTIFICATE.ERROR_PIN_INVALID'},
        securepin_wrong => $L{'CERTIFICATE.ERROR_PIN_WRONG'},
        securepin_locked => $L{'CERTIFICATE.ERROR_PIN_LOCKED'},
        securepin_unavailable => $L{'CERTIFICATE.ERROR_PIN_UNAVAILABLE'},
        confirmation_required => $L{'CERTIFICATE.ERROR_CONFIRMATION'},
        certificate_busy => $L{'CERTIFICATE.ERROR_BUSY'},
        certificate_unsupported => $L{'CERTIFICATE.ERROR_UNSUPPORTED'},
        certificate_failed => $L{'CERTIFICATE.ERROR_FAILED'},
        service_action_failed => $L{'STATUS.ERROR_ACTION'},
    );
    my $code = $result->{error}{code} // '';
    $result->{error}{message} = $messages{$code} if exists $messages{$code};
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
                loxone_control_enabled => ($q->{loxone_control_enabled} // '') eq '1'
                    ? JSON::PP::true : JSON::PP::false,
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
    } elsif ($action eq 'list_sessions') {
        $result = admin_call('list_sessions', {});
    } elsif ($action eq 'revoke_all') {
        $result = admin_call('revoke_all', {});
    } elsif ($action eq 'status') {
        $result = admin_call('status', {});
    } elsif ($action eq 'service_status') {
        $result = admin_call('service_status', {});
    } elsif ($action eq 'service_action') {
        my $command = $q->{command} // '';
        if ($command =~ /\A(?:start|stop|restart)\z/) {
            $result = admin_call('service_action', {command => $command});
            if ($result->{ok}) {
                admin_logger()->INF("service-action=$command result=completed");
            } else {
                admin_logger()->ERR("service-action=$command result=failed");
            }
        } else {
            $result = {ok => JSON::PP::false, error => {code => 'invalid_request', message => 'Unsupported service action'}};
        }
    } elsif ($action eq 'diagnostic') {
        $result = admin_call('diagnostic', {});
    } elsif ($action eq 'certificate_status') {
        $result = admin_call('certificate_status', {});
    } elsif ($action eq 'renew_certificate') {
        $result = admin_call('renew_certificate', {
            securepin => ($q->{securepin} // ''),
            confirmation => ($q->{renew_confirmation} // ''),
        });
        $q->{securepin} = '';
        admin_logger()->INF('certificate-renewal result=scheduled') if $result->{ok};
    } else {
        $result = {ok => JSON::PP::false, error => {code => 'invalid_request', message => 'Unsupported action'}};
    }
    localize_admin_error($result);
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
    my $notice = $result->{ok}
        ? ($action eq 'renew_certificate' ? 'certificate_scheduled' : 'success')
        : 'error';
    print $cgi->redirect("index.cgi?notice=$notice");
    exit;
}

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
my $public_origin = $config->{server}{public_origin} // '';
my $certificate = ref($page_state->{certificate}) eq 'HASH'
    ? $page_state->{certificate} : {};
my $service = ref($page_state->{service}) eq 'HASH'
    ? $page_state->{service} : {};
my $renewal = ref($certificate->{renewal}) eq 'HASH' ? $certificate->{renewal} : {};
my $general_config = stored_general_config();
my $sslport = ref($general_config->{Webserver}) eq 'HASH'
    ? $general_config->{Webserver}{Sslport} : 443;
my $hostname_mcp_url = local_mcp_url(LoxBerry::System::lbhostname(), $sslport);
my $ip_mcp_url = local_mcp_url(LoxBerry::System::get_localip(), $sslport);
my %renewal_labels = (
    idle => $L{'CERTIFICATE.STATE_IDLE'},
    scheduled => $L{'CERTIFICATE.STATE_SCHEDULED'},
    running => $L{'CERTIFICATE.STATE_RUNNING'},
    success => $L{'CERTIFICATE.STATE_SUCCESS'},
    error => $L{'CERTIFICATE.STATE_ERROR'},
);
my $renewal_state = $renewal->{state} // 'idle';
my $notice_value = $q->{notice} // '';
my $notice_text = $notice_value eq 'success' ? $L{'AJAX.SUCCESS'}
    : $notice_value eq 'certificate_scheduled' ? $L{'CERTIFICATE.STATE_SCHEDULED'}
    : $notice_value ne '' ? $L{'AJAX.ERROR'} : '';
my $notice_kind = $notice_value eq 'success' || $notice_value eq 'certificate_scheduled'
    ? 'success' : 'error';
$template->param(
    VERSION => $version,
    ENABLED => $config->{server}{enabled} ? 1 : 0,
    PUBLIC_ORIGIN => $public_origin,
    HOSTNAME_MCP_URL => $hostname_mcp_url,
    IP_MCP_URL => $ip_mcp_url,
    EXPLORER_URL => 'explorer.cgi',
    ENDPOINT => $display_endpoint,
    MINISERVERS => $miniservers,
    MANUAL_ENDPOINT => $has_selected_miniserver ? 0 : 1,
    CONNECTION_TIMEOUT => $config->{loxone}{connection_timeout} // 10,
    LOXONE_CONTROL_ENABLED => $config->{tools}{loxone_control_enabled} ? 1 : 0,
    REQUESTS_PER_MINUTE => $config->{limits}{requests_per_minute} // 60,
    CONTROL_REQUESTS_PER_MINUTE => $config->{limits}{control_requests_per_minute} // 10,
    MAX_PARALLEL_CALLS => $config->{limits}{max_parallel_calls} // 4,
    SERVICE_ACTIVE => $page_state->{service_active} ? 1 : 0,
    SERVICE_INSTALLED => $service->{installed} ? 1 : 0,
    SERVICE_FAILED => ($service->{active_state} // '') eq 'failed' ? 1 : 0,
    SERVICE_KNOWN => ($service->{active_state} // 'unknown') ne 'unknown' ? 1 : 0,
    SERVICE_ACTIVE_STATE => $service->{active_state} // 'unknown',
    SERVICE_SUB_STATE => $service->{sub_state} // 'unknown',
    SERVICE_PID => $service->{pid} // '-',
    SERVICE_NAME => $service->{name} // 'loxberry-mcpserver.service',
    SERVICE_LOG_URL => "/admin/system/tools/logfile.cgi?logfile=plugins/$lbpplugindir/service.log&header=html&format=template",
    CERTIFICATE_AVAILABLE => $certificate->{available} ? 1 : 0,
    CERTIFICATE_SOURCE_LOXBERRY => ($certificate->{source} // '') eq 'loxberry_ca' ? 1 : 0,
    CERTIFICATE_EXPIRES_AT => $certificate->{expires_at} // '',
    CERTIFICATE_EXPIRES => format_expiry($certificate->{expires_at}),
    CERTIFICATE_DNS_COUNT => $certificate->{dns_san_count} // 0,
    CERTIFICATE_IP_COUNT => $certificate->{ip_san_count} // 0,
    CERTIFICATE_ORIGIN_CONFIGURED => $certificate->{origin_configured} ? 1 : 0,
    CERTIFICATE_ORIGIN_MATCHES => $certificate->{origin_matches} ? 1 : 0,
    CERTIFICATE_HOSTNAME_MATCHES => $certificate->{hostname_matches} ? 1 : 0,
    CERTIFICATE_WARNING => $certificate->{available}
        && (!$certificate->{origin_matches} || !$certificate->{hostname_matches}) ? 1 : 0,
    CERTIFICATE_RENEWAL_SUPPORTED => $certificate->{renewal_supported} ? 1 : 0,
    CERTIFICATE_RENEWAL_STATE => $renewal_labels{$renewal_state}
        // $L{'CERTIFICATE.STATE_ERROR'},
    SESSIONS => $sessions,
    HAS_SESSIONS => scalar(@$sessions) ? 1 : 0,
    NOTICE => $notice_text,
    NOTICE_KIND => $notice_kind,
    LOGLIST => LoxBerry::Web::loglist_html(),
);

our %navbar;
$navbar{10}{Name} = $L{'NAV.STATUS'};
$navbar{10}{URL} = '#status';
$navbar{20}{Name} = $L{'NAV.SETUP'};
$navbar{20}{URL} = '#setup';
$navbar{30}{Name} = $L{'NAV.SESSIONS'};
$navbar{30}{URL} = '#sessions';
$navbar{40}{Name} = $L{'NAV.DIAGNOSTICS'};
$navbar{40}{URL} = '#diagnostics';
$navbar{45}{Name} = $L{'NAV.CERTIFICATE'};
$navbar{45}{URL} = '#certificate';
$navbar{50}{Name} = $L{'NAV.HELP'};
$navbar{50}{URL} = '#help';

LoxBerry::Web::lbheader($L{'BASIC.TITLE'} . " V$version", '', '', 'nojqm');
print LoxBerry::Log::get_notifications_html($lbpplugindir);
print $template->output();
LoxBerry::Web::lbfooter();
exit;
