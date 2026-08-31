# D1 specification review #1 — verdict: HOLD (2026-08-31)

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
