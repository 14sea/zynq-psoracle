# D1 specification reviews — #1: HOLD, #2: ACCEPTED WITH Q7 CONDITION (2026-08-31)

## Review #2 — v0.2, verdict: **ACCEPTED WITH Q7 CONDITION** (2026-08-31)

Non-author re-review of v0.2, relayed verbatim by the owner. Not an L5 build or board
authorisation. Q1–Q6 accepted as scoped; Q7 accepted on the condition that the C↔Python
corpus's `N` is pinned in the L5 design/manifest, not left as an unbound quantifier.
**Discharged the same day: `N = 256`, pinned in `fixtures/d1_corpus_v1.json` (entry 0 =
the blank candidate, entry 1 = the known answer, entries 2–255 deterministic per-index
seeds) and in `docs/l5_design.md`.** The owner also established the batch-authorisation
working mode, recorded as `docs/decisions.md` D5.

---

> 我逐項重審 v0.2。結論：上輪四個 blocker 已正確關閉，沒有再發現同級缺陷；D1 可評為「接受但
> 附條件」。這不是 L5 build 或上板授權。
>
> 逐項裁決：
>
> 1. Q1：接受狹義定義。host 不搜尋、排序、計分，只對每個候選執行 gate/signature veto；這仍是
>    permission authority，但不屬於 search loop。文件已誠實揭露此界線。
> 2. Q2：接受，作為明示 downgrade。app_oracle_record 不得替代 L2–L4 的 host-observed
>    oracle_record；raw ring、audit、post-run replay 只能提供有限保證，文件目前表述正確。
> 3. Q3：接受 T1。console relay 有既有 L2–L4 證據基礎；T2 必須另做非擾動驗證，不能直接切換。
> 4. Q4：接受 session brackets。COMPLETED、STOPPED、PROTOCOL 的 closing obligations 已分開
>    定義；closing unsigned ARM 放最後也合理。
> 5. Q5：接受 watchdog on。只由主迴圈在 framed line 後 kick，watchdog reset 歸類 CRASHED，且
>    不虛構 terminal/ring evidence，這點已封閉。
> 6. Q6：接受 host-supplied seed。L5 必須在標題或狀態中明示這是 deterministic/test mode，不得
>    宣稱 autonomous discovery；文件已有此限制。
> 7. Q7：有條件接受。C↔Python corpus 是正確 exit gate，但 N random genomes 的 N 必須在 L5
>    design/manifest 中釘死，不能保留為未定量詞。
>
> 我也確認了上輪指出的四項已同步：refusal 與 epoch taxonomy 不再矛盾；framing 使用完整
> 128-bit token；identity page 使用完整 256-bit carrier hash，且不宣稱 app 自行驗證
> bitstream；watchdog crash 不再要求不存在的 terminal/ring dump。
>
> 因此建議：將 D1 狀態記為 reviewed: ACCEPTED WITH Q7 CONDITION；補一個明確的 corpus N；經你
> 確認後才進入 contracts/L5 design host-only 工作；不因此授权 L5 build、ruling 或板上操作。

The owner confirmed entry into the contracts / L5-design host-only batch the same day,
with the D5 working mode:

> 之後採「批次授權」：host-only 規格、validator、測試、文件同步：在既定範圍內連續完成，不逐步
> 請示。上板前一次提交整體 review package，我做批次覆核。通過後由你一次授權該階段的 build、
> ruling 與板上序列；不再為每個小步驟單獨請示。若發現超出已授權範圍、規格矛盾或 stop-loss
> 事件，才中途暫停並回報。目前 D1 v0.2 可按上述方式進入下一批 host-only 工作；Q7 的 corpus N
> 仍需在 L5 design/manifest 中釘死。

---

# Review #1 — v0.1, verdict: HOLD (2026-08-31)

Non-author review of `docs/d1_standalone_spec.md` v0.1, relayed verbatim by the owner.
The reviewer modified no files and authorised no L5 build, no ruling, no board contact.
Recorded verbatim below (as relayed, in the reviewer's language); the specification's
v0.2 revision addresses it item by item (see the spec's §12 change log).

---

> 審核結論：HOLD，尚不能接受為 L5 規格。我沒有修改檔案，也沒有授權 L5 build、ruling 或上板。
>
> 主要 blocker：
>
> 1. notary refusal 的 epoch 語義自相矛盾
>     - §3c（約 154–158 行）把 notary refusal 列為立即終止 epoch。
>     - §4.3（sign refusal）卻明定拒絕是搜尋正常流程，記錄後繼續下一個 genome。
>
>    必須二選一並統一所有 schema、validator、session_summary 與 watchdog 行為。若 gate refusal
>    可繼續，應明確區分 REFUSED_BY_GATE 與會終止 epoch 的 transport/protocol failure。
>
> 2. session token 實際只傳 32 位
>
>    §3 使用 128-bit token，但 §5b framing 是 token_lo32。因此 host 不能驗證完整 session token，
>    存在碰撞／錯綁風險；§3c 所稱「token consistency」也沒有完整實現。
>
>    應改成完整 128-bit token，或明確引入不可碰撞的 session handle 並說明其安全性。不能用低
>    32 位宣稱綁定 128 位 identity。
>
> 3. carrier identity 也只保留低 32 位
>
>    identity_page.carrier_sha_lo32 與 app_identity 僅記錄低 32 位，完整 hash 只在 host log。
>    應說明 app 端究竟如何確認載入的是完整指定 carrier；否則這只是弱標識，不能支撐「同一
>    carrier instance」的完整語義。
>
> 4. watchdog／終止時序仍未封閉
>
>    §3c 說 watchdog 只產生 reset、沒有 terminal line；§4.7 又要求 STOP 時完整 dump ring。需明確
>    規定 watchdog 觸發時 ring 是否、如何、由誰保存，以及 host 將其分類為 HOLD、CRASHED 或其他
>    outcome。
>
> 次要但需在 L5 design 固化：
>
> - §4.0 要求 closing baseline，但 §3c 的 budget/stop condition 可先結束 epoch；需規定 closing
>   restore 是不可跳過的 finally 還是條件式。
> - §4.7 的 audit 是機率性偵測，不是完整證明；文件目前有承認，但 validator／L5 acceptance 必須
>   明確寫成有限保證。
> - §5c「host 不在 decision loop」只成立於「不搜尋、不排序、不計分」的狹義定義；signer 仍決定
>   哪些 candidate 允許執行，Q1 必須由覆核者明確接受這個定義。
> - §4.6 對 configuration_valid_hw=0 的兩種原因仍寫成 F_ARM_TABLE 或 F_ARM_AUTH，應避免暗示可由
>   現有觀測排他診斷。
>
> 建議修正順序：
>
> 1. 先統一 refusal／epoch／closing-baseline 狀態機。
> 2. 封閉完整 token 與 carrier identity 綁定。
> 3. 定義 watchdog crash 的證據保存及 verdict。

---

Author's verification against the v0.1 text before revising (all four blockers confirmed
real, none disputed): §3c did list "a notary refusal, timeout, or malformed reply" in one
epoch-ending clause while §4.3 said a refusal continues the loop; §5b's frame carried
`token_lo32` only; the identity page carried `carrier_sha_lo32` only; the watchdog path had
no defined evidence disposition. The four secondary items are likewise accepted as written.
