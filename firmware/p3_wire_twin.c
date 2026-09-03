/* p3_wire_twin — the host driver that exposes `p3_wire.c` on stdin/stdout.
 *
 * This is what makes `tests/test_firmware_wire_contract.py` a real contract test rather
 * than another test of a Python model: the bytes it prints come from the SAME C source the
 * board image links, so the Python validator on the other side is judging the application's
 * actual wire serialisation. (The gap this closes: the L5 rehearsal validated
 * host/l5_refloop.py, the Python reference, while the C application emitted flat records
 * with no seq/verified/evidence and never sent IDENT or HB at all.)
 *
 * Host-only; never cross-compiled into the image. One command per line:
 *
 *   line   <type> <seq> <token> <payload_b64|->      -> the framed line
 *   ident  k=v ...                                   -> IDENT frame
 *   signreq k=v ...                                  -> SIGNREQ frame
 *   rec    k=v ...                                   -> REC frame
 *   audit  k=v ...                                   -> AUDIT frame
 *   term   k=v ...                                   -> TERM frame
 *   hb     token=<32hex> seq=<n>                     -> HB frame
 *   ready  k=v ...                                   -> AUDIT_READY frame (L6 pull)
 *   sparse file=<hex words, one line> seq= chunk= span=  -> a sparse-v1 AUDIT chunk from the C encoder
 *   rectx  k=v ... [corrupt=1]                       -> the REC transaction (rec-v3): builds the REC
 *          frame as `rec` would and runs firmware/p3_rectx.c's state machine INTERACTIVELY —
 *          every transmission goes to stdout (flushed); every host line is read from stdin
 *          and fed BYTE BY BYTE through p3_rectx_recv_line (the board's own bounded
 *          whole-line receiver, idle bound TWIN_IDLE_POLLS): a plain line arrives whole with
 *          its newline; `!raw <text>` arrives WITHOUT a newline (a truncated host line);
 *          `!idle` (and EOF) deliver nothing, so the receiver's bound runs out — then prints
 *          `!rectx rc=… attempts=… gets=… idle=… stale=… partial=… corrupted_first=… acked=… why=…`
 *
 * Every frame command prints the complete framed line exactly as the board would emit it
 * (payload base64url-encoded by p3_derive's own encoder). `!` prefixes an error.
 */

#include "p3_wire.h"
#include "p3_derive.h"
#include "p3_rectx.h"
#include "p3_pull.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAXK 64
#define MAXV 4096

static char g_plain[8192];
static char g_b64[12288];
static char g_line[16384];

/* ---------------------------------------------------------------- key=value parsing --- */

struct kv {
    char key[MAXK];
    char val[MAXV];
};

static struct kv g_kv[48];
static int g_kvn;

static void kv_parse(char *rest)
{
    char *tok;

    g_kvn = 0;
    for (tok = strtok(rest, " \t\n"); tok != NULL; tok = strtok(NULL, " \t\n")) {
        char *eq = strchr(tok, '=');
        if (eq == NULL || g_kvn >= (int)(sizeof(g_kv) / sizeof(g_kv[0])))
            continue;
        *eq = 0;
        snprintf(g_kv[g_kvn].key, MAXK, "%s", tok);
        snprintf(g_kv[g_kvn].val, MAXV, "%s", eq + 1);
        g_kvn++;
    }
}

static const char *kv(const char *key)
{
    int i;

    for (i = 0; i < g_kvn; i++)
        if (strcmp(g_kv[i].key, key) == 0)
            return g_kv[i].val;
    return NULL;
}

static int kv_has(const char *key)
{
    return kv(key) != NULL;
}

static const char *kv_or(const char *key, const char *dflt)
{
    const char *v = kv(key);
    return v ? v : dflt;
}

static unsigned long kv_u(const char *key, unsigned long dflt)
{
    const char *v = kv(key);
    return v ? strtoul(v, NULL, 0) : dflt;
}

static unsigned long long kv_x64(const char *key)
{
    const char *v = kv(key);
    return v ? strtoull(v, NULL, 16) : 0ull;
}

/* Splits "a,b,c" in place into up to `max` pointers; returns the count. */
static int kv_list(const char *key, const char **out, int max)
{
    static char bufs[8][MAXV];
    static int next;
    char *p;
    int n = 0;
    const char *v = kv(key);

    if (v == NULL)
        return 0;
    p = bufs[next % 8];
    next++;
    snprintf(p, MAXV, "%s", v);
    for (; n < max;) {
        char *comma = strchr(p, ',');
        out[n++] = p;
        if (comma == NULL)
            break;
        *comma = 0;
        p = comma + 1;
    }
    return n;
}

/* ---------------------------------------------------------------- emit helpers -------- */

static int emit(const char *type, uint32_t seq, const char *token, size_t plain_len)
{
    size_t n;

    if (plain_len == 0) {
        printf("!payload-overflow\n");
        return 0;
    }
    p3_base64url((const uint8_t *)g_plain, plain_len, g_b64);
    n = p3_wire_line(type, seq, token, g_b64, g_line, sizeof(g_line));
    if (n == 0) {
        printf("!line-overflow\n");
        return 0;
    }
    fwrite(g_line, 1, n, stdout);
    return 1;
}

/* ---------------------------------------------------------------- commands ------------ */

static void cmd_ident(void)
{
    p3_wire_identity_in in;
    const char *findings[8];

    memset(&in, 0, sizeof(in));
    in.pss_idcode = (uint32_t)kv_u("idcode", 0x03722093ul);
    in.token = kv_or("token", "");
    in.uboot_epoch = (uint32_t)kv_u("uboot_epoch", 0);
    in.carrier_sha256 = kv_or("carrier_sha256", "");
    in.nonce_at_start = kv_x64("nonce");
    in.status_at_start = (uint32_t)kv_u("status", 0);
    in.fclk0_hz_decoded = (uint32_t)kv_u("fclk0", 50000000ul);
    in.app_epoch = (uint32_t)kv_u("app_epoch", 0);
    in.findings_n = kv_list("findings", findings, 8);
    in.findings = in.findings_n ? findings : NULL;
    in.master_seed = (uint32_t)kv_u("master_seed", 0);
    in.schedule_mode = kv_or("schedule_mode", "abba");
    in.operator_data_sha256 = kv_or("operator_sha", "");
    in.protocol = kv_or("protocol", "rel-v4");
    in.rec_retry_control = (int)kv_u("rec_control", 0);
    in.sign_retry_control = (int)kv_u("sign_control", 0);
    emit("IDENT", (uint32_t)kv_u("seq", 0), in.token,
         p3_wire_identity(&in, g_plain, sizeof(g_plain)));
}

/* the IDENT line into `out` (framed, newline included), for `identtx` */
static size_t build_ident(char *out, size_t max)
{
    p3_wire_identity_in in;
    const char *findings[8];
    size_t n;

    memset(&in, 0, sizeof(in));
    in.pss_idcode = (uint32_t)kv_u("idcode", 0x03722093ul);
    in.token = kv_or("token", "");
    in.uboot_epoch = (uint32_t)kv_u("uboot_epoch", 0);
    in.carrier_sha256 = kv_or("carrier_sha256", "");
    in.nonce_at_start = kv_x64("nonce");
    in.status_at_start = (uint32_t)kv_u("status", 0);
    in.fclk0_hz_decoded = (uint32_t)kv_u("fclk0", 50000000ul);
    in.app_epoch = (uint32_t)kv_u("app_epoch", 0);
    in.findings_n = kv_list("findings", findings, 8);
    in.findings = in.findings_n ? findings : NULL;
    in.master_seed = (uint32_t)kv_u("master_seed", 0);
    in.schedule_mode = kv_or("schedule_mode", "abba");
    in.operator_data_sha256 = kv_or("operator_sha", "");
    in.protocol = kv_or("protocol", "rel-v4");
    in.rec_retry_control = (int)kv_u("rec_control", 0);
    in.sign_retry_control = (int)kv_u("sign_control", 0);
    n = p3_wire_identity(&in, g_plain, sizeof(g_plain));
    if (n == 0)
        return 0;
    p3_base64url((const uint8_t *)g_plain, n, g_b64);
    return p3_wire_line("IDENT", 0, in.token, g_b64, out, max);
}

static void cmd_signreq(void)
{
    uint32_t seq = (uint32_t)kv_u("seq", 1);
    const char *token = kv_or("token", "");

    emit("SIGNREQ", seq, token,
         p3_wire_sign_request(token, (uint32_t)kv_u("app_epoch", 0), seq,
                              kv_or("genome", ""), kv_x64("nonce"),
                              g_plain, sizeof(g_plain)));
}

/* Builds the REC frame from the k=v fields into `out` (the framed line, newline included);
 * returns its length or 0. Shared by `rec` (print it) and `rectx` (transact it). */
static size_t build_rec(char *out, size_t max)
{
    p3_wire_record_in in;
    const char *kinds[8];
    const char *tables[P3_WIRE_SCORES];
    const char *readout[P3_WIRE_SCORES];
    const char *scores[P3_WIRE_SCORES];
    uint32_t ints[8];
    int i, n;

    memset(&in, 0, sizeof(in));
    in.seq = (uint32_t)kv_u("seq", 1);
    in.genome = kv_or("genome", "");
    in.outcome = kv_or("outcome", "SCORED");
    in.audited = (int)kv_u("audited", 0);
    in.arm = kv("arm");                      /* absent -> a baseline record, no arm key */

    if (kv_has("finding_kinds")) {
        in.have_sign_refusal = 1;
        in.finding_kinds_n = kv_list("finding_kinds", kinds, 8);
        in.finding_kinds = kinds;
    }
    if (kv_has("commit")) {
        in.have_sign_reply = 1;
        in.commit = kv("commit");
        in.tag = kv_or("tag", "");
        n = kv_list("tables", tables, P3_WIRE_SCORES);
        for (i = 0; i < P3_WIRE_SCORES; i++)
            in.tables[i] = i < n ? tables[i] : "";
    }
    if (kv_has("staged")) {
        in.have_oracle = 1;
        in.staged_sha256 = kv("staged");
        in.staged_stream_sha256 = kv_or("stream", "");
        in.readback_sha256 = kv_or("readback", "");
        in.envelopes_n = (int)kv_u("envelopes", 3);
        if (in.envelopes_n > 8)
            in.envelopes_n = 8;
        for (i = 0; i < in.envelopes_n; i++)
            ints[i] = (uint32_t)kv_u("int_sts", 0x50020004ul);
        in.envelope_int_sts = ints;
        in.audit_available = (int)kv_u("audit_available", 1);
    }
    if (kv_has("nonce_before")) {
        in.have_arm = 1;
        in.nonce_before = kv_x64("nonce_before");
        in.nonce_after = kv_x64("nonce_after");
        in.status_after = (uint32_t)kv_u("status_after", 0);
        in.fault_after = (uint32_t)kv_u("fault_after", 0);
        in.key_loaded_observed = (int)kv_u("key_loaded", 1);
        in.writes_issued = (int)kv_u("writes_issued", 25);
        /* the settle poll; defaults describe a gate that settled on the first read */
        in.settle_polls = (uint32_t)kv_u("settle_polls", 1);
        in.settle_polls_max = (uint32_t)kv_u("settle_max", 1000000);
        in.settled = (int)kv_u("settled", 1);
        in.status_first = kv_has("status_first") ? (uint32_t)kv_u("status_first", 0)
                                                 : in.status_after;
    }
    if (kv_has("sign_stop_why")) { /* rel-v4 STOP_SIGN */
        in.have_sign_stop = 1;
        in.sign_stop_attempts = (uint32_t)kv_u("sign_stop_attempts", 3);
        in.sign_stop_why = kv("sign_stop_why");
    }
    if (kv_has("audit_stop_why")) {
        in.have_audit_stop = 1;
        in.audit_stop_why = kv("audit_stop_why");
        in.audit_chunks_served = (uint32_t)kv_u("audit_chunks_served", 0);
    }
    if (kv_has("hw_commit")) {
        in.have_score = 1;
        in.hw_candidate_commit = kv("hw_commit");
        n = kv_list("readout", readout, P3_WIRE_SCORES);
        for (i = 0; i < P3_WIRE_SCORES; i++)
            in.readout[i] = i < n ? readout[i] : "";
        n = kv_list("scores", scores, P3_WIRE_SCORES);
        for (i = 0; i < P3_WIRE_SCORES; i++)
            in.scores[i] = i < n ? (uint32_t)strtoul(scores[i], NULL, 10) : 0u;
        in.hb_before = (uint32_t)kv_u("hb_before", 0);
        in.hb_after = (uint32_t)kv_u("hb_after", 0);
    }
    {
        size_t plain_len = p3_wire_loop_record(&in, g_plain, sizeof(g_plain));
        if (plain_len == 0)
            return 0;
        p3_base64url((const uint8_t *)g_plain, plain_len, g_b64);
        return p3_wire_line("REC", in.seq, kv_or("token", ""), g_b64, out, max);
    }
}

static void cmd_rec(void)
{
    size_t n = build_rec(g_line, sizeof(g_line));
    if (n == 0) {
        printf("!payload-overflow\n");
        return;
    }
    fwrite(g_line, 1, n, stdout);
}

/* ---------------------------------------------------------------- rectx (rec-v3) ------- */

static char g_rectx_token[64];
static char g_rectx_rx[16384];
static char g_rectx_scratch[16384];
static char g_rectx_json[8192];

static int rectx_send(const char *line, size_t n, void *ctx)
{
    (void)ctx;
    fwrite(line, 1, n, stdout);
    fflush(stdout);
    return 0;
}

/* The scripted byte source: one stdin line per wait, delivered through the board's own
 * receiver so truncation and silence exercise ITS bound, not the twin's. */
#define TWIN_IDLE_POLLS 200u
static char g_rx_buf[16384];
static size_t g_rx_len, g_rx_pos;

static uint64_t g_twin_ticks;   /* the twin's clock: one tick per RX poll, so the timed bound is exercised */

static int twin_rx_ready(void *ctx)
{
    (void)ctx;
    g_twin_ticks++;
    return g_rx_pos < g_rx_len;
}

static uint64_t twin_now_ticks(void *ctx)
{
    (void)ctx;
    return g_twin_ticks;
}
#define TWIN_IDLE_TICKS 300u

static int twin_rx_byte(void *ctx)
{
    (void)ctx;
    return (int)(unsigned char)g_rx_buf[g_rx_pos++];
}

static int rectx_recv(char *out, size_t max, void *ctx)
{
    p3_rectx_rx rx;
    size_t n;
    (void)ctx;
    rx.rx_ready = twin_rx_ready;
    rx.rx_byte = twin_rx_byte;
    rx.now_ticks = twin_now_ticks;
    rx.ctx = NULL;
    g_rx_len = g_rx_pos = 0;
    if (fgets(g_rx_buf, (int)sizeof(g_rx_buf), stdin) != NULL) {
        n = strlen(g_rx_buf);
        if (strncmp(g_rx_buf, "!idle", 5) == 0) {
            n = 0; /* nothing arrives: the receiver's idle bound runs out */
        } else if (strncmp(g_rx_buf, "!raw ", 5) == 0) {
            memmove(g_rx_buf, g_rx_buf + 5, n - 5);
            n -= 5;
            while (n > 0 && (g_rx_buf[n - 1] == '\n' || g_rx_buf[n - 1] == '\r'))
                n--; /* the truncated line: no newline ever comes */
        }
        g_rx_len = n;
    }
    return p3_rectx_recv_line_timed(&rx, out, max, TWIN_IDLE_POLLS, TWIN_IDLE_TICKS);
}

/* the same checks p3_app.c's parse_frame makes: magic, CRC over the body, the full token */
static const char *rectx_parse(char *line, char *type_out, size_t type_max, uint32_t *seq_out, void *ctx)
{
    char *last = strrchr(line, ' ');
    char expect[16];
    char *f[5];
    size_t i, k = 0;
    (void)ctx;
    if (!last)
        return NULL;
    *last = 0;
    snprintf(expect, sizeof(expect), "%08lx", (unsigned long)p3_crc32((const uint8_t *)line, strlen(line)));
    if (strcmp(expect, last + 1) != 0)
        return NULL;
    f[k++] = line;
    for (i = 0; line[i] && k < 5; i++)
        if (line[i] == ' ') {
            line[i] = 0;
            f[k++] = line + i + 1;
        }
    if (k != 5 || strcmp(f[0], "P3L5") != 0)
        return NULL;
    if (strcmp(f[3], g_rectx_token) != 0)
        return NULL;
    *seq_out = (uint32_t)strtoul(f[2], NULL, 10);
    snprintf(type_out, type_max, "%s", f[1]);
    return f[4];
}

static int rectx_payload_seq(const char *payload_b64, uint32_t *seq_out, void *ctx)
{
    size_t jn = p3_base64url_decode(payload_b64, (uint8_t *)g_rectx_json, sizeof(g_rectx_json) - 1u);
    const char *p;
    uint32_t v = 0;
    int n = 0;
    (void)ctx;
    if (jn == 0u)
        return -1;
    g_rectx_json[jn] = 0;
    p = strstr(g_rectx_json, "\"seq\":");
    if (!p)
        return -1;
    p += 6;
    while (*p >= '0' && *p <= '9' && n < 10) {
        v = v * 10u + (uint32_t)(*p - '0');
        p++;
        n++;
    }
    if (n == 0 || (*p != ',' && *p != '}'))
        return -1;
    *seq_out = v;
    return 0;
}

static void cmd_rectx(void)
{
    p3_rectx_io io;
    p3_rectx_result r;
    size_t n = build_rec(g_line, sizeof(g_line));
    int rc;

    if (n == 0) {
        printf("!payload-overflow\n");
        return;
    }
    snprintf(g_rectx_token, sizeof(g_rectx_token), "%s", kv_or("token", ""));
    memset(&io, 0, sizeof(io));
    io.send = rectx_send;
    io.recv_bounded = rectx_recv;
    io.parse = rectx_parse;
    io.payload_seq = rectx_payload_seq;
    io.rx = g_rectx_rx;
    io.rx_max = sizeof(g_rectx_rx);
    rc = p3_rectx_run(g_line, n, (uint32_t)kv_u("seq", 1), (int)kv_u("corrupt", 0), &io,
                      g_rectx_scratch, sizeof(g_rectx_scratch), &r);
    printf("!rectx rc=%d attempts=%lu gets=%lu idle=%lu stale=%lu partial=%lu corrupted_first=%d acked=%d why=%s\n",
           rc, (unsigned long)r.attempts, (unsigned long)r.gets, (unsigned long)r.idle_expiries,
           (unsigned long)r.stale, (unsigned long)r.partial, r.corrupted_first, r.acked, r.why ? r.why : "");
    fflush(stdout);
}

/* ---------------------------------------------------------------- rel-v4 transactions --- */

/* identtx / signtx / termtx: the board's IDENT / SIGNREQ / TERM transaction (p3_tx_run, the
 * same source the image links) over the pipe — the host test plays the runner. Prints
 * `!tx rc=… attempts=… gets=… idle=… stale=… partial=… prev_acks=… corrupted_first=… acked=…
 * ack_type=… why=…`. signtx: prev_seq= (the previous record's seq) enables the strict
 * previous-acknowledgement rule as the board applies it. */
static void cmd_tx(const char *which)
{
    p3_rectx_io io;
    p3_rectx_result r;
    p3_tx_kinds k;
    size_t n;
    int rc;

    uint32_t tx_seq = (uint32_t)kv_u("seq", 1);

    snprintf(g_rectx_token, sizeof(g_rectx_token), "%s", kv_or("token", ""));
    if (strcmp(which, "identtx") == 0) {
        tx_seq = 0u;
        n = build_ident(g_line, sizeof(g_line));
        k.ack_a = "IDENTACK"; k.ack_b = NULL; k.get = NULL;
        k.stop_why = "STOP_IDENT: the identity was not acknowledged after 3 attempts";
        k.prev_seq = 0u; k.prev_strict = 0;
    } else if (strcmp(which, "signtx") == 0) {
        n = p3_wire_sign_request(g_rectx_token, (uint32_t)kv_u("app_epoch", 0), (uint32_t)kv_u("seq", 1),
                                 kv_or("genome", ""), kv_x64("nonce"), g_plain, sizeof(g_plain));
        if (n != 0) {
            p3_base64url((const uint8_t *)g_plain, n, g_b64);
            n = p3_wire_line("SIGNREQ", (uint32_t)kv_u("seq", 1), g_rectx_token, g_b64, g_line, sizeof(g_line));
        }
        k.ack_a = "SIGNOK"; k.ack_b = "SIGNREF"; k.get = "SIGNGET";
        k.stop_why = "STOP_SIGN: the sign exchange was not acknowledged after 3 attempts";
        k.prev_seq = (uint32_t)kv_u("prev_seq", 0); k.prev_strict = 1;
    } else {
        p3_wire_summary_in in;
        memset(&in, 0, sizeof(in));
        in.token = g_rectx_token;
        in.kind = kv_or("kind", "COMPLETED");
        in.reason = kv_or("reason", "budget");
        in.last_seq = (uint32_t)kv_u("last_seq", 0);
        in.closing_restore = (int)kv_u("closing_restore", 1);
        in.closing_baseline = (int)kv_u("closing_baseline", 1);
        in.closing_unsigned = (int)kv_u("closing_unsigned", 1);
        p3_wire_tally(&in.total, &in.audited);
        in.drop_budget = 16;
        in.have_closing_control = in.closing_unsigned;
        in.close_fault = (uint32_t)kv_u("closing_fault", 13);
        in.close_status = (uint32_t)kv_u("closing_status", 0x982);
        in.close_nonce_before = kv_x64("closing_nb");
        in.close_nonce_after = kv_x64("closing_na");
        tx_seq = (uint32_t)kv_u("seq", in.last_seq + 1); /* the TERM's seq is last_seq + 1 */
        n = p3_wire_summary(&in, g_plain, sizeof(g_plain));
        if (n != 0) {
            p3_base64url((const uint8_t *)g_plain, n, g_b64);
            n = p3_wire_line("TERM", tx_seq, g_rectx_token, g_b64, g_line, sizeof(g_line));
        }
        k.ack_a = "TERMACK"; k.ack_b = NULL; k.get = "TERMGET";
        k.stop_why = "TERM_UNACKED: the summary was not acknowledged after 3 attempts";
        k.prev_seq = 0u; k.prev_strict = 0;
    }
    if (n == 0) {
        printf("!line-overflow\n");
        return;
    }
    io.send = rectx_send;
    io.recv_bounded = rectx_recv;
    io.parse = rectx_parse;
    io.payload_seq = rectx_payload_seq;
    io.rx = g_rectx_rx;
    io.rx_max = sizeof(g_rectx_rx);
    io.ctx = NULL;
    rc = p3_tx_run(g_line, n, tx_seq, &k,
                   (int)kv_u("corrupt", 0), &io, g_rectx_scratch, sizeof(g_rectx_scratch), &r);
    printf("!tx rc=%d attempts=%lu gets=%lu idle=%lu stale=%lu partial=%lu prev_acks=%lu corrupted_first=%d acked=%d ack_type=%s why=%s\n",
           rc, (unsigned long)r.attempts, (unsigned long)r.gets, (unsigned long)r.idle_expiries,
           (unsigned long)r.stale, (unsigned long)r.partial, (unsigned long)r.prev_acks, r.corrupted_first,
           r.acked, r.acked ? r.ack_type : "-", r.why ? r.why : "-");
    fflush(stdout);
}

/* pulltx seq= chunks= token=: the board's audit pull (p3_pull_run, the same source the image
 * links) over the pipe with all-zero windows: AUDIT_READY, then every AUDITGET answered with
 * the chunk asked for, AUDIT_READY resent on the bound while no GET was seen, AUDITWAIT after
 * the last chunk, until AUDITDONE / AUDITABORT / exhaustion. Prints `!pull rc=… ready_sent=…
 * gets=… served=… waits=… idle=… stale=… mask=… done=… aborted=… why=…`. */
static char g_pull_ready[16384];
static uint32_t g_pull_seq, g_pull_chunks, g_pull_total;
static const char *g_pull_span;

static uint32_t pull_zero_word(uint32_t i)
{
    (void)i;
    return 0u;
}

static int pull_send_ready(void *ctx)
{
    (void)ctx;
    fwrite(g_pull_ready, 1, strlen(g_pull_ready), stdout);
    fflush(stdout);
    return 0;
}

static int pull_serve_chunk(uint32_t chunk, void *ctx)
{
    uint32_t lo = chunk * P3_WIRE_SPARSE_WINDOW;
    uint32_t hi = lo + P3_WIRE_SPARSE_WINDOW < g_pull_total ? lo + P3_WIRE_SPARSE_WINDOW : g_pull_total;
    static char words_b64[8192];
    size_t n;
    (void)ctx;
    n = p3_wire_sparse_entries(pull_zero_word, lo, hi, words_b64, sizeof(words_b64));
    if (n == 0u)
        words_b64[0] = 0;
    n = p3_wire_audit_sparse(g_pull_seq, chunk, g_pull_chunks, g_pull_span, g_pull_total, lo, hi, words_b64,
                             g_plain, sizeof(g_plain));
    if (n == 0)
        return -1;
    p3_base64url((const uint8_t *)g_plain, n, g_b64);
    n = p3_wire_line("AUDIT", g_pull_seq, g_rectx_token, g_b64, g_line, sizeof(g_line));
    if (n == 0)
        return -1;
    fwrite(g_line, 1, n, stdout);
    fflush(stdout);
    return 0;
}

static int pull_send_wait(uint32_t served, void *ctx)
{
    size_t n = p3_wire_audit_wait(g_pull_seq, served, g_plain, sizeof(g_plain));
    (void)ctx;
    if (n == 0)
        return -1;
    p3_base64url((const uint8_t *)g_plain, n, g_b64);
    n = p3_wire_line("AUDITWAIT", g_pull_seq, g_rectx_token, g_b64, g_line, sizeof(g_line));
    if (n == 0)
        return -1;
    fwrite(g_line, 1, n, stdout);
    fflush(stdout);
    return 0;
}

static int pull_payload_fields(const char *payload_b64, uint32_t *seq_out, uint32_t *chunk_out, int *has_chunk, void *ctx)
{
    const char *p;
    size_t jn = p3_base64url_decode(payload_b64, (uint8_t *)g_rectx_json, sizeof(g_rectx_json) - 1u);
    (void)ctx;
    if (jn == 0u)
        return -1;
    g_rectx_json[jn] = 0;
    p = strstr(g_rectx_json, "\"seq\":");
    if (p == NULL)
        return -1;
    *seq_out = (uint32_t)strtoul(p + 6, NULL, 10);
    p = strstr(g_rectx_json, "\"chunk\":");
    *has_chunk = (p != NULL);
    if (p != NULL)
        *chunk_out = (uint32_t)strtoul(p + 8, NULL, 10);
    return 0;
}

static int pull_channel_failed(void *ctx)
{
    (void)ctx;
    return 0;
}

static void cmd_pulltx(void)
{
    p3_pull_io io;
    p3_pull_result r;
    size_t n;
    int rc;

    snprintf(g_rectx_token, sizeof(g_rectx_token), "%s", kv_or("token", ""));
    g_pull_seq = (uint32_t)kv_u("seq", 1);
    g_pull_span = kv_or("span", "streams+readback");
    g_pull_total = (uint32_t)kv_u("total_words", strcmp(g_pull_span, "streams") == 0 ? 1602 : 2814);
    g_pull_chunks = (g_pull_total + P3_WIRE_SPARSE_WINDOW - 1u) / P3_WIRE_SPARSE_WINDOW;
    n = p3_wire_audit_ready(g_pull_seq, g_pull_span, g_pull_total, g_pull_chunks, 0, g_plain, sizeof(g_plain));
    if (n == 0) {
        printf("!payload-overflow\n");
        return;
    }
    p3_base64url((const uint8_t *)g_plain, n, g_b64);
    if (p3_wire_line("AUDIT_READY", g_pull_seq, g_rectx_token, g_b64, g_pull_ready, sizeof(g_pull_ready)) == 0) {
        printf("!line-overflow\n");
        return;
    }
    io.send_ready = pull_send_ready;
    io.serve_chunk = pull_serve_chunk;
    io.send_wait = pull_send_wait;
    io.recv_bounded = rectx_recv;
    io.parse = rectx_parse;
    io.payload_fields = pull_payload_fields;
    io.channel_failed = pull_channel_failed;
    io.rx = g_rectx_rx;
    io.rx_max = sizeof(g_rectx_rx);
    io.ctx = NULL;
    rc = p3_pull_run(g_pull_seq, g_pull_chunks, &io, &r);
    printf("!pull rc=%d ready_sent=%lu gets=%lu served=%lu waits=%lu idle=%lu stale=%lu mask=%lu done=%d aborted=%d why=%s\n",
           rc, (unsigned long)r.ready_sent, (unsigned long)r.gets_seen, (unsigned long)r.chunks_served,
           (unsigned long)r.waits_sent, (unsigned long)r.idle_expiries, (unsigned long)r.stale,
           (unsigned long)r.served_mask, r.done, r.aborted, r.why ? r.why : "-");
    fflush(stdout);
}

static uint32_t g_words[2814];
static uint32_t g_words_n;

static uint32_t sparse_word(uint32_t i)
{
    return i < g_words_n ? g_words[i] : 0u;
}

static void cmd_ready(void)
{
    uint32_t seq = (uint32_t)kv_u("seq", 1);
    emit("AUDIT_READY", seq, kv_or("token", ""),
         p3_wire_audit_ready(seq, kv_or("span", "streams+readback"), (uint32_t)kv_u("total_words", 2814),
                             (uint32_t)kv_u("chunks", 8), (uint32_t)kv_u("nonzero", 0),
                             g_plain, sizeof(g_plain)));
}

static void cmd_sparse(void)
{
    static char entries[4096];
    const char *path = kv("file");
    uint32_t seq = (uint32_t)kv_u("seq", 1), chunk = (uint32_t)kv_u("chunk", 0);
    const char *span = kv_or("span", "streams+readback");
    uint32_t total = (uint32_t)kv_u("total_words", 2814), lo, hi, chunks;
    FILE *f;
    unsigned int v;

    if (path == NULL) {
        printf("!sparse-needs-file\n");
        return;
    }
    f = fopen(path, "r");
    if (f == NULL) {
        printf("!sparse-file\n");
        return;
    }
    g_words_n = 0;
    while (g_words_n < 2814u && fscanf(f, "%8x", &v) == 1)
        g_words[g_words_n++] = (uint32_t)v;
    fclose(f);
    chunks = (total + P3_WIRE_SPARSE_WINDOW - 1u) / P3_WIRE_SPARSE_WINDOW;
    lo = chunk * P3_WIRE_SPARSE_WINDOW;
    hi = lo + P3_WIRE_SPARSE_WINDOW < total ? lo + P3_WIRE_SPARSE_WINDOW : total;
    if (p3_wire_sparse_entries(sparse_word, lo, hi, entries, sizeof(entries)) == 0 && hi > lo) {
        /* zero length is legal only when the window is all zero */
        uint32_t i, nz = 0;
        for (i = lo; i < hi; i++)
            if (sparse_word(i))
                nz++;
        if (nz) {
            printf("!sparse-overflow\n");
            return;
        }
        entries[0] = 0;
    }
    emit("AUDIT", seq, kv_or("token", ""),
         p3_wire_audit_sparse(seq, chunk, chunks, span, total, lo, hi, entries, g_plain, sizeof(g_plain)));
}

static void cmd_audit(void)
{
    emit("AUDIT", (uint32_t)kv_u("seq", 1), kv_or("token", ""),
         p3_wire_audit((uint32_t)kv_u("seq", 1), (uint32_t)kv_u("chunk", 0),
                       (uint32_t)kv_u("chunks", 1), (uint32_t)kv_u("word_offset", 0),
                       (uint32_t)kv_u("word_count", 0), (uint32_t)kv_u("total_words", 0),
                       kv_or("span", "streams+readback"), kv_or("words", ""),
                       g_plain, sizeof(g_plain)));
}

static void cmd_term(void)
{
    p3_wire_summary_in in;

    memset(&in, 0, sizeof(in));
    in.token = kv_or("token", "");
    in.kind = kv_or("kind", "COMPLETED");
    in.reason = kv_or("reason", "budget");
    in.last_seq = (uint32_t)kv_u("last_seq", 0);
    in.scored = (uint32_t)kv_u("scored", 0);
    in.refused_by_gate = (uint32_t)kv_u("refused_by_gate", 0);
    in.closing_restore = (int)kv_u("closing_restore", 0);
    in.closing_baseline = (int)kv_u("closing_baseline", 0);
    in.closing_unsigned = (int)kv_u("closing_unsigned", 0);
    /* As the application does: the audit block comes from the serialiser's own tally of
     * the records it produced. An explicit audited=/total= overrides it — that is how the
     * contract tests prove the validator rejects a miscount in either direction. */
    p3_wire_tally(&in.total, &in.audited);
    if (kv_has("audited"))
        in.audited = (uint32_t)kv_u("audited", 0);
    if (kv_has("total"))
        in.total = (uint32_t)kv_u("total", 0);
    in.crc_dropped = (uint32_t)kv_u("crc_dropped", 0);
    in.drop_budget = (uint32_t)kv_u("drop_budget", 16);
    /* rel-v4: the closing control's fields ride in the TERM when the control was reached */
    if (kv_has("closing_nb")) {
        in.have_closing_control = 1;
        in.close_fault = (uint32_t)kv_u("closing_fault", 13);
        in.close_status = (uint32_t)kv_u("closing_status", 0x982);
        in.close_nonce_before = kv_x64("closing_nb");
        in.close_nonce_after = kv_x64("closing_na");
    }
    emit("TERM", (uint32_t)kv_u("seq", in.last_seq + 1), in.token,
         p3_wire_summary(&in, g_plain, sizeof(g_plain)));
}

static void cmd_closing(void)
{
    emit("CLOSE", (uint32_t)kv_u("seq", 1), kv_or("token", ""),
         p3_wire_closing(kv_x64("nonce_before"), kv_x64("nonce_after"),
                         (uint32_t)kv_u("fault", 13), (uint32_t)kv_u("status", 0),
                         g_plain, sizeof(g_plain)));
}

static void cmd_hb(void)
{
    size_t n;
    const char *payload = "-";
    if (kv_has("i")) { /* rel-v4: the indexed heartbeat */
        size_t pn = p3_wire_hb((uint32_t)kv_u("i", 0), g_plain, sizeof(g_plain));
        p3_base64url((const uint8_t *)g_plain, pn, g_b64);
        payload = g_b64;
    }
    n = p3_wire_line("HB", (uint32_t)kv_u("seq", 0), kv_or("token", ""), payload,
                     g_line, sizeof(g_line));
    if (n == 0) {
        printf("!line-overflow\n");
        return;
    }
    fwrite(g_line, 1, n, stdout);
}

static void cmd_line(char *rest)
{
    char *type = strtok(rest, " \t\n");
    char *seq = strtok(NULL, " \t\n");
    char *token = strtok(NULL, " \t\n");
    char *payload = strtok(NULL, " \t\n");
    size_t n;

    if (type == NULL || seq == NULL || token == NULL) {
        printf("!line-args\n");
        return;
    }
    n = p3_wire_line(type, (uint32_t)strtoul(seq, NULL, 10), token,
                     payload ? payload : "-", g_line, sizeof(g_line));
    if (n == 0) {
        printf("!line-overflow\n");
        return;
    }
    fwrite(g_line, 1, n, stdout);
}

int main(void)
{
    static char buf[MAXV * 2];

    while (fgets(buf, sizeof(buf), stdin) != NULL) {
        char *cmd = strtok(buf, " \t\n");
        char *rest;

        if (cmd == NULL || cmd[0] == '#')
            continue;
        rest = strtok(NULL, "\n");
        if (strcmp(cmd, "line") == 0) {
            cmd_line(rest ? rest : (char *)"");
            continue;
        }
        kv_parse(rest ? rest : (char *)"");
        if (strcmp(cmd, "ident") == 0)
            cmd_ident();
        else if (strcmp(cmd, "signreq") == 0)
            cmd_signreq();
        else if (strcmp(cmd, "rec") == 0)
            cmd_rec();
        else if (strcmp(cmd, "rectx") == 0)
            cmd_rectx();
        else if (strcmp(cmd, "identtx") == 0 || strcmp(cmd, "signtx") == 0 || strcmp(cmd, "termtx") == 0)
            cmd_tx(cmd);
        else if (strcmp(cmd, "pulltx") == 0)
            cmd_pulltx();
        else if (strcmp(cmd, "audit") == 0)
            cmd_audit();
        else if (strcmp(cmd, "term") == 0)
            cmd_term();
        else if (strcmp(cmd, "closing") == 0)
            cmd_closing();
        else if (strcmp(cmd, "hb") == 0)
            cmd_hb();
        else if (strcmp(cmd, "ready") == 0)
            cmd_ready();
        else if (strcmp(cmd, "sparse") == 0)
            cmd_sparse();
        else
            printf("!unknown-command\n");
    }
    return 0;
}
