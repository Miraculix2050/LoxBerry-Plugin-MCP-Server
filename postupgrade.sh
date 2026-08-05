#!/bin/bash
set -u

hook_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit 2
postinstall_hook="$hook_dir/postinstall.sh"
if [ ! -f "$postinstall_hook" ] || [ -L "$postinstall_hook" ]; then
    echo "<ERROR> The trusted postinstall hook is unavailable during upgrade."
    exit 2
fi

# LoxBerry invokes postupgrade instead of postinstall for an upgrade. Reuse the
# complete atomic runtime rebuild and backup restoration so changed project code
# and package data cannot remain hidden behind the previous virtual environment.
exec /bin/bash "$postinstall_hook" "$@"
