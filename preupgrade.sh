#!/bin/bash
set -u

actual_folder=$3
installer_root=${6:-}
if [ -z "$actual_folder" ] || [ -z "$installer_root" ] || [ -z "${LBPCONFIG:-}" ] || [ -z "${LBPDATA:-}" ]; then
    echo "<ERROR> LoxBerry plugin paths are unavailable."
    exit 2
fi

if systemctl is-active --quiet loxberry-mcpserver.service; then
    if ! sudo -n /bin/systemctl stop loxberry-mcpserver.service; then
        # Older plugin releases did not grant `stop`, but their service runs as
        # this hook's loxberry user and treats SIGTERM as a clean exit.
        main_pid=$(systemctl show --property=MainPID --value --no-pager loxberry-mcpserver.service || true)
        case "$main_pid" in
            ''|0|*[!0-9]*) echo "<ERROR> MCP service has no safe main PID."; exit 2 ;;
        esac
        kill -TERM "$main_pid" || exit 2
        stopped=0
        for _ in {1..20}; do
            if ! systemctl is-active --quiet loxberry-mcpserver.service; then
                stopped=1
                break
            fi
            sleep 1
        done
        if [ "$stopped" -ne 1 ]; then
            echo "<ERROR> MCP service did not stop before upgrade migration."
            exit 2
        fi
    fi
    echo "<INFO> MCP service stopped before upgrade data migration."
fi

config_file="$LBPCONFIG/$actual_folder/mcpserver.json"
auth_dir="$LBPDATA/$actual_folder/auth"
backup_dir="$installer_root/.mcpserver-upgrade"
if [ -e "$backup_dir" ]; then
    echo "<ERROR> Upgrade backup path is unsafe."
    exit 2
fi
mkdir -p "$backup_dir" || exit 2
chmod 700 "$backup_dir" || exit 2
if [ -f "$config_file" ]; then
    install -m 600 "$config_file" "$backup_dir/mcpserver.json" || exit 2
    echo "<INFO> Existing configuration saved for the upgrade."
else
    echo "<INFO> No existing configuration needs to be saved."
fi
for auth_file in sessions.json loxone-tokens.json.enc install.key; do
    if [ -f "$auth_dir/$auth_file" ]; then
        install -m 600 "$auth_dir/$auth_file" "$backup_dir/$auth_file" || exit 2
    fi
done
echo "<INFO> Existing sessions, encrypted tokens and installation key saved for the upgrade."
exit 0
