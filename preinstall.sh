#!/bin/bash
set -u

if ! command -v python3.13 >/dev/null 2>&1; then
    echo "<ERROR> Python 3.13 is required."
    exit 2
fi
if [ "$(dpkg --print-architecture 2>/dev/null)" != "arm64" ]; then
    echo "<ERROR> This prerelease package contains arm64 runtime wheels only."
    exit 2
fi
for command in openssl systemctl systemd-run apache2ctl; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "<ERROR> Required command $command is unavailable."
        exit 2
    fi
done
echo "<OK> Runtime prerequisites are available."
exit 0
