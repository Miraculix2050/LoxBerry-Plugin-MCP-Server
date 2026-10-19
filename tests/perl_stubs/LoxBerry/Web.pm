package LoxBerry::Web;
use strict;
use warnings;
sub lbheader { return; }
sub lbfooter { return; }
sub loglist_html {
    our $loglist_calls;
    $loglist_calls++;
    die 'private-detail' if $ENV{LB_TEST_LOGLIST_DIE};
    return undef if $ENV{LB_TEST_LOGLIST_FAIL_ONCE} && $loglist_calls == 1;
    return undef if $ENV{LB_TEST_LOGLIST_UNAVAILABLE};
    return $ENV{LB_TEST_LOGLIST_HTML} // '';
}
1;
