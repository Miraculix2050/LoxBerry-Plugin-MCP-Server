package LoxBerry::Log;
use strict;
use warnings;
use Exporter 'import';
our @EXPORT = qw(LOGERR);
sub new { return bless {}, shift; }
sub _record {
    my ($event) = @_;
    return if !$ENV{LB_TEST_LOG_EVENTS_PATH};
    open my $log, '>>', $ENV{LB_TEST_LOG_EVENTS_PATH} or die $!;
    print {$log} "$event\n";
    close $log;
}
sub LOGSTART { _record('start'); }
sub LOGEND { _record('end'); }
sub ERR { _record('error'); }
sub LOGERR { return; }
sub get_notifications_html { return ''; }
1;
