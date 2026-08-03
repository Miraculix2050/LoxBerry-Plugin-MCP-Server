#!/bin/bash
set -u

marker="# Managed by the LoxBerry MCP Server plugin."
unit=/etc/systemd/system/loxberry-mcpserver.service
apache=/etc/apache2/conf-available/loxberry-mcpserver.conf
sudoers=/etc/sudoers.d/loxberry-mcpserver

actual_folder=$3
if [ -z "$actual_folder" ] || [ -z "${LBPBIN:-}" ] || [ -z "${LBPCONFIG:-}" ] || [ -z "${LBPDATA:-}" ] || [ -z "${LBPLOG:-}" ]; then
    echo "<ERROR> LoxBerry plugin paths are unavailable."
    exit 2
fi
plugin_config="$LBPCONFIG/$actual_folder"
plugin_data="$LBPDATA/$actual_folder"
plugin_log="$LBPLOG/$actual_folder"

for target in "$unit" "$apache" "$sudoers"; do
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
mkdir -p "$plugin_data/auth"
if [ ! -f "$key" ]; then
    (umask 0137 && openssl rand 32 > "$key") || exit 2
fi
chown root:loxberry "$key"
chmod 640 "$key"

host=$(hostname -f 2>/dev/null || hostname)
case "$host" in
    *[!A-Za-z0-9.-]*|'') echo "<ERROR> Invalid local hostname."; exit 2 ;;
esac

sed \
    -e "s|@CONFIG@|$plugin_config/mcpserver.json|g" \
    -e "s|@SESSIONS@|$plugin_data/auth/sessions.json|g" \
    -e "s|@TOKENS@|$plugin_data/auth/loxone-tokens.json.enc|g" \
    -e "s|@KEY@|$key|g" \
    -e "s|@HOST@|$host|g" \
    -e "s|@VENV@|$plugin_data/venv|g" \
    -e "s|@CONFIG_DIR@|$plugin_config|g" \
    -e "s|@DATA_DIR@|$plugin_data|g" \
    -e "s|@LOG_DIR@|$plugin_log|g" \
    "$plugin_config/systemd/loxberry-mcpserver.service.in" > "$unit" || exit 2

cp "$plugin_config/apache/mcpserver.conf" "$apache" || exit 2
chown root:root "$unit" "$apache"
chmod 644 "$unit" "$apache"
{
    echo "$marker"
    echo 'loxberry ALL=(root) NOPASSWD: /bin/systemctl restart loxberry-mcpserver.service'
    echo 'loxberry ALL=(root) NOPASSWD: /bin/systemctl is-active --quiet loxberry-mcpserver.service'
} > "$sudoers"
chmod 440 "$sudoers"
visudo -cf "$sudoers" >/dev/null || { rm -f "$sudoers"; exit 2; }

a2enmod proxy proxy_http >/dev/null || exit 2
a2enconf loxberry-mcpserver >/dev/null || exit 2
apache2ctl configtest >/dev/null || { a2disconf loxberry-mcpserver >/dev/null; exit 2; }
systemctl daemon-reload
systemctl enable loxberry-mcpserver.service >/dev/null
systemctl restart loxberry-mcpserver.service
systemctl reload apache2
echo "<OK> Service and Apache proxy installed."
exit 0
