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
sub lbhostname { return 'localhost'; }
sub get_localip { return '127.0.0.1'; }
sub read_file { return ''; }
sub readlanguage {
    return (
        'DIAGNOSTICS.LOGLIST_EMPTY' => $ENV{LB_TEST_LOG_TEXT_BYTES}
            ? "Keine Logeintr\xC3\xA4ge." : 'No LogManager entry is registered for this plugin.',
        'DIAGNOSTICS.LOGLIST_UNAVAILABLE' => 'The LogManager is unavailable.',
        'SETUP.EMERGENCY_STOP_AUTH_BUSY' => "Anmeldung l\xC3\xA4uft.",
        'STATUS.ERROR_ACTION' => "Aktion f\xC3\xBCr Dienst fehlgeschlagen.",
    );
}
1;
