# L3 diagnostic — localising session #1's LINK3_MISMATCH (specification)

Status: host-only, 2026-08-30, approved in outline by the owner; ruling text
`whole-of-probe P3-L3-diag`. Runner `host/l3_diag_runner.py`; terminal JTAG helper
`host/l3_diag_jtag.py` (runs as the signer principal, the pod's owner); fake tests
`tests/test_l3_diag.py`.

## Question

After three envelope writes in one session, `0x00400A20` read back BLANK over PCAP,
although L2 read the same envelope-0 write bit-exact. Is the frame blank in the fabric
(later writes cleared or misplaced it), or does PCAP readback return zeros after
multi-envelope writes?

## Sequence (one ruling, consumed by the PCAP phase whatever happens)

```
setup load
→ env0 write → read A20
→ env1 write → read A20, C1A
→ env2 write → read A20, C1A, C20
→ seal (sha256 of every record) → jtag_request.json
→ terminal JTAG read of A20, C1A, C20   (signer principal; nothing after it)
```

Expected content: `A20` = the known answer's frame (`15cb05e6…`); `C1A`, `C20` = base
(blank). Every write and every read leaves its full record. No ARM, no provisioning.

## Stop semantics

- A link-3 mismatch in phase k ends **all further PCAP writes**. The reads listed for
  phase k are completed, then one **closing read** of {A20, C1A, C20} (non-destructive),
  then the seal. Later phases' writes and reads do not happen.
- The JTAG read is terminal and runs once (`--jtag` refuses if `jtag.json` exists) and only
  after `sealed.json` exists. The seal's sha256 is in `jtag_request.json`.
- Any session refusal / host exception is recorded as the outcome; the seal is still
  written over whatever records exist.

## Adjudication (pure, `adjudicate`)

Per FAR, last PCAP verdict/sha (closing read if it happened) vs JTAG sha vs expected:

| PCAP | JTAG | kind |
|---|---|---|
| PASS | = expected | CONSISTENT |
| not PASS, sha = blank | = expected | **PCAP_READBACK_ZERO** (fabric holds the write; readback path) |
| not PASS | = blank, expected ≠ blank | **FABRIC_BLANK** (write cleared/misplaced) |
| any | ≠ blank where expected = blank | **FABRIC_MISPLACED** (candidate content where base should be) |
| else | | DIVERGENT |

Session verdict = NO_REPRODUCTION (all CONSISTENT) / PCAP_READBACK_ZERO / FABRIC_BLANK /
FABRIC_MISPLACED / DIVERGENT; HOLD if JTAG did not read. `STAT.CRC_ERROR` is reported.

## Principal boundary for the JTAG step

The pod is owned by `p3jtag`; the runner cannot open it. `host/l3_diag_jtag.py` runs as
`p3signer` via one sudoers line restricted to the evidence directory prefix:
`test ALL=(p3signer) NOPASSWD: /usr/bin/python3 /home/test/zynq_psoracle/host/l3_diag_jtag.py /home/test/zynq_psoracle/evidence/*`
(the helper takes exactly one argument; extra words are rejected). It writes nothing into
the evidence directory; the runner saves its stdout as `jtag.json`.
