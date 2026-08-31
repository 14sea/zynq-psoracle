#!/usr/bin/env bash
# Runs the suite, keeps the ORIGINAL exit status, and records counts + the environment's sudo
# capability into evidence/tests/test_report_<UTC>.json (reviewer request 2026-08-31).
set -u
cd "$(dirname "$0")/.."
ts=$(date -u +%Y-%m-%dT%H%M%SZ); log=$(mktemp)
python3 -m unittest discover -s tests > "$log" 2>&1; rc=$?
ran=$(grep -oE '^Ran [0-9]+' "$log" | grep -oE '[0-9]+'); tail=$(grep -E '^(OK|FAILED)' "$log" | tail -1)
probe=$(sudo -n -u p3signer /usr/bin/python3 /home/test/zynq_psoracle/host/sign_arm.py /var/lib/p3signer/keys/K.bin <<<'{"op":"probe"}' 2>&1 | head -c 300)
python3 - "$ts" "$rc" "${ran:-0}" "$tail" "$probe" "$(hostname)" "$(id -un)" "$(git rev-parse HEAD)" <<'PY'
import json, sys
ts, rc, ran, tail, probe, host, user, head = sys.argv[1:]
rep = {"at": ts, "exit_status": int(rc), "ran": int(ran), "result_line": tail, "host": host, "user": user, "commit": head,
       "sudo_signer_probe": probe, "boundary_available": probe.strip().startswith("{")}
open(f"evidence/tests/test_report_{ts}.json", "w").write(json.dumps(rep, indent=2) + "\n")
print(json.dumps(rep, indent=1))
PY
# the report is evidence: register it in the import manifest and stage it, so the two-way
# closure test (tracked <=> declared) holds on the next run
rep="evidence/tests/test_report_${ts}.json"
grep -q "\`$rep\`" docs/import_manifest.md || sed -i "s#^| \`host/run_tests.sh\` |\$#| \`host/run_tests.sh\` |\n| \`$rep\` |#" docs/import_manifest.md
git add "$rep" docs/import_manifest.md 2>/dev/null
cat "$log" | grep -E 'skipped|^Ran|^OK|^FAILED' ; rm -f "$log"; exit $rc
