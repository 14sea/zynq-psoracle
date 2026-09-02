#!/usr/bin/env python3
"""L6 — calibration (C1, C2) and soak (S) of the P3 loop. Ruling text RULING_TEXT.

The L5 runner with what prereg §4 adds and nothing else: per-frame timestamps, the audit
schedule (all-self-reporting for C1/C2, sampled per §3a for S), `--duration`, N and the
timeout derived from the two calibration records' hashes (D-s3), the expected frame
count and CRC budget computed before the session (D-s4), the arm-aware and L6-identity
checks, and the rate report. The console loop, the notary relay and the collector are
L5's; the U-Boot preamble is copied from `host/l5_runner.py` verbatim rather than shared,
so that the L5 instrument that PASSED is not edited to serve L6.

FAIL-CLOSED, in this order, before any board contact: the ruling text; the session kind;
a `provisioning P3-K` ruling present, parseable and unconsumed (mandatory: without it the
L6 ruling is never claimed and the port never opened); the manifest's frozen
preregistration hash; a pinned two-operator image that the file on disk hashes to; the
watchdog pinned ON with the D-s1 load value; BOTH rulings bound to this session, the
frozen prereg, the pinned image and the sha256 of the L6 manifest file itself (and the L6
ruling to the pinned master seed); the
frozen carrier (manifest file and bitstream file hash to their pins; the nonce seed is the
manifest's own pin — there is no --l5-manifest input); the pinned master
seed and, for S, exactly the pinned duration; for S, both calibration reports hashing to
their pins; the principal boundary < 6 h AND bound to this invocation (the effective
UID's name, signer user, key path); the evidence directory not existing. Board-phase preflight blockers 1–5
(owner 2026-09-01) are each a named refusal with a negative test.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pwd
import secrets
import shutil
import sys
import time
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R / "scripts")); sys.path.insert(0, str(R / "host")); sys.path.insert(0, str(R))
sys.path.insert(0, str(R / "imported/fabricmap/scripts"))
import board_session as bsn  # noqa: E402
import p2_observe as ob  # noqa: E402
import pcap_probe_runner as pr  # noqa: E402
import l3_runner as l3  # noqa: E402
import l5_notary as n  # noqa: E402
import l5_runner as l5  # noqa: E402
import l6_checks as lc  # noqa: E402
import l6_console as lcs  # noqa: E402
import l6_operators as lo  # noqa: E402
import l6_rate as lr  # noqa: E402
import l6_reader as lrd  # noqa: E402
import l6_schedule as ls  # noqa: E402
import l6_timing as lt  # noqa: E402
import p3_gate as g  # noqa: E402
import p3_genome as gn  # noqa: E402
import p3_oracle as po  # noqa: E402
from validators import records  # noqa: E402

TOOL_VERSION = "l6_runner.py/0.2.0"
# rec-v3 (prereg v0.4): the wire protocol THIS runner implements on the host side. An image
# or a frozen preregistration of another protocol is refused: a pull-v2 image would receive
# RECACK/RECGET lines it never reads, and a rec-v3 host would wait for records a pull-v2
# image never transacts.
HOST_PROTOCOL = "rec-v3"
RULING_TEXT = "whole-of-probe P3-L6"
PROVISION_RULING_TEXT = "provisioning P3-K"       # host/sign_arm.py's text; the signer re-checks it
SESSIONS = ("C1", "C2", "S")
L6_MANIFEST = R / "manifests/l6_manifest.json"
PREREG = R / "docs/l6_soak_prereg.md"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bind_ruling(ruling: dict, text: str, session: str, prereg_sha: str, image_sha: str,
                l6m_sha: str, master_seed: int | None) -> None:
    """A ruling authorises ONE session against ONE frozen prereg, ONE pinned image and ONE
    L6 manifest (and, for the L6 ruling, one master seed). Missing or mismatching bindings
    are refusals by name, so a C1 ruling cannot be spent on C2 or S, no ruling survives a
    re-freeze or a rebuild, and a swapped manifest — which carries the carrier pins, the
    soak duration and the calibration pins — is refused even with prereg/image/seed intact
    (board-phase preflight blocker 2; closing review blocker 1, owner 2026-09-01)."""
    want = {"session": session, "prereg_sha256": prereg_sha, "image_sha256": image_sha,
            "l6_manifest_sha256": l6m_sha}
    if master_seed is not None:
        want["master_seed"] = master_seed
    for k, v in want.items():
        if k not in ruling:
            raise bsn.SessionRefusal(f"ruling {text!r} is not bound: it lacks {k!r}")
        got = ruling[k]
        if k == "master_seed" and isinstance(got, str):
            try:
                got = int(got, 0)
            except ValueError:
                raise bsn.SessionRefusal(f"ruling {text!r}: master_seed {got!r} is not a number") from None
        if got != v:
            raise bsn.SessionRefusal(f"ruling {text!r} is bound to {k} = {got!r}, this session needs {v!r}")


def plan_session(l6m: dict, session: str, master_seed: int | None, duration_s: float,
                 calibration: dict | None, session_timeout_s: float | None) -> dict:
    """Everything derived BEFORE the session, pure: mode, N, the schedule, the audit seqs,
    the expected frames and CRC budget, the timeout, the flags word. `calibration` (S only)
    is {"C1": report dict, "C2": report dict} already hash-checked by the caller."""
    if session not in SESSIONS:
        raise ValueError(f"session {session!r} is not one of {SESSIONS}")
    spec = l6m["sessions"][session]
    pinned_seed = spec.get("master_seed")
    if not isinstance(pinned_seed, int) or not 0 <= pinned_seed <= ls.MASK32:
        raise ValueError(f"the manifest pins no 32-bit master seed for {session}")
    if master_seed is None:
        master_seed = pinned_seed
    if master_seed != pinned_seed:
        raise ValueError(f"master seed {master_seed:#x} is not the pinned {pinned_seed:#x} for {session} (owner 2026-09-01)")
    if session == "S" and duration_s != float(spec["duration_s"]):
        raise ValueError(f"the soak's duration must be exactly the pinned {spec['duration_s']} s, not {duration_s:g} "
                         f"(a shorter T shrinks both N and the 0.9 T floor)")
    mode = spec["mode"]
    inputs: dict = {"session": session, "mode": mode, "master_seed": master_seed}
    if session == "S":
        if not calibration or set(calibration) != {"C1", "C2"}:
            raise ValueError("the soak needs both calibration reports (C1, C2)")
        rates = {}
        contract = l6m["operator"]["operator_data_sha256"]
        pins = {"image_sha256": l6m["pinned_at_build"]["app_image_sha256"], "prereg_sha256": l6m["prereg"]["sha256"],
                "protocol": l6m["pinned_at_build"].get("protocol")}
        for k, rep in calibration.items():
            # prereg v0.4: a calibration is valid only for the image, preregistration and
            # protocol it ran under — a new image or protocol changes the nominal period.
            # The report carries its binding (l6_rate.binding_of); a report without one
            # (C1 #4, C2 #1 under v0.3/pull-v2) cannot be reused: C1 and C2 are re-run.
            b = rep.get("binding")
            if not isinstance(b, dict):
                raise ValueError(f"calibration report {k} carries no binding (made before prereg v0.4): "
                                 f"it cannot budget this soak — re-run {k} under the current image and protocol")
            for key, want in pins.items():
                if b.get(key) != want:
                    raise ValueError(f"calibration report {k} is bound to {key} {str(b.get(key))[:16]}…, this soak's pin is "
                                     f"{str(want)[:16]}… (a new image/prereg/protocol needs new C1/C2)")
            if b.get("session") != k or b.get("schedule_mode") != l6m["sessions"][k]["mode"] \
                    or b.get("master_seed") != l6m["sessions"][k]["master_seed"]:
                raise ValueError(f"calibration report {k}'s binding names session/mode/seed "
                                 f"{(b.get('session'), b.get('schedule_mode'), b.get('master_seed'))}, not "
                                 f"{(k, l6m['sessions'][k]['mode'], l6m['sessions'][k]['master_seed'])}")
            if rep.get("operator_data_sha256") != contract:
                raise ValueError(f"calibration report {k} ran under operator contract "
                                 f"{str(rep.get('operator_data_sha256'))[:16]}…, not the pinned {contract[:16]}… "
                                 f"(mutation_bits / map data changed: C1/C2 must be re-run)")
            if rep.get("session") != k or rep.get("schedule_mode") != l6m["sessions"][k]["mode"]:
                raise ValueError(f"calibration report {k} is not a {k} report of mode {l6m['sessions'][k]['mode']!r}")
            if not isinstance(rep.get("evals_per_hour"), (int, float)):
                raise ValueError(f"calibration report {k} carries no evals_per_hour")
            rates[k] = float(rep["evals_per_hour"])
        n = ls.soak_n(rates["C1"], rates["C2"], duration_s)
        timeout = ls.session_timeout_s(n, rates["C1"], rates["C2"])
        audit_policy = "sampled"
        audit_seqs = ls.sampled_audit_seqs(n, l6m["audit"]["every"])
        settle_med = [lc.median_settle_polls_from_report(calibration[k]) for k in ("C1", "C2")]
        inputs.update({"rate_C1_per_h": rates["C1"], "rate_C2_per_h": rates["C2"], "duration_s": duration_s,
                       "soak_fraction": ls.SOAK_FRACTION, "n_formula": "floor(0.9 × min(rate) × T)",
                       "timeout_formula": "1.25 × (N+2) × 3600/min(rate) + 600",
                       "settle_polls_median_calibration": settle_med})
    else:
        n = int(spec["n"])
        timeout = float(session_timeout_s) if session_timeout_s else float(l6m["sessions"]["S"]["duration_s"])
        audit_policy = "all-self-reporting"
        audit_seqs = ls.all_seqs(n)
        inputs.update({"timeout_source": "CLI --session-timeout-s (no calibration exists yet)"})
    sched = ls.schedule(master_seed, n, mode)
    expected = ls.expected_frames(n, audit_seqs, l6m["pinned_at_build"].get("protocol", "push-v1"))
    budget = ls.crc_budget(expected["total"])
    # rec-v3 (prereg v0.4): the forced REC-retry control is armed in EVERY session — the
    # opening baseline's record proves the real wire retry within seconds, preregistered
    return {"session": session, "mode": mode, "master_seed": master_seed, "n": n, "schedule": sched,
            "audit_policy": audit_policy, "audit_seqs": audit_seqs, "expected_frames": expected,
            "crc_budget": budget, "crc_formula": "ceil(4 × expected_total / 1000)",
            "session_timeout_s": timeout, "inputs": inputs, "protocol": HOST_PROTOCOL, "rec_retry_control": True,
            "flags": ls.flags_for(mode, watchdog=bool(l6m["pinned_at_build"]["watchdog_enabled"]), rec_control=True)}


def _plan_json(plan: dict) -> dict:
    return {**plan, "audit_seqs": sorted(plan["audit_seqs"])}


def expected_genomes(plan: dict, data: dict) -> dict[int, str]:
    return {row["seq"]: gn.to_hex(lo.OPERATORS[row["arm"]](row["seed"], data)) for row in plan["schedule"]}


def run_l6(session: bsn.BoardSession, out_dir: Path, ruling: dict, cfg: dict) -> dict:
    manifest = cfg["manifest"]
    phen = g.load_manifest()
    token = cfg["token"]
    plan = cfg["plan"]
    l6m = cfg["l6_manifest"]
    summary = {"tool": TOOL_VERSION, "ruling": ruling, "outcome": None, "token": token, "stages": {},
               "l6": _plan_json(plan), "findings": []}
    collector = n.Collector(token, heartbeat_s=cfg["heartbeat_s"])
    relay = n.NotaryRelay(token, cfg["signer"].sign_genome, drop_budget=plan["crc_budget"])
    timeline = lt.Timeline()
    reader = None

    def finish(rec, name):
        pr.write_record(out_dir, name, rec)
        summary["stages"][name] = rec.get("verdict", "recorded")

    def send(line: str, mtype: str, seq: int) -> None:
        l5.send_raw_line(session.transport, line)
        timeline.note_sent(mtype, seq, time.monotonic(), time.time())

    try:
        # ---- preamble: verbatim from host/l5_runner.py (steps 2–5) ---------------------
        summary["precheck"] = pr.precheck(session)
        summary["identity"] = session.verify_identity()
        l3.ensure_dcache_off(session)
        cpu_clk = session.read_word(l5.CPU_CLK_CTRL)
        preflight = {"stage": "L6_0_preflight", "CPU_CLK_CTRL": f"{cpu_clk:#010x}",
                     "addr": f"{l5.CPU_CLK_CTRL:#010x}", "verdict": "READ"}
        finish(preflight, "L6_0_preflight")
        summary["cpu_clk_ctrl"] = preflight["CPU_CLK_CTRL"]
        fclk = ob.fclk0_mhz(*[session.read_word(a) for a in
                              (ob.IO_PLL_CTRL, ob.ARM_PLL_CTRL, ob.DDR_PLL_CTRL, ob.FPGA0_CLK_CTRL)])
        summary["fclk0"] = fclk
        summary["setup_load"] = session.load_carrier(
            bsn.SETUP_LOAD_CAPABILITY, cfg["bitstream"], manifest["bitstream_sha256"], out_dir / "ymodem.log")
        summary["provisioning"] = cfg["signer"].provision(
            execute=cfg["provision_execute"], ruling=cfg["provision_ruling"])
        plane = l3.Plane(session)
        status = plane.read(po.STATUS)
        if not status >> po.ST["key_loaded"] & 1:
            raise l3.Stop("KEY_NOT_LOADED", f"STATUS {status:#010x}")
        nonce = plane.read(po.NONCE_LO) | plane.read(po.NONCE_HI) << 32
        page = l5.build_page(token, session.epoch, cfg["image_sha256"], manifest["bitstream_sha256"], nonce,
                             status, plan["master_seed"], plan["n"], plan["flags"], int(fclk["mhz"] * 1e6))
        for i, w in enumerate(page):
            session.command(f"mw.l {l5.PAGE_ADDR + 4 * i:#010x} {w:#010x} 1")
        readback = session.read_words(l5.PAGE_ADDR, len(page))
        if readback != page:
            raise l3.Stop("PAGE_MISMATCH", "the identity page did not read back as written")
        finish({"stage": "L6_1_identity_page", "words": [f"{w:08x}" for w in page],
                "flags": f"{plan['flags']:#x}", "verdict": "WRITTEN"}, "L6_1_identity_page")
        session.begin_ymodem(l5.APP_LOAD_ADDR)
        session.finish_ymodem(cfg["image"], out_dir / "ymodem_app.log", cfg["image"].stat().st_size)
        summary["image_loaded"] = {"addr": f"{l5.APP_LOAD_ADDR:#010x}", "sha256": cfg["image_sha256"],
                                   "bytes": cfg["image"].stat().st_size}

        # ---- the console belongs to the application; every line is stamped -------------
        # The L6 reader reads only what is waiting on the transport's own handle, so a
        # stamp is the read that completed the line (C1 #1 finding 2: psmap's drain()
        # returns only after 100 ms of silence and gave a whole candidate one stamp).
        reader = lrd.L6LineReader(session.transport._serial)  # noqa: SLF001 — same handle, same epoch
        l5.send_raw_line(session.transport, f"go {l5.APP_LOAD_ADDR:#x}")
        t_go = time.monotonic()
        # The collector was constructed before the preamble (minutes of carrier ymodem); its
        # silence clock starts NOW, when the application is handed the console. With the
        # blocking drain() the first poll only ran after the IDENT burst had refreshed the
        # clock, which hid this; with the non-blocking reader the first poll returned empty
        # and the preamble's minutes read as "silence > 30 s" — C1 #2 (2026-09-01-07) ended
        # 0.4 s after `go` on exactly that, with nothing heard. Silence is measured from `go`.
        collector.last_heard = collector.clock()
        deadline = t_go + plan["session_timeout_s"]
        console = lcs.ConsoleSession(token, collector, relay, timeline, plan["audit_seqs"], plan["crc_budget"], send,
                                     reader=reader, clock=time.monotonic)
        while collector.epoch_end is None and time.monotonic() < deadline:
            for line, t_mono, t_wall in reader.poll():
                console.on_line(line, t_mono, t_wall)
            console.tick()                           # fragments into the ledger; the pull's monotonic deadline
            if reader.saw_uboot_banner():
                collector.on_banner()
            collector.poll()
            time.sleep(0.02)
        if collector.epoch_end is None:
            collector._crash(f"the runner's own {plan['session_timeout_s']} s bound elapsed")

        # ---- assemble, adjudicate --------------------------------------------------------
        (out_dir / "console.log").write_bytes(bytes(reader.raw))
        (out_dir / "console.ts.log").write_bytes(timeline.console_ts_log())
        pr.write_record(out_dir, "timeline", timeline.to_json())
        summary["epoch_end"] = collector.epoch_end
        summary["audits"] = len(collector.audits)
        summary["fragments"] = len(timeline.fragments)   # torn lines quarantined by the reader (C1 #5)
        if collector.session_summary is None:
            # S #1 (2026-09-01-11): the crash-path summary said `audited 0` while the host
            # gate had verified 31, so the validator named rule (ix) instead of the seq gap.
            # The count is the HOST AUDIT GATE's marks (validators.audit.verify) — the same
            # derivation the validator uses — never a pull count, never the firmware's mark.
            gate_log = {"loop_records": collector.loop_records}
            audited_n, audited_src = lc.crash_audit_count(gate_log, collector.audits, phen)
            summary["crash_summary_audit"] = {"audited": audited_n, "total": len(collector.loop_records), "source": audited_src}
            collector.session_summary = collector.crashed_summary(
                audit={"audited": audited_n, "total": len(collector.loop_records)},
                crc_dropped=console.crc_dropped, drop_budget=plan["crc_budget"])   # the ledger, not the relay
        seqs = [r["seq"] for r in collector.loop_records]
        timing = lt.record_timing(timeline.frames, seqs)
        log = {"control_plane": "standalone", "app_identity": collector.app_identity,
               "loop_records": collector.loop_records, "session_summary": collector.session_summary,
               "notary_log": relay.notary_log(),
               "timing": {"clocks": lt.CLOCKS, "t_go_mono": t_go, "records": {str(s): timing[s] for s in seqs}},
               "l6": _plan_json(plan)}
        if collector.closing_negative is not None:
            log["closing_negative"] = collector.closing_negative
        pr.write_record(out_dir, "run_log", log)
        pr.write_record(out_dir, "audits", {"chunks": collector.audits, "pulls": console.pull_ledgers,
                                            "recs": console.rec_ledgers_json()})
        blank_commit = g.gate(g.build_streams(gn.frames_from_genome(gn.blank_genome(phen), phen), phen),
                              phen)["candidate_sha256"]
        findings = []
        try:
            v = records.validate_standalone_run_log(log, blank_commit, cfg["seed_nonce"], collector.audits, phen)
            summary["run_log_validation"] = {k: v[k] for k in ("scored", "audited", "chain_length")}
            summary["audit_verification"] = {str(k): d for k, d in v["audit"].items()}
            summary["audit_policy"] = records.check_audit_policy(
                log, v["marks"], plan["audit_policy"],
                plan["audit_seqs"] if plan["audit_policy"] == "sampled" else None)
            summary["arm_check"] = records.check_arm_schedule(log, plan["schedule"], plan["n"], cfg["expected_genomes"])
            summary["l6_identity"] = records.check_l6_identity(
                log["app_identity"] or {}, plan["master_seed"], plan["mode"], l6m["operator"]["operator_data_sha256"],
                protocol=plan["protocol"], rec_retry_control=bool(plan["flags"] & ls.FLAG_REC_CONTROL))
            findings += lc.structural_findings(log, collector.audits, plan["audit_seqs"], timeline.frames)
            findings += lc.baseline_findings(log)
            findings += lc.rec_closure_findings(log, console.rec_ledgers_json())      # v0.4 PASS condition 7
            findings += lc.rec_control_findings(console.rec_ledgers_json(), bool(plan["flags"] & ls.FLAG_REC_CONTROL))
            try:
                rep = lr.rate_report(log, plan["session"], hashlib.sha256(
                    json.dumps(log, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest(),
                    audits={"pulls": console.pull_ledgers, "recs": console.rec_ledgers_json()}, frames=timeline.frames)
                pr.write_record(out_dir, "rate_report", rep)
                summary["rate"] = {k: rep[k] for k in ("candidates", "evals_per_hour", "cov", "cov_wall", "failure_rate")}
                summary["rate"]["nominal_cov"] = (rep.get("nominal") or {}).get("cov")
                summary["rate"]["candidates_with_recovery"] = (rep.get("recovery") or {}).get("candidates_with_recovery")
                pc = l6m["pass_conditions"]
                if plan["session"] in ("C1", "C2"):
                    # the PASS rule follows the preregistration the session is bound to: v0.4
                    # bounds the inclusive CoV (C1 #5 = HOLD stays HOLD); the v0.5 DRAFT's rule
                    # applies only once the manifest pins v0.5 (nothing here re-judges C1 #5)
                    if str(l6m["prereg"].get("version")) == "v0.5":
                        findings += lc.calibration_findings_v05(rep, pc)
                    else:
                        findings += lc.calibration_findings(rep, pc["cov_max"])
                else:
                    med = min(x for x in plan["inputs"]["settle_polls_median_calibration"] if x is not None)
                    findings += lc.soak_findings(
                        log, timeline.frames, console.crc_dropped, plan["crc_budget"], rep["session_span_s"],
                        plan["inputs"]["duration_s"], pc["hb_gap_max_s"], med, pc["settle_bound_factor"],
                        pc["wall_fraction_min"])
            except lr.RateError as exc:
                findings.append(f"no rate report: {exc}")
            summary["findings"] = findings
            base = l5.outcome_for(collector.epoch_end)
            summary["outcome"] = base if base == "PASS" and not findings else (
                base if base != "PASS" else "HOLD instrument: " + "; ".join(findings))
        except records.RecordError as exc:
            summary["run_log_validation"] = f"REJECTED: {exc}"
            summary["outcome"] = l5.classify_rejection(exc)
    except l3.Stop as stop:
        summary["outcome"] = (f"KILL {stop.detail}" if stop.verdict == "KILL" else f"STOP {stop.verdict}: {stop.detail}")
    except pr.ProbeStop as stop:
        summary["outcome"] = f"STOP {stop.verdict}: {stop.detail}"
    except bsn.SessionRefusal as refusal:
        summary["outcome"] = f"REFUSED: {refusal}"
    except Exception as exc:  # noqa: BLE001 — any exception must still leave a summary
        import traceback
        summary["outcome"] = f"CRASHED host-side: {type(exc).__name__}: {exc}"
        summary["traceback"] = traceback.format_exc()
    finally:
        if reader is not None and not (out_dir / "console.log").exists():
            (out_dir / "console.log").write_bytes(bytes(reader.raw))
            (out_dir / "console.ts.log").write_bytes(timeline.console_ts_log())
        summary["uart_log"] = session.log
        summary["disruptions"] = session.disruptions
        summary["transport_rereads"] = session.rereads
        summary["epoch_final"] = session.epoch
        # the ONE inbound ledger (design review 2026-09-01): the relay never sees a CRC-failed
        # line, so its counter is not evidence of anything
        summary["crc_dropped"] = timeline.crc_dropped
        summary["crc_dropped_by_type"] = dict(timeline.crc_dropped_by_type)
        summary["bad_frames"] = timeline.bad_frames
        summary["crc_budget"] = plan["crc_budget"]
        pr.write_record(out_dir, "summary", summary)
    return summary


def preflight(a) -> dict:
    """The fail-closed checks, in the documented order. Returns cfg or raises SessionRefusal."""
    ruling = pr.check_ruling(a.ruling, text=RULING_TEXT)
    if a.session not in SESSIONS:
        raise bsn.SessionRefusal(f"--session must be one of {SESSIONS}")
    # blocker 1: provisioning is a board action with its own ruling; without one the L6
    # ruling must not be claimed and the port must not be opened
    if a.provision_ruling is None:
        raise bsn.SessionRefusal("--provision-ruling is mandatory for an L6 session: no `provisioning P3-K` ruling, no board contact")
    if a.provision_ruling.with_name(a.provision_ruling.name + ".consumed").exists():
        raise bsn.SessionRefusal(f"the provisioning ruling {a.provision_ruling} was already used")
    pk = pr._parse_ruling(a.provision_ruling, text=PROVISION_RULING_TEXT)
    l6m = json.loads(a.l6_manifest.read_text())
    l6m_sha = _sha(a.l6_manifest)      # the rulings bind THIS file: it carries every other pin
    pinned_prereg = l6m["prereg"]["sha256"]
    if not pinned_prereg:
        raise bsn.SessionRefusal("the L6 preregistration is not frozen (manifests/l6_manifest.json prereg.sha256 is null)")
    if pinned_prereg != _sha(a.prereg):
        raise bsn.SessionRefusal("docs/l6_soak_prereg.md does not hash to the frozen preregistration")
    pinned = l6m["pinned_at_build"]["app_image_sha256"]
    if not pinned:
        raise bsn.SessionRefusal("no pinned two-operator image (manifests/l6_manifest.json app_image_sha256 is null)")
    if not a.image.is_file():
        raise bsn.SessionRefusal(f"no application image at {a.image}")
    image_sha = _sha(a.image)
    if image_sha != pinned:
        raise bsn.SessionRefusal(f"the image is not the pinned one: {image_sha[:16]}… != {pinned[:16]}…")
    wd = l6m["pinned_at_build"]
    if not wd["watchdog_enabled"] or wd["watchdog_load_value"] != 1250000035 or wd["watchdog_prescaler"] != 7:
        raise bsn.SessionRefusal("D-s1: the watchdog must be pinned ON with prescaler 7 and load 1250000035")
    if not wd.get("board_ready"):
        raise bsn.SessionRefusal("the pinned image is not marked board-ready (freeze batch 2026-09-01: one image, one authority)")
    if wd.get("protocol") != HOST_PROTOCOL:
        raise bsn.SessionRefusal(f"the pinned image's protocol {wd.get('protocol')!r} is not this runner's {HOST_PROTOCOL} "
                                 f"(prereg v0.4): an image without the REC transaction cannot run under it")
    if l6m["prereg"].get("protocol") != HOST_PROTOCOL:
        raise bsn.SessionRefusal(f"the frozen preregistration is a {l6m['prereg'].get('protocol')!r} one; this runner "
                                 f"implements {HOST_PROTOCOL} — freeze prereg v0.4 first")
    # blocker 2: both rulings are bound to THIS session and to the frozen prereg + pinned image
    pinned_seed = l6m["sessions"][a.session].get("master_seed")
    bind_ruling(ruling, "whole-of-probe P3-L6", a.session, pinned_prereg, pinned, l6m_sha, pinned_seed)
    bind_ruling(pk, "provisioning P3-K", a.session, pinned_prereg, pinned, l6m_sha, None)
    # blocker 4: the frozen carrier, by the files' own hashes, not the CLI's word
    car = l6m["instrument"]["carrier"]
    if _sha(a.manifest) != car["manifest_sha256"]:
        raise bsn.SessionRefusal(f"the carrier manifest {a.manifest} does not hash to the frozen {car['manifest_sha256'][:16]}…")
    if not a.bitstream.is_file() or _sha(a.bitstream) != car["bitstream_sha256"]:
        raise bsn.SessionRefusal(f"the bitstream {a.bitstream} does not hash to the frozen carrier {car['bitstream_sha256'][:16]}…")
    calibration = None
    if a.session == "S":
        calibration = {}
        for k, path in (("C1", a.calibration_c1), ("C2", a.calibration_c2)):
            pin = l6m["calibration"][k]["rate_report_sha256"]
            if not pin:
                raise bsn.SessionRefusal(f"D-s3: no pinned {k} calibration record in the manifest")
            if path is None or not path.is_file():
                raise bsn.SessionRefusal(f"D-s3: --calibration-{k.lower()} must name the {k} rate report")
            if _sha(path) != pin:
                raise bsn.SessionRefusal(f"D-s3: {path} does not hash to the pinned {k} calibration record")
            calibration[k] = json.loads(path.read_text())
    if shutil.which("sb") is None:
        raise bsn.SessionRefusal("`sb` is not installed")
    manifest = json.loads(a.manifest.read_text()); records.validate(manifest)
    boundary = json.loads(a.boundary.read_text())
    records.boundary_established(boundary, time.time())
    # blocker 3: the D4 record is bound to this invocation — the OS user IS the runner
    # principal, the signer user and the key path ARE the record's
    me = pwd.getpwuid(os.getuid()).pw_name   # the effective UID's name, never LOGNAME/USER
    if boundary["runner_user"] != me:
        raise bsn.SessionRefusal(f"principal boundary: the record's runner_user {boundary['runner_user']!r} is not this OS user {me!r}")
    if boundary["signer_user"] != a.signer_user:
        raise bsn.SessionRefusal(f"principal boundary: --signer-user {a.signer_user!r} is not the record's {boundary['signer_user']!r}")
    want_key = os.path.normpath(os.path.join(boundary["key_store"], "K.bin"))
    if os.path.normpath(str(a.key)) != want_key:
        raise bsn.SessionRefusal(f"principal boundary: --key {a.key} is not the record's key store's {want_key}")
    if a.out.exists():
        raise bsn.SessionRefusal(f"{a.out} exists; evidence is never replaced")
    plan = plan_session(l6m, a.session, a.master_seed, a.duration_s, calibration, a.session_timeout_s)
    # prereg v0.4: the run log and its rate report carry the pins the session ran under, so
    # a calibration can never be reused for another image, preregistration or protocol
    plan["binding"] = {"image_sha256": image_sha, "prereg_sha256": pinned_prereg, "protocol": HOST_PROTOCOL,
                       "session": a.session, "schedule_mode": plan["mode"], "master_seed": plan["master_seed"]}
    data = lo.operator_data(g.load_manifest(), lo.load_local_map())
    if lo.operator_data_sha256(data) != l6m["operator"]["operator_data_sha256"]:
        raise bsn.SessionRefusal("the operator data regenerated from local_map.json is not the pinned derivation")
    return {"ruling": ruling, "l6_manifest": l6m, "manifest": manifest, "bitstream": a.bitstream,
            "image": a.image, "image_sha256": image_sha, "plan": plan, "expected_genomes": expected_genomes(plan, data),
            "signer": l3.SubprocessSigner(a.key, signer_user=a.signer_user),
            "provision_execute": a.provision_ruling is not None, "provision_ruling": a.provision_ruling,
            "token": secrets.token_hex(16), "seed_nonce": int(car["nonce_seed"], 16),
            "heartbeat_s": l6m["protocol"]["heartbeat_s"]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ruling", type=Path, required=True)
    ap.add_argument("--session", required=True, help="C1 | C2 | S")
    ap.add_argument("--master-seed", type=lambda s: int(s, 0), default=None,
                    help="optional; must equal the manifest's pinned seed for the session (owner 2026-09-01)")
    ap.add_argument("--provision-ruling", type=Path, default=None)
    ap.add_argument("--boundary", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True, help="the carrier manifest")
    ap.add_argument("--l6-manifest", type=Path, default=L6_MANIFEST)
    ap.add_argument("--prereg", type=Path, default=PREREG)
    ap.add_argument("--bitstream", type=Path, required=True)
    ap.add_argument("--image", type=Path, default=R / "firmware/bsp/out/p3_app_l6.bin")
    ap.add_argument("--key", type=Path, default=Path("/var/lib/p3signer/keys/K.bin"))
    ap.add_argument("--signer-user", default="p3signer")
    ap.add_argument("--port", default=bsn.PORT)
    ap.add_argument("--duration-s", type=float, default=7200.0, help="T for the soak (D-s3); must equal the pinned 7200 s")
    ap.add_argument("--session-timeout-s", type=float, default=None, help="C1/C2 only; S derives its own")
    ap.add_argument("--calibration-c1", type=Path, default=None)
    ap.add_argument("--calibration-c2", type=Path, default=None)
    a = ap.parse_args(argv)
    try:
        cfg = preflight(a)
    except (bsn.SessionRefusal, pr.ProbeStop, ValueError, records.RecordError, OSError, KeyError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    consumed = pr.claim_ruling(a.ruling)
    a.out.mkdir(parents=True)
    l3._install_sigterm()
    outcome = "CRASHED before a summary was written"
    try:
        transport = bsn.SerialTransport(a.port)
        try:
            outcome = run_l6(bsn.BoardSession(transport), a.out, cfg["ruling"], cfg)["outcome"]
        finally:
            transport.close()
    except bsn.SessionRefusal as exc:
        outcome = f"REFUSED: {exc}"
    finally:
        pr.record_outcome(consumed, outcome)
        if a.provision_ruling:
            l3._record_pk(a.provision_ruling, outcome)
    print(outcome, file=sys.stderr if outcome != "PASS" else sys.stdout)
    return 0 if outcome == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
