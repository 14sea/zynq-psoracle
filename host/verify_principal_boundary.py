#!/usr/bin/env python3
"""Verify the D4 principal boundary FROM THE RUNNER'S SIDE and write a `principal_boundary`
record the L3 runner requires before it starts (docs/decisions.md D4 option A).

Run as the runner user (no sudo). Every check is an observation of the OS, not a claim:
  R1  this user is not the signer and not in the pod group
  R2  this user cannot read the signer's key store (open() fails with EACCES)
  R3  this user cannot open the JTAG pod device node (if a pod is attached)
  R4  `sudo -n -u <signer> python3 sign_arm.py` is permitted and the signer CAN read the key
      (the signer answers a probe with its key_id, never the key)
  R5  the signer user is in the pod group
A record with any check false is written too — the runner refuses it; nothing is hidden.
"""
from __future__ import annotations

import argparse
import errno
import grp
import json
import os
import pwd
import subprocess
import sys
import time
from pathlib import Path

R = Path(__file__).resolve().parent.parent
SIGNER_USER, POD_GROUP = "p3signer", "p3jtag"
KEY_STORE = Path("/var/lib/p3signer/keys")
POD_IDS = (("0403", "6011"), ("0403", "6014"))


def pod_device_nodes() -> list[Path]:
    out = []
    for dev in Path("/sys/bus/usb/devices").glob("*"):
        try:
            vid = (dev / "idVendor").read_text().strip(); pid = (dev / "idProduct").read_text().strip()
            if (vid, pid) in POD_IDS:
                bus = int((dev / "busnum").read_text()); num = int((dev / "devnum").read_text())
                out.append(Path(f"/dev/bus/usb/{bus:03d}/{num:03d}"))
        except (OSError, ValueError):
            continue
    return out


def check(checks: list, name: str, ok: bool, detail: str):
    checks.append({"check": name, "passed": bool(ok), "detail": detail})


def run_checks(signer=SIGNER_USER, group=POD_GROUP, store=KEY_STORE, sign_arm=R / "host/sign_arm.py") -> dict:
    checks: list = []
    me = pwd.getpwuid(os.getuid()).pw_name
    my_groups = {grp.getgrgid(g).gr_name for g in os.getgroups()}
    check(checks, "R1_runner_is_not_signer", me != signer and group not in my_groups,
          f"user {me}, groups {sorted(my_groups)}")
    try:
        (store / "K.bin").open("rb").close(); r2, d2 = False, "runner OPENED the key file"
    except OSError as e:
        r2, d2 = e.errno in (errno.EACCES, errno.EPERM), f"open: {os.strerror(e.errno)}"
    check(checks, "R2_runner_cannot_read_key", r2, d2)
    nodes = pod_device_nodes()
    if nodes:
        res = []
        for n in nodes:
            try:
                os.open(n, os.O_RDWR); res.append(f"{n}: OPENED")
            except OSError as e:
                res.append(f"{n}: {os.strerror(e.errno)}")
        check(checks, "R3_runner_cannot_open_pod", all("OPENED" not in x for x in res), "; ".join(res))
    else:
        check(checks, "R3_runner_cannot_open_pod", False, "no pod attached: not verifiable now (attach the pod and re-run)")
    try:
        p = subprocess.run(["sudo", "-n", "-u", signer, sys.executable, str(sign_arm), str(store / "K.bin")],
                           input=json.dumps({"op": "probe"}), capture_output=True, text=True, timeout=30)
        ans = json.loads(p.stdout) if p.returncode == 0 else {}
        check(checks, "R4_signer_reachable_and_holds_key", p.returncode == 0 and "key_id" in ans and "key" not in ans,
              f"rc={p.returncode} {p.stderr.strip()[:120]} key_id={ans.get('key_id', '')[:12]}")
        key_id = ans.get("key_id")
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        check(checks, "R4_signer_reachable_and_holds_key", False, str(e)); key_id = None
    try:
        sg = grp.getgrnam(group).gr_mem; pw = pwd.getpwnam(signer)
        in_group = signer in sg or pw.pw_gid == grp.getgrnam(group).gr_gid
        check(checks, "R5_signer_in_pod_group", in_group, f"members {sg}, signer gid {pw.pw_gid}")
    except KeyError as e:
        check(checks, "R5_signer_in_pod_group", False, f"missing principal: {e}")
    return {"schema": "principal_boundary", "schema_version": "1.0.0", "runner_user": me, "signer_user": signer,
            "pod_group": group, "key_store": str(store), "checks": checks, "all_passed": all(c["passed"] for c in checks),
            "key_id": key_id, "at": time.time(), "host": os.uname().nodename}


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--out", type=Path, required=True); a = ap.parse_args()
    rec = run_checks()
    a.out.write_text(json.dumps(rec, indent=2) + "\n")
    for c in rec["checks"]:
        print(("PASS " if c["passed"] else "FAIL ") + c["check"] + "  " + c["detail"])
    print("boundary:", "ALL PASSED" if rec["all_passed"] else "NOT ESTABLISHED", "->", a.out)
    return 0 if rec["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
