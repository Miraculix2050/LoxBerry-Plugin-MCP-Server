package LoxBerry::System;
use strict;
use warnings;
use Exporter 'import';
our @EXPORT = qw($lbpplugindir $lbpconfigdir $lbpdatadir $lbpbindir $lbptemplatedir);
our ($lbpplugindir, $lbpconfigdir, $lbpdatadir, $lbpbindir, $lbptemplatedir);
sub pluginversion { return 'test'; }
sub read_file { return ''; }
sub readlanguage { return (); }
1;
