#!/bin/bash
set -u

actual_folder=$3
if [ -z "$actual_folder" ] || [ -z "${LBPCONFIG:-}" ] || [ -z "${LBPDATA:-}" ]; then
    echo "<ERROR> LoxBerry plugin paths are unavailable."
    exit 2
fi

# Schema 1 is the first released configuration. The migration is intentionally
# idempotent and never replaces an existing configuration or session store.
plugin_config="$LBPCONFIG/$actual_folder"
plugin_data="$LBPDATA/$actual_folder"
if [ ! -f "$plugin_config/mcpserver.json" ]; then
    cp "$plugin_config/default-config.json" "$plugin_config/mcpserver.json" || exit 2
fi
chmod 600 "$plugin_config/mcpserver.json"
mkdir -p "$plugin_data/auth"
chmod 700 "$plugin_data/auth"
echo "<OK> Configuration and sessions retained."
exit 0
