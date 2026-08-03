#!/bin/bash
set -u

marker="# Managed by the LoxBerry MCP Server plugin."
unit=/etc/systemd/system/loxberry-mcpserver.service
apache=/etc/apache2/conf-available/loxberry-mcpserver.conf
sudoers=/etc/sudoers.d/loxberry-mcpserver

systemctl disable --now loxberry-mcpserver.service >/dev/null 2>&1 || true
a2disconf loxberry-mcpserver >/dev/null 2>&1 || true
for target in "$unit" "$apache" "$sudoers"; do
    if [ -f "$target" ] && grep -Fqx "$marker" "$target"; then
        rm -f -- "$target"
    fi
done
systemctl daemon-reload
systemctl reload apache2 >/dev/null 2>&1 || true
echo "<OK> External LoxBerry MCP Server artifacts removed."
exit 0
