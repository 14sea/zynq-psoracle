# Whole-line gate review — result (2026-08-29, non-author, relayed by the owner)

> **Status note (2026-08-31):** statements about rung status in this document are historical — what was true when it was written. The canonical status is `docs/status.md`.


Verdict: **HOLD. No `P3-L2` ruling; no board contact.**

Verbatim (owner's relay):

> 整體 gate review 結論：HOLD，暫不建立 P3-L2 ruling，也不碰板。
>
> 主要 blocker 是 D4 鑰匙保管模型：
> - gate-signer 與 runner 目前是同一 OS user 的不同 process；
> - runner 為了 setup load 必須讀取 keyed bitstream；
> - keyed bitstream 本身被文件承認是 key material，且 K 以常數烤入 bitstream；
> - 因此「runner process 沒有 KeyHolder」不等於 runner principal 無法取得或離線分析 K。這不足以支撐「只有 gate 能產生有效 ARM」的 authority 宣稱。
>
> 需要在上板前補一個真正的 principal boundary，例如：
> - signer 使用不同 OS user/受限服務，runner 無法讀取 key 或 keyed bitstream；
> - 或使用外部/HSM/硬體 signer；
> - 並在測試與文件中把「可讀 keyed bitstream」與 key custody 的關係釘清楚。
>
> 其他項目方向大致可接受：L2/L3 runner 順序與 fake 負向控制；link 1–3 的責任分界；sticky fault 導致每個 negative control 需獨立 ruling；L2 heartbeat 上下界與 control-first；目前沒有已觸發的 line-wide kill criterion。
>
> 另外，L0 文件仍寫著 not marked PASS，需與先前 L0 exit 覆核結果同步；但這是狀態紀錄問題，不取代 D4 blocker。
>
> 在 D4 修正並重新覆核前，不批准 P3-L2/P3-L3 ruling 或任何板上操作。

Standing after the verdict: L2/L3 tooling direction accepted; **D4 is the blocker**;
proposal in `docs/d4_principal_boundary.md`; re-review required before any ruling.

## Re-review result (2026-08-29, later — after D4 option A + host principal)

Verdict (owner's relay, verbatim):

> 逐項檢查結果：D4 principal boundary 已解除，整體可接受。
> 已確認：/tmp 無殘留 provisioning script；runner 身分執行 R1–R5 全部通過；runner 端沒有 K.bin，只保留 nonce seed；signer 回傳的 key_id 與既有 manifest 一致；sudoers 僅允許執行 sign_arm.py；repo 乾淨、215 tests 通過、psmap 未修改。
> sudoers 尾端的 * 是一項應收緊的防禦性改善，但目前不構成 D4 blocker：sign_arm.py 只接受 key path，KeyHolder 僅接受 16-byte/0400 檔案，輸出也不包含 K；即使 runner 指向其他檔案，也不能取得固定 PL key。仍建議在上板前把 wildcard 改成固定 signer key 路徑（必要時另列 control key），以縮小 signer service 的輸入面。這可納入 re-review delta，不需重新推翻目前 D4 結論。
> 目前裁決：D4：PASS；L1 host/build/principal preparation：PASS；P3-L2/L3 ruling：尚未建立；板上操作：仍需新的 whole-of-probe ruling；在 ruling 建立前不要碰板。

Standing: **D4 PASS, L1 preparation PASS.** Sudoers wildcard → fixed paths (setup script
updated; the owner re-applies it with sudo before the board). No ruling exists; no board contact.
