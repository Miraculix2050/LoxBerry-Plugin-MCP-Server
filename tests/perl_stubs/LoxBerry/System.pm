package LoxBerry::System;
use strict;
use warnings;
use Exporter 'import';
our @EXPORT = qw($lbhomedir $lbpplugindir $lbpconfigdir $lbpdatadir $lbpbindir $lbptemplatedir);
our ($lbhomedir, $lbpplugindir, $lbpconfigdir, $lbpdatadir, $lbpbindir, $lbptemplatedir);
sub pluginversion { return 'test'; }
sub read_file { return ''; }
sub readlanguage { return (); }
1;
