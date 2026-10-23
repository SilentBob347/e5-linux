#!/bin/sh
# DNS contract now runs against the real native collector with private RPCs.
set -eu
exec python3 "$(dirname "$0")/../../openwrt/tests/native-dashboard.py" Dashboard.test_dns_deduplicates_top_level_v4_v6_and_ignores_inactive_fields -v
