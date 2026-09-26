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
use Time::HiRes qw(clock_gettime CLOCK_MONOTONIC);
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
my $render_started = clock_gettime(CLOCK_MONOTONIC);
my $request_id = sprintf('%x-%x', $$, int($render_started * 1_000_000));
my %L;
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

sub ascii_html_text {
    my ($value) = @_;
    return '' if !defined($value) || ref($value);
    $value =~ s/&/&amp;/g;
    $value =~ s/</&lt;/g;
    $value =~ s/>/&gt;/g;
    $value =~ s/"/&quot;/g;
    $value =~ s/'/&#39;/g;
    $value =~ s/([^\x20-\x7E])/sprintf('&#x%X;', ord($1))/ge;
    return $value;
}

sub native_loglist_html {
    my $html = LoxBerry::Web::loglist_html();
    if (!defined($html)) {
        # The native LogManager is an independent loopback CGI. A transient
        # failure during concurrent page hydration is worth one short retry.
        select(undef, undef, undef, 0.2);
        $html = LoxBerry::Web::loglist_html();
        admin_log('warning', sprintf(
            'component=logmanager request_id=%s outcome=unavailable attempts=2',
            $request_id,
        ))
            if !defined($html);
    }
    return $html if defined($html) && $html =~ /logfile\.cgi\?/;
    my $unavailable = !defined($html);
    my $label = $L{$unavailable ? 'DIAGNOSTICS.LOGLIST_UNAVAILABLE' : 'DIAGNOSTICS.LOGLIST_EMPTY'};
    $label = '' if !defined($label);
    $label = decode('UTF-8', $label, FB_DEFAULT) if !is_utf8($label);
    return sprintf(
        '<p class="mcp-status" data-kind="%s" role="status">%s</p>',
        $unavailable ? 'error' : 'warning',
        ascii_html_text($label),
    );
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
    if (!$admin_log) {
        $admin_log = LoxBerry::Log->new(
            name => 'admin-ui',
            package => $lbpplugindir,
            addtime => 1,
        );
        $admin_log->LOGSTART(sprintf(
            'component=admin_ui request_id=%s severity=info outcome=started', $request_id,
        )) if $admin_log;
    }
    my $log_method = $method{$severity};
    $admin_log->$log_method($message) if $admin_log;
}

END {
    $admin_log->LOGEND(sprintf(
        'component=admin_ui request_id=%s severity=info outcome=finished', $request_id,
    )) if $admin_log;
}

$ENV{LBPDATA} = $lbpdatadir;
$ENV{MCPSERVER_CONFIG} = "$lbpconfigdir/mcpserver.json";
$ENV{MCPSERVER_AUTH_STORE} = "$lbpdatadir/auth/sessions.json";
$ENV{MCPSERVER_LOXONE_TOKEN_STORE} = "$lbpdatadir/auth/loxone-tokens.json.enc";
$ENV{MCPSERVER_INSTALL_KEY} = "$lbpdatadir/auth/install.key";
$ENV{MCPSERVER_MQTT_CREDENTIALS} = "$lbpdatadir/auth/mqtt-credentials.json.enc";
$ENV{MCPSERVER_EVENT_HISTORY_STORE} = "$lbpdatadir/event-history/state-events.sqlite3";
$ENV{MCPSERVER_WEB_CERT} = "$lbhomedir/data/system/LoxBerryCA/certs/wwwcert.pem";
$ENV{MCPSERVER_CA_CERT} = "$lbhomedir/data/system/LoxBerryCA/cacert.pem";
$ENV{MCPSERVER_CERT_HELPER} = '/usr/local/sbin/loxberry-mcpserver-renew-web-certificate';
$ENV{MCPSERVER_CERT_STATUS} = "$lbpdatadir/certificate-renewal.json";

sub admin_call {
    my ($action, $payload) = @_;
    my $started = clock_gettime(CLOCK_MONOTONIC);
    my $routine_poll = $action eq 'service_status' || $action eq 'list_sessions';
    my ($child_in, $child_out);
    my $child_err = gensym;
    my $pid = open3($child_in, $child_out, $child_err, "$lbpbindir/mcpserver-admin");
    print {$child_in} encode_json({action => $action, payload => ($payload // {})});
    close $child_in;
    local $/;
    my $stdout = <$child_out> // '';
    my $stderr = <$child_err> // '';
    waitpid($pid, 0);
    if ($stderr =~ /(?:\A|\n)mcpserver_admin_timing=(\{[^\r\n]{1,2048}\})/) {
        my $timing = eval { decode_json($1) };
        if (ref($timing) eq 'HASH') {
            my %safe_timing = map {
                ($_ => $timing->{$_})
            } grep {
                /\A[a-z_]{1,64}\z/ && defined($timing->{$_}) && $timing->{$_} =~ /\A\d+(?:\.\d+)?\z/
            } keys %$timing;
            admin_log('debug', sprintf(
                'component=admin_helper request_id=%s action=%s timing=%s',
                $request_id, $action, encode_json(\%safe_timing),
            )) if %safe_timing && !$routine_poll;
        }
    }
    my $duration_ms = (clock_gettime(CLOCK_MONOTONIC) - $started) * 1000;
    if ($routine_poll) {
        my $slow_threshold_ms = $action eq 'service_status' ? 5000 : 10000;
        admin_log('warning', sprintf(
            'component=admin_ui request_id=%s action=%s outcome=slow duration_ms=%.1f',
            $request_id, $action, $duration_ms,
        )) if $duration_ms >= $slow_threshold_ms;
    } else {
        admin_log('debug', sprintf(
            'component=admin_ui request_id=%s action=%s duration_ms=%.1f',
            $request_id, $action, $duration_ms,
        ));
    }
    if ($? != 0 || $stdout eq '') {
        admin_log('error', 'component=admin_helper outcome=failed');
        return {ok => JSON::PP::false, error => {code => 'internal_error', message => 'Administrative action failed'}};
    }
    my $result = eval { decode_json($stdout) };
    if (!$result || ref($result) ne 'HASH') {
        admin_log('error', 'component=admin_helper outcome=invalid_response');
        return {ok => JSON::PP::false, error => {code => 'internal_error', message => 'Administrative action failed'}};
    }
    if (!$result->{ok} && ref($result->{error}) eq 'HASH') {
        my $code = $result->{error}{code} // '';
        if ($code =~ /\A[a-z_]{1,128}\z/) {
            admin_log('warning', sprintf(
                'component=admin_helper request_id=%s action=%s outcome=rejected code=%s',
                $request_id,
                $action,
                $code,
            ));
        }
    }
    if ($action eq 'page_snapshot' && $result->{ok} && ref($result->{data}) eq 'HASH') {
        for my $section (qw(get_config page_state service_status certificate_status list_sessions)) {
            my $entry = $result->{data}{$section};
            next if ref($entry) ne 'HASH' || $entry->{ok};
            my $code = ref($entry->{error}) eq 'HASH' ? ($entry->{error}{code} // '') : '';
            $code = 'internal_error' if $code !~ /\A[a-z_]{1,128}\z/;
            admin_log($code eq 'internal_error' ? 'error' : 'warning', sprintf(
                'component=admin_helper request_id=%s action=page_snapshot section=%s outcome=rejected code=%s',
                $request_id, $section, $code,
            ));
        }
    }
    if (($action eq 'emergency_stop_options' || $action eq 'emergency_stop_retry')
        && $result->{ok} && ref($result->{data}) eq 'HASH') {
        my $failure_code = delete $result->{data}{discovery_failure_code};
        if (defined $failure_code && $failure_code =~ /\A[a-z_]{1,128}\z/) {
            my %labels = (
                authentication_suppressed => 'EMERGENCY_STOP_AUTH_SUPPRESSED',
                authentication_busy => 'EMERGENCY_STOP_AUTH_BUSY',
                credentials_unavailable => 'EMERGENCY_STOP_CREDENTIALS_UNAVAILABLE',
                connection_failed => 'EMERGENCY_STOP_CONNECTION_FAILED',
                structure_failed => 'EMERGENCY_STOP_STRUCTURE_FAILED',
            );
            $result->{data}{failure_text} = $L{'SETUP.' . ($labels{$failure_code} // 'EMERGENCY_STOP_LOAD_ERROR')};
            admin_log('warning', sprintf(
                'component=emergency_stop outcome=options_unavailable request_id=%s code=%s',
                $request_id,
                $failure_code,
            ));
        }
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
    my ($template_duration_ms) = @_;
    print "Cache-Control: no-store\n";
    print "Pragma: no-cache\n";
    print "Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'\n";
    print "Referrer-Policy: no-referrer\n";
    print "X-Content-Type-Options: nosniff\n";
    print "X-Frame-Options: DENY\n";
    printf "Server-Timing: mcp-template;dur=%.1f\n", $template_duration_ms
        if defined $template_duration_ms;
}

sub redirect_reply {
    my ($location) = @_;
    print $cgi->header(-status => 302, -location => $location, security_header_args());
    exit;
}

sub json_unicode_text {
    my ($value) = @_;
    return $value if !defined($value) || ref($value) || is_utf8($value);
    return decode('UTF-8', $value, FB_DEFAULT);
}

sub json_reply {
    my ($result, $status) = @_;
    if (ref($result->{data}) eq 'HASH' && defined($result->{data}{failure_text})) {
        $result->{data}{failure_text} = json_unicode_text($result->{data}{failure_text});
    }
    if (ref($result->{error}) eq 'HASH' && defined($result->{error}{message})) {
        $result->{error}{message} = json_unicode_text($result->{error}{message});
    }
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
%L = LoxBerry::System::readlanguage($template, 'language.ini');
my $template_setup_ms = (clock_gettime(CLOCK_MONOTONIC) - $render_started) * 1000;

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
my $fallback_retry_result;
if ($action ne '') {
    if (!same_origin_post()) {
        my $failure = {ok => JSON::PP::false, error => {code => 'forbidden', message => 'Same-origin POST required'}};
        json_reply($failure, 403) if $q->{ajax};
        redirect_reply('index.cgi?notice=forbidden');
    }

    my $result;
    if ($action eq 'save_mcp_config') {
        my $document = {
            schema_version => 9,
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
                explorer_binding_retention_hours => 0 + ($q->{explorer_binding_retention_hours} // 72),
                max_parallel_calls => 0 + ($q->{max_parallel_calls} // 4),
                structure_refresh_seconds => 0 + ($q->{structure_refresh_seconds} // 300),
                max_active_runtime_sessions => 0 + ($q->{max_active_runtime_sessions} // 16),
                runtime_session_idle_seconds => 0 + ($q->{runtime_session_idle_seconds} // 900),
                miniserver_auth_probe_initial_seconds => 0 + ($q->{miniserver_auth_probe_initial_seconds} // 900),
                miniserver_auth_probe_max_seconds => 0 + ($q->{miniserver_auth_probe_max_seconds} // 86400),
                max_structure_controls => 0 + ($q->{max_structure_controls} // 20000),
                max_structure_state_references => 0 + ($q->{max_structure_state_references} // 100000),
                max_structure_depth => 0 + ($q->{max_structure_depth} // 32),
                max_states_per_identity => 0 + ($q->{max_states_per_identity} // 20000),
            },
            cache => {
                statistics_memory_max_mib => 0 + ($q->{statistics_memory_max_mib} // 128),
            },
            event_history => {
                enabled => ($q->{event_history_enabled} // '') eq '1'
                    ? JSON::PP::true : JSON::PP::false,
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
    } elsif ($action eq 'get_config') {
        $result = admin_call('get_config', {});
    } elsif ($action eq 'page_snapshot') {
        $result = admin_call('page_snapshot', {});
        admin_log('debug', sprintf(
            'component=admin_ui request_id=%s action=page_snapshot template_setup_ms=%.1f',
            $request_id, $template_setup_ms,
        ));
    } elsif ($action eq 'page_auxiliary') {
        my $aux_started = clock_gettime(CLOCK_MONOTONIC);
        my ($notifications, $loglist);
        my $notifications_ok = eval {
            $notifications = LoxBerry::Log::get_notifications_html($lbpplugindir) // '';
            1;
        };
        my $notification_duration_ms = (clock_gettime(CLOCK_MONOTONIC) - $aux_started) * 1000;
        admin_log('error', sprintf(
            'component=admin_ui request_id=%s action=page_auxiliary section=page_notifications outcome=rejected code=internal_error',
            $request_id,
        )) if !$notifications_ok;
        my $loglist_started = clock_gettime(CLOCK_MONOTONIC);
        my $loglist_ok = eval {
            $loglist = native_loglist_html();
            1;
        };
        admin_log('error', sprintf(
            'component=admin_ui request_id=%s action=page_auxiliary section=page_loglist outcome=rejected code=internal_error',
            $request_id,
        )) if !$loglist_ok;
        admin_log('debug', sprintf(
            'component=admin_ui request_id=%s action=page_auxiliary duration_ms=%.1f notifications_ms=%.1f loglist_ms=%.1f template_setup_ms=%.1f',
            $request_id,
            (clock_gettime(CLOCK_MONOTONIC) - $aux_started) * 1000,
            $notification_duration_ms,
            (clock_gettime(CLOCK_MONOTONIC) - $loglist_started) * 1000,
            $template_setup_ms,
        ));
        $result = {
            ok => JSON::PP::true,
            data => {
                page_notifications => $notifications_ok
                    ? {ok => JSON::PP::true, data => {notifications_html => $notifications}}
                    : {ok => JSON::PP::false, error => {code => 'internal_error'}},
                page_loglist => $loglist_ok
                    ? {ok => JSON::PP::true, data => {loglist_html => $loglist}}
                    : {ok => JSON::PP::false, error => {code => 'internal_error'}},
            },
        };
    } elsif ($action eq 'page_notifications') {
        my $started = clock_gettime(CLOCK_MONOTONIC);
        $result = {
            ok => JSON::PP::true,
            data => {
                notifications_html => LoxBerry::Log::get_notifications_html($lbpplugindir) // '',
            },
        };
        admin_log('debug', sprintf(
            'component=admin_ui request_id=%s action=page_notifications duration_ms=%.1f',
            $request_id,
            (clock_gettime(CLOCK_MONOTONIC) - $started) * 1000,
        ));
    } elsif ($action eq 'page_loglist') {
        $result = {
            ok => JSON::PP::true,
            data => {
                loglist_html => native_loglist_html(),
            },
        };
    } elsif ($action eq 'page_state') {
        $result = admin_call('page_state', {});
    } elsif ($action eq 'emergency_stop_options') {
        $result = admin_call('emergency_stop_options', {});
    } elsif ($action eq 'emergency_stop_cached_options') {
        $result = admin_call('emergency_stop_cached_options', {});
    } elsif ($action eq 'emergency_stop_retry') {
        $result = admin_call('emergency_stop_retry', {});
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
    if (($action eq 'emergency_stop_retry' || $action eq 'emergency_stop_options')
        && ($q->{fallback} // '') eq '1') {
        $fallback_retry_result = $result;
    } else {
        redirect_reply("index.cgi?notice=$notice");
    }
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

my $server_rendered_fallback = ($q->{fallback} // '') eq '1';
my $config = {};
my $sessions = [];
my $remote_cleanup = {available => 0};
my $loxberry_bindings = [];
my $loxberry_operate_bindings = [];
my $emergency_stop_options = [];
my $selected_emergency_stop_unavailable = 0;
my $emergency_stop_status_text = $L{'SETUP.EMERGENCY_STOP_LOADING'};
my $emergency_stop_status_kind = 'info';
my $emergency_stop_status_visible = 1;
my $emergency_stop_retry_visible = 0;
my $emergency_stop_retry_enabled = 0;
my $emergency_stop_button_label = $L{'SETUP.EMERGENCY_STOP_LOAD'};
my $emergency_stop_button_action = 'emergency_stop_options';
my $fallback_configuration_loaded = 0;
my $fallback_summary_configuration_loaded = 0;
my $fallback_summary_sessions_loaded = 0;
my $notifications_html = '';
my $loglist_html = '';
my $service_enabled_setting_known = 0;
my $service_enabled_setting = 0;
my $service = {};
my $emergency_stop_runtime = {availability => 'unavailable'};
if ($server_rendered_fallback) {
    my $config_result = admin_call('get_config', {});
    $config = $config_result->{data}{configuration}
        if $config_result->{ok} && ref($config_result->{data}{configuration}) eq 'HASH';
    $fallback_configuration_loaded = $config_result->{ok} ? 1 : 0;
    $fallback_summary_configuration_loaded =
        $config_result->{ok} && ref($config_result->{data}{configuration}) eq 'HASH' ? 1 : 0;
    my $service_result = admin_call('service_status', {});
    if ($service_result->{ok} && ref($service_result->{data}{service}) eq 'HASH') {
        $service = $service_result->{data}{service};
        $service_enabled_setting_known = 1;
        $service_enabled_setting = $service->{enabled} ? 1 : 0;
    }
    if ($service_result->{ok} && ref($service_result->{data}{emergency_stop_runtime}) eq 'HASH') {
        $emergency_stop_runtime = $service_result->{data}{emergency_stop_runtime};
    }
    $notifications_html = LoxBerry::Log::get_notifications_html($lbpplugindir) // '';
    $loglist_html = native_loglist_html();
    my $sessions_result = admin_call('list_sessions', {});
    if ($sessions_result->{ok} && ref($sessions_result->{data}) eq 'HASH') {
        $remote_cleanup = $sessions_result->{data}{remote_cleanup}
            if ref($sessions_result->{data}{remote_cleanup}) eq 'HASH';
        $sessions = $sessions_result->{data}{sessions}
            if ref($sessions_result->{data}{sessions}) eq 'ARRAY';
        $fallback_summary_sessions_loaded = 1
            if ref($sessions_result->{data}{sessions}) eq 'ARRAY';
        $loxberry_bindings = $sessions_result->{data}{loxberry_bindings}
            if ref($sessions_result->{data}{loxberry_bindings}) eq 'ARRAY';
        $loxberry_operate_bindings = $sessions_result->{data}{loxberry_operate_bindings}
            if ref($sessions_result->{data}{loxberry_operate_bindings}) eq 'ARRAY';
    }
}
$config->{server} = {} if ref($config->{server}) ne 'HASH';
$config->{loxone} = {} if ref($config->{loxone}) ne 'HASH';
$config->{tools} = {} if ref($config->{tools}) ne 'HASH';
$config->{limits} = {} if ref($config->{limits}) ne 'HASH';
$config->{logging} = {} if ref($config->{logging}) ne 'HASH';
$config->{cache} = {} if ref($config->{cache}) ne 'HASH';
$config->{mqtt} = {} if ref($config->{mqtt}) ne 'HASH';
$config->{emergency_stop} = {} if ref($config->{emergency_stop}) ne 'HASH';
my $selected_emergency_stop = $config->{emergency_stop}{virtual_status_uuid} // '';
if ($server_rendered_fallback) {
    my $options_result = $fallback_retry_result
        // admin_call('emergency_stop_cached_options', {});
    my $options_data = ref($options_result->{data}) eq 'HASH'
        ? $options_result->{data} : {};
    my $options = $options_data->{options};
    if ($options_result->{ok} && ref($options) eq 'ARRAY') {
        for my $option (@$options) {
            next if ref($option) ne 'HASH';
            my $uuid = $option->{uuid};
            my $name = $option->{name};
            next if !defined($uuid) || !defined($name) || ref($uuid) || ref($name);
            push @$emergency_stop_options, {
                uuid => $uuid,
                name_html => ascii_html_text($name),
                selected => $uuid eq $selected_emergency_stop ? 1 : 0,
            };
        }
        $selected_emergency_stop_unavailable = $selected_emergency_stop ne ''
            && !grep { $_->{selected} } @$emergency_stop_options;
        my $status = $options_data->{status} // '';
        if ($status eq 'available') {
            if ($options_data->{stale}) {
                $emergency_stop_status_text = $L{'SETUP.EMERGENCY_STOP_STALE'};
            } elsif (!@$emergency_stop_options) {
                $emergency_stop_status_text = $L{'SETUP.EMERGENCY_STOP_NO_OPTIONS'};
            } elsif ($options_data->{cached}) {
                $emergency_stop_status_text = $L{'SETUP.EMERGENCY_STOP_CACHED'};
            } else {
                $emergency_stop_status_visible = 0;
            }
            $emergency_stop_button_label = $L{'SETUP.EMERGENCY_STOP_REFRESH'};
            $emergency_stop_retry_visible = 1;
            $emergency_stop_retry_enabled = 1;
        } elsif ($status eq 'not_loaded') {
            $emergency_stop_status_text = $L{'SETUP.EMERGENCY_STOP_NOT_LOADED'};
            $emergency_stop_retry_visible = 1;
            $emergency_stop_retry_enabled = 1;
        } elsif ($status eq 'not_configured') {
            $emergency_stop_status_text = $L{'SETUP.EMERGENCY_STOP_NOT_CONFIGURED'};
            $emergency_stop_status_kind = 'error';
            $emergency_stop_retry_visible = 1;
            $emergency_stop_retry_enabled = 1;
        } else {
            $emergency_stop_status_text = $options_data->{failure_text}
                // $L{'SETUP.EMERGENCY_STOP_LOAD_ERROR'};
            $emergency_stop_status_text .= ' ' . $L{'SETUP.EMERGENCY_STOP_STALE'}
                if $options_data->{stale};
            $emergency_stop_status_kind = 'error';
            $emergency_stop_button_label = $L{'SETUP.EMERGENCY_STOP_RETRY'};
            $emergency_stop_button_action = 'emergency_stop_retry';
            $emergency_stop_retry_visible = 1;
            $emergency_stop_retry_enabled = 1;
            my $retry_at = $options_data->{retry_not_before};
            if ($status eq 'unavailable' && defined($retry_at)
                && "$retry_at" =~ /\A[0-9]{1,10}\z/
                && $retry_at <= MAX_EXPIRY_EPOCH) {
                $emergency_stop_status_text .= ' ' . format_expiry($retry_at);
                $emergency_stop_retry_enabled = time() >= $retry_at ? 1 : 0;
            }
        }
    } else {
        $emergency_stop_status_text = $L{'SETUP.EMERGENCY_STOP_LOAD_ERROR'};
        $emergency_stop_status_kind = 'error';
        $emergency_stop_retry_visible = 1;
        $emergency_stop_retry_enabled = 1;
    }
}
my $miniservers = configured_miniservers($config->{loxone}{endpoint} // '');
my $has_selected_miniserver = grep { $_->{selected} } @$miniservers;
my ($selected_miniserver) = grep { $_->{selected} } @$miniservers;
my $display_endpoint = $config->{loxone}{endpoint} // '';
$display_endpoint = $selected_miniserver->{endpoint}
    if $display_endpoint eq '' && $selected_miniserver;
my $public_origin = $config->{server}{public_origin} // '';
my $certificate = {};
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
my $fallback_url = 'index.cgi?fallback=1';
$fallback_url .= '&notice=' . $notice_value
    if $notice_value =~ /\A(?:success|certificate_scheduled|error|forbidden)\z/;
for my $session (@$sessions) {
    next if ref($session) ne 'HASH';
    $session->{expires_display} = format_expiry($session->{expires_at});
}
my $fallback_approval_count = 0;
if ($fallback_summary_sessions_loaded) {
    for my $session (@$sessions) {
        next if ref($session) ne 'HASH';
        $fallback_approval_count++ if $session->{loxone_token_confirmation_required};
        $fallback_approval_count++
            if $session->{loxberry_read_eligible} && !$session->{loxberry_read_approved};
        $fallback_approval_count++
            if $session->{loxberry_operate_eligible} && !$session->{loxberry_operate_approved};
    }
}
for my $bindings ($loxberry_bindings, $loxberry_operate_bindings) {
    next if ref($bindings) ne 'ARRAY';
    for my $binding (@$bindings) {
        next if ref($binding) ne 'HASH' || ref($binding->{rows}) ne 'ARRAY';
        for my $row (@{$binding->{rows}}) {
            next if ref($row) ne 'HASH' || !$row->{retention_expires_at};
            $row->{retention_expires_display} = format_expiry($row->{retention_expires_at});
        }
    }
}
my @service_logs;
for my $suffix ('', '.1', '.2') {
    my $filename = "service.log$suffix";
    next if $suffix ne '' && !-f "$lbplogdir/$filename";
    push @service_logs, {
        filename => $filename,
        url => "/admin/system/tools/logfile.cgi?logfile=plugins/$lbpplugindir/$filename&header=html&format=template",
    };
}
my $runtime_availability = $emergency_stop_runtime->{availability} // 'unavailable';
$runtime_availability = 'unavailable'
    if $runtime_availability !~ /\A(?:available|service_inactive|unavailable)\z/;
my $runtime_status = $emergency_stop_runtime->{status} // 'unknown';
$runtime_status = 'unknown' if $runtime_status !~ /\A(?:not_configured|clear|active|unknown)\z/;
my $runtime_signal_uuid = $emergency_stop_runtime->{signal_uuid};
$runtime_signal_uuid = '' if !defined($runtime_signal_uuid) || ref($runtime_signal_uuid);
my $runtime_signal_name = $emergency_stop_runtime->{signal_name};
$runtime_signal_name = '' if !defined($runtime_signal_name) || ref($runtime_signal_name);
my @remote_cleanup_notices;
if ($server_rendered_fallback) {
    if (!$remote_cleanup->{available}) {
        push @remote_cleanup_notices, $L{'SESSIONS.REMOTE_STATUS_UNAVAILABLE'};
    } else {
        push @remote_cleanup_notices, $L{'SESSIONS.REMOTE_BREAKER_WARNING'}
            if ($remote_cleanup->{breaker_state} // '') eq 'open_source_ip_blocked';
        for my $entry (
            ['pending', 'SESSIONS.REMOTE_PENDING_WARNING'],
            ['retryable', 'SESSIONS.REMOTE_RETRYABLE_WARNING'],
            ['unconfirmed', 'SESSIONS.REMOTE_UNCONFIRMED_WARNING'],
        ) {
            my ($field, $label) = @$entry;
            my $count = $remote_cleanup->{$field};
            push @remote_cleanup_notices, "$L{$label} $count"
                if defined($count) && !ref($count) && $count =~ /\A[0-9]+\z/ && $count > 0;
        }
        my %failure_labels = (
            authentication_rejected => 'SESSIONS.REMOTE_REJECTED',
            source_ip_blocked => 'SESSIONS.REMOTE_BLOCKED',
            transport_failed => 'SESSIONS.REMOTE_TRANSPORT',
            command_rejected => 'SESSIONS.REMOTE_COMMAND',
        );
        my $category = $remote_cleanup->{last_failure_category} // '';
        my $at = $remote_cleanup->{last_failure_at};
        if (@remote_cleanup_notices && exists $failure_labels{$category}
            && defined($at) && !ref($at) && $at =~ /\A[0-9]+\z/) {
            my $failure_label = $failure_labels{$category};
            push @remote_cleanup_notices,
                $L{'SESSIONS.REMOTE_LAST_FAILURE'} . ' '
                . $L{$failure_label} . ', ' . format_expiry($at);
        }
    }
}
my $remote_cleanup_warning = join(' ', @remote_cleanup_notices);
my $runtime_signal = $server_rendered_fallback && $runtime_availability eq 'available'
    ? ($runtime_signal_name ne '' ? $runtime_signal_name
        : $runtime_signal_uuid ne '' ? $runtime_signal_uuid
        : $L{'SETUP.EMERGENCY_STOP_NONE'})
    : $server_rendered_fallback && $runtime_availability eq 'service_inactive'
        ? $L{'SETUP.EMERGENCY_STOP_RUNTIME_SERVICE_INACTIVE'}
        : $server_rendered_fallback ? $L{'SETUP.EMERGENCY_STOP_RUNTIME_UNAVAILABLE'}
        : $L{'SETUP.EMERGENCY_STOP_LOADING'};
$template->param(
    VERSION => $version,
    SERVER_RENDERED_FALLBACK => $server_rendered_fallback,
    FALLBACK_CONFIGURATION_LOADED => $fallback_configuration_loaded,
    FALLBACK_SUMMARY_CONFIGURATION_LOADED => $fallback_summary_configuration_loaded,
    FALLBACK_SUMMARY_SESSIONS_LOADED => $fallback_summary_sessions_loaded,
    FALLBACK_SESSION_COUNT => scalar(@$sessions),
    FALLBACK_APPROVAL_COUNT => $fallback_approval_count,
    FALLBACK_HAS_APPROVALS => $fallback_approval_count > 0 ? 1 : 0,
    FALLBACK_URL => $fallback_url,
    NOTIFICATIONS_HTML => $notifications_html,
    LOGLIST_HTML => $loglist_html,
    SERVICE_ENABLED_SETTING => $service_enabled_setting,
    SERVICE_ENABLED_SETTING_KNOWN => $service_enabled_setting_known,
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
    EVENT_HISTORY_ENABLED => $config->{event_history}{enabled} ? 1 : 0,
    EVENT_HISTORY_SOURCE_COUNT => scalar(@{$config->{event_history}{sources} // []}),
    REQUESTS_PER_MINUTE => $config->{limits}{requests_per_minute} // 60,
    CONTROL_REQUESTS_PER_MINUTE => $config->{limits}{control_requests_per_minute} // 10,
    LOXBERRY_REQUESTS_PER_MINUTE => $config->{limits}{loxberry_requests_per_minute} // 30,
    HISTORY_REQUESTS_PER_MINUTE => $config->{limits}{history_requests_per_minute} // 12,
    LOXBERRY_OPERATE_REQUESTS_PER_MINUTE => $config->{limits}{loxberry_operate_requests_per_minute} // 3,
    EXPLORER_BINDING_RETENTION_HOURS => $config->{limits}{explorer_binding_retention_hours} // 72,
    STATISTICS_MEMORY_MAX_MIB => $config->{cache}{statistics_memory_max_mib} // 128,
    MAX_PARALLEL_CALLS => $config->{limits}{max_parallel_calls} // 4,
    STRUCTURE_REFRESH_SECONDS => $config->{limits}{structure_refresh_seconds} // 300,
    MAX_ACTIVE_RUNTIME_SESSIONS => $config->{limits}{max_active_runtime_sessions} // 16,
    RUNTIME_SESSION_IDLE_SECONDS => $config->{limits}{runtime_session_idle_seconds} // 900,
    MINISERVER_AUTH_PROBE_INITIAL_SECONDS => $config->{limits}{miniserver_auth_probe_initial_seconds} // 900,
    MINISERVER_AUTH_PROBE_MAX_SECONDS => $config->{limits}{miniserver_auth_probe_max_seconds} // 86400,
    MAX_STRUCTURE_CONTROLS => $config->{limits}{max_structure_controls} // 20000,
    MAX_STRUCTURE_STATE_REFERENCES => $config->{limits}{max_structure_state_references} // 100000,
    MAX_STRUCTURE_DEPTH => $config->{limits}{max_structure_depth} // 32,
    MAX_STATES_PER_IDENTITY => $config->{limits}{max_states_per_identity} // 20000,
    SELECTED_EMERGENCY_STOP => $selected_emergency_stop,
    EMERGENCY_STOP_OPTIONS => $emergency_stop_options,
    EMERGENCY_STOP_SELECTED_UNAVAILABLE => $selected_emergency_stop_unavailable,
    EMERGENCY_STOP_STATUS_TEXT => $emergency_stop_status_text,
    EMERGENCY_STOP_STATUS_KIND => $emergency_stop_status_kind,
    EMERGENCY_STOP_STATUS_VISIBLE => $emergency_stop_status_visible,
    EMERGENCY_STOP_RETRY_VISIBLE => $emergency_stop_retry_visible,
    EMERGENCY_STOP_RETRY_ENABLED => $emergency_stop_retry_enabled,
    EMERGENCY_STOP_BUTTON_LABEL => $emergency_stop_button_label,
    EMERGENCY_STOP_BUTTON_ACTION => $emergency_stop_button_action,
    EMERGENCY_STOP_RUNTIME_SIGNAL_VALUE => $runtime_signal,
    EMERGENCY_STOP_RUNTIME_UUID => $runtime_signal_uuid,
    EMERGENCY_STOP_RUNTIME_UUID_VISIBLE => $server_rendered_fallback
        && $runtime_availability eq 'available' && $runtime_signal_uuid ne '',
    EMERGENCY_STOP_RUNTIME_STATE_VALUE => $server_rendered_fallback
        && $runtime_availability eq 'available' ? $runtime_status : 'unknown',
    EMERGENCY_STOP_RUNTIME_BUSY => $server_rendered_fallback ? 0 : 1,
    LOG_LEVEL => $config->{logging}{level} // 'warning',
    LOG_LEVEL_OFF => ($config->{logging}{level} // 'warning') eq 'off' ? 1 : 0,
    LOG_LEVEL_ERROR => ($config->{logging}{level} // 'warning') eq 'error' ? 1 : 0,
    LOG_LEVEL_WARNING => ($config->{logging}{level} // 'warning') eq 'warning' ? 1 : 0,
    LOG_LEVEL_INFO => ($config->{logging}{level} // 'warning') eq 'info' ? 1 : 0,
    LOG_LEVEL_DEBUG => ($config->{logging}{level} // 'warning') eq 'debug' ? 1 : 0,
    SERVICE_ACTIVE => $service->{active} ? 1 : 0,
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
    REMOTE_CLEANUP_WARNING_VISIBLE => length($remote_cleanup_warning) ? 1 : 0,
    REMOTE_CLEANUP_WARNING => $remote_cleanup_warning,
    LOXBERRY_BINDINGS => $loxberry_bindings,
    LOXBERRY_OPERATE_BINDINGS => $loxberry_operate_bindings,
    HAS_SESSIONS => scalar(@$sessions) ? 1 : 0,
    NOTICE => $notice_text,
    NOTICE_KIND => $notice_kind,
);

my $page = $template->output();
my $template_duration_ms = (clock_gettime(CLOCK_MONOTONIC) - $render_started) * 1000;
print_html_security_headers($template_duration_ms);
my $header_started = clock_gettime(CLOCK_MONOTONIC);
LoxBerry::Web::lbheader($L{'BASIC.TITLE'} . " V$version", '', '', 'nojqm');
admin_log('debug', sprintf(
    'component=admin_ui request_id=%s phase=loxberry_header duration_ms=%.1f',
    $request_id,
    (clock_gettime(CLOCK_MONOTONIC) - $header_started) * 1000,
));
print $page;
LoxBerry::Web::lbfooter();
admin_log('debug', sprintf(
    'component=admin_ui request_id=%s phase=initial_render duration_ms=%.1f',
    $request_id,
    (clock_gettime(CLOCK_MONOTONIC) - $render_started) * 1000,
));
exit;
