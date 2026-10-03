package MCPServer::RequestSecurity;

use strict;
use warnings;
use Socket qw(AF_INET AF_INET6 inet_pton);

sub request_scheme {
    my ($environment) = @_;
    my ($tls_scheme, $request_scheme);
    if (exists $environment->{HTTPS}) {
        my $tls = lc($environment->{HTTPS} // '');
        return undef unless $tls =~ /\A(?:on|off|1|0)\z/;
        $tls_scheme = ($tls eq 'on' || $tls eq '1') ? 'https' : 'http';
    }
    if (exists $environment->{REQUEST_SCHEME}) {
        $request_scheme = lc($environment->{REQUEST_SCHEME} // '');
        return undef unless $request_scheme =~ /\Ahttps?\z/;
    }
    return undef if defined($tls_scheme) && defined($request_scheme)
        && $tls_scheme ne $request_scheme;
    # Native Apache leaves HTTPS unset for cleartext requests. Never infer TLS
    # from a port, the supplied Origin, or client-controlled forwarding headers.
    return $request_scheme // $tls_scheme // 'http';
}

sub authority {
    my ($value, $scheme) = @_;
    return undef unless defined($value) && length($value) <= 320;
    my ($host, $port, $identity);
    if ($value =~ /\A\[([0-9a-fA-F:.]+)\](?::([0-9]{1,5}))?\z/) {
        ($host, $port) = ($1, $2);
        my $packed = inet_pton(AF_INET6, $host);
        return undef unless defined $packed;
        $identity = 'ipv6:' . unpack('H*', $packed);
    } elsif ($value =~ /\A([A-Za-z0-9.-]+)(?::([0-9]{1,5}))?\z/) {
        ($host, $port) = ($1, $2);
        return undef if length($host) > 253;
        if ($host =~ /\A[0-9.]+\z/) {
            my $packed = inet_pton(AF_INET, $host);
            return undef unless defined $packed;
            $identity = 'ipv4:' . unpack('H*', $packed);
        } else {
            my $labels = $host;
            $labels =~ s/\.\z//;
            return undef if $labels eq '';
            for my $label (split /\./, $labels, -1) {
                return undef unless $label =~ /\A[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\z/;
            }
            $identity = 'dns:' . lc($host);
        }
    } else {
        return undef;
    }
    $port = defined($port) ? int($port) : ($scheme eq 'https' ? 443 : 80);
    return undef unless $port >= 1 && $port <= 65535;
    return [$identity, $port];
}

sub same_origin_post {
    my ($environment) = @_;
    $environment //= \%ENV;
    return 0 unless uc($environment->{REQUEST_METHOD} // '') eq 'POST';
    my $scheme = request_scheme($environment);
    return 0 unless defined $scheme;
    my $origin = $environment->{HTTP_ORIGIN} // '';
    return 0 unless length($origin) <= 328 && $origin =~ /\A(https?):\/\/([^\s]+)\z/i;
    my ($origin_scheme, $origin_authority) = (lc($1), $2);
    return 0 unless $origin_scheme eq $scheme;
    my $expected = authority($environment->{HTTP_HOST}, $scheme);
    my $actual = authority($origin_authority, $origin_scheme);
    return 0 unless defined($expected) && defined($actual);
    return $expected->[0] eq $actual->[0] && $expected->[1] == $actual->[1] ? 1 : 0;
}

1;
