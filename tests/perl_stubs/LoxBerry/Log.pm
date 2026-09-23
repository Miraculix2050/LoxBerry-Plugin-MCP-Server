package LoxBerry::Log;
use strict;
use warnings;
use Exporter 'import';
our @EXPORT = qw(LOGERR);
sub new { return bless {}, shift; }
sub _record {
    my ($event, $message) = @_;
    return if !$ENV{LB_TEST_LOG_EVENTS_PATH};
    open my $log, '>>', $ENV{LB_TEST_LOG_EVENTS_PATH} or die $!;
    print {$log} "$event:$message\n";
    close $log;
}
sub LOGSTART { shift; _record('start', @_); }
sub LOGEND { shift; _record('end', @_); }
sub ERR { shift; _record('error', @_); }
sub LOGERR { return; }
sub get_notifications_html { return ''; }
1;
