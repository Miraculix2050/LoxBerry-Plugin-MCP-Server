#!/bin/bash
set -u

if [ -z "${LBPCONFIG:-}" ] || [ -z "${LBPDATA:-}" ]; then
    echo "<ERROR> LoxBerry plugin paths are unavailable."
    exit 2
fi
echo "<INFO> Existing configuration and sessions will be retained."
exit 0
