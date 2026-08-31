# L5 post-build package — review result

Non-author review of the post-build package (`docs/l5_findings.md`, `docs/l5_prereg.md`,
`manifests/l5_manifest.json`), relayed by the owner, 2026-08-31.

## Verdict: HOLD — one provenance blocker; everything else accepted.

## Review, verbatim (relayed)

> 逐項覆核結果：post-build package 暫 HOLD，尚不能進入 push／ruling／上板。主要 build 與 watchdog 修正都成立，但有一個 provenance blocker。
>
> 已確認可接受：
>
> - watchdog_enabled=false、watchdog_load_value=null、identity flag bit1=0；
> - watchdog-off 下的 CRASHED／host recovery 流程已寫入 prereg；
> - CPU clock readback 已列為上板前 blocking preflight；
> - image hash 已在零 firmware 變更下固定；
> - 新增 WDT audit 是 strengthening，不是放寬 gate，且沒有改變 prereg 的板上操作；
> - closure 漏洞已修正，341 tests 在 tracked／manifest 完整狀態下通過。
>
> 仍需處理：
>
> 1. BSP 來源不可重現性尚未達 build gate
>
>    p3_app.c 的 image 依賴本機 /home/test/Xilinx/2025.2/data/embeddedsw，但約 25 個 BSP source 未進 repo，也未逐檔 hash 釘在 manifest。現在的 app_image_sha256 只能證明「這台主機上的那份 BSP + xPack」產物，不足以讓 post-build package 完整重現。
>
>    在上板前至少要做其中一項：
>     - 將實際使用的 BSP 檔案逐檔列入 manifest，含相對來源路徑、大小、SHA256、版本；
>     - 或 vendor 這些檔案（若授權允許）。
>
>    不必因此修改 firmware 或重新設計，但 manifest 必須能檢查 build 所使用的 BSP exact inputs。
>
> 2. build.sh 必須在 clean／staged 狀態下重新執行一次，並把：
>     - toolchain SHA；
>     - BSP input manifest；
>     - linker map；
>     - image SHA；
>     - 341 tests / 0 skipped
>
>    一起寫入 post-build evidence。
>
> 3. 這輪 source-audit strengthening 應在 prereg §7 旁明確標成「防禦性測試增加、未改變執行語義」，避免被解讀成事後改 gate。
>
> 完成上述 BSP provenance 後，提交一次更新 package；若沒有其他差異，我會一次裁定 push、P3-L5/P3-K rulings 與首個 N=8 session。

## Per-item disposition (each checked against the source before fixing)

Every "已確認可接受" item was re-checked and is true as stated. The three open items were
each confirmed against the repo and then addressed — all host-only, no firmware change, no
board contact, no push.

**Blocker 1 — BSP source provenance. CONFIRMED, FIXED.**
Confirmed against `firmware/bsp/build.sh`: it compiles Xilinx `embeddedsw` sources
(`standalone_v9_4`, `scuwdt_v2_6`) in place from `/home/test/Xilinx/2025.2/…`; none were
hashed in any manifest, so `app_image_sha256` was reproducible only relative to this host's
tree (this repo's own `docs/l5_findings.md` §6 and `import_manifest.md` already recorded it as
a reproducibility limit). Took the reviewer's lighter option (pin, not vendor — avoids the
licence question and keeps the firmware untouched), and made it rigorous:
- `manifests/l5_bsp_inputs.json` pins **65** embeddedsw files — every source build.sh compiles
  **and their full header closure** — by path (relative to the embeddedsw root), size, sha256,
  and package/version dir. Not a hand-written "~25" list: `host/gen_bsp_input_manifest.py`
  derives it from the pinned toolchain's own `gcc -M` dependency output, so a header the build
  actually reads cannot be omitted.
- `tests/test_bsp_inputs_manifest.py` re-hashes every entry against the tree on this host
  (skips only that recompute when the tree is absent, e.g. a reviewer sandbox — structure is
  still checked fail-closed), asserts every source build.sh names is pinned, and guards the
  generator's list against build.sh drift.
- `manifests/l5_manifest.json` `pinned_at_build.bsp_inputs` now points at it;
  `docs/l5_findings.md` §6 and `import_manifest.md` narrowed from "reproducible only against
  whatever tree this host has" to "reproducible against this *identified* input set + the
  pinned toolchain" (verified: rebuilt → `7540239f…`, byte-identical).

**Blocker 2 — post-build evidence bundle. CONFIRMED, FIXED.**
`build.sh` re-run; image reproduced byte-identical. `host/gen_build_evidence.py` writes
`evidence/l5_build/build_evidence.json` (git state, toolchain sha, BSP-input-manifest sha,
linker-map sha, image sha with `reproduced_byte_identical: true`, and a pointer to the
fail-closed test report) and a tracked copy of the linker map `evidence/l5_build/p3_app.map`.
The test count/skip standing stays in its own fail-closed artifact under `evidence/tests/`
(`host/run_tests.sh`), which the bundle references rather than duplicates. The suite was run
in a **staged** state so the two-way import closure covers the new files.

**Item 3 — mark the strengthening in prereg §7. CONFIRMED, DONE.**
§7 already framed the watchdog-gating audit test as a strengthening; added a paragraph
covering this round's provenance additions (`l5_bsp_inputs.json` + its test,
`evidence/l5_build/`) as **defensive additions that do not change execution semantics** —
they pin/re-hash inputs, touch no firmware, change no image, and alter no board operation.

## State after the fix
Host-only throughout. No firmware source changed; image unchanged (`7540239f…`). Local commit
only — **not pushed** (push stays the owner's call). Awaiting the owner's re-review; on
approval the reviewer said they would rule push + `P3-L5`/`P3-K` + the first N=8 session in one
go.
