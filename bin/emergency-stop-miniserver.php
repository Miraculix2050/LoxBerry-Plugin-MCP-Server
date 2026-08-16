#!/usr/bin/perl
use strict;
use warnings;

# Read one configured Miniserver through the supported LoxBerry SDK only.
use LoxBerry::System;
use JSON;

my $endpoint = shift // '';
exit 2 if @ARGV || length($endpoint) > 512;

my %miniservers = LoxBerry::System::get_miniservers();
for my $number (sort { $a <=> $b } keys %miniservers) {
    my $miniserver = $miniservers{$number};
    next if ref($miniserver) ne 'HASH';
    my $host = $miniserver->{IPAddress} // '';
    next if $host eq '';
    $host = "[$host]" if $host =~ /:/ && $host !~ /^\[/;
    my $scheme = $miniserver->{Transport} // ($miniserver->{PreferHttps} ? 'https' : 'http');
    next if $scheme ne 'http' && $scheme ne 'https';
    my $port = $scheme eq 'https' ? ($miniserver->{PortHttps} // 443) : ($miniserver->{Port} // 80);
    next if $port !~ /^\d+$/ || $port < 1 || $port > 65535;
    my $default_port = $scheme eq 'https' ? 443 : 80;
    my $candidate = $scheme . '://' . $host . ($port == $default_port ? '' : ':' . $port);
    next if $candidate ne $endpoint;
    my $username = $miniserver->{Admin} // '';
    my $password = $miniserver->{Pass_RAW} // $miniserver->{Pass} // '';
    exit 3 if $username eq '' || $password eq '';
    print JSON::to_json({ username => $username, password => $password }, { canonical => 1 });
    exit 0;
}
exit 4;
