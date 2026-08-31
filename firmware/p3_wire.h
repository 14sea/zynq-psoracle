/* p3_wire — the standalone application's wire serialisation, as a pure unit.
 *
 * WHY THIS FILE EXISTS. The first L5 board attempt was blocked because the C
 * application's framed output had never been checked against the host validator that
 * consumes it: records were emitted flat (no `seq`, no `verified`, no nested `evidence`),
 * no `IDENT` was ever sent although `validate_standalone_run_log` requires `app_identity`,
 * and no heartbeat was sent although the collector calls 30 s of silence a CRASH. The
 * host-only rehearsal had validated `host/l5_refloop.py` -- the *Python* reference -- so
 * every test was green while the C wire format was incompatible.
 *
 * The fix is structural, and it is the same move `p3_derive.c` already makes for the
 * hashes: everything provable on the host lives in a unit with no MMIO and no board
 * dependency, so a host test can compile THIS source, drive it, and feed the bytes it
 * produces to the real Python validator (`tests/test_firmware_wire_contract.py`). What
 * stays in `p3_app.c` is the HAL and the state machine. A green test here is therefore
 * evidence about the bytes the board will actually emit, not about a model of them.
 *
 * Every builder writes compact JSON with sorted keys into a caller buffer and returns the
 * length, or 0 if it would not fit (callers treat 0 as a PROTOCOL-class failure and never
 * emit a truncated line).
 */
#ifndef P3_WIRE_H
#define P3_WIRE_H

#include <stddef.h>
#include <stdint.h>

#define P3_WIRE_SCORES 6
#define P3_WIRE_TOKEN_HEX 32
#define P3_WIRE_SHA_HEX 64
#define P3_WIRE_GENOME_HEX 80
#define P3_WIRE_TABLE_HEX 16
#define P3_WIRE_TAG_HEX 32

/* ------------------------------------------------------------------ framed line ----- */

/* "P3L5 <type> <seq> <token> <payload> <crc32>\n" (spec 5b: the FULL 128-bit token).
 * `payload` is already base64url, or "-" for a payload-less type such as HB. */
size_t p3_wire_line(const char *type, uint32_t seq, const char *token,
                    const char *payload_b64, char *out, size_t max);

/* ------------------------------------------------------------------ app_identity ---- */

typedef struct {
    uint32_t pss_idcode;
    const char *token;          /* 32 hex */
    uint32_t uboot_epoch;
    const char *carrier_sha256; /* 64 hex */
    uint64_t nonce_at_start;
    uint32_t status_at_start;
    uint32_t fclk0_hz_decoded;
    uint32_t app_epoch;
    const char *const *findings; /* may be NULL when n == 0 */
    int findings_n;
} p3_wire_identity_in;

size_t p3_wire_identity(const p3_wire_identity_in *in, char *out, size_t max);

/* ------------------------------------------------------------------ sign_request ---- */

size_t p3_wire_sign_request(const char *token, uint32_t app_epoch, uint32_t seq,
                            const char *genome_hex, uint64_t nonce, char *out, size_t max);

/* ------------------------------------------------------------------ loop_record ----- */

/* One candidate. The `have_*` flags select the evidence members, which the validator
 * requires to match the outcome exactly (see validators/records.py _check_loop_record):
 *   REFUSED_BY_GATE      -> sign_refusal only
 *   STOP_AXI, STOP_LINK2 -> sign_reply (no arm, no score)
 *   STOP_LINK3           -> sign_reply + app_oracle_record (no arm, no score)
 *   REFUSED_BY_PL        -> sign_reply + app_oracle_record + arm (no score)
 *   SCORED               -> sign_reply + app_oracle_record + arm + score
 */
typedef struct {
    uint32_t seq;
    const char *genome;   /* 80 hex */
    const char *outcome;  /* one of LOOP_OUTCOMES */
    int audited;          /* -> "verified": "audited" | "replayed-only" */

    int have_sign_refusal;
    const char *const *finding_kinds;
    int finding_kinds_n;

    int have_sign_reply;
    const char *commit;                          /* 64 hex */
    const char *tables[P3_WIRE_SCORES];          /* 16 hex each */
    const char *tag;                             /* 32 hex */

    int have_oracle;
    const char *staged_sha256;                   /* 64 hex */
    const char *staged_stream_sha256;            /* 64 hex, a different domain */
    const char *readback_sha256;                 /* 64 hex */
    int envelopes_n;
    const uint32_t *envelope_int_sts;            /* envelopes_n words, may be NULL */
    int audit_available;

    int have_arm;
    uint64_t nonce_before, nonce_after;
    uint32_t status_after, fault_after;
    int key_loaded_observed;

    int have_score;
    const char *hw_candidate_commit;             /* 64 hex */
    const char *readout[P3_WIRE_SCORES];         /* 16 hex each */
    uint32_t scores[P3_WIRE_SCORES];
    uint32_t hb_before, hb_after;
} p3_wire_record_in;

size_t p3_wire_loop_record(const p3_wire_record_in *in, char *out, size_t max);

/* ------------------------------------------------------------------ audit ----------- */

/* One chunk of the raw words held in the evidence ring for candidate `seq`. The collector
 * reassembles `chunk`/`chunks`, recomputes both link-2 hashes and the link-3 hash, and
 * compares them with the compact record it already holds (spec 4.7). `words_b64` is
 * base64url of the chunk's words, big-endian, 4 bytes each. */
size_t p3_wire_audit(uint32_t seq, uint32_t chunk, uint32_t chunks, uint32_t word_offset,
                     uint32_t word_count, const char *words_b64, char *out, size_t max);

/* ------------------------------------------------------------------ closing control - */

/* The closing unsigned ARM (spec 4.0) is NOT a loop_record: "CLOSING_CONTROL" is not one of
 * LOOP_OUTCOMES, and the validator reads it from the log's own `closing_negative` key. It
 * travels as its own frame type so the collector can file it there. */
size_t p3_wire_closing(uint64_t nonce_before, uint64_t nonce_after, uint32_t fault,
                       uint32_t status, char *out, size_t max);

/* ------------------------------------------------------------------ summary --------- */

typedef struct {
    const char *token;
    const char *kind;        /* COMPLETED | STOPPED | PROTOCOL */
    const char *reason;
    uint32_t last_seq;
    uint32_t scored, refused_by_gate;
    int closing_restore, closing_baseline, closing_unsigned; /* -> done | not_reached */
    uint32_t audited, total;
    uint32_t crc_dropped, drop_budget;
} p3_wire_summary_in;

size_t p3_wire_summary(const p3_wire_summary_in *in, char *out, size_t max);

#endif /* P3_WIRE_H */
