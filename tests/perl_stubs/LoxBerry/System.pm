package LoxBerry::System;
use strict;
use warnings;
use Exporter 'import';
our @EXPORT = qw($lbhomedir $lbpplugindir $lbpconfigdir $lbpdatadir $lbpbindir $lbptemplatedir $lbplogdir);
our ($lbhomedir, $lbpplugindir, $lbpconfigdir, $lbpdatadir, $lbpbindir, $lbptemplatedir, $lbplogdir);
sub pluginversion { return 'test'; }
sub pluginloglevel { return 3; }
sub read_file { return ''; }
sub readlanguage { return (); }
1;
