#!/bin/bash
set -u

actual_folder=$3
if [ -z "$actual_folder" ] || [ -z "${LBPCONFIG:-}" ] || [ -z "${LBPDATA:-}" ]; then
    echo "<ERROR> LoxBerry plugin paths are unavailable."
    exit 2
fi
case "$actual_folder" in
    *[!A-Za-z0-9_-]*|'') echo "<ERROR> Invalid plugin folder."; exit 2 ;;
esac

# Schema migrations are idempotent and never replace an existing session store.
plugin_config="$LBPCONFIG/$actual_folder"
plugin_data="$LBPDATA/$actual_folder"

prepare_private_directory() {
    python3 - "$1" <<'PY'
import grp
import os
import pwd
import stat
import sys

path = sys.argv[1]
parent, name = os.path.split(path)
parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
try:
    try:
        os.mkdir(name, 0o700, dir_fd=parent_fd)
    except FileExistsError:
        pass
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    fd = os.open(name, flags, dir_fd=parent_fd)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISDIR(opened.st_mode):
            raise RuntimeError("private path is not a directory")
        os.fchown(fd, pwd.getpwnam("loxberry").pw_uid, grp.getgrnam("loxberry").gr_gid)
        os.fchmod(fd, 0o700)
        current = os.lstat(path)
        if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
            raise RuntimeError("private directory path changed during preparation")
    finally:
        os.close(fd)
finally:
    os.close(parent_fd)
PY
}

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
changed = False
if isinstance(logging_config, dict) and "debug_until" in logging_config:
    logging_config.pop("debug_until")
    changed = True
if document.get("schema_version") == 1:
    tools = document.setdefault("tools", {})
    limits = document.setdefault("limits", {})
    policies = document.setdefault("policies", {})
    cache = document.setdefault("cache", {})
    tools.setdefault("loxone_history_enabled", False)
    tools.setdefault("loxberry_operate_enabled", False)
    limits.setdefault("history_requests_per_minute", 12)
    limits.setdefault("loxberry_operate_requests_per_minute", 3)
    policies.setdefault("loxberry_operate_bindings", [])
    cache.setdefault("statistics_mode", "memory")
    cache.setdefault("statistics_max_mib", 128)
    document["schema_version"] = 2
    changed = True
if changed:
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
prepare_private_directory "$plugin_data/statistics-cache" || exit 2

echo "<OK> Configuration and sessions retained."
exit 0
