#!/usr/bin/perl
use strict;
use warnings;

# Read one configured Miniserver through the supported LoxBerry SDK only.
use LoxBerry::System;
use JSON::PP;

my $endpoint = $ARGV[0] // '';
exit 2 if @ARGV != 1 || length($endpoint) > 512;

my %servers = LoxBerry::System::get_miniservers();
for my $number (sort { $a <=> $b } keys %servers) {
    my $server = $servers{$number};
    next if ref($server) ne 'HASH';
    my $host = $server->{IPAddress} // '';
    next if !defined($host) || $host eq '';
    $host = "[$host]" if $host =~ /:/ && $host !~ /\A\[.*\]\z/;
    my $scheme = $server->{Transport} // ($server->{PreferHttps} ? 'https' : 'http');
    next if $scheme ne 'http' && $scheme ne 'https';
    my $port = $scheme eq 'https' ? ($server->{PortHttps} // 443) : ($server->{Port} // 80);
    next if $port !~ /\A[0-9]{1,5}\z/ || $port < 1 || $port > 65535;
    my $default_port = $scheme eq 'https' ? 443 : 80;
    my $candidate = "$scheme://$host" . ($port == $default_port ? '' : ":$port");
    next if $candidate ne $endpoint;
    my $username = $server->{Admin} // '';
    my $password = $server->{Pass_RAW} // $server->{Pass} // '';
    exit 3 if ref($username) || ref($password) || $username eq '' || $password eq '';
    print encode_json({ username => $username, password => $password });
    exit 0;
}

exit 4;
