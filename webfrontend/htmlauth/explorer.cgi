#!/usr/bin/perl

use strict;
use warnings;
use CGI;
use HTML::Template;
use LoxBerry::System;
use LoxBerry::Web;

my $cgi = CGI->new;
my $q = $cgi->Vars;
if (($q->{lang} // '') =~ /\A(?:de|en)\z/) {
    $LoxBerry::System::lang = $q->{lang};
    $LoxBerry::Web::lang = $q->{lang};
}

my $version = LoxBerry::System::pluginversion();
my $template_text = LoxBerry::System::read_file("$lbptemplatedir/explorer.html");
my $template = HTML::Template->new_scalar_ref(
    \$template_text,
    global_vars => 1,
    loop_context_vars => 1,
    die_on_bad_params => 0,
);
my %L = LoxBerry::System::readlanguage($template, 'language.ini');

$template->param(VERSION => $version);

our %navbar;
$navbar{10}{Name} = $L{'EXPLORER.BACK'};
$navbar{10}{URL} = 'index.cgi';

print "Cache-Control: no-store\n";
print "Pragma: no-cache\n";
print "Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'\n";
print "Referrer-Policy: no-referrer\n";
print "X-Content-Type-Options: nosniff\n";
print "X-Frame-Options: DENY\n";
LoxBerry::Web::lbheader($L{'EXPLORER.TITLE'} . " V$version", '', '', 'nojqm');
print $template->output();
LoxBerry::Web::lbfooter();
exit;
