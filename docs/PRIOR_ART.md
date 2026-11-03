# Prior art

Added 2026-11-03 after a full-text literature review and a check against AMD
documentation. Additive only: this repository is archived, and no existing document,
manifest or result is changed by this file.

| What this repo does | Prior work / vendor documentation | Status |
|---|---|---|
| PS-side PCAP readback as the oracle for what the fabric holds | AMD UG585 (Device Configuration Interface, `XDcfg_PcapReadback()`); readback CRC and the SEM IP (UG470 v1.17) | **Vendor feature** — inherited via `zynq-psmap` |
| Authenticating configuration traffic with a keyed MAC | Zynq-7000 secure boot / bitstream authentication with AES + HMAC (UG585 v1.15, *Device Secure Boot* and DevC AES/HMAC engines) | **Same family of idea**; this repo applies a MAC to an *application-level* write transaction on the author's own board, not to the boot image |
| Measured load of bitstreams by digest | Standard measured-boot practice | Not new |
| Preregistered acceptance ladder (L0–L6), owner-signed rulings, fail-closed offline adjudication, negative controls | No published equivalent found in the 2026-11 search of the evolvable-hardware and FPGA-reconfiguration literature (provisional) | What this repo adds is **evidence practice**, not a mechanism |

References: AMD UG585 v1.15, UG470 v1.17, XAPP538 v1.0 (2012).
