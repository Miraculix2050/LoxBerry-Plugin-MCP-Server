#!/bin/bash
set -u

actual_folder=$3
installer_root=${6:-}
if [ -z "$actual_folder" ] || [ -z "$installer_root" ] || [ -z "${LBPCONFIG:-}" ] || [ -z "${LBPDATA:-}" ]; then
    echo "<ERROR> LoxBerry plugin paths are unavailable."
    exit 2
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
