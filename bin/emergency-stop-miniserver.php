#!/usr/bin/php
<?php
/* Read one configured Miniserver through the supported LoxBerry SDK only. */
require_once "loxberry_system.php";

$endpoint = $argv[1] ?? "";
if (!is_string($endpoint) || strlen($endpoint) > 512) { exit(2); }
$servers = LBSystem::get_miniservers();
foreach ($servers as $server) {
    if (!is_array($server)) { continue; }
    $host = $server['Ipaddress'] ?? '';
    $port = $server['Preferhttps'] ? ($server['Porthttps'] ?? 443) : ($server['Port'] ?? 80);
    $scheme = $server['Preferhttps'] ? 'https' : 'http';
    $candidate = $scheme . '://' . $host . (($scheme === 'https' && $port == 443) || ($scheme === 'http' && $port == 80) ? '' : ':' . $port);
    if ($candidate !== $endpoint) { continue; }
    $username = $server['Username'] ?? $server['User'] ?? '';
    $password = $server['Password'] ?? $server['Pass'] ?? '';
    if (!is_string($username) || !is_string($password) || $username === '' || $password === '') { exit(3); }
    echo json_encode(['username' => $username, 'password' => $password], JSON_UNESCAPED_SLASHES);
    exit(0);
}
exit(4);
