#!/bin/bash
set -u

actual_folder=$3
installer_root=${6:-}
if [ -z "$actual_folder" ] || [ -z "$installer_root" ] || [ -z "${LBPBIN:-}" ] || [ -z "${LBPCONFIG:-}" ] || [ -z "${LBPDATA:-}" ] || [ -z "${LBPLOG:-}" ]; then
    echo "<ERROR> LoxBerry did not provide the plugin paths or actual folder."
    exit 2
fi

plugin_bin="$LBPBIN/$actual_folder"
plugin_config="$LBPCONFIG/$actual_folder"
plugin_data="$LBPDATA/$actual_folder"
plugin_log="$LBPLOG/$actual_folder"
config_file="$plugin_config/mcpserver.json"
upgrade_backup_dir="$installer_root/.mcpserver-upgrade"
upgrade_backup="$upgrade_backup_dir/mcpserver.json"
venv="$plugin_data/venv"
new_venv="$plugin_data/.venv.new.$$"
old_venv="$plugin_data/.venv.previous.$$"
wheelhouse="$plugin_bin/wheelhouse"
cleanup() {
    rm -rf -- "$new_venv"
}
trap cleanup EXIT

mkdir -p "$plugin_config" "$plugin_data/auth" "$plugin_log"
chmod 700 "$plugin_data/auth"

if [ -f "$upgrade_backup" ] && [ ! -L "$upgrade_backup" ]; then
    install -m 600 "$upgrade_backup" "$config_file" || exit 2
    rm -f -- "$upgrade_backup"
    echo "<INFO> Existing configuration restored after the upgrade."
elif [ ! -f "$config_file" ]; then
    cp "$plugin_config/default-config.json" "$config_file"
fi
chmod 600 "$config_file"

for auth_file in sessions.json loxone-tokens.json.enc install.key; do
    upgrade_auth="$upgrade_backup_dir/$auth_file"
    if [ -f "$upgrade_auth" ] && [ ! -L "$upgrade_auth" ]; then
        install -m 600 "$upgrade_auth" "$plugin_data/auth/$auth_file" || exit 2
        rm -f -- "$upgrade_auth"
    fi
done
rmdir "$upgrade_backup_dir" 2>/dev/null || true

if [ ! -d "$wheelhouse" ] || ! find "$wheelhouse" -maxdepth 1 -name '*.whl' -print -quit | grep -q .; then
    echo "<ERROR> Offline wheelhouse is missing from the package."
    exit 2
fi

python3.13 -m venv "$new_venv" || exit 2
"$new_venv/bin/python" -m pip install --no-index --no-deps --find-links "$wheelhouse" -r "$plugin_bin/runtime-arm64.lock" || exit 2
"$new_venv/bin/python" -m pip install --no-index --no-deps --find-links "$wheelhouse" loxberry-mcpserver==0.4.0a10 || exit 2
if [ -d "$venv" ]; then
    mv "$venv" "$old_venv" || exit 2
fi
if ! mv "$new_venv" "$venv"; then
    [ ! -d "$old_venv" ] || mv "$old_venv" "$venv"
    exit 2
fi
rewrite_failed=0
while IFS= read -r -d '' script; do
    if [ "$(head -n 1 "$script")" = "#!$new_venv/bin/python" ]; then
        sed -i "1c\\#!$venv/bin/python" "$script" || rewrite_failed=1
    fi
done < <(find "$venv/bin" -maxdepth 1 -type f -perm /111 -print0)
if [ "$rewrite_failed" -ne 0 ]; then
    rm -rf -- "$venv"
    [ ! -d "$old_venv" ] || mv "$old_venv" "$venv"
    exit 2
fi
rm -rf -- "$old_venv"
trap - EXIT

chown -R loxberry:loxberry "$plugin_config" "$plugin_data" "$plugin_log"
chmod 700 "$plugin_data/venv" "$plugin_data/auth"
echo "<OK> Python runtime installed offline for plugin folder $actual_folder."
exit 0
