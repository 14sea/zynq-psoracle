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
 *
 * Every frame command prints the complete framed line exactly as the board would emit it
 * (payload base64url-encoded by p3_derive's own encoder). `!` prefixes an error.
 */

#include "p3_wire.h"
#include "p3_derive.h"

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
    emit("IDENT", (uint32_t)kv_u("seq", 0), in.token,
         p3_wire_identity(&in, g_plain, sizeof(g_plain)));
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

static void cmd_rec(void)
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
    emit("REC", in.seq, kv_or("token", ""),
         p3_wire_loop_record(&in, g_plain, sizeof(g_plain)));
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
    size_t n = p3_wire_line("HB", (uint32_t)kv_u("seq", 0), kv_or("token", ""), "-",
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
        else if (strcmp(cmd, "audit") == 0)
            cmd_audit();
        else if (strcmp(cmd, "term") == 0)
            cmd_term();
        else if (strcmp(cmd, "closing") == 0)
            cmd_closing();
        else if (strcmp(cmd, "hb") == 0)
            cmd_hb();
        else
            printf("!unknown-command\n");
    }
    return 0;
}
