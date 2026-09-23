from __future__ import annotations

import json
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
    assert "server-timing: mcp-template;dur=" in page.stdout.lower()

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

    notifications_request = "action=page_notifications&ajax=1"
    notifications = subprocess.run(
        common,
        check=True,
        capture_output=True,
        text=True,
        input=notifications_request,
        env={**ajax_environment, "CONTENT_LENGTH": str(len(notifications_request))},
    )
    assert '"ok":true' in notifications.stdout
    assert '"notifications_html"' in notifications.stdout
    assert '"loglist_html"' not in notifications.stdout

    loglist_request = "action=page_loglist&ajax=1"
    loglist = subprocess.run(
        common,
        check=True,
        capture_output=True,
        text=True,
        input=loglist_request,
        env={**ajax_environment, "CONTENT_LENGTH": str(len(loglist_request))},
    )
    assert '"ok":true' in loglist.stdout
    assert '"loglist_html"' in loglist.stdout
    assert '"notifications_html"' not in loglist.stdout
    assert "No native plugin logs are available yet." in loglist.stdout
    assert 'role=\\"status\\"' in loglist.stdout

    populated_loglist = subprocess.run(
        common,
        check=True,
        capture_output=True,
        text=True,
        input=loglist_request,
        env={
            **ajax_environment,
            "CONTENT_LENGTH": str(len(loglist_request)),
            "LB_TEST_LOGLIST_HTML": '<ul id="native-log"><li>admin-ui</li></ul>',
        },
    )
    assert "native-log" in populated_loglist.stdout
    assert "admin-ui" in populated_loglist.stdout
    assert "No native plugin logs are available yet." not in populated_loglist.stdout


def test_admin_ajax_localized_messages_are_utf8(tmp_path: Path) -> None:
    perl = shutil.which("perl")
    if perl is None or os.name == "nt":
        return
    environment = _admin_cgi_environment(tmp_path)
    (tmp_path / "mcpserver-admin").write_text(
        "#!/usr/bin/env perl\n"
        "my $request = <STDIN>;\n"
        "if ($request =~ /emergency_stop_options/) {\n"
        '  print q({"ok":true,"data":{"status":"unavailable","options":[],'
        '"discovery_failure_code":"authentication_busy"}});\n'
        "} else {\n"
        '  print q({"ok":false,"error":{"code":"service_action_failed"}});\n'
        "}\n",
        encoding="utf-8",
    )
    cgi = ROOT / "webfrontend" / "htmlauth" / "index.cgi"
    for action, field, expected in (
        ("emergency_stop_options", "failure_text", "Anmeldung läuft."),
        ("status", "message", "Aktion für Dienst fehlgeschlagen."),
    ):
        request = f"action={action}&ajax=1"
        response = subprocess.run(
            [perl, f"-I{ROOT / 'tests' / 'perl_stubs'}", str(cgi)],
            check=True,
            capture_output=True,
            text=True,
            input=request,
            env={
                **environment,
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": "application/x-www-form-urlencoded",
                "CONTENT_LENGTH": str(len(request)),
                "HTTP_ORIGIN": "https://loxberry.example",
                "HTTP_HOST": "loxberry.example",
            },
        )
        payload = json.loads(response.stdout.partition("\n\n")[2])
        detail = payload["data"] if field == "failure_text" else payload["error"]
        assert detail[field] == expected


def test_initial_page_hydrates_configuration_after_the_visible_shell() -> None:
    cgi = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")

    assert "} elsif ($action eq 'get_config') {" in cgi
    assert "admin_call('get_config', {})" in cgi
    assert "} elsif ($action eq 'page_notifications') {" in cgi
    assert "notifications_html => LoxBerry::Log::get_notifications_html($lbpplugindir) // ''" in cgi
    assert "} elsif ($action eq 'page_loglist') {" in cgi
    assert "loglist_html => native_loglist_html()" in cgi
    assert "my $server_rendered_fallback = ($q->{fallback} // '') eq '1';" in cgi
    assert "if ($server_rendered_fallback) {" in cgi
    assert "my $config_result = admin_call('get_config', {});" in cgi
    assert "my $sessions_result = admin_call('list_sessions', {});" in cgi
    assert "// admin_call('emergency_stop_options', {});" in cgi
    assert "admin_call('page_state', {})" in cgi
    assert "my $service_setting_result = admin_call('service_status', {});" not in cgi
    assert "SERVER_RENDERED_FALLBACK => $server_rendered_fallback" in cgi
    assert "SELECTED_EMERGENCY_STOP => $selected_emergency_stop" in cgi
    assert "body.set('action', 'page_state')" in template
    assert "body.set('action', 'get_config')" in template
    assert "const loadConfiguration = async () =>" in template
    assert "const publicOrigin = String(server.public_origin || '')" in template
    assert "String(loxone.endpoint || miniserverEndpoint.value || '')" in template
    assert "setFormValue(mqttConfigForm, 'mqtt_host', mqtt.host);" in template
    assert "setFormValue(mqttConfigForm, 'mqtt_port', mqtt.port);" in template
    assert "setFormValue(mqttConfigForm, 'mqtt_username', mqtt.username);" in template
    assert "setFormValue(mqttConfigForm, 'mqtt_root_topic', mqtt.root_topic);" in template
    assert (
        "setFormValue(mqttConfigForm, 'mqtt_heartbeat_seconds', mqtt.heartbeat_seconds);"
        in template
    )
    assert "mqtt[name]" not in template
    assert 'id="loxberry-notifications" aria-busy="true" aria-live="polite"' in template
    assert (
        '<span class="mcp-status" data-kind="working"><TMPL_VAR AJAX.NOTIFICATIONS_LOADING>'
        in template
    )
    assert 'id="plugin-log-list" aria-busy="true" aria-live="polite"' in template
    assert '<span class="mcp-status" data-kind="working"><TMPL_VAR AJAX.WORKING>' in template
    assert "const loadLoxberryNotifications = async () =>" in template
    assert "body.set('action', 'page_notifications')" in template
    assert "const loadPluginLogList = async () =>" in template
    assert "body.set('action', 'page_loglist')" in template
    assert "loadLoxberryNotifications," in template
    assert "loadPluginLogList," in template
    assert template.index("loadLoxberryNotifications,") < template.index("loadConfiguration,")
    assert template.index("loadPluginLogList,") > template.index(
        "() => pollSessions({initial: true}),"
    )
    assert "<TMPL_VAR LOGLIST>" not in template
    assert (
        '<noscript><meta http-equiv="refresh" content="0;url='
        '<TMPL_VAR FALLBACK_URL ESCAPE=HTML>"></noscript>' in template
    )
    assert "FALLBACK_CONFIGURATION_LOADED => $fallback_configuration_loaded" in cgi
    assert "NOTIFICATIONS_HTML => $notifications_html" in cgi
    assert "LOGLIST_HTML => $loglist_html" in cgi
    assert "$loglist_html = native_loglist_html();" in cgi
    assert "mcpserver_admin_timing=" in cgi
    assert "component=admin_helper request_id=%s action=%s timing=%s" in cgi
    assert (
        'id="mcp-config-fields" class="mcp-configuration-fields" '
        "<TMPL_UNLESS SERVER_RENDERED_FALLBACK>disabled" in template
    )
    assert (
        'id="mqtt-config-fields" class="mcp-configuration-fields" '
        "<TMPL_UNLESS SERVER_RENDERED_FALLBACK>disabled" in template
    )
    assert (
        'id="logging-config-fields" class="mcp-configuration-fields" '
        "<TMPL_UNLESS SERVER_RENDERED_FALLBACK>disabled" in template
    )
    assert "document.getElementById('logging-config-fields')," in template
    assert "configurationFallbackLink.hidden = false;" in template
    assert (
        "if (<TMPL_IF SERVER_RENDERED_FALLBACK>true<TMPL_ELSE>false</TMPL_IF>) return;" in template
    )
    assert 'id="service-enabled-setting-status"' in template
    assert 'id="mqtt-page-state-status"' in template
    assert 'id="emergency-stop-select"' in template
    assert (
        'aria-describedby="emergency-stop-help emergency-stop-status" disabled aria-busy="true"'
    ) in template
    assert 'name="emergency_stop_virtual_status_uuid"' in template
    assert "EMERGENCY_STOP_OPTIONS => $emergency_stop_options" in cgi
    assert "<TMPL_VAR SETUP.EMERGENCY_STOP_LOADING>" in template
    assert "const loadInitialState" in template
    assert "const backgroundHydrationLimit = 1;" in template
    assert "const backgroundHydrationQueue = [];" in template
    assert "Promise.resolve()" in template
    assert ".then(task)" in template
    assert "loadConfiguration," in template
    assert "loadInitialState," in template
    assert "() => pollServiceStatus({initial: true})," in template
    assert "loadCertificateStatus," in template
    assert "() => pollSessions({initial: true})," in template
    assert (
        "queueBackgroundHydration([() => loadEmergencyStopOptions(emergencyStopGeneration)]);"
        in template
    )
    assert "window.requestAnimationFrame(() => {" in template
    assert "if (document.hidden) {" in template
    assert "scheduleBackgroundHydration();" in template
    assert "let initialBackgroundHydrationComplete = false;" in template
    assert "let pageIsUnloading = false;" in template
    assert "window.addEventListener('beforeunload', markPageUnloading);" in template
    assert "window.addEventListener('pagehide', markPageUnloading);" in template
    assert "if (pageIsUnloading) return;" in template
    assert "if (accessSection.open && initialBackgroundHydrationComplete)" in template
    assert "if (sessionsSection.open && initialBackgroundHydrationComplete)" in template
    assert "const emergencyStopGeneration = emergencyStopDiscoveryGeneration;" in template
    assert "queueBackgroundHydration([" in template
    assert 'id="emergency-stop-refresh"' not in template
    assert "emergencyStopRefresh" not in template
    assert "let emergencyStopDiscoveryGeneration = 0;" in template
    assert "emergencyStopDiscoveryGeneration += 1;" in template
    assert "emergencyStopSelect.disabled = false;" in template
    assert (
        "const loadEmergencyStopOptions = async (" in template
        and "expectedGeneration = emergencyStopDiscoveryGeneration, manualRetry = false" in template
    )
    assert "if (expectedGeneration !== emergencyStopDiscoveryGeneration) return;" in template
    assert "const generation = expectedGeneration;" in template
    assert template.count("if (generation !== emergencyStopDiscoveryGeneration) return;") == 4
    assert "component=admin_ui request_id=%s action=%s duration_ms=%.1f" in cgi
    assert "component=admin_helper request_id=%s action=%s outcome=rejected code=%s" in cgi
    assert "component=admin_ui request_id=%s phase=initial_render duration_ms=%.1f" in cgi
    assert "Server-Timing: mcp-template;dur=%.1f" in cgi
    assert "phase=loxberry_header duration_ms=%.1f" in cgi
    assert "lbheader($L{'BASIC.TITLE'} . \" V$version\", '', '', 'nojqm')" in cgi
    assert 'class="mcp-section-nav"' in template
    assert "mcp-admin-shell-parsed" in template
    assert "mcp-admin-background-hydration-started" in template
    assert "print LoxBerry::Log::get_notifications_html($lbpplugindir);" not in cgi
    assert "my $failure_code = delete $result->{data}{discovery_failure_code};" in cgi
    assert "component=emergency_stop outcome=options_unavailable request_id=%s code=%s" in cgi
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
    assert "if (accessSection.open) loadCertificateStatus();" not in template
    assert "if (sessionsSection.open) pollSessions();" not in template
    assert "serviceSection.setAttribute('aria-busy', 'false');" in template
    assert "sessionsSection.setAttribute('aria-busy', 'false');" in template
    assert "updateCertificate(null);" in template
    assert "let serviceLoaded = false;" in template
    assert "let sessionsLoaded = false;" in template
    assert "if (!sessionsLoaded)" in template
    assert (
        '<div id="session-list"><TMPL_UNLESS SERVER_RENDERED_FALLBACK>'
        '<p class="mcp-status" data-kind="working" role="status">' in template
    )
    assert (
        "<TMPL_ELSE><TMPL_IF SERVER_RENDERED_FALLBACK><p><TMPL_VAR SESSIONS.EMPTY></p>" in template
    )


def test_emergency_stop_selection_is_preserved_while_options_load() -> None:
    cgi = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    german = (ROOT / "templates/lang/language_de.ini").read_text(encoding="utf-8")
    english = (ROOT / "templates/lang/language_en.ini").read_text(encoding="utf-8")

    assert "SELECTED_EMERGENCY_STOP => $selected_emergency_stop" in cgi
    assert 'id="emergency-stop-value" name="emergency_stop_virtual_status_uuid"' in template
    assert 'id="emergency-stop-select"' in template
    assert 'id="emergency-stop-refresh"' not in template
    assert "EMERGENCY_STOP_REFRESH" not in template
    assert "EMERGENCY_STOP_REFRESH" not in german
    assert "EMERGENCY_STOP_REFRESH" not in english
    assert "EMERGENCY_STOP_LOADING=" in german
    assert "EMERGENCY_STOP_LOADING=" in english
    assert "emergencyStopSelect.disabled = false;" in template
    assert "emergencyStopValue.value = emergencyStopSelect.value;" in template
    assert "option.textContent = label;" in template
    assert "EMERGENCY_STOP_LOAD_ERROR" in template
    assert "EMERGENCY_STOP_LOADING" in template
    assert "EMERGENCY_STOP_NO_OPTIONS" in template
    assert "EMERGENCY_STOP_NOT_CONFIGURED" in template
    assert 'id="emergency-stop-retry"' in template
    assert "body.set('action', manualRetry ? 'emergency_stop_retry'" in template
    assert "result.data.failure_text" in template
    assert "retry_not_before" in template
    assert "Number.isInteger(status.pending) && status.pending > 0)" in template
    assert "REMOTE_CLEANUP_WARNING_VISIBLE" in template
    assert "REMOTE_CLEANUP_WARNING ESCAPE=HTML" in template
    assert "REMOTE_CLEANUP_WARNING => $remote_cleanup_warning" in cgi
    assert "authentication_busy => 'EMERGENCY_STOP_AUTH_BUSY'" in cgi
    assert "emergencyStopValue.value = emergencyStopSelect.value;" in template
    for key in (
        "EMERGENCY_STOP_AUTH_SUPPRESSED",
        "EMERGENCY_STOP_AUTH_BUSY",
        "EMERGENCY_STOP_CREDENTIALS_UNAVAILABLE",
        "EMERGENCY_STOP_CONNECTION_FAILED",
        "EMERGENCY_STOP_STRUCTURE_FAILED",
        "EMERGENCY_STOP_RETRY",
    ):
        assert key in german and key in english


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
    assert "const hideSuccess = (element, defer = () => false) =>" in template
    assert "if (element.dataset.kind === 'success') element.hidden = true;" in template
    assert "window.clearTimeout(hideStatusTimers.get(status))" in template
    assert "url.searchParams.delete('notice')" in template
    assert "postAjax(body, actionTimeout(submittedAction))" in template
    assert "save_mcp_config: 90000" in template
    assert "save_mqtt_config: 165000" in template
    assert "result.data.retained_cleanup?.status === 'failed'" in template
    assert "AJAX.MQTT_CLEANUP_WARNING" in template
    assert "revoke_all: 75000" in template
    assert "postAjax(body, 5000)" in template
    assert "new URLSearchParams(new FormData(form))" in template
    assert "const body = new FormData" not in template
    assert "if (result.data.certificate) updateCertificate" in template
    assert 'id="session-table-template"' in template
    assert "row.dataset.fingerprint !== sessionFingerprint(session)" in template
    assert "for (const row of existing.values()) row.remove()" in template


def test_event_history_enablement_is_preserved_in_server_rendered_fallback() -> None:
    cgi = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")

    assert "EVENT_HISTORY_ENABLED => $config->{event_history}{enabled} ? 1 : 0" in cgi
    assert (
        'MCPSERVER_EVENT_HISTORY_STORE} = "$lbpdatadir/event-history/state-events.sqlite3"' in cgi
    )
    assert (
        'name="event_history_enabled" type="checkbox" value="1" '
        "<TMPL_IF EVENT_HISTORY_ENABLED>checked</TMPL_IF>"
    ) in template


def test_server_rendered_emergency_stop_status_is_terminal_after_discovery() -> None:
    cgi = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")

    assert "if (@$emergency_stop_options) {" in cgi
    assert "$emergency_stop_status_visible = 0;" in cgi
    assert "EMERGENCY_STOP_NO_OPTIONS" in cgi
    assert "EMERGENCY_STOP_NOT_CONFIGURED" in cgi
    assert "$options_data->{failure_text}" in cgi
    assert "EMERGENCY_STOP_STATUS_TEXT => $emergency_stop_status_text" in cgi
    assert "EMERGENCY_STOP_STATUS_KIND => $emergency_stop_status_kind" in cgi
    assert "EMERGENCY_STOP_STATUS_VISIBLE => $emergency_stop_status_visible" in cgi
    assert (
        'id="emergency-stop-status" class="mcp-status" '
        'data-kind="<TMPL_VAR EMERGENCY_STOP_STATUS_KIND ESCAPE=HTML>" '
        "<TMPL_UNLESS EMERGENCY_STOP_STATUS_VISIBLE>hidden</TMPL_UNLESS>"
    ) in template
    assert "<TMPL_VAR EMERGENCY_STOP_STATUS_TEXT ESCAPE=HTML>" in template


def test_server_rendered_emergency_stop_retry_uses_one_explicit_probe() -> None:
    cgi = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    german = (ROOT / "templates/lang/language_de.ini").read_text(encoding="utf-8")
    english = (ROOT / "templates/lang/language_en.ini").read_text(encoding="utf-8")

    assert "my $fallback_retry_result;" in cgi
    assert "if ($action eq 'emergency_stop_retry' && ($q->{fallback} // '') eq '1')" in cgi
    assert "$fallback_retry_result = $result;" in cgi
    assert "$fallback_retry_result\n        // admin_call('emergency_stop_options', {});" in cgi
    assert "$emergency_stop_retry_enabled = time() >= $retry_at ? 1 : 0;" in cgi
    assert 'name="fallback" value="1"' in template
    assert 'name="action" value="emergency_stop_retry"' in template
    assert 'form="fallback-emergency-stop-retry-form"' in template
    assert template.index(
        "</form>\n    <TMPL_IF SERVER_RENDERED_FALLBACK>"
        '<form id="fallback-emergency-stop-retry-form"'
    ) > template.index('id="mcp-config-form"')
    assert "<TMPL_UNLESS EMERGENCY_STOP_RETRY_ENABLED>disabled</TMPL_UNLESS>" in template
    assert 'href="index.cgi?fallback=1"' in template
    assert "EMERGENCY_STOP_RELOAD=" in german
    assert "EMERGENCY_STOP_RELOAD=" in english


def test_server_rendered_option_names_escape_unicode_without_raw_bytes() -> None:
    cgi = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    assert "name_html => ascii_html_text($name)" in cgi
    assert "<TMPL_VAR name_html></option>" in template
    assert "<TMPL_VAR name ESCAPE=HTML></option>" not in template

    perl = shutil.which("perl")
    if perl is None:
        return
    helper = re.search(r"(?ms)^sub ascii_html_text \{\n.*?^\}", cgi)
    assert helper is not None
    program = (
        helper.group(0)
        + "\n"
        + 'my $name = chr(0xFC) . q|<script>alert("x")</script> & \'|;\n'
        + "my $escaped = ascii_html_text($name);\n"
        + "utf8::upgrade($name);\n"
        + "die q(Unicode flag changed escaping) if ascii_html_text($name) ne $escaped;\n"
        + "my $source = q|<option><TMPL_VAR NAME_HTML></option>|;\n"
        + "my $template = HTML::Template->new_scalar_ref(\\$source);\n"
        + "$template->param(NAME_HTML => $escaped);\n"
        + "print $template->output();\n"
    )
    result = subprocess.run(
        [perl, "-MHTML::Template", "-e", program],
        check=True,
        capture_output=True,
    )
    assert result.stdout == (
        b"<option>&#xFC;&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; &amp; &#39;</option>"
    )


def test_admin_cards_use_consistent_vertical_spacing() -> None:
    template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    explorer = (ROOT / "templates" / "explorer.html").read_text(encoding="utf-8")
    stylesheet = (ROOT / "webfrontend" / "htmlauth" / "mcp-ui.css").read_text(encoding="utf-8")

    assert 'href="mcp-ui.css?v=<TMPL_VAR VERSION ESCAPE=HTML>-admin-sessions-v3"' in template
    assert '<link rel="stylesheet" href="mcp-ui.css">' in explorer
    assert "<style>" not in template
    assert "<style>" not in explorer
    assert ".mcp-page { display: grid; gap: 1rem;" in stylesheet
    assert ".mcp-field-stack { display: grid; gap: .85rem; }" in stylesheet
    assert ".mcp-explorer { max-width: 92rem;" in stylesheet
    assert '<div class="mcp-field-stack">' in template


def test_admin_top_notices_do_not_leave_empty_grid_rows() -> None:
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    top = template[
        template.index('<main class="mcp-page">') : template.index('<nav class="mcp-section-nav"')
    ]

    assert '<p><a id="configuration-fallback-link"' not in top
    assert '<a id="configuration-fallback-link" href="index.cgi?fallback=1" hidden>' in top
    assert "<TMPL_UNLESS NOTIFICATIONS_HTML>hidden</TMPL_UNLESS>" in top
    assert "loxberryNotifications.hidden = !loxberryNotifications.innerHTML.trim();" in template
    assert "loxberryNotifications.hidden = false;" in template


def test_service_status_is_first_and_uses_a_lightweight_ajax_contract() -> None:
    cgi = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")

    assert template.index('id="status"') < template.index('id="configuration"')
    assert 'data-ajax="service_status"' not in template
    for command in ("start", "stop", "restart"):
        assert f'data-service-command="{command}"' in template
    assert 'data-ajax="set_service_enabled"' in template
    assert "body.set('action', 'service_status')" in template
    assert "window.setTimeout(pollServiceStatus, delay)" in template
    assert "const pollServiceStatus = async ({initial = false} = {}) =>" in template
    assert "(!initial && document.hidden)" in template
    assert "|| serviceInteractionActive() || servicePollInFlight" in template
    assert "document.addEventListener('visibilitychange'" in template
    assert "admin_call('service_status', {})" in cgi
    assert "admin_call('service_action', {command => $command})" in cgi
    assert "admin_call('set_service_enabled', {enabled => $enabled})" in cgi
    assert "$command eq 'start' || $command eq 'stop' || $command eq 'restart'" in cgi
    assert "service.log&header=html&format=template" in cgi


def test_emergency_stop_runtime_display_uses_service_data_not_the_form_selection() -> None:
    cgi = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")

    assert 'id="emergency-stop-runtime"' in template
    assert 'id="emergency-stop-runtime-uuid"' in template
    assert 'id="emergency-stop-runtime-mismatch"' in template
    assert "const renderEmergencyStopRuntime = (runtime) =>" in template
    assert "runtime?.availability === 'available'" in template
    assert "runtime.status" in template
    assert "state === 'not_configured'" in template
    assert "emergencyStopRuntime.dataset.notConfigured" in template
    assert (
        "String(emergencyStopValue.value || '') !== String(runtime.signal_uuid || '')" in template
    )
    assert "emergencyStopRuntime: result.data.emergency_stop_runtime" in template
    assert "scheduleServicePoll(0);" in template
    assert "emergency_stop_runtime" in cgi
    assert "EMERGENCY_STOP_RUNTIME_MISMATCH" in template


def test_sessions_poll_only_while_visible_and_open_and_patch_changed_rows() -> None:
    cgi = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")

    assert "admin_call('list_sessions', {})" in cgi
    assert "body.set('action', 'list_sessions')" in template
    assert "window.setTimeout(pollSessions, delay)" in template
    assert "const pollSessions = async ({initial = false} = {}) =>" in template
    assert "(!initial && (document.hidden || !sessionsSection.open))" in template
    assert "|| activeSessionActions.size > 0 || sessionPollInFlight" in template
    assert "sessionsSection.addEventListener('toggle'" in template
    assert "row.dataset.fingerprint !== sessionFingerprint(session)" in template
    assert "sessionList.replaceChildren(fragment)" in template


def test_session_action_coordinator_allows_only_non_conflicting_actions() -> None:
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    coordinator = re.search(
        r"// session-action-coordinator-start\n(.*?)// session-action-coordinator-end",
        template,
        re.DOTALL,
    )
    assert coordinator is not None
    node = shutil.which("node")
    assert node is not None, "Node.js is required for the complete deterministic gate"
    script = (
        """
let sessionDataVersion = 0;
let nextSessionActionToken = 0;
const activeSessionActions = new Map();
const sessionActionFailures = new Map();
"""
        + coordinator.group(1)
        + """
const descriptor = (action, sessionId = '', bindingId = '') => ({
  action, sessionId, bindingId, key: sessionActionKey(action, sessionId, bindingId),
});
const readA = descriptor('allow_loxberry_read', 'session-a');
const operateA = descriptor('allow_loxberry_operate', 'session-a');
const revokeA = descriptor('revoke_session', 'session-a');
const readB = descriptor('allow_loxberry_read', 'session-b');
const first = beginSessionAction(readA, null);
const operate = beginSessionAction(operateA, null);
const otherSession = beginSessionAction(readB, null);
const result = {
  duplicateBlocked: beginSessionAction(readA, null) === null,
  sameSessionRevokeBlocked: beginSessionAction(revokeA, null) === null,
  readAndOperateAllowed: Boolean(first && operate),
  otherSessionAllowed: Boolean(otherSession),
  revokeAllBlockedWhileActive: beginSessionAction(descriptor('revoke_all'), null) === null,
  bindingRevocationBlockedDuringSessionAction: beginSessionAction(
    descriptor('revoke_loxberry_read', '', 'binding-a'), null,
  ) === null,
  finalFinishOnly: [
    finishSessionAction(operate), finishSessionAction(otherSession), finishSessionAction(first),
  ],
};
for (const token of [...activeSessionActions.keys()]) finishSessionAction(token);

const createForm = (action, sessionId = '', bindingId = '') => {
  const attributes = new Map();
  const button = {
    disabled: false,
    setAttribute: (name, value) => attributes.set(name, value),
    removeAttribute: (name) => attributes.delete(name),
    hasAttribute: (name) => attributes.has(name),
  };
  const rowAttributes = new Set();
  const row = {
    toggleAttribute: (name, enabled) => enabled
      ? rowAttributes.add(name) : rowAttributes.delete(name),
    hasAttribute: (name) => rowAttributes.has(name),
  };
  return {
    button, row,
    form: {
      dataset: {ajax: action},
      closest: (selector) => selector === 'tr' ? row : null,
      querySelector: (selector) => {
        if (selector === 'button[type="submit"]') return button;
        if (selector === 'input[name="id"]') return action === 'revoke_session'
          ? {value: sessionId} : null;
        if (selector === 'input[name="session_id"]') return action === 'revoke_session'
          ? null : {value: sessionId};
        if (selector === 'input[name="binding_id"]') return bindingId
          ? {value: bindingId} : null;
        return null;
      },
    },
  };
};
const readBindingA = createForm('revoke_loxberry_read', '', 'binding-a');
const readBindingB = createForm('revoke_loxberry_read', '', 'binding-b');
const operateBindingA = createForm('revoke_loxberry_operate', '', 'binding-a');
const operateBindingB = createForm('revoke_loxberry_operate', '', 'binding-c');
const sessionForm = createForm('allow_loxberry_read', 'session-c');
const revokeSessionForm = createForm('revoke_session', 'session-d');
const revokeAllForm = createForm('revoke_all');
const forms = [
  readBindingA.form, readBindingB.form, operateBindingA.form, operateBindingB.form,
  sessionForm.form, revokeSessionForm.form, revokeAllForm.form,
];
const document = {querySelectorAll: () => forms};
const bindingA = beginSessionAction(
  sessionActionDescriptor(readBindingA.form), readBindingA.button,
);
updateSessionActionControls();
result.activeBindingBusy = readBindingA.button.disabled
  && readBindingA.button.hasAttribute('aria-busy');
result.activeBindingRowDimmed = readBindingA.row.hasAttribute('data-revoking');
result.otherBindingRowNotDimmed = !readBindingB.row.hasAttribute('data-revoking');
result.blockedSessionRowNotDimmed = !revokeSessionForm.row.hasAttribute('data-revoking');
result.differentReadEnabled = !readBindingB.button.disabled
  && !readBindingB.button.hasAttribute('aria-busy');
result.differentOperateEnabled = !operateBindingB.button.disabled
  && !operateBindingB.button.hasAttribute('aria-busy');
result.sameBindingAcrossScopesBlocked = operateBindingA.button.disabled;
result.revokeAllBlockedDuringBindingRevocation = revokeAllForm.button.disabled;
result.sessionActionBlockedDuringBindingRevocation = sessionForm.button.disabled;
result.duplicateBindingBlocked = beginSessionAction(
  sessionActionDescriptor(readBindingA.form), readBindingA.button,
) === null;
result.sameBindingAcrossScopesRejected = beginSessionAction(
  sessionActionDescriptor(operateBindingA.form), operateBindingA.button,
) === null;
const bindingB = beginSessionAction(
  sessionActionDescriptor(readBindingB.form), readBindingB.button,
);
const operateB = beginSessionAction(
  sessionActionDescriptor(operateBindingB.form), operateBindingB.button,
);
result.differentBindingsAllowed = Boolean(bindingA && bindingB && operateB);
for (const token of [...activeSessionActions.keys()]) finishSessionAction(token);
updateSessionActionControls();
result.controlsRecovered = forms.every(({querySelector}) => {
  const button = querySelector('button[type="submit"]');
  return !button.disabled && !button.hasAttribute('aria-busy');
});
result.bindingRowsRecovered = [readBindingA, readBindingB, operateBindingA, operateBindingB]
  .every(({row}) => !row.hasAttribute('data-revoking'));
const sessionRevoke = beginSessionAction(
  sessionActionDescriptor(revokeSessionForm.form), revokeSessionForm.button,
);
updateSessionActionControls();
result.sessionRowDimmed = revokeSessionForm.row.hasAttribute('data-revoking');
result.otherSessionRowNotDimmed = !sessionForm.row.hasAttribute('data-revoking');
finishSessionAction(sessionRevoke);
updateSessionActionControls();
result.sessionRowRecovered = !revokeSessionForm.row.hasAttribute('data-revoking');
const revokeAll = beginSessionAction(
  sessionActionDescriptor(revokeAllForm.form), revokeAllForm.button,
);
result.revokeAllExclusive = Boolean(revokeAll) && beginSessionAction(readA, null) === null;
result.version = sessionDataVersion;
console.log(JSON.stringify(result));
"""
    )
    result = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)

    assert result.stdout.strip() == (
        '{"duplicateBlocked":true,"sameSessionRevokeBlocked":true,'
        '"readAndOperateAllowed":true,"otherSessionAllowed":true,'
        '"revokeAllBlockedWhileActive":true,'
        '"bindingRevocationBlockedDuringSessionAction":true,'
        '"finalFinishOnly":[false,false,true],'
        '"activeBindingBusy":true,"activeBindingRowDimmed":true,'
        '"otherBindingRowNotDimmed":true,"blockedSessionRowNotDimmed":true,'
        '"differentReadEnabled":true,'
        '"differentOperateEnabled":true,"sameBindingAcrossScopesBlocked":true,'
        '"revokeAllBlockedDuringBindingRevocation":true,'
        '"sessionActionBlockedDuringBindingRevocation":true,'
        '"duplicateBindingBlocked":true,"sameBindingAcrossScopesRejected":true,'
        '"differentBindingsAllowed":true,"controlsRecovered":true,'
        '"bindingRowsRecovered":true,"sessionRowDimmed":true,'
        '"otherSessionRowNotDimmed":true,"sessionRowRecovered":true,'
        '"revokeAllExclusive":true,"version":8}'
    )
    assert "const activeSessionActions = new Map();" in template
    assert "const sessionActionsConflict = (left, right)" in template
    assert "applySuccessfulSessionAction(form, sessionAction, result.data);" in template
    assert "const refreshSessions = finishSessionAction(sessionActionToken);" in template
    assert "if (refreshSessions) scheduleSessionPoll(0);" in template
    assert "let sessionDataVersion = 0;" in template
    assert "const expectedSessionDataVersion = sessionDataVersion;" in template
    assert "if (expectedSessionDataVersion !== sessionDataVersion) return;" in template
    assert (
        "scheduleSessionPoll(expectedSessionDataVersion === sessionDataVersion ? 10000 : 0);"
        in template
    )
    assert "sessionDataVersion += 1;" in coordinator.group(1)
    assert "setSessionActionControlsDisabled" not in template
    assert "sessionActionRunning" not in template
    assert "const result = await postAjax(body, 15000);" in template
    assert "const mergeLoxberryBindings = (bindings) =>" in template
    assert "const mergeLoxberryOperateBindings = (bindings) =>" in template
    assert "const setAjaxStatus = (kind, message) =>" in template
    assert "const sessionActionFailures = new Map();" in template
    assert "const showSessionActionFailure = () =>" in template
    assert "hideSuccess(status, () => activeSessionActions.size > 0);" in template
    assert "return `binding:${bindingId}`;" in template
    assert "if (leftIsBindingRevocation && rightIsBindingRevocation) return true;" not in template
    assert "if (Array.isArray(data.sessions)) updateSessions(data.sessions);" in template
    assert "pendingSessionActionButtons" not in template


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
    assert "sub native_loglist_html" in cgi
    assert "LoxBerry::Web::loglist_html()" in cgi
    assert "DIAGNOSTICS.LOGLIST_EMPTY" in cgi
    assert cgi.count("LoxBerry::Log->new") == 1


def test_empty_native_log_list_has_localized_accessible_status() -> None:
    cgi = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    german = (ROOT / "templates/lang/language_de.ini").read_text(encoding="utf-8")
    english = (ROOT / "templates/lang/language_en.ini").read_text(encoding="utf-8")

    assert "return $html if $html =~ /\\S/;" in cgi
    assert '<p class="mcp-status" role="status">%s</p>' in cgi
    assert "LOGLIST_EMPTY=Es sind noch keine nativen Plugin-Logs verfügbar." in german
    assert "LOGLIST_EMPTY=No native plugin logs are available yet." in english
    assert 'id="plugin-log-list" aria-busy="true" aria-live="polite"' in template


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
    assert "lastService = service;\n    serviceLoaded = true;" in template
    assert "emergencyStopRuntime: result.data.emergency_stop_runtime" in template
    assert "let serviceEnabledSetting = serviceEnabledInput.checked" in template
    assert (
        "let serviceEnabledSettingLoaded = serviceEnableForm.dataset."
        "serviceEnabledSettingKnown === '1'" in template
    )
    assert "serviceEnabledSetting = enabled" in template
    assert "serviceEnabledSettingLoaded = true" in template
    assert "serviceEnabledInput.checked = enabled" in template
    assert "if (updateEnabledSetting || !serviceEnabledSettingLoaded)" in template
    assert (
        "serviceEnabledInput.disabled = serviceActionRunning || !serviceEnabledSettingLoaded"
        in template
    )
    assert "serviceEnabled.textContent = '<TMPL_VAR AJAX.ERROR ESCAPE=JS>';" in template
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
    cgi = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")

    assert 'href="mcp-ui.css?v=<TMPL_VAR VERSION ESCAPE=HTML>-admin-sessions-v3"' in template
    expected_sections = [
        ("status", "STATUS.TITLE"),
        ("configuration", "SETUP.TITLE"),
        ("access", "ACCESS.TITLE"),
        ("sessions", "SESSIONS.TITLE"),
        ("mqtt", "MQTT.TITLE"),
        ("diagnostics", "DIAGNOSTICS.TITLE"),
        ("help", "HELP.TITLE"),
    ]
    for section, label_key in expected_sections:
        assert f'<details id="{section}" class="mcp-card" data-persist-collapse' in template
        section_markup = template[template.index(f'id="{section}"') :]
        assert re.search(
            rf"<summary(?: [^>]*)?>.*?<TMPL_VAR {re.escape(label_key)}",
            section_markup,
            re.DOTALL,
        )
    assert '<details id="status" class="mcp-card" data-persist-collapse open' in template
    assert '<details id="configuration" class="mcp-card" data-persist-collapse open' in template
    assert "mcpserver.admin.sections.v2" in template
    assert "const storedCollapseState = readCollapseState();" in template
    assert "window.localStorage.setItem(collapseStorageKey" in template
    assert "element.addEventListener('toggle', persistCollapsibles)" in template
    assert "window.addEventListener('hashchange', () => openHashSection())" in template
    assert "target instanceof HTMLDetailsElement" in template
    navbar = template[template.index('<nav class="mcp-section-nav"') : template.index("</nav>")]
    assert 'aria-label="<TMPL_VAR NAV.SECTIONS ESCAPE=HTML>"' in navbar
    assert (
        re.findall(r'<a href="#([^"]+)"><TMPL_VAR ([A-Z.]+) ESCAPE=HTML></a>', navbar)
        == expected_sections
    )
    assert "our %navbar" not in cgi
    assert re.findall(
        r'<details id="([^"]+)" class="mcp-card" data-persist-collapse', template
    ) == [section for section, _label_key in expected_sections]
    for section in ("access", "sessions", "diagnostics", "help"):
        assert re.search(
            rf'<details id="{section}" class="mcp-card" data-persist-collapse '
            r"<TMPL_IF SERVER_RENDERED_FALLBACK>open</TMPL_IF>",
            template,
        )


def test_admin_collapse_state_preserves_existing_preferences() -> None:
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    migration = re.search(
        r"// collapse-state-migration-start\n(.*?)// collapse-state-migration-end",
        template,
        re.DOTALL,
    )
    assert migration is not None
    node = shutil.which("node")
    assert node is not None, "Node.js is required for the complete deterministic gate"
    script = (
        "const assert = require('node:assert/strict');\n"
        "const collapseStorageKey = 'mcpserver.admin.sections.v2';\n"
        + migration.group(1)
        + """
const storage = (values) => ({ getItem: (key) => values[key] ?? null });
const read = (values) => {
  global.window = { localStorage: storage(values) };
  return readCollapseState();
};
assert.deepEqual(read({
  'mcpserver.admin.sections.v1': JSON.stringify({
    status: false, setup: false, certificate: true, sessions: true, mqtt: false, help: true,
  }),
}), {
  status: false, setup: false, certificate: true, sessions: true, mqtt: false, help: true,
  configuration: false, access: true,
});
assert.deepEqual(read({
  'mcpserver.admin.sections.v1': JSON.stringify({ setup: false }),
  'mcpserver.admin.sections.v2': JSON.stringify({ configuration: true, access: false }),
}), { configuration: true, access: false });
assert.equal(read({
  'mcpserver.admin.sections.v1': JSON.stringify({ help: true, certificate: false }),
}).access, true);
assert.equal(read({
  'mcpserver.admin.sections.v1': JSON.stringify({ help: false, certificate: false }),
}).access, false);
assert.deepEqual(read({
  'mcpserver.admin.sections.v1': 'null',
}), {});
assert.deepEqual(read({
  'mcpserver.admin.sections.v1': '{',
}), {});
global.window = { localStorage: { getItem: () => { throw new Error('disabled'); } } };
assert.deepEqual(readCollapseState(), {});
global.window = {};
Object.defineProperty(window, 'localStorage', { get: () => { throw new Error('disabled'); } });
assert.deepEqual(readCollapseState(), {});
"""
    )
    subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)


def test_admin_hash_navigation_preserves_closed_reload_and_opens_new_links() -> None:
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    navigation = template[
        template.index("  const openHashSection =") : template.index("  const miniserverSelect =")
    ]
    node = shutil.which("node")
    assert node is not None, "Node.js is required for the complete deterministic gate"
    script = (
        "const assert = require('node:assert/strict');\n"
        "class HTMLDetailsElement { constructor() { this.open = false; } }\n"
        "class Element { closest() { return { hash: '#access' }; } }\n"
        "const section = new HTMLDetailsElement();\n"
        "const configuration = new HTMLDetailsElement();\n"
        "const mqtt = new HTMLDetailsElement();\n"
        "const status = new HTMLDetailsElement();\n"
        "const sessions = new HTMLDetailsElement();\n"
        "const diagnostics = new HTMLDetailsElement();\n"
        "const help = new HTMLDetailsElement();\n"
        "const storedCollapseState = {mqtt: false};\n"
        "const listeners = {};\n"
        "const window = { location: { hash: '#mqtt' }, "
        "performance: {getEntriesByType: () => [{type: 'reload'}]}, "
        "addEventListener: (type, callback) => { listeners[type] = callback; } };\n"
        "const document = { getElementById: (id) => "
        "({ access: section, configuration, mqtt, status, "
        "sessions, diagnostics, help })[id] || null, "
        "addEventListener: (type, callback) => { listeners[type] = callback; } };\n"
        "let persistCount = 0;\n"
        "const persistCollapsibles = () => { persistCount += 1; };\n"
        + navigation
        + """
assert.equal(mqtt.open, false);
listeners.click({ target: new Element() });
assert.equal(section.open, true);
section.open = false;
window.location.hash = '#access';
listeners.hashchange({ type: 'hashchange' });
assert.equal(section.open, true);
window.location.hash = '#setup';
listeners.hashchange({ type: 'hashchange' });
assert.equal(configuration.open, true);
section.open = false;
window.location.hash = '#certificate';
listeners.hashchange({ type: 'hashchange' });
assert.equal(section.open, true);
assert.equal(persistCount, 4);
openHashSection('#mqtt', true);
assert.equal(mqtt.open, false);
assert.equal(persistCount, 4);
openHashSection('#mqtt');
assert.equal(mqtt.open, true);
assert.equal(persistCount, 5);
storedCollapseState.mqtt = true;
mqtt.open = false;
openHashSection('#mqtt', true);
assert.equal(mqtt.open, true);
assert.equal(persistCount, 6);
for (const id of ['status', 'configuration', 'access', 'sessions', 'mqtt', 'diagnostics', 'help']) {
  const target = document.getElementById(id);
  target.open = false;
  storedCollapseState[id] = false;
  const before = persistCount;
  openHashSection(`#${id}`, true);
  assert.equal(target.open, false, `${id} reopens on reload`);
  assert.equal(persistCount, before);
  openHashSection(`#${id}`);
  assert.equal(target.open, true, `${id} does not open on a new link`);
  assert.equal(persistCount, before + 1);
}
configuration.open = false;
section.open = false;
openHashSection('#setup', true);
openHashSection('#certificate', true);
assert.equal(configuration.open, false);
assert.equal(section.open, false);
openHashSection('#setup');
openHashSection('#certificate');
assert.equal(configuration.open, true);
assert.equal(section.open, true);
"""
    )
    subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)


def test_admin_access_section_groups_connection_urls_and_certificate_controls() -> None:
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")

    access = template[template.index('id="access"') : template.index('id="sessions"')]
    help_section = template[template.index('id="help"') : template.index("</main>")]
    assert 'id="mcp-url-hostname"' in access
    assert 'id="mcp-url-ip"' in access
    assert 'id="certificate-panel"' in access
    assert 'data-state-idle="<TMPL_VAR CERTIFICATE.STATE_IDLE ESCAPE=HTML>"' in access
    assert "idle: certificatePanel.dataset.stateIdle," in template
    assert 'data-ajax="renew_certificate"' in access
    assert 'id="explorer-link"' not in access
    assert 'id="schema-reference-link"' not in access
    assert 'id="explorer-link"' in help_section
    assert 'id="schema-reference-link"' in help_section
    assert '<summary id="setup"><TMPL_VAR SETUP.TITLE>' in template
    assert '<summary id="certificate"><TMPL_VAR ACCESS.TITLE>' in template
    assert '<details id="setup"' not in template
    assert '<details id="certificate"' not in template
    assert "const accessSection = document.getElementById('access');" in template
    assert "const certificatePanel = document.getElementById('certificate-panel');" in template


def test_certificate_idle_status_does_not_use_failure_label() -> None:
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    labels = re.search(
        r"  const certificateStateLabels = certificatePanel \? \{.*?\} : \{\};",
        template,
        re.DOTALL,
    )
    assert labels is not None
    assert 'data-state-idle="<TMPL_VAR CERTIFICATE.STATE_IDLE ESCAPE=HTML>"' in template
    node = shutil.which("node")
    assert node is not None, "Node.js is required for the complete deterministic gate"
    script = (
        "const assert = require('node:assert/strict');\n"
        "const certificatePanel = {dataset: {stateIdle: 'Not started', "
        "stateError: 'Reissue failed'}};\n"
        + labels.group(0)
        + "\nassert.equal(certificateStateLabels.idle, 'Not started');\n"
        "assert.notEqual(certificateStateLabels.idle, certificateStateLabels.error);\n"
    )
    subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)


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
    assert template.count("syncOperateDependency();") == 2


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
    assert (
        "<TMPL_UNLESS SERVER_RENDERED_FALLBACK><TMPL_UNLESS MANUAL_ENDPOINT>"
        "hidden</TMPL_UNLESS></TMPL_UNLESS>" in template
    )
    assert 'id="miniserver-endpoint"' in template
    assert (
        "<TMPL_UNLESS SERVER_RENDERED_FALLBACK><TMPL_IF MANUAL_ENDPOINT>"
        "required<TMPL_ELSE>readonly</TMPL_IF></TMPL_UNLESS>" in template
    )
    assert "miniserverEndpoint.readOnly = Boolean(selectedEndpoint)" in template
    assert "miniserverEndpoint.required = !selectedEndpoint" in template
    assert "manualEndpointFields.hidden = Boolean(selectedEndpoint)" in template
    assert (
        "const submittedAction = form === mcpConfigForm ? button.value : form.dataset.ajax"
        in template
    )


def test_status_and_progressive_configuration_keep_existing_form_contracts() -> None:
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    german = (ROOT / "templates/lang/language_de.ini").read_text(encoding="utf-8")
    english = (ROOT / "templates/lang/language_en.ini").read_text(encoding="utf-8")

    status = template[template.index('<details id="status"') : template.index("</details>")]
    assert status.count('id="service-enable-form"') == 1
    assert status.index('id="service-enable-form"') < status.index('id="service-actions"')
    assert 'data-ajax="set_service_enabled"' in status
    assert 'name="service_enabled"' in status
    assert "SERVICE_ENABLED_SETTING_KNOWN" in status
    assert "STATUS.ENABLED_SETTING" in status

    configuration = template[
        template.index('id="mcp-config-form"') : template.index(
            'id="fallback-emergency-stop-retry-form"'
        )
    ]
    advanced = configuration[configuration.index('<details class="mcp-persistent-section">') :]
    assert configuration.count('<details class="mcp-persistent-section">') == 1
    assert configuration.index("SETUP.CONNECTION") < configuration.index("SETUP.ACCESS_SAFETY")
    assert configuration.index("SETUP.ACCESS_SAFETY") < configuration.index("SETUP.PERMISSIONS")
    assert configuration.index("SETUP.PERMISSIONS") < configuration.index("SETUP.ADVANCED_SETTINGS")
    assert configuration.index('name="event_history_enabled"') < configuration.index(
        "SETUP.ADVANCED_SETTINGS"
    )
    for name in (
        "connection_timeout",
        "max_parallel_calls",
        "requests_per_minute",
        "control_requests_per_minute",
        "loxberry_requests_per_minute",
        "history_requests_per_minute",
        "loxberry_operate_requests_per_minute",
        "explorer_binding_retention_hours",
        "structure_refresh_seconds",
        "max_active_runtime_sessions",
        "runtime_session_idle_seconds",
        "max_structure_controls",
        "max_structure_state_references",
        "max_structure_depth",
        "max_states_per_identity",
        "statistics_memory_max_mib",
        "event_history_retention_days",
        "event_history_maximum_mib",
    ):
        assert configuration.count(f'name="{name}"') == 1
        assert f'name="{name}"' in advanced
        assert re.search(rf'name="{name}" type="number" min="\d+" max="\d+"', advanced)
    assert 'name="action" value="save_mcp_config"' in configuration
    assert 'name="action" value="test_connection" formnovalidate' in configuration
    assert configuration.index('name="action" value="test_connection"') < configuration.index(
        "SETUP.ACCESS_SAFETY"
    )
    assert 'id="test-connection-fields"' not in template
    assert "if (form === mcpConfigForm) body.set('action', submittedAction)" in template
    assert "if (submittedAction === 'save_mcp_config')" in template
    for key in (
        "CONNECTION",
        "ACCESS_SAFETY",
        "PERMISSIONS",
        "ADVANCED_SETTINGS",
        "ADVANCED_CONNECTION",
        "ADVANCED_RATES",
        "ENABLED_SETTING",
    ):
        assert re.search(rf"^{key}=", german, re.MULTILINE)
        assert re.search(rf"^{key}=", english, re.MULTILINE)


def test_connection_test_uses_unsaved_form_endpoint_in_fallback() -> None:
    cgi = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    endpoint_function = re.search(r"sub requested_endpoint \{.*?^\}", cgi, re.MULTILINE | re.DOTALL)
    assert endpoint_function is not None
    assert 'name="miniserver_endpoint"' in template
    assert 'name="endpoint" type="url"' in template
    assert 'name="action" value="test_connection" formnovalidate' in template
    assert "$result = admin_call('test_connection', {endpoint => requested_endpoint($q)})" in cgi
    assert (
        'id="manual-endpoint-fields" class="mcp-manual-endpoint" '
        "<TMPL_UNLESS SERVER_RENDERED_FALLBACK>" in template
    )
    perl = shutil.which("perl")
    assert perl is not None
    script = (
        f"{endpoint_function.group(0)}\n"
        "print requested_endpoint({miniserver_endpoint => 'https://unsaved-selected', "
        "endpoint => 'https://saved'}), \"\\n\";\n"
        "print requested_endpoint({miniserver_endpoint => '', "
        "endpoint => 'https://unsaved-manual'}), \"\\n\";\n"
    )
    result = subprocess.run([perl, "-e", script], capture_output=True, text=True, check=True)
    assert result.stdout.splitlines() == ["https://unsaved-selected", "https://unsaved-manual"]


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


def test_session_tables_have_matching_mobile_labels_in_fallback_and_ajax_rows() -> None:
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    css = (ROOT / "webfrontend/htmlauth/mcp-ui.css").read_text(encoding="utf-8")
    assert template.count('class="mcp-table mcp-session-table"') == 4
    assert template.count('class="mcp-table-wrap mcp-session-table-wrap"') == 4

    cases = (
        (
            "<TMPL_LOOP SESSIONS><tr",
            "const createSessionRow =",
            "const updateSessions =",
            ("CLIENT", "INSTANCE", "IDENTITY", "TOKEN", "SCOPES", "EXPIRES", "ACTION"),
        ),
        (
            "<TMPL_LOOP LOXBERRY_BINDINGS><TMPL_LOOP rows><tr",
            "const loxberryBindingRows =",
            "const updateLoxberryBindingTable =",
            ("CLIENT", "INSTANCE", "IDENTITY", "BINDING_ID", "ACTION"),
        ),
        (
            "<TMPL_LOOP LOXBERRY_OPERATE_BINDINGS><TMPL_LOOP rows><tr",
            "const loxberryBindingRows =",
            "const updateLoxberryBindingTable =",
            ("CLIENT", "INSTANCE", "IDENTITY", "BINDING_ID", "ACTION"),
        ),
    )
    for fallback_start, js_start, js_end, expected in cases:
        row = template[template.index(fallback_start) :]
        row = row[: row.index("</tr>")]
        fallback_labels = re.findall(
            r'<td data-label="<TMPL_VAR SESSIONS\.(\w+) ESCAPE=HTML>"', row
        )
        js = template[template.index(js_start) : template.index(js_end)]
        js_labels = re.findall(r"dataset\.label = '<TMPL_VAR SESSIONS\.(\w+) ESCAPE=JS>'", js)
        if js_start == "const createSessionRow =":
            leading = js[
                js.index("const labels = [") : js.index("];", js.index("const labels = ["))
            ]
            js_labels = re.findall(r"SESSIONS\.(\w+) ESCAPE=JS", leading) + js_labels
        assert tuple(fallback_labels) == expected
        assert tuple(js_labels) == expected

    assert "@media (max-width: 48rem)" in css
    assert ".mcp-permission-table td, .mcp-permission-table td:first-child { width: 100%;" in css
    assert "#sessions .mcp-session-table-wrap { box-sizing: border-box; width: 100%;" in css
    assert '#sessions form[data-ajax^="revoke"] .lb-button' in css
    assert "#sessions .mcp-session-table tr[data-revoking] { opacity: .55; }" in css
    assert "data-session-token-state" in template
    assert "const updateSessionActionControls = () =>" in template


def test_explorer_approval_retention_and_inactive_states_are_visible_in_both_languages() -> None:
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    cgi = (ROOT / "webfrontend/htmlauth/index.cgi").read_text(encoding="utf-8")
    german = (ROOT / "templates/lang/language_de.ini").read_text(encoding="utf-8")
    english = (ROOT / "templates/lang/language_en.ini").read_text(encoding="utf-8")

    assert 'name="explorer_binding_retention_hours" type="number" min="1" max="720"' in template
    assert "bindingRow.inactive_login_required" in template
    assert "bindingRow.retention_expires_at" in template
    assert "explorer_binding_retention_hours => 0 +" in cgi
    assert "INACTIVE_LOGIN_REQUIRED=Inaktiv — erneute Anmeldung erforderlich" in german
    assert "LEGACY_INACTIVE=Legacy inactive approval" in english
    assert "OAuth-Sitzung trennen" in german
    assert "Disconnect OAuth session" in english


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
