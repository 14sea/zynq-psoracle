/* p3_rectx — the REC transaction (rec-v3), as a pure unit with injected I/O.
 *
 * WHY THIS FILE EXISTS. S #1 (2026-09-01-11) lost ~536 bytes inside `REC 465` on the
 * console; the line failed CRC, the collector saw seq 466 after 464 and ended the epoch.
 * The pull protocol could re-request any audit chunk but not the record itself. From
 * rec-v3 on, a record is a TRANSACTION: the application sends the line, then waits — with
 * a bound — for the host's `RECACK` (accepted) or `RECGET` (arrived broken: send it again),
 * and resends the SAME bytes on a RECGET or when the bound runs out, at most
 * P3_RECTX_ATTEMPTS times. Without an acknowledgement the application does not propose the
 * next candidate: the caller stops the epoch (`STOP_REC`, restore, TERM).
 *
 * The state machine lives here, with no MMIO and no console dependency, so the SAME source
 * the board image links is compiled on the host (firmware/p3_wire_twin.c `rectx`) and
 * driven by tests/test_firmware_wire_contract.py over a pipe: the host test plays the
 * runner, sending RECACK/RECGET/garbage/nothing, and judges the bytes and the attempt
 * count this code actually produces. `p3_app.c` supplies the I/O (put_str + watchdog kick,
 * the bounded RX-FIFO poll, its frame parser and JSON scan) and nothing of the logic.
 *
 * The preregistered control (identity page flags.bit4, `P3_RECTX_CONTROL_FLAG`): when the
 * caller asks for it, the FIRST transmission is sent with the last hex digit of its CRC
 * field flipped — a deliberate, recorded CRC failure on the wire — so that every session
 * proves the real retry on its opening baseline within seconds. Only attempt 1; the resend
 * is the true line.
 */
#ifndef P3_RECTX_H
#define P3_RECTX_H

#include <stddef.h>
#include <stdint.h>

#define P3_RECTX_ATTEMPTS 3u        /* the first transmission + two retries */
#define P3_RECTX_CONTROL_FLAG 16u   /* identity page flags.bit4: forced REC-retry control */
#define P3_RECTX_STALE_LIMIT 64u    /* lines of the wrong type/seq ignored per wait, then the bound */

typedef struct {
    /* put the whole line on the wire (framing already done); 0 ok, -1 channel failure */
    int (*send)(const char *line, size_t n, void *ctx);
    /* one host line into `out` (no newline): >= 0 length, -1 over-long (discard, keep
     * waiting), -2 the bounded wait ran out with nothing received */
    int (*recv_bounded)(char *out, size_t max, void *ctx);
    /* magic + CRC + token; on success fills type (NUL-terminated), the frame seq and
     * returns the payload field, else NULL. May mutate `line`. */
    const char *(*parse)(char *line, char *type_out, size_t type_max, uint32_t *seq_out, void *ctx);
    /* the payload's own "seq" field; 0 ok, -1 absent/unreadable */
    int (*payload_seq)(const char *payload_b64, uint32_t *seq_out, void *ctx);
    char *rx;          /* the caller's line buffer for recv_bounded */
    size_t rx_max;
    void *ctx;
} p3_rectx_io;

typedef struct {
    uint32_t attempts;        /* transmissions made, including the corrupted control one */
    uint32_t gets;            /* RECGETs answered */
    uint32_t idle_expiries;   /* bounded waits that ran out */
    uint32_t stale;           /* lines ignored (wrong type/seq/token/broken) */
    int corrupted_first;      /* the control was applied to attempt 1 */
    int acked;
    const char *why;          /* set when not acked */
} p3_rectx_result;

/* Runs one record's transaction: `line` is the framed REC line INCLUDING its trailing
 * newline (n bytes), `seq` the record's seq. Returns 0 when RECACK for this seq arrived,
 * -1 when P3_RECTX_ATTEMPTS transmissions went unacknowledged (result->why set), -2 when
 * the channel itself failed while sending. `scratch` (>= n bytes) holds the corrupted copy
 * for the control. The bytes of every real transmission are identical: `line` is never
 * modified. */
int p3_rectx_run(const char *line, size_t n, uint32_t seq, int corrupt_first,
                 const p3_rectx_io *io, char *scratch, size_t scratch_max,
                 p3_rectx_result *result);

/* The control's corruption, in one place: the last hex digit of the CRC field of a framed
 * line (the character before the newline) — '0' becomes '1', anything else '0'. */
void p3_rectx_corrupt_crc(char *line, size_t n);

#endif /* P3_RECTX_H */
