#!/usr/bin/php
<?php
/* Read one configured Miniserver through the supported LoxBerry SDK only. */
require_once "loxberry_system.php";

$endpoint = $argv[1] ?? "";
if (!is_string($endpoint) || strlen($endpoint) > 512) { exit(2); }
$servers = LBSystem::get_miniservers();
foreach ($servers as $server) {
    if (!is_array($server)) { continue; }
    $host = $server['IPAddress'] ?? '';
    if (!is_string($host) || $host === '') { continue; }
    if (str_contains($host, ':') && !str_starts_with($host, '[')) { $host = "[$host]"; }
    $scheme = $server['Transport'] ?? (($server['PreferHttps'] ?? false) ? 'https' : 'http');
    if ($scheme !== 'http' && $scheme !== 'https') { continue; }
    $port = $scheme === 'https' ? ($server['PortHttps'] ?? 443) : ($server['Port'] ?? 80);
    if (!is_int($port) && !ctype_digit((string)$port)) { continue; }
    $port = (int)$port;
    if ($port < 1 || $port > 65535) { continue; }
    $defaultPort = $scheme === 'https' ? 443 : 80;
    $candidate = $scheme . '://' . $host . ($port === $defaultPort ? '' : ':' . $port);
    if ($candidate !== $endpoint) { continue; }
    $username = $server['Admin_RAW'] ?? $server['Admin'] ?? '';
    $password = $server['Pass_RAW'] ?? $server['Pass'] ?? '';
    if (!is_string($username) || !is_string($password) || $username === '' || $password === '') { exit(3); }
    echo json_encode(['username' => $username, 'password' => $password], JSON_UNESCAPED_SLASHES);
    exit(0);
}
exit(4);
