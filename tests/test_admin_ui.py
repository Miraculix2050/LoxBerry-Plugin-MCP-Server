from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _admin_cgi_environment(tmp_path: Path) -> dict[str, str]:
    helper = tmp_path / "mcpserver-admin"
    helper.write_text(
        "#!/usr/bin/env perl\n"
        "use strict; use warnings;\n"
        "my $request = <STDIN>;\n"
        'print qq({\\"ok\\":true,\\"data\\":{}});\n',
        encoding="utf-8",
    )
    helper.chmod(0o755)
    return {
        **os.environ,
        "LB_TEST_HOME": str(tmp_path),
        "LB_TEST_CONFIG_DIR": str(tmp_path),
        "LB_TEST_DATA_DIR": str(tmp_path),
        "LB_TEST_BIN_DIR": str(tmp_path),
        "LB_TEST_TEMPLATE_DIR": str(tmp_path),
        "LB_TEST_LOG_DIR": str(tmp_path),
    }


def _assert_admin_security_headers(output: str) -> None:
    headers = output.lower()
    assert "cache-control: no-store" in headers
    assert "pragma: no-cache" in headers
    assert "content-security-policy:" in headers
    assert "frame-ancestors 'none'" in headers
    assert "base-uri 'self'" in headers
    assert "object-src 'none'" in headers
    assert "form-action 'self'" in headers
    assert "connect-src 'self'" in headers
    assert "referrer-policy: no-referrer" in headers
    assert "x-content-type-options: nosniff" in headers
    assert "x-frame-options: deny" in headers


def test_admin_responses_emit_no_store_and_frame_protection(tmp_path: Path) -> None:
    perl = shutil.which("perl")
    if perl is None or os.name == "nt":
        return
    environment = _admin_cgi_environment(tmp_path)
    cgi = ROOT / "webfrontend" / "htmlauth" / "index.cgi"
    common = [perl, f"-I{ROOT / 'tests' / 'perl_stubs'}", str(cgi)]

    page = subprocess.run(common, check=True, capture_output=True, text=True, env=environment)
    _assert_admin_security_headers(page.stdout)

    ajax_environment = {
        **environment,
        "REQUEST_METHOD": "POST",
        "CONTENT_TYPE": "application/x-www-form-urlencoded",
        "CONTENT_LENGTH": "20",
        "HTTP_ORIGIN": "https://loxberry.example",
        "HTTP_HOST": "loxberry.example",
    }
    ajax = subprocess.run(
        common,
        check=True,
        capture_output=True,
        text=True,
        input="action=status&ajax=1",
        env=ajax_environment,
    )
    _assert_admin_security_headers(ajax.stdout)


def test_initial_page_renders_configuration_before_loading_dynamic_state() -> None:
    cgi = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")

    assert "admin_call('get_config', {})" in cgi
    assert "admin_call('page_state', {})" in cgi
    assert "my $service_setting_result = admin_call('service_status', {});" in cgi
    assert "SERVICE_ENABLED_SETTING_KNOWN => $service_setting_known" in cgi
    assert "body.set('action', 'page_state')" in template
    assert "const loadInitialState" in template
    assert "loadInitialState();" in template
    assert "field.addEventListener('input'" in template
    assert "if (!mqttUseLoxberryGateway.checked)" in template
    assert 'aria-busy="true"' in template
    assert '<strong id="service-active-state"><TMPL_VAR AJAX.WORKING></strong>' in template
    assert '<strong id="service-sub-state"><TMPL_VAR AJAX.WORKING></strong>' in template
    assert '<strong id="service-installed"><TMPL_VAR AJAX.WORKING></strong>' in template
    assert (
        'data-service-enabled-setting-known="<TMPL_IF SERVICE_ENABLED_SETTING_KNOWN>1' in template
    )
    assert (
        'name="service_enabled" type="checkbox" value="1" <TMPL_IF SERVICE_ENABLED_SETTING>checked'
        in template
    )
    assert '<strong id="certificate-source"><TMPL_VAR AJAX.WORKING></strong>' in template
    assert (
        '<time id="certificate-expiry" class="mcp-expiry"><TMPL_VAR AJAX.WORKING></time>'
        in template
    )
    assert (
        "if (element.dataset.expiresAt) updateExpiry(element, element.dataset.expiresAt);"
        in template
    )
    assert 'id="certificate-unavailable" class="mcp-status" hidden' in template
    assert "updateCertificate(null);" in template
    assert (
        "sessionList.replaceChildren(document.createTextNode('<TMPL_VAR AJAX.ERROR ESCAPE=JS>'))"
        in template
    )


def test_common_actions_update_the_page_without_a_reload() -> None:
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")

    assert 'data-ajax="save_mcp_config"' in template
    assert 'data-ajax="save_mqtt_config"' in template
    assert 'name="mqtt_username"' in template
    assert 'name="mqtt_password" type="password"' in template
    assert 'name="mqtt_clear_password"' in template
    assert 'name="mqtt_use_loxberry_gateway"' in template
    assert "Array.isArray(result.data.sessions)" in template
    assert "updateSessions(result.data.sessions)" in template
    assert "window.location.reload" not in template
    assert "window.setTimeout(() => { element.hidden = true; }, 4000)" in template
    assert "window.clearTimeout(hideStatusTimers.get(status))" in template
    assert "url.searchParams.delete('notice')" in template
    assert "postAjax(body, actionTimeout(form.dataset.ajax))" in template
    assert "save_mcp_config: 90000" in template
    assert "save_mqtt_config: 75000" in template
    assert "revoke_all: 75000" in template
    assert "postAjax(body, 5000)" in template
    assert "new URLSearchParams(new FormData(form))" in template
    assert "const body = new FormData" not in template
    assert "if (result.data.certificate) updateCertificate" in template
    assert 'id="session-table-template"' in template
    assert "row.dataset.fingerprint !== sessionFingerprint(session)" in template
    assert "for (const row of existing.values()) row.remove()" in template


def test_admin_cards_use_consistent_vertical_spacing() -> None:
    template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    explorer = (ROOT / "templates" / "explorer.html").read_text(encoding="utf-8")
    stylesheet = (ROOT / "webfrontend" / "htmlauth" / "mcp-ui.css").read_text(encoding="utf-8")

    assert '<link rel="stylesheet" href="mcp-ui.css">' in template
    assert '<link rel="stylesheet" href="mcp-ui.css">' in explorer
    assert "<style>" not in template
    assert "<style>" not in explorer
    assert ".mcp-page { display: grid; gap: 1rem;" in stylesheet
    assert ".mcp-field-stack { display: grid; gap: .85rem; }" in stylesheet
    assert ".mcp-explorer { max-width: 92rem;" in stylesheet
    assert '<div class="mcp-field-stack">' in template


def test_service_status_is_first_and_uses_a_lightweight_ajax_contract() -> None:
    cgi = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")

    assert template.index('id="status"') < template.index('id="setup"')
    assert 'data-ajax="service_status"' not in template
    for command in ("start", "stop", "restart"):
        assert f'data-service-command="{command}"' in template
    assert 'data-ajax="set_service_enabled"' in template
    assert "body.set('action', 'service_status')" in template
    assert "window.setTimeout(pollServiceStatus, delay)" in template
    assert "document.hidden || serviceInteractionActive() || servicePollInFlight" in template
    assert "document.addEventListener('visibilitychange'" in template
    assert "admin_call('service_status', {})" in cgi
    assert "admin_call('service_action', {command => $command})" in cgi
    assert "admin_call('set_service_enabled', {enabled => $enabled})" in cgi
    assert "$command eq 'start' || $command eq 'stop' || $command eq 'restart'" in cgi
    assert "service.log&header=html&format=template" in cgi


def test_sessions_poll_only_while_visible_and_open_and_patch_changed_rows() -> None:
    cgi = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")

    assert "admin_call('list_sessions', {})" in cgi
    assert "body.set('action', 'list_sessions')" in template
    assert "window.setTimeout(pollSessions, delay)" in template
    assert (
        "document.hidden || !sessionsSection.open || sessionActionRunning || sessionPollInFlight"
        in template
    )
    assert "sessionsSection.addEventListener('toggle'" in template
    assert "row.dataset.fingerprint !== sessionFingerprint(session)" in template
    assert "sessionList.replaceChildren(fragment)" in template


def test_parallel_session_actions_pause_polling_without_blocking_buttons() -> None:
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")

    assert "const isSessionAction = (action)" in template
    assert "let activeSessionActions = 0;" in template
    assert "let sessionDataVersion = 0;" in template
    assert "const pendingSessionActionButtons = new Set();" in template
    assert "activeSessionActions += 1;" in template
    assert "sessionDataVersion += 1;" in template
    assert "sessionActionRunning = activeSessionActions > 0;" in template
    assert "if (!sessionActionRunning) scheduleSessionPoll(0);" in template
    assert "if (isSessionAction(form.dataset.ajax) && sessionActionRunning) return;" not in template
    assert "if (expectedSessionDataVersion !== sessionDataVersion) return;" in template
    assert "if (!isSessionAction(form.dataset.ajax)) {" in template
    assert "pendingSessionActionButtons.add(button);" in template
    assert "releasePendingSessionActionButtons();" in template
    assert template.count("if (isSessionAction(form.dataset.ajax)) {") == 3


def test_read_only_ajax_polling_does_not_create_admin_log_files() -> None:
    cgi = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")

    assert "sub admin_log" in cgi
    assert cgi.index("sub admin_log") < cgi.index("LoxBerry::Log->new")
    assert "$admin_log->close() if $admin_log;" not in cgi
    assert "LOGSTART('index.cgi called')" not in cgi
    assert "loglevel => 7" not in cgi
    assert "            filename => $filename," not in cgi
    assert "append => 1" not in cgi
    assert "nosession => 1" not in cgi
    assert "LoxBerry::System::pluginloglevel($lbpplugindir)" in cgi
    assert "name => 'admin-ui'" in cgi
    assert "ADMIN_LOG_MESSAGE_BYTES => 8 * 1024" in cgi
    assert "LOGSTART('Administrative action')" not in cgi
    assert "LOGEND('Administrative action finished')" not in cgi
    assert "action=service_$command outcome=completed" in cgi
    assert "component=admin_helper outcome=failed" in cgi
    assert "component=miniserver_config outcome=invalid" in cgi


def test_diagnostics_offer_dedicated_persistent_service_logging_controls() -> None:
    cgi = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")

    assert "admin_call('set_logging', {mode => ($q->{mode} // '')})" in cgi
    assert 'data-ajax="set_logging"' in template
    for level in ("off", "error", "warning", "info", "debug"):
        assert f'value="{level}"' in template
    assert 'value="debug_15"' not in template
    assert 'value="debug_60"' not in template
    assert 'value="stop_debug"' not in template
    assert "debug_until" not in template + cgi
    assert "DIAGNOSTICS.SERVICE_LEVEL" in template
    assert "DIAGNOSTICS.LOGMANAGER_HELP" in template
    assert "DIAGNOSTICS.SERVICE_SECTION" in template
    assert "DIAGNOSTICS.PLUGIN_SECTION" in template
    assert template.count('class="mcp-log-section"') == 2
    assert template.index('id="service-log-heading"') < template.index('id="plugin-log-heading"')
    service_log_section = template[
        template.index('id="service-log-heading"') : template.index('id="plugin-log-heading"')
    ]
    assert 'class="mcp-log-files"' in service_log_section
    assert "TMPL_LOOP SERVICE_LOGS" in service_log_section
    assert 'href="<TMPL_VAR url ESCAPE=HTML>"' in service_log_section
    assert "DIAGNOSTICS.SERVICE_LOG_FILES" in service_log_section
    assert "SERVICE_LOGS => \\@service_logs" in cgi
    assert "for my $suffix ('', '.1', '.2')" in cgi
    assert "set_logging: 75000" in template
    assert "renderLogging(result.data.configuration)" in template
    assert "window.location.reload" not in template


def test_first_setup_prefills_https_origin_from_loxberry_hostname() -> None:
    cgi = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")

    assert "my $hostname_mcp_url = local_mcp_url(LoxBerry::System::lbhostname(), $sslport);" in cgi
    assert "if ($public_origin eq '' && $hostname_mcp_url ne '')" in cgi
    assert "s{/plugins/mcpserver/mcp\\z}{}" in cgi


def test_service_actions_use_an_accessible_confirmation_and_dynamic_controls() -> None:
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")

    assert '<dialog id="service-confirm"' in template
    assert 'aria-labelledby="service-confirm-title"' in template
    assert "serviceConfirmMessages[confirmationKey]" in template
    assert "form.dataset.confirmed = 'true'" in template
    assert "form.requestSubmit()" in template
    assert "command === 'start' && !active" in template
    assert "command === 'stop' && active" in template
    assert "serviceState.dataset.kind = kind" in template
    assert "serviceActionRunning = true" in template
    assert (
        "renderService(result.data.service, {updateEnabledSetting: !serviceEnabledSettingLoaded});"
        in template
    )
    assert "let serviceEnabledSetting = serviceEnabledInput.checked" in template
    assert (
        "let serviceEnabledSettingLoaded = serviceEnableForm.dataset."
        "serviceEnabledSettingKnown === '1'" in template
    )
    assert "serviceEnabledSetting = enabled" in template
    assert "serviceEnabledSettingLoaded = true" in template
    assert "serviceEnabledInput.checked = enabled" in template
    assert (
        "serviceEnabledInput.disabled = serviceActionRunning || !serviceEnabledSettingLoaded"
        in template
    )
    assert (
        "serviceEnabledApplyButton.disabled = serviceActionRunning || !serviceEnabledSettingLoaded"
        in template
    )
    assert "updateEnabledSetting: form.dataset.ajax === 'set_service_enabled'" in template
    assert "command === 'restart'" in template
    assert "const commandReady = command === 'start' ? !active : active" in template
    assert "const available = visible && commandReady && serviceEnabledSetting" in template
    assert "form.hidden = !visible" in template
    assert "serviceEnabledInput.checked = serviceEnabledSetting" in template
    assert "body.set('service_enabled', requestedServiceEnabled ? '1' : '0')" in template
    assert "Boolean(service.enabled) !== requestedServiceEnabled" in template
    assert "Boolean(service.active) !== requestedServiceEnabled" in template
    assert (
        "const serviceInteractionActive = () => serviceActionRunning || pendingServiceForm !== null"
        in template
    )
    assert "if (serviceInteractionActive()) return;" in template
    assert "serviceEnabledInput.disabled = serviceActionRunning" in template
    assert "serviceStatusRefreshRequired" not in template
    assert "preserveRequestedEnabledState" not in template
    assert "set_service_enabled: 75000" in template


def test_admin_sections_are_native_persistent_collapsibles() -> None:
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")

    for section in ("status", "setup", "mqtt", "help", "certificate", "sessions", "diagnostics"):
        assert f'<details id="{section}" class="mcp-card" data-persist-collapse' in template
    assert '<details id="status" class="mcp-card" data-persist-collapse open' in template
    assert '<details id="setup" class="mcp-card" data-persist-collapse open' in template
    assert "mcpserver.admin.sections.v1" in template
    assert "window.localStorage.getItem(collapseStorageKey)" in template
    assert "window.localStorage.setItem(collapseStorageKey" in template
    assert "element.addEventListener('toggle', persistCollapsibles)" in template
    assert "window.addEventListener('hashchange', openHashSection)" in template
    assert "target instanceof HTMLDetailsElement" in template


def test_permission_policy_uses_grouped_scope_labeled_checkboxes() -> None:
    cgi = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")

    assert template.index('id="loxone-permissions-heading"') < template.index(
        'id="loxberry-permissions-heading"'
    )
    assert "SETUP.PERMISSIONS_ACTIVE" in template
    assert "SETUP.PERMISSIONS_OPTION" in template
    assert "SETUP.PERMISSIONS_SCOPE" in template
    assert "SETUP.PERMISSIONS_EFFECT" in template
    assert "SETUP.PERMISSIONS_ALWAYS" in template
    for field, scope in (
        ("loxone_history_enabled", "loxone:history"),
        ("loxone_control_enabled", "loxone:control"),
        ("loxberry_read_enabled", "loxberry:read"),
        ("loxberry_operate_enabled", "loxberry:operate"),
    ):
        assert f'name="{field}" type="checkbox" value="1"' in template
        assert f"<code>{scope}</code>" in template
        assert f"($q->{{{field}}} // '') eq '1'" in cgi
    assert "<code>loxone:read</code>" in template
    assert '<select name="loxone_control_enabled">' not in template


def test_cache_operation_checkbox_tracks_history_dependency() -> None:
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")

    assert 'id="loxone-history-enabled"' in template
    assert 'id="loxberry-operate-enabled"' in template
    assert "operateEnabled.disabled = !historyEnabled.checked" in template
    assert "if (operateEnabled.disabled) operateEnabled.checked = false" in template
    assert "historyEnabled.addEventListener('change', syncOperateDependency)" in template
    assert template.count("syncOperateDependency();") == 1


def test_permission_policy_is_localized_in_german_and_english() -> None:
    german = (ROOT / "templates/lang/language_de.ini").read_text(encoding="utf-8")
    english = (ROOT / "templates/lang/language_en.ini").read_text(encoding="utf-8")

    for key in (
        "PERMISSIONS_ACTIVE",
        "PERMISSIONS_OPTION",
        "PERMISSIONS_SCOPE",
        "PERMISSIONS_EFFECT",
        "PERMISSIONS_ALWAYS",
        "READ_DESCRIPTION",
        "HISTORY_DESCRIPTION",
        "CONTROL_DESCRIPTION",
        "LOXBERRY_DESCRIPTION",
        "OPERATE_DESCRIPTION",
        "OPERATE_DEPENDENCY",
        "PERMISSIONS_HINT",
    ):
        assert f"{key}=" in german
        assert f"{key}=" in english


def test_miniserver_selection_uses_local_sanitized_loxberry_metadata() -> None:
    cgi = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")

    assert '"$lbhomedir/config/system/general.json"' in cgi
    assert "LoxBerry::System::get_miniservers()" not in cgi
    assert "next if enabled_value($stored->{Useclouddns})" in cgi
    assert "IPAddress => $stored->{Ipaddress}" in cgi
    assert "PortHttps => $stored->{Porthttps}" in cgi
    assert "miniserver_endpoint($server)" in cgi
    assert "FullURI" not in cgi + template
    assert "Credentials" not in cgi + template
    assert 'id="miniserver-select"' in template
    assert "<TMPL_LOOP MINISERVERS>" in template
    assert 'id="manual-endpoint-fields"' in template
    assert "<TMPL_UNLESS MANUAL_ENDPOINT>hidden</TMPL_UNLESS>" in template
    assert 'id="miniserver-endpoint"' in template
    assert "<TMPL_IF MANUAL_ENDPOINT>required<TMPL_ELSE>readonly</TMPL_IF>" in template
    assert "miniserverEndpoint.readOnly = Boolean(selectedEndpoint)" in template
    assert "miniserverEndpoint.required = !selectedEndpoint" in template
    assert "manualEndpointFields.hidden = Boolean(selectedEndpoint)" in template
    assert "miniserverEndpoint.addEventListener('input', syncTestEndpoint)" in template


def test_miniserver_endpoint_builder_rejects_unsafe_metadata() -> None:
    cgi = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")
    builder = re.search(r"sub miniserver_endpoint \{.*?^\}", cgi, re.MULTILINE | re.DOTALL)

    assert builder is not None
    perl = shutil.which("perl")
    assert perl is not None, "Perl is required for the complete deterministic gate"
    script = f"""
use Socket qw(AF_INET AF_INET6 inet_ntop inet_pton);
{builder.group(0)}
my @cases = (
    {{Transport => 'http', IPAddress => '192.168.1.20', Port => 80}},
    {{Transport => 'http', IPAddress => '192.168.1.20', Port => 8080}},
    {{Transport => 'https', IPAddress => 'miniserver.example', PortHttps => 443}},
    {{Transport => 'https', IPAddress => '2001:db8::1', PortHttps => 8443}},
    {{Transport => 'http', IPAddress => 'fc00:0:0:0:0:0:0:1', Port => 80}},
    {{Transport => 'http', IPAddress => '8.8.8.8', Port => 80}},
    {{Transport => 'http', IPAddress => '999.999.999.999', Port => 80}},
    {{Transport => 'http', IPAddress => '2001:db8::1', Port => 80}},
    {{Transport => 'http', IPAddress => 'host.example', Port => 80}},
    {{Transport => 'https', IPAddress => 'user@host.example', PortHttps => 443}},
    {{Transport => 'https', IPAddress => 'host.example/path', PortHttps => 443}},
    {{Transport => 'https', IPAddress => '2001:::1', PortHttps => 443}},
    {{Transport => 'https', IPAddress => 'host.example', PortHttps => 0}},
);
for my $case (@cases) {{ print((miniserver_endpoint($case) // 'rejected') . "\\n"); }}
"""
    result = subprocess.run([perl, "-e", script], check=True, capture_output=True, text=True)

    assert result.stdout.splitlines() == [
        "http://192.168.1.20",
        "http://192.168.1.20:8080",
        "https://miniserver.example",
        "https://[2001:db8::1]:8443",
        "http://[fc00::1]",
        "rejected",
        "rejected",
        "rejected",
        "rejected",
        "rejected",
        "rejected",
        "rejected",
        "rejected",
    ]


def test_local_mcp_url_builder_handles_hostname_ip_port_and_unsafe_values() -> None:
    cgi = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")
    builder = re.search(r"sub local_mcp_url \{.*?^\}", cgi, re.MULTILINE | re.DOTALL)

    assert builder is not None
    perl = shutil.which("perl")
    assert perl is not None, "Perl is required for the complete deterministic gate"
    script = f"""
use Socket qw(AF_INET AF_INET6 inet_ntop inet_pton);
{builder.group(0)}
my @cases = (
    ['loxberry-test', 443],
    ['loxberry-test', 8443],
    ['192.0.2.10', 443],
    ['2001:db8::1', 8443],
    ['user@host', 443],
    ['host/path', 443],
    ['', 443],
);
for my $case (@cases) {{ print((local_mcp_url(@$case) // '') . "\n"); }}
"""
    result = subprocess.run([perl, "-e", script], check=True, capture_output=True, text=True)

    assert result.stdout.splitlines() == [
        "https://loxberry-test/plugins/mcpserver/mcp",
        "https://loxberry-test:8443/plugins/mcpserver/mcp",
        "https://192.0.2.10/plugins/mcpserver/mcp",
        "https://[2001:db8::1]:8443/plugins/mcpserver/mcp",
        "",
        "",
        "",
    ]


def test_session_expiry_is_rendered_as_a_local_date_and_time() -> None:
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")

    assert 'class="mcp-expiry"' in template
    assert 'data-expires-at="<TMPL_VAR expires_at ESCAPE=HTML>"' in template
    assert "<TMPL_VAR expires_display ESCAPE=HTML>" in template
    assert "new Intl.DateTimeFormat(document.documentElement.lang || undefined" in template
    assert "element.textContent = expiryFormatter.format(date)" in template
    assert "<td><TMPL_VAR expires_at ESCAPE=HTML></td>" not in template


def test_sessions_show_client_name_before_the_stable_instance_identifier() -> None:
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    german = (ROOT / "templates/lang/language_de.ini").read_text(encoding="utf-8")
    english = (ROOT / "templates/lang/language_en.ini").read_text(encoding="utf-8")

    assert template.index("<TMPL_VAR SESSIONS.CLIENT>") < template.index(
        "<TMPL_VAR SESSIONS.INSTANCE>"
    )
    assert "<TMPL_IF client_name><TMPL_VAR client_name ESCAPE=HTML>" in template
    assert "<TMPL_ELSE><TMPL_VAR SESSIONS.UNNAMED>" in template
    assert "INSTANCE=Client-Instanz" in german
    assert "UNNAMED=Unbenannter OAuth-Client" in german
    assert "INSTANCE=Client instance" in english
    assert "UNNAMED=Unnamed OAuth client" in english
    assert "LOXBERRY_APPROVALS=Freigegebene Bindungen für loxberry:read" in german
    assert "LOXBERRY_OPERATE_APPROVALS=Approved bindings for loxberry:operate" in english
    assert "ALLOW_LOXBERRY_READ=loxberry:read freigeben" in german
    assert "ALLOW_LOXBERRY_OPERATE=Allow loxberry:operate" in english
    assert 'id="loxberry-binding-list"' in template
    assert 'id="loxberry-operate-binding-list"' in template
    assert "BINDING_ID=Bindungs-ID" in german
    assert "BINDING_ID=Binding ID" in english
    assert (
        "<TMPL_VAR SESSIONS.SCOPES>"
        not in template[
            template.index('id="loxberry-binding-section"') : template.index('id="diagnostics"')
        ]
    )


def test_perl_expiry_formatter_rejects_out_of_range_values_safely() -> None:
    cgi = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")
    constant = re.search(r"use constant MAX_EXPIRY_EPOCH => [^;]+;", cgi)
    formatter = re.search(r"sub format_expiry \{.*?^\}", cgi, re.MULTILINE | re.DOTALL)

    assert constant is not None
    assert formatter is not None
    perl = shutil.which("perl")
    assert perl is not None, "Perl is required for the complete deterministic gate"
    script = f"""
use POSIX qw(strftime);
{constant.group(0)}
{formatter.group(0)}
for my $value (@ARGV) {{ print format_expiry($value), "\\n"; }}
for my $value ("1" . chr(0x0662), "1" . chr(0xff12)) {{
    print format_expiry($value) eq $value ? "unicode-raw\\n" : "unicode-changed\\n";
}}
print format_expiry(undef), "\\n";
"""
    values = [
        "1900000000",
        "4102444799",
        "4102444800",
        "999999999999999999",
        "-1",
        "1.5",
        " 1",
        "01",
    ]
    result = subprocess.run(
        [perl, "-e", script, *values],
        check=True,
        capture_output=True,
        text=True,
    )
    output = result.stdout.splitlines()

    assert output[0] != values[0]
    assert output[1] != values[1]
    assert output[2:] == [*values[2:], "unicode-raw", "unicode-raw", ""]


def test_browser_expiry_parser_uses_the_same_bounds() -> None:
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    parser = re.search(
        r"const MAX_EXPIRY_EPOCH = .*?^  \};",
        template,
        re.MULTILINE | re.DOTALL,
    )

    assert parser is not None
    node = shutil.which("node")
    assert node is not None, "Node.js is required for the complete deterministic gate"
    values = [
        "1900000000",
        "4102444799",
        "4102444800",
        "999999999999999999",
        "-1",
        "1.5",
        " 1",
        "01",
        "1\u0662",
        "1\uff12",
        "",
    ]
    script = f"""
{parser.group(0)}
console.log(JSON.stringify(process.argv.slice(1).map(parseExpiry)));
"""
    result = subprocess.run(
        [node, "-e", script, *values],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == (
        "[1900000000,4102444799,null,null,null,null,null,null,null,null,null]"
    )
