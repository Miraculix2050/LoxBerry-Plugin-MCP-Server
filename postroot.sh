#!/bin/bash
set -u

marker="# Managed by the LoxBerry MCP Server plugin."
unit=/etc/systemd/system/loxberry-mcpserver.service
apache=/etc/apache2/conf-available/loxberry-mcpserver.conf
sudoers=/etc/sudoers.d/loxberry-mcpserver
certificate_helper=/usr/local/sbin/loxberry-mcpserver-renew-web-certificate

actual_folder=$3
installer_root=${6:-}
if [ -z "$actual_folder" ] || [ -z "$installer_root" ] || [ -z "${LBHOMEDIR:-}" ] || [ -z "${LBPCONFIG:-}" ] || [ -z "${LBPDATA:-}" ] || [ -z "${LBPLOG:-}" ]; then
    echo "<ERROR> LoxBerry plugin paths are unavailable."
    exit 2
fi
case "$LBHOMEDIR" in
    /*) ;;
    *) echo "<ERROR> Invalid LoxBerry home directory."; exit 2 ;;
esac
case "$LBHOMEDIR" in
    *[!A-Za-z0-9_./-]*) echo "<ERROR> Invalid LoxBerry home directory."; exit 2 ;;
esac
loxberry_home=$(realpath -e -- "$LBHOMEDIR") || { echo "<ERROR> Invalid LoxBerry home directory."; exit 2; }
case "$loxberry_home" in
    /|*[!A-Za-z0-9_./-]*) echo "<ERROR> Invalid LoxBerry home directory."; exit 2 ;;
esac
if [ ! -d "$loxberry_home/libs/perllib" ]; then
    echo "<ERROR> LoxBerry Perl libraries are unavailable."
    exit 2
fi
case "$actual_folder" in
    *[!A-Za-z0-9_-]*|'') echo "<ERROR> Invalid plugin folder."; exit 2 ;;
esac
case "$installer_root" in
    /*) ;;
    *) echo "<ERROR> Invalid installer root."; exit 2 ;;
esac
installer_root=$(realpath -e -- "$installer_root") || { echo "<ERROR> Invalid installer root."; exit 2; }
if [ ! -d "$installer_root" ] || [ ! -f "$installer_root/config/systemd/loxberry-mcpserver.service.in" ] \
    || [ ! -f "$installer_root/config/apache/mcpserver.conf" ] \
    || [ ! -f "$installer_root/bin/renew-web-certificate" ] \
    || [ ! -f "$installer_root/bin/root-lifecycle-paths.py" ]; then
    echo "<ERROR> Required package templates are unavailable."
    exit 2
fi
plugin_config="$LBPCONFIG/$actual_folder"
plugin_data="$LBPDATA/$actual_folder"
plugin_log="$LBPLOG/$actual_folder"
service_log="$plugin_log/service.log"
root_path_helper="$installer_root/bin/root-lifecycle-paths.py"
preserve_disabled_service=0

# A new installation starts enabled. During an upgrade, preserve an explicit
# administrator choice to keep the unit disabled across package replacement.
if [ -f "$unit" ] && grep -Fqx "$marker" "$unit" \
    && ! systemctl is-enabled --quiet loxberry-mcpserver.service; then
    preserve_disabled_service=1
fi

for target in "$unit" "$apache" "$sudoers" "$certificate_helper"; do
    if [ -e "$target" ] && ! grep -Fqx "$marker" "$target"; then
        echo "<ERROR> Refusing to overwrite foreign file $target."
        exit 2
    fi
done

if ss -H -ltn 'sport = :8765' | grep -q . && ! systemctl is-active --quiet loxberry-mcpserver.service; then
    echo "<ERROR> TCP port 8765 is already owned by another service."
    exit 2
fi
if grep -RIl --exclude='loxberry-mcpserver.conf' '/plugins/mcpserver/mcp' /etc/apache2 2>/dev/null | grep -q .; then
    echo "<ERROR> Another Apache configuration already owns /plugins/mcpserver/mcp."
    exit 2
fi

key="$plugin_data/auth/install.key"
python3 "$root_path_helper" statistics-cache --home "$loxberry_home" --folder "$actual_folder" || exit 2
python3 "$root_path_helper" install-key --home "$loxberry_home" --folder "$actual_folder" || exit 2

host=$(hostname -f 2>/dev/null || hostname)
case "$host" in
    *[!A-Za-z0-9.-]*|'') echo "<ERROR> Invalid local hostname."; exit 2 ;;
esac
local_ip=$(perl -I"$loxberry_home/libs/perllib" -MLoxBerry::System -e \
    'print LoxBerry::System::get_localip()' 2>/dev/null)
case "$local_ip" in
    *[!0-9A-Fa-f:.]*|'') echo "<ERROR> Invalid local IP address."; exit 2 ;;
esac
if [[ "$local_ip" == *:* ]]; then
    local_ip_host="[$local_ip]"
else
    local_ip_host="$local_ip"
fi

sed \
    -e "s|@CONFIG@|$plugin_config/mcpserver.json|g" \
    -e "s|@SESSIONS@|$plugin_data/auth/sessions.json|g" \
    -e "s|@TOKENS@|$plugin_data/auth/loxone-tokens.json.enc|g" \
    -e "s|@KEY@|$key|g" \
    -e "s|@HOST@|$host|g" \
    -e "s|@LOCAL_IP_HOST@|$local_ip_host|g" \
    -e "s|@VENV@|$plugin_data/venv|g" \
    -e "s|@CONFIG_DIR@|$plugin_config|g" \
    -e "s|@DATA_DIR@|$plugin_data|g" \
    -e "s|@LOG_DIR@|$plugin_log|g" \
    "$installer_root/config/systemd/loxberry-mcpserver.service.in" > "$unit" || exit 2

cp "$installer_root/config/apache/mcpserver.conf" "$apache" || exit 2
chown root:root "$unit" "$apache"
chmod 644 "$unit" "$apache"
certificate_helper_tmp=$(mktemp "${certificate_helper}.tmp.XXXXXX") || exit 2
if ! sed "s|@LBHOMEDIR@|$loxberry_home|g" \
    "$installer_root/bin/renew-web-certificate" > "$certificate_helper_tmp" \
    || ! chown root:root "$certificate_helper_tmp" \
    || ! chmod 755 "$certificate_helper_tmp" \
    || ! mv -f "$certificate_helper_tmp" "$certificate_helper"; then
    rm -f "$certificate_helper_tmp"
    exit 2
fi
{
    echo "$marker"
    echo 'loxberry ALL=(root) NOPASSWD: /bin/systemctl start loxberry-mcpserver.service'
    echo 'loxberry ALL=(root) NOPASSWD: /bin/systemctl stop loxberry-mcpserver.service'
    echo 'loxberry ALL=(root) NOPASSWD: /bin/systemctl restart loxberry-mcpserver.service'
    echo 'loxberry ALL=(root) NOPASSWD: /bin/systemctl enable loxberry-mcpserver.service'
    echo 'loxberry ALL=(root) NOPASSWD: /bin/systemctl disable loxberry-mcpserver.service'
    echo 'loxberry ALL=(root) NOPASSWD: /bin/systemctl is-active --quiet loxberry-mcpserver.service'
    echo 'loxberry ALL=(root) NOPASSWD: /usr/local/sbin/loxberry-mcpserver-renew-web-certificate ""'
} > "$sudoers"
chmod 440 "$sudoers"
visudo -cf "$sudoers" >/dev/null || { rm -f "$sudoers"; exit 2; }

a2enmod proxy proxy_http >/dev/null || exit 2
a2enconf loxberry-mcpserver >/dev/null || exit 2
apache2ctl configtest >/dev/null || { a2disconf loxberry-mcpserver >/dev/null; exit 2; }

if systemctl is-active --quiet loxberry-mcpserver.service; then
    systemctl stop loxberry-mcpserver.service || exit 2
fi
python3 "$root_path_helper" service-log --home "$loxberry_home" --folder "$actual_folder" || exit 2

systemctl daemon-reload
if [ "$preserve_disabled_service" -eq 1 ]; then
    systemctl disable loxberry-mcpserver.service >/dev/null
    echo "<INFO> Service remains disabled after upgrade."
else
    systemctl enable loxberry-mcpserver.service >/dev/null
    systemctl restart loxberry-mcpserver.service || exit 2
    service_ready=0
    for _ in {1..30}; do
        if curl --fail --silent --max-time 2 http://127.0.0.1:8765/healthz >/dev/null; then
            service_ready=1
            break
        fi
        sleep 1
    done
    if [ "$service_ready" -ne 1 ]; then
        echo "<ERROR> Service did not become healthy after installation."
        exit 2
    fi
fi
systemctl reload apache2
echo "<OK> Service and Apache proxy installed."
exit 0
