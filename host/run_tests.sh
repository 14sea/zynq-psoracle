#!/usr/bin/env bash
# Runs the suite and lands the evidence report FAIL-CLOSED (reviewer 2026-08-31):
#   exit = the suite's own status  ONLY IF the report was written, registered and staged;
#   exit 3 otherwise (report/manifest/git failure), whatever the suite said.
set -u
cd "$(dirname "$0")/.."
log=$(mktemp)
python3 -m unittest discover -s tests > "$log" 2>&1; trc=$?
grep -E 'skipped|^Ran|^OK|^FAILED' "$log"
python3 host/test_report.py --exit-status "$trc" --log "$log"; rrc=$?
rm -f "$log"
if [ "$rrc" -ne 0 ]; then echo "EXIT 3: evidence report did not land (suite status was $trc)"; exit 3; fi
echo "EXIT $trc"; exit "$trc"
