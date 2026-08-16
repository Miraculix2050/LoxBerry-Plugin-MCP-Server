package LoxBerry::System;
use strict;
use warnings;
use Exporter 'import';
our @EXPORT = qw($lbhomedir $lbpplugindir $lbpconfigdir $lbpdatadir $lbpbindir $lbptemplatedir $lbplogdir);
our ($lbhomedir, $lbpplugindir, $lbpconfigdir, $lbpdatadir, $lbpbindir, $lbptemplatedir, $lbplogdir);
BEGIN {
    $lbhomedir = $ENV{LB_TEST_HOME} // '';
    $lbpplugindir = $ENV{LB_TEST_PLUGIN_DIR} // 'mcpserver';
    $lbpconfigdir = $ENV{LB_TEST_CONFIG_DIR} // '';
    $lbpdatadir = $ENV{LB_TEST_DATA_DIR} // '';
    $lbpbindir = $ENV{LB_TEST_BIN_DIR} // '';
    $lbptemplatedir = $ENV{LB_TEST_TEMPLATE_DIR} // '';
    $lbplogdir = $ENV{LB_TEST_LOG_DIR} // '';
}
sub pluginversion { return 'test'; }
sub pluginloglevel { return 3; }
sub read_file { return ''; }
sub readlanguage { return (); }
1;
