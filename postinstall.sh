#!/bin/bash
set -u

actual_folder=$3
if [ -z "$actual_folder" ] || [ -z "${LBPBIN:-}" ] || [ -z "${LBPCONFIG:-}" ] || [ -z "${LBPDATA:-}" ] || [ -z "${LBPLOG:-}" ]; then
    echo "<ERROR> LoxBerry did not provide the plugin paths or actual folder."
    exit 2
fi

plugin_bin="$LBPBIN/$actual_folder"
plugin_config="$LBPCONFIG/$actual_folder"
plugin_data="$LBPDATA/$actual_folder"
plugin_log="$LBPLOG/$actual_folder"
config_file="$plugin_config/mcpserver.json"
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

if [ ! -f "$config_file" ]; then
    cp "$plugin_config/default-config.json" "$config_file"
fi
chmod 600 "$config_file"

if [ ! -d "$wheelhouse" ] || ! find "$wheelhouse" -maxdepth 1 -name '*.whl' -print -quit | grep -q .; then
    echo "<ERROR> Offline wheelhouse is missing from the package."
    exit 2
fi

python3.13 -m venv "$new_venv" || exit 2
"$new_venv/bin/python" -m pip install --no-index --no-deps --find-links "$wheelhouse" -r "$plugin_bin/runtime-arm64.lock" || exit 2
"$new_venv/bin/python" -m pip install --no-index --no-deps --find-links "$wheelhouse" loxberry-mcpserver==0.1.0a1 || exit 2
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
