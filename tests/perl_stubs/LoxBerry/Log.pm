package LoxBerry::Log;
use strict;
use warnings;
use Exporter 'import';
our @EXPORT = qw(LOGERR);
sub new { return bless {}, shift; }
sub LOGSTART { return; }
sub LOGERR { return; }
sub get_notifications_html { return ''; }
1;
