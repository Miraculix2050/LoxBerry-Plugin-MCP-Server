#!/bin/sh
set -eu

if [ "$#" -ne 2 ]; then
	echo "usage: $0 PYTHON TEST_ROOT" >&2
	exit 2
fi

python=$1
test_root=$2
work_dir=$(mktemp -d /tmp/mcpserver-runtime-gate.XXXXXX)
server_pid=""

cleanup() {
	if [ -n "$server_pid" ]; then
		kill "$server_pid" 2>/dev/null || true
		wait "$server_pid" 2>/dev/null || true
	fi
	rm -rf "$work_dir"
}
trap cleanup EXIT INT TERM

start_server() {
	store_path=$1
	env \
		MCPSERVER_ALLOWED_HOSTS=127.0.0.1:8765 \
		MCPSERVER_PUBLIC_ORIGIN=https://localhost \
		MCPSERVER_AUTH_STORE="$store_path" \
		MCPSERVER_LOXONE_ENDPOINT=http://192.168.255.254 \
		"$python" -m mcpserver.server >"$work_dir/server.log" 2>&1 &
	server_pid=$!
}

wait_for_health() {
	attempt=0
	while [ "$attempt" -lt 150 ]; do
		if ! kill -0 "$server_pid" 2>/dev/null; then
			cat "$work_dir/server.log" >&2
			exit 1
		fi
		if curl -fsS http://127.0.0.1:8765/healthz >/dev/null 2>&1; then
			return
		fi
		attempt=$((attempt + 1))
		sleep 0.05
	done
	echo "runtime gate server did not become healthy" >&2
	exit 1
}

stop_server() {
	kill "$server_pid"
	wait "$server_pid" 2>/dev/null || true
	server_pid=""
}

printf 'WHEELS=%s\n' "$(find "$test_root/wheelhouse" -maxdepth 1 -name '*.whl' | wc -l)"
printf 'WHEELHOUSE_KIB=%s\n' "$(du -sk "$test_root/wheelhouse" | cut -f1)"
printf 'RUNTIME_VENV_KIB=%s\n' "$(du -sk "$test_root/runtime-env" | cut -f1)"

index=1
while [ "$index" -le 5 ]; do
	started=$(date +%s%3N)
	start_server "$work_dir/auth-$index/sessions.json"
	wait_for_health
	healthy=$(date +%s%3N)
	rss=$(ps -o rss= -p "$server_pid" | tr -d ' ')
	printf 'START_%s_MS=%s RSS_%s_KIB=%s\n' \
		"$index" "$((healthy - started))" "$index" "$rss"
	stop_server
	index=$((index + 1))
done

start_server "$work_dir/auth-idle/sessions.json"
wait_for_health
rss_initial=$(ps -o rss= -p "$server_pid" | tr -d ' ')
sleep 30
rss_idle=$(ps -o rss= -p "$server_pid" | tr -d ' ')
printf 'RSS_INITIAL_KIB=%s RSS_IDLE_30S_KIB=%s\n' "$rss_initial" "$rss_idle"
stop_server
