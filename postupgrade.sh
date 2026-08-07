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
python3 - "$plugin_config/mcpserver.json" <<'PY' || exit 2
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

path = Path(sys.argv[1])
metadata = path.lstat()
if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
    raise SystemExit("configuration is not a regular file")
document = json.loads(path.read_text(encoding="utf-8"))
logging_config = document.get("logging")
if isinstance(logging_config, dict) and "debug_until" in logging_config:
    logging_config.pop("debug_until")
    descriptor, temporary_name = tempfile.mkstemp(prefix=".mcpserver.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, ensure_ascii=True, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
PY
chmod 600 "$plugin_config/mcpserver.json"
mkdir -p "$plugin_data/auth"
chmod 700 "$plugin_data/auth"

# The former CGI logger created one timestamped file per administrative action.
# Removing those legacy files makes the new active file plus two backups the
# immediate upper bound after an upgrade. Missing files are hidden by the
# native LogManager even if an old volatile database entry still exists.
plugin_log="${LBHOMEDIR:-/opt/loxberry}/log/plugins/$actual_folder"
if [ -d "$plugin_log" ]; then
    find "$plugin_log" -maxdepth 1 -type f -name '*_admin-ui.log' -delete || exit 2
fi
echo "<OK> Configuration and sessions retained."
exit 0
