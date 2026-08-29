# Whole-line gate review — result (2026-08-29, non-author, relayed by the owner)

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
