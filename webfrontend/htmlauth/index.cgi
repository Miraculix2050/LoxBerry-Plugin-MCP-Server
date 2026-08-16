#!/usr/bin/perl

use strict;
use warnings;
use CGI;
use Encode qw(decode encode is_utf8 FB_DEFAULT);
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
use constant ADMIN_LOG_MESSAGE_BYTES => 8 * 1024;
use constant ADMIN_LOG_TRUNCATION_SUFFIX => ' ... [truncated]';

sub bounded_admin_message {
    my ($message) = @_;
    $message = '' if !defined($message) || ref($message);
    $message =~ s/[\r\n]+/ /g;
    my $encoded = encode('UTF-8', $message);
    my $suffix = encode('UTF-8', ADMIN_LOG_TRUNCATION_SUFFIX);
    return $message if length($encoded) <= ADMIN_LOG_MESSAGE_BYTES;
    my $prefix = substr($encoded, 0, ADMIN_LOG_MESSAGE_BYTES - length($suffix));
    return decode('UTF-8', $prefix, FB_DEFAULT) . ADMIN_LOG_TRUNCATION_SUFFIX;
}

sub admin_log {
    my ($severity, $message) = @_;
    my %threshold = (error => 3, warning => 4, info => 6, debug => 7);
    my %method = (error => 'ERR', warning => 'WARN', info => 'INF', debug => 'DEB');
    return if !exists $threshold{$severity // ''};
    my $plugin_level = LoxBerry::System::pluginloglevel($lbpplugindir);
    $plugin_level = 3 if !defined($plugin_level) || $plugin_level !~ /\A[0-7]\z/;
    return if $plugin_level == 0 || $threshold{$severity} > $plugin_level;

    $message = bounded_admin_message($message);
    $admin_log //= LoxBerry::Log->new(
        name => 'admin-ui',
        package => $lbpplugindir,
        addtime => 1,
    );
    my $log_method = $method{$severity};
    $admin_log->$log_method($message) if $admin_log;
}

$ENV{LBPDATA} = $lbpdatadir;
$ENV{MCPSERVER_CONFIG} = "$lbpconfigdir/mcpserver.json";
$ENV{MCPSERVER_AUTH_STORE} = "$lbpdatadir/auth/sessions.json";
$ENV{MCPSERVER_LOXONE_TOKEN_STORE} = "$lbpdatadir/auth/loxone-tokens.json.enc";
$ENV{MCPSERVER_INSTALL_KEY} = "$lbpdatadir/auth/install.key";
$ENV{MCPSERVER_MQTT_CREDENTIALS} = "$lbpdatadir/auth/mqtt-credentials.json.enc";
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
        admin_log('error', 'component=admin_helper outcome=failed');
        return {ok => JSON::PP::false, error => {code => 'internal_error', message => 'Administrative action failed'}};
    }
    my $result = eval { decode_json($stdout) };
    if (!$result || ref($result) ne 'HASH') {
        admin_log('error', 'component=admin_helper outcome=invalid_response');
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

sub security_header_args {
    return (
        -Cache_Control => 'no-store',
        -Pragma => 'no-cache',
        -Content_Security_Policy => "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'",
        -Referrer_Policy => 'no-referrer',
        -X_Content_Type_Options => 'nosniff',
        -X_Frame_Options => 'DENY',
    );
}

sub print_html_security_headers {
    print "Cache-Control: no-store\n";
    print "Pragma: no-cache\n";
    print "Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'\n";
    print "Referrer-Policy: no-referrer\n";
    print "X-Content-Type-Options: nosniff\n";
    print "X-Frame-Options: DENY\n";
}

sub redirect_reply {
    my ($location) = @_;
    print $cgi->header(-status => 302, -location => $location, security_header_args());
    exit;
}

sub json_reply {
    my ($result, $status) = @_;
    print $cgi->header(
        -type => 'application/json',
        -charset => 'utf-8',
        -status => ($status // 200),
        security_header_args(),
    );
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
        admin_log('warning', 'component=loxberry_config outcome=unreadable');
        $general_config_cache = {};
        return $general_config_cache;
    }
    open my $handle, '<:raw', $path or do {
        admin_log('warning', 'component=loxberry_config outcome=open_failed');
        $general_config_cache = {};
        return $general_config_cache;
    };
    local $/;
    my $raw = <$handle> // '';
    close $handle;
    if (length($raw) > 1024 * 1024) {
        admin_log('warning', 'component=loxberry_config outcome=oversized');
        $general_config_cache = {};
        return $general_config_cache;
    }
    my $document = eval { decode_json($raw) };
    if ($@ || ref($document) ne 'HASH') {
        admin_log('warning', 'component=loxberry_config outcome=invalid');
        $general_config_cache = {};
        return $general_config_cache;
    }
    $general_config_cache = $document;
    return $general_config_cache;
}

sub stored_miniservers {
    my $document = stored_general_config();
    if (ref($document->{Miniserver}) ne 'HASH') {
        admin_log('warning', 'component=miniserver_config outcome=invalid');
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
        redirect_reply('index.cgi?notice=forbidden');
    }

    my $result;
    if ($action eq 'save_mcp_config') {
        my $document = {
            schema_version => 5,
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
                loxberry_read_enabled => ($q->{loxberry_read_enabled} // '') eq '1'
                    ? JSON::PP::true : JSON::PP::false,
                loxone_history_enabled => ($q->{loxone_history_enabled} // '') eq '1'
                    ? JSON::PP::true : JSON::PP::false,
                loxberry_operate_enabled => ($q->{loxberry_operate_enabled} // '') eq '1'
                    ? JSON::PP::true : JSON::PP::false,
            },
            limits => {
                requests_per_minute => 0 + ($q->{requests_per_minute} // 60),
                control_requests_per_minute => 0 + ($q->{control_requests_per_minute} // 10),
                loxberry_requests_per_minute => 0 + ($q->{loxberry_requests_per_minute} // 30),
                history_requests_per_minute => 0 + ($q->{history_requests_per_minute} // 12),
                loxberry_operate_requests_per_minute => 0 + ($q->{loxberry_operate_requests_per_minute} // 3),
                max_parallel_calls => 0 + ($q->{max_parallel_calls} // 4),
                structure_refresh_seconds => 0 + ($q->{structure_refresh_seconds} // 300),
                max_active_runtime_sessions => 0 + ($q->{max_active_runtime_sessions} // 16),
                runtime_session_idle_seconds => 0 + ($q->{runtime_session_idle_seconds} // 900),
                max_structure_controls => 0 + ($q->{max_structure_controls} // 20000),
                max_structure_state_references => 0 + ($q->{max_structure_state_references} // 100000),
                max_structure_depth => 0 + ($q->{max_structure_depth} // 32),
                max_states_per_identity => 0 + ($q->{max_states_per_identity} // 20000),
            },
            cache => {
                statistics_memory_max_mib => 0 + ($q->{statistics_memory_max_mib} // 128),
            },
            emergency_stop => {
                virtual_status_uuid => $q->{emergency_stop_virtual_status_uuid} // '',
            },
        };
        $result = admin_call('save_mcp_config', $document);
        admin_log($result->{ok} ? 'info' : 'warning',
            'action=save_mcp_config outcome=' . ($result->{ok} ? 'completed' : 'rejected'));
    } elsif ($action eq 'save_mqtt_config') {
        my $document = {
            schema_version => 5,
            mqtt => {
                enabled => $q->{mqtt_enabled} ? JSON::PP::true : JSON::PP::false,
                root_topic => $q->{mqtt_root_topic} // 'mcpserver',
                heartbeat_seconds => 0 + ($q->{mqtt_heartbeat_seconds} // 60),
                use_loxberry_gateway => $q->{mqtt_use_loxberry_gateway} ? JSON::PP::true : JSON::PP::false,
                host => $q->{mqtt_host} // '',
                port => 0 + ($q->{mqtt_port} // 1883),
                username => $q->{mqtt_username} // '',
            },
        };
        $document->{mqtt_password} = $q->{mqtt_password} if defined $q->{mqtt_password};
        $document->{mqtt_clear_password} = ($q->{mqtt_clear_password} // '') eq '1'
            ? JSON::PP::true : JSON::PP::false;
        $result = admin_call('save_mqtt_config', $document);
        admin_log($result->{ok} ? 'info' : 'warning',
            'action=save_mqtt_config outcome=' . ($result->{ok} ? 'completed' : 'rejected'));
    } elsif ($action eq 'set_logging') {
        $result = admin_call('set_logging', {mode => ($q->{mode} // '')});
        admin_log($result->{ok} ? 'info' : 'warning',
            'action=set_service_log_level outcome=' . ($result->{ok} ? 'completed' : 'rejected'));
    } elsif ($action eq 'page_state') {
        $result = admin_call('page_state', {});
    } elsif ($action eq 'test_connection') {
        $result = admin_call('test_connection', {endpoint => requested_endpoint($q)});
    } elsif ($action eq 'revoke_session') {
        $result = admin_call('revoke_session', {id => ($q->{id} // '')});
        admin_log($result->{ok} ? 'info' : 'warning',
            'action=revoke_session outcome=' . ($result->{ok} ? 'completed' : 'rejected'));
    } elsif ($action eq 'confirm_loxone_token') {
        $result = admin_call('confirm_loxone_token', {session_id => ($q->{session_id} // '')});
        admin_log($result->{ok} ? 'info' : 'warning',
            'action=confirm_loxone_token outcome=' . ($result->{ok} ? 'completed' : 'rejected'));
    } elsif ($action eq 'allow_loxberry_read') {
        $result = admin_call('allow_loxberry_read', {session_id => ($q->{session_id} // '')});
        admin_log($result->{ok} ? 'info' : 'warning',
            'action=allow_loxberry_read outcome=' . ($result->{ok} ? 'completed' : 'rejected'));
    } elsif ($action eq 'revoke_loxberry_read') {
        $result = admin_call('revoke_loxberry_read', {binding_id => ($q->{binding_id} // '')});
        admin_log($result->{ok} ? 'info' : 'warning',
            'action=revoke_loxberry_read outcome=' . ($result->{ok} ? 'completed' : 'rejected'));
    } elsif ($action eq 'allow_loxberry_operate') {
        $result = admin_call('allow_loxberry_operate', {session_id => ($q->{session_id} // '')});
        admin_log($result->{ok} ? 'info' : 'warning',
            'action=allow_loxberry_operate outcome=' . ($result->{ok} ? 'completed' : 'rejected'));
    } elsif ($action eq 'revoke_loxberry_operate') {
        $result = admin_call('revoke_loxberry_operate', {binding_id => ($q->{binding_id} // '')});
        admin_log($result->{ok} ? 'info' : 'warning',
            'action=revoke_loxberry_operate outcome=' . ($result->{ok} ? 'completed' : 'rejected'));
    } elsif ($action eq 'list_sessions') {
        $result = admin_call('list_sessions', {});
    } elsif ($action eq 'revoke_all') {
        $result = admin_call('revoke_all', {});
        admin_log($result->{ok} ? 'info' : 'warning',
            'action=revoke_all outcome=' . ($result->{ok} ? 'completed' : 'rejected'));
    } elsif ($action eq 'status') {
        $result = admin_call('status', {});
    } elsif ($action eq 'service_status') {
        $result = admin_call('service_status', {});
    } elsif ($action eq 'set_service_enabled') {
        my $enabled = $q->{service_enabled} ? JSON::PP::true : JSON::PP::false;
        $result = admin_call('set_service_enabled', {enabled => $enabled});
        admin_log($result->{ok} ? 'info' : 'warning',
            'action=set_service_enabled outcome=' . ($result->{ok} ? 'completed' : 'rejected'));
    } elsif ($action eq 'service_action') {
        my $command = $q->{command} // '';
        if ($command eq 'start' || $command eq 'stop' || $command eq 'restart') {
            $result = admin_call('service_action', {command => $command});
            if ($result->{ok}) {
                admin_log('info', "action=service_$command outcome=completed");
            } else {
                admin_log('error', "action=service_$command outcome=failed");
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
        admin_log($result->{ok} ? 'info' : 'warning',
            'action=certificate_renewal outcome=' . ($result->{ok} ? 'scheduled' : 'rejected'));
    } else {
        $result = {ok => JSON::PP::false, error => {code => 'invalid_request', message => 'Unsupported action'}};
    }
    localize_admin_error($result);
    if ($action eq 'diagnostic' && $result->{ok}) {
        print $cgi->header(
            -type => 'application/json',
            -charset => 'utf-8',
            -attachment => 'mcpserver-diagnostic.json',
            security_header_args(),
        );
        print encode_json($result->{data});
        exit;
    }
    json_reply($result, $result->{ok} ? 200 : 400) if $q->{ajax};
    my $notice = $result->{ok}
        ? ($action eq 'renew_certificate' ? 'certificate_scheduled' : 'success')
        : 'error';
    redirect_reply("index.cgi?notice=$notice");
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

my $config_result = admin_call('get_config', {});
my $config = $config_result->{ok} ? ($config_result->{data}{configuration} // {}) : {};
my $service_setting_result = admin_call('service_status', {});
my $service_setting = $service_setting_result->{ok}
    && ref($service_setting_result->{data}{service}) eq 'HASH'
    ? $service_setting_result->{data}{service} : {};
my $service_setting_known = $service_setting_result->{ok} ? 1 : 0;
my $emergency_options_result = admin_call('emergency_stop_options', {});
my $emergency_options = $emergency_options_result->{ok}
    ? ($emergency_options_result->{data}{options} // []) : [];
my $sessions = [];
my $loxberry_bindings = [];
my $loxberry_operate_bindings = [];
$config->{server} = {} if ref($config->{server}) ne 'HASH';
$config->{loxone} = {} if ref($config->{loxone}) ne 'HASH';
$config->{tools} = {} if ref($config->{tools}) ne 'HASH';
$config->{limits} = {} if ref($config->{limits}) ne 'HASH';
$config->{logging} = {} if ref($config->{logging}) ne 'HASH';
$config->{cache} = {} if ref($config->{cache}) ne 'HASH';
$config->{emergency_stop} = {} if ref($config->{emergency_stop}) ne 'HASH';
my $selected_emergency_stop = $config->{emergency_stop}{virtual_status_uuid} // '';
for my $option (@$emergency_options) {
    # HTML::Template writes byte strings. Convert only Unicode data returned by
    # the Python helper; language strings are already UTF-8 bytes.
    if (defined($option->{name}) && !ref($option->{name}) && is_utf8($option->{name})) {
        $option->{name} = encode('UTF-8', $option->{name});
    }
    $option->{selected} = $option->{uuid} eq $selected_emergency_stop ? 1 : 0;
}
my $miniservers = configured_miniservers($config->{loxone}{endpoint});
my $has_selected_miniserver = grep { $_->{selected} } @$miniservers;
my ($selected_miniserver) = grep { $_->{selected} } @$miniservers;
my $display_endpoint = $config->{loxone}{endpoint} // '';
$display_endpoint = $selected_miniserver->{endpoint}
    if $display_endpoint eq '' && $selected_miniserver;
my $public_origin = $config->{server}{public_origin} // '';
my $certificate = {};
my $service = {};
my $renewal = {};
my $general_config = stored_general_config();
my $sslport = ref($general_config->{Webserver}) eq 'HASH'
    ? $general_config->{Webserver}{Sslport} : 443;
my $hostname_mcp_url = local_mcp_url(LoxBerry::System::lbhostname(), $sslport);
my $ip_mcp_url = local_mcp_url(LoxBerry::System::get_localip(), $sslport);
if ($public_origin eq '' && $hostname_mcp_url ne '') {
    ($public_origin = $hostname_mcp_url) =~ s{/plugins/mcpserver/mcp\z}{};
}
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
my @service_logs;
for my $suffix ('', '.1', '.2') {
    my $filename = "service.log$suffix";
    next if $suffix ne '' && !-f "$lbplogdir/$filename";
    push @service_logs, {
        filename => $filename,
        url => "/admin/system/tools/logfile.cgi?logfile=plugins/$lbpplugindir/$filename&header=html&format=template",
    };
}
$template->param(
    VERSION => $version,
    SERVICE_ENABLED_SETTING => $service_setting->{enabled} ? 1 : 0,
    SERVICE_ENABLED_SETTING_KNOWN => $service_setting_known,
    ENABLED => $config->{server}{enabled} ? 1 : 0,
    MQTT_ENABLED => $config->{mqtt}{enabled} ? 1 : 0,
    MQTT_ROOT_TOPIC => $config->{mqtt}{root_topic} // 'mcpserver',
    MQTT_HEARTBEAT_SECONDS => $config->{mqtt}{heartbeat_seconds} // 60,
    MQTT_USE_LOXBERRY_GATEWAY => $config->{mqtt}{use_loxberry_gateway} ? 1 : 0,
    MQTT_HOST => $config->{mqtt}{host} // '',
    MQTT_PORT => $config->{mqtt}{port} // 1883,
    MQTT_USERNAME => $config->{mqtt}{username} // '',
    PUBLIC_ORIGIN => $public_origin,
    HOSTNAME_MCP_URL => $hostname_mcp_url,
    IP_MCP_URL => $ip_mcp_url,
    EXPLORER_URL => 'explorer.cgi',
    SCHEMA_REFERENCE_URL => 'tool-schema-reference.html',
    ENDPOINT => $display_endpoint,
    MINISERVERS => $miniservers,
    MANUAL_ENDPOINT => $has_selected_miniserver ? 0 : 1,
    CONNECTION_TIMEOUT => $config->{loxone}{connection_timeout} // 10,
    LOXONE_CONTROL_ENABLED => $config->{tools}{loxone_control_enabled} ? 1 : 0,
    LOXBERRY_READ_ENABLED => $config->{tools}{loxberry_read_enabled} ? 1 : 0,
    LOXONE_HISTORY_ENABLED => $config->{tools}{loxone_history_enabled} ? 1 : 0,
    LOXBERRY_OPERATE_ENABLED => $config->{tools}{loxberry_operate_enabled} ? 1 : 0,
    REQUESTS_PER_MINUTE => $config->{limits}{requests_per_minute} // 60,
    CONTROL_REQUESTS_PER_MINUTE => $config->{limits}{control_requests_per_minute} // 10,
    LOXBERRY_REQUESTS_PER_MINUTE => $config->{limits}{loxberry_requests_per_minute} // 30,
    HISTORY_REQUESTS_PER_MINUTE => $config->{limits}{history_requests_per_minute} // 12,
    LOXBERRY_OPERATE_REQUESTS_PER_MINUTE => $config->{limits}{loxberry_operate_requests_per_minute} // 3,
    STATISTICS_MEMORY_MAX_MIB => $config->{cache}{statistics_memory_max_mib} // 128,
    MAX_PARALLEL_CALLS => $config->{limits}{max_parallel_calls} // 4,
    STRUCTURE_REFRESH_SECONDS => $config->{limits}{structure_refresh_seconds} // 300,
    MAX_ACTIVE_RUNTIME_SESSIONS => $config->{limits}{max_active_runtime_sessions} // 16,
    RUNTIME_SESSION_IDLE_SECONDS => $config->{limits}{runtime_session_idle_seconds} // 900,
    MAX_STRUCTURE_CONTROLS => $config->{limits}{max_structure_controls} // 20000,
    MAX_STRUCTURE_STATE_REFERENCES => $config->{limits}{max_structure_state_references} // 100000,
    MAX_STRUCTURE_DEPTH => $config->{limits}{max_structure_depth} // 32,
    MAX_STATES_PER_IDENTITY => $config->{limits}{max_states_per_identity} // 20000,
    EMERGENCY_STOP_OPTIONS => $emergency_options,
    LOG_LEVEL => $config->{logging}{level} // 'warning',
    LOG_LEVEL_OFF => ($config->{logging}{level} // 'warning') eq 'off' ? 1 : 0,
    LOG_LEVEL_ERROR => ($config->{logging}{level} // 'warning') eq 'error' ? 1 : 0,
    LOG_LEVEL_WARNING => ($config->{logging}{level} // 'warning') eq 'warning' ? 1 : 0,
    LOG_LEVEL_INFO => ($config->{logging}{level} // 'warning') eq 'info' ? 1 : 0,
    LOG_LEVEL_DEBUG => ($config->{logging}{level} // 'warning') eq 'debug' ? 1 : 0,
    SERVICE_ACTIVE => 0,
    SERVICE_INSTALLED => $service->{installed} ? 1 : 0,
    SERVICE_FAILED => ($service->{active_state} // '') eq 'failed' ? 1 : 0,
    SERVICE_KNOWN => ($service->{active_state} // 'unknown') ne 'unknown' ? 1 : 0,
    SERVICE_ACTIVE_STATE => $service->{active_state} // 'unknown',
    SERVICE_SUB_STATE => $service->{sub_state} // 'unknown',
    SERVICE_PID => $service->{pid} // '-',
    SERVICE_NAME => $service->{name} // 'loxberry-mcpserver.service',
    SERVICE_LOG_URL => "/admin/system/tools/logfile.cgi?logfile=plugins/$lbpplugindir/service.log&header=html&format=template",
    SERVICE_LOGS => \@service_logs,
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
    LOXBERRY_BINDINGS => $loxberry_bindings,
    LOXBERRY_OPERATE_BINDINGS => $loxberry_operate_bindings,
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

print_html_security_headers();
LoxBerry::Web::lbheader($L{'BASIC.TITLE'} . " V$version", '', '', 'nojqm');
print LoxBerry::Log::get_notifications_html($lbpplugindir);
print $template->output();
LoxBerry::Web::lbfooter();
exit;
