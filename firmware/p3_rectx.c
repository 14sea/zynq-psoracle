/* p3_rectx — see p3_rectx.h. Pure: no MMIO, no console, no global state. */

#include "p3_rectx.h"

#include <string.h>

int p3_rectx_recv_line(const p3_rectx_rx *rx, char *out, size_t max, uint32_t idle_polls)
{
    size_t n = 0;
    uint32_t idle = 0u, total = 0u;
    const uint32_t line_polls = idle_polls * P3_RECTX_LINE_POLL_FACTOR;

    if (max == 0u)
        return -1;
    out[0] = 0;
    for (;;) {
        int c;
        if (!rx->rx_ready(rx->ctx)) {
            if (++idle > idle_polls) {
                out[n] = 0;
                return n == 0u ? -2 : -3; /* silence: nothing at all, or a line cut short */
            }
            if (++total > line_polls) {
                out[n] = 0;
                return n == 0u ? -2 : -3;
            }
            continue;
        }
        idle = 0u;
        if (++total > line_polls) {
            out[n] = 0;
            return -3; /* a line that never ends within the overall bound */
        }
        c = rx->rx_byte(rx->ctx);
        if (c == '\n')
            break;
        if (c == '\r')
            continue;
        if (n + 1u >= max) {
            out[n] = 0;
            return -1; /* over-long: the caller discards it and keeps waiting */
        }
        out[n++] = (char)c;
    }
    out[n] = 0;
    return (int)n;
}

void p3_rectx_corrupt_crc(char *line, size_t n)
{
    size_t i;

    if (n < 2u)
        return;
    i = (line[n - 1] == '\n') ? n - 2u : n - 1u;
    line[i] = (line[i] == '0') ? '1' : '0';
}

static int rectx_send(const char *line, size_t n, uint32_t attempt, int corrupt_first,
                      const p3_rectx_io *io, char *scratch, size_t scratch_max,
                      p3_rectx_result *r)
{
    r->attempts++;
    if (attempt == 1u && corrupt_first) {
        if (scratch == NULL || scratch_max < n)
            return -1;
        memcpy(scratch, line, n);
        p3_rectx_corrupt_crc(scratch, n);
        r->corrupted_first = 1;
        return io->send(scratch, n, io->ctx);
    }
    return io->send(line, n, io->ctx); /* the real bytes, identical on every transmission */
}

int p3_rectx_run(const char *line, size_t n, uint32_t seq, int corrupt_first,
                 const p3_rectx_io *io, char *scratch, size_t scratch_max,
                 p3_rectx_result *r)
{
    uint32_t attempt;

    memset(r, 0, sizeof(*r));
    for (attempt = 1u; attempt <= P3_RECTX_ATTEMPTS; attempt++) {
        uint32_t stale = 0u;

        if (rectx_send(line, n, attempt, corrupt_first, io, scratch, scratch_max, r) != 0) {
            r->why = "PROTOCOL: the channel failed while sending the record";
            return -2;
        }
        /* wait for THIS record's RECACK or RECGET; anything else is ignored, within bounds */
        for (;;) {
            char type[16];
            uint32_t fseq = 0u, pseq = 0u;
            const char *payload;
            int got = io->recv_bounded(io->rx, io->rx_max, io->ctx);

            if (got == -2) {
                r->idle_expiries++;
                break; /* the bound ran out: resend, or exhaust */
            }
            if (got < 0) {
                r->stale++; /* over-long (-1) or partial (-3): not a line of ours */
                if (got == -3)
                    r->partial++;
            } else {
                payload = io->parse(io->rx, type, sizeof(type), &fseq, io->ctx);
                if (payload == NULL || fseq != seq || payload[0] == 0 ||
                    io->payload_seq(payload, &pseq, io->ctx) != 0 || pseq != seq) {
                    r->stale++; /* broken, foreign, or another seq's line: not ours */
                } else if (strcmp(type, "RECACK") == 0) {
                    r->acked = 1;
                    return 0;
                } else if (strcmp(type, "RECGET") == 0) {
                    r->gets++;
                    break; /* the host asked: send the same bytes again */
                } else {
                    r->stale++;
                }
            }
            if (++stale >= P3_RECTX_STALE_LIMIT) {
                r->idle_expiries++;
                break; /* the P3_RECTX_STALE_LIMIT-th ignored line ends the wait like the bound */
            }
        }
    }
    r->why = "STOP_REC: the record was not acknowledged after 3 attempts";
    return -1;
}
