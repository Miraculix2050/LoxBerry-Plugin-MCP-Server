package LoxBerry::Web;
use strict;
use warnings;
sub lbheader { return; }
sub lbfooter { return; }
sub loglist_html { return $ENV{LB_TEST_LOGLIST_HTML} // ''; }
1;
