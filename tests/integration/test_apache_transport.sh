#!/bin/sh
set -eu

if [ "$#" -ne 2 ]; then
	echo "usage: $0 PYTHON REPOSITORY_ROOT" >&2
	exit 2
fi

python=$1
repository_root=$2
work_dir=$(mktemp -d /tmp/mcpserver-apache-test.XXXXXX)
server_pid=""
apache_pid=""

cleanup() {
	if [ -n "$apache_pid" ]; then
		kill "$apache_pid" 2>/dev/null || true
		wait "$apache_pid" 2>/dev/null || true
	fi
	if [ -n "$server_pid" ]; then
		kill "$server_pid" 2>/dev/null || true
		wait "$server_pid" 2>/dev/null || true
	fi
	rm -rf "$work_dir"
}
trap cleanup EXIT INT TERM

require_running() {
	process_name=$1
	process_pid=$2
	process_log=$3
	if ! kill -0 "$process_pid" 2>/dev/null; then
		printf '%s exited before owning its test port\n' "$process_name" >&2
		cat "$process_log" >&2 2>/dev/null || true
		exit 1
	fi
}

"$python" - <<'PY'
import socket

for port in (8765, 18888):
    with socket.socket() as listener:
        try:
            listener.bind(("127.0.0.1", port))
        except OSError as error:
            raise SystemExit(f"test port {port} is already occupied: {error}") from error
PY

mkdir "$work_dir/empty"
cat >"$work_dir/apache.conf" <<EOF
ServerRoot "/etc/apache2"
PidFile "$work_dir/apache.pid"
DefaultRuntimeDir "$work_dir"
Listen 127.0.0.1:18888
ServerName localhost
ErrorLog "$work_dir/apache-error.log"
LogLevel warn
LoadModule mpm_event_module /usr/lib/apache2/modules/mod_mpm_event.so
LoadModule authz_core_module /usr/lib/apache2/modules/mod_authz_core.so
LoadModule proxy_module /usr/lib/apache2/modules/mod_proxy.so
LoadModule proxy_http_module /usr/lib/apache2/modules/mod_proxy_http.so
DocumentRoot "$work_dir/empty"
<Directory "$work_dir/empty">
    Require all denied
</Directory>
Include "$repository_root/config/apache/mcpserver.conf"
EOF

/usr/sbin/apache2 -t -f "$work_dir/apache.conf"

MCPSERVER_ALLOWED_HOSTS="127.0.0.1:8765,127.0.0.1:18888" \
	MCPSERVER_ALLOWED_ORIGINS="http://127.0.0.1:18888" \
	PYTHONPATH="$repository_root/src" \
	"$python" -m mcpserver.server >"$work_dir/server.log" 2>&1 &
server_pid=$!

/usr/sbin/apache2 -f "$work_dir/apache.conf" -DFOREGROUND &
apache_pid=$!

attempt=0
while [ "$attempt" -lt 100 ]; do
	require_running "MCP server" "$server_pid" "$work_dir/server.log"
	require_running "Apache" "$apache_pid" "$work_dir/apache-error.log"
	if curl -fsS http://127.0.0.1:8765/healthz >/dev/null 2>&1; then
		break
	fi
	attempt=$((attempt + 1))
	sleep 0.05
done
require_running "MCP server" "$server_pid" "$work_dir/server.log"
require_running "Apache" "$apache_pid" "$work_dir/apache-error.log"
if [ "$attempt" -eq 100 ]; then
	printf 'MCP server did not become ready\n' >&2
	exit 1
fi

request='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"apache-spike","version":"1"}}}'
response=$(curl -fsS \
	-H 'Accept: application/json, text/event-stream' \
	-H 'Content-Type: application/json' \
	-H 'Origin: http://127.0.0.1:18888' \
	--data "$request" \
	http://127.0.0.1:18888/plugins/mcpserver/mcp)
printf '%s' "$response" | "$python" -c \
	'import json,sys; body=json.load(sys.stdin); assert body["result"]["protocolVersion"] == "2025-11-25"'

untrusted_host_status=$(curl -sS -o /dev/null -w '%{http_code}' \
	-H 'Host: untrusted.example' \
	-H 'Accept: application/json, text/event-stream' \
	-H 'Content-Type: application/json' \
	--data "$request" \
	http://127.0.0.1:18888/plugins/mcpserver/mcp)
test "$untrusted_host_status" = "421"

untrusted_status=$(curl -sS -o /dev/null -w '%{http_code}' \
	-H 'Accept: application/json, text/event-stream' \
	-H 'Content-Type: application/json' \
	-H 'Origin: https://untrusted.example' \
	--data "$request" \
	http://127.0.0.1:18888/plugins/mcpserver/mcp)
test "$untrusted_status" = "403"

stream_seconds=${MCPSERVER_STREAM_TEST_SECONDS:-3}
set +e
timeout "$stream_seconds" curl -NsS \
	-H 'Accept: text/event-stream' \
	-H 'Origin: http://127.0.0.1:18888' \
	http://127.0.0.1:18888/plugins/mcpserver/mcp >/dev/null
stream_status=$?
set -e
test "$stream_status" = "124"

printf 'APACHE_STREAMABLE_HTTP=pass\n'
printf 'APACHE_HOST_REJECTION=pass\n'
printf 'APACHE_ORIGIN_REJECTION=pass\n'
printf 'APACHE_SSE_%s_SECONDS=pass\n' "$stream_seconds"
