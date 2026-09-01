/* p3_wire — see p3_wire.h. Pure serialisation: no MMIO, no board dependency, so the host
 * contract test compiles this exact source and validates the bytes it produces. */

#include "p3_wire.h"
#include "p3_derive.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

/* A bounded appender. Once it overflows it stays overflowed and the builder returns 0, so
 * a caller can never emit a truncated line and call it evidence. */
typedef struct {
    char *buf;
    size_t max;
    size_t n;
    int ok;
} p3_w;

static void w_init(p3_w *w, char *buf, size_t max)
{
    w->buf = buf;
    w->max = max;
    w->n = 0;
    w->ok = (buf != NULL && max > 0);
    if (w->ok)
        buf[0] = 0;
}

static void w_fmt(p3_w *w, const char *fmt, ...)
{
    va_list ap;
    int r;

    if (!w->ok)
        return;
    va_start(ap, fmt);
    r = vsnprintf(w->buf + w->n, w->max - w->n, fmt, ap);
    va_end(ap);
    if (r < 0 || (size_t)r >= w->max - w->n) {
        w->ok = 0;
        return;
    }
    w->n += (size_t)r;
}

/* A JSON string body we emit must be plain: these are hashes, hex, fixed vocabulary and
 * reason strings we author. Anything outside printable ASCII, or a quote/backslash, would
 * make the line unparseable, so it is replaced rather than escaped. */
static void w_str(p3_w *w, const char *s)
{
    if (!w->ok)
        return;
    w_fmt(w, "\"");
    for (; s != NULL && *s != 0; s++) {
        char c = *s;
        if (c == '"' || c == '\\' || (unsigned char)c < 0x20 || (unsigned char)c > 0x7E)
            c = '.';
        w_fmt(w, "%c", c);
    }
    w_fmt(w, "\"");
}

static size_t w_done(const p3_w *w)
{
    return w->ok ? w->n : 0;
}

/* ------------------------------------------------------------------ framed line ----- */

size_t p3_wire_line(const char *type, uint32_t seq, const char *token,
                    const char *payload_b64, char *out, size_t max)
{
    p3_w w;
    size_t body;

    w_init(&w, out, max);
    w_fmt(&w, "P3L5 %s %lu %s %s", type, (unsigned long)seq, token,
          (payload_b64 != NULL && payload_b64[0] != 0) ? payload_b64 : "-");
    body = w_done(&w);
    if (body == 0)
        return 0;
    w_fmt(&w, " %08lx\n", (unsigned long)p3_crc32((const uint8_t *)out, body));
    return w_done(&w);
}

/* ------------------------------------------------------------------ app_identity ---- */

size_t p3_wire_identity(const p3_wire_identity_in *in, char *out, size_t max)
{
    p3_w w;
    int i;

    w_init(&w, out, max);
    w_fmt(&w, "{\"app_epoch\":%lu,\"carrier_sha256\":", (unsigned long)in->app_epoch);
    w_str(&w, in->carrier_sha256);
    w_fmt(&w, ",\"control_plane\":\"standalone\",\"fclk0_hz_decoded\":%lu,\"findings\":[",
          (unsigned long)in->fclk0_hz_decoded);
    for (i = 0; i < in->findings_n; i++) {
        if (i)
            w_fmt(&w, ",");
        w_str(&w, in->findings[i]);
    }
    w_fmt(&w, "],\"nonce_at_start\":\"%016llx\",\"pss_idcode\":\"0x%08lx\",\"schema\":"
              "\"app_identity\",\"schema_version\":\"1.0.0\",\"status_at_start\":\"0x%08lx\","
              "\"token\":",
          (unsigned long long)in->nonce_at_start, (unsigned long)in->pss_idcode,
          (unsigned long)in->status_at_start);
    w_str(&w, in->token);
    w_fmt(&w, ",\"uboot_epoch\":%lu}", (unsigned long)in->uboot_epoch);
    return w_done(&w);
}

/* ------------------------------------------------------------------ sign_request ---- */

size_t p3_wire_sign_request(const char *token, uint32_t app_epoch, uint32_t seq,
                            const char *genome_hex, uint64_t nonce, char *out, size_t max)
{
    p3_w w;

    w_init(&w, out, max);
    w_fmt(&w, "{\"app_epoch\":%lu,\"genome\":", (unsigned long)app_epoch);
    w_str(&w, genome_hex);
    w_fmt(&w, ",\"nonce\":\"%016llx\",\"schema\":\"sign_request\",\"schema_version\":"
              "\"1.0.0\",\"seq\":%lu,\"token\":",
          (unsigned long long)nonce, (unsigned long)seq);
    w_str(&w, token);
    w_fmt(&w, "}");
    return w_done(&w);
}

/* ------------------------------------------------------------------ loop_record ----- */

static void w_tables(p3_w *w, const char *const *t)
{
    int i;

    w_fmt(w, "[");
    for (i = 0; i < P3_WIRE_SCORES; i++) {
        if (i)
            w_fmt(w, ",");
        w_str(w, t[i]);
    }
    w_fmt(w, "]");
}

static void w_sign_reply(p3_w *w, const p3_wire_record_in *in)
{
    w_fmt(w, "\"sign_reply\":{\"commit\":");
    w_str(w, in->commit);
    w_fmt(w, ",\"expected_tables\":");
    w_tables(w, in->tables);
    w_fmt(w, ",\"schema\":\"sign_reply\",\"schema_version\":\"1.0.0\",\"seq\":%lu,\"tag\":",
          (unsigned long)in->seq);
    w_str(w, in->tag);
    w_fmt(w, "}");
}

static void w_oracle(p3_w *w, const p3_wire_record_in *in)
{
    int i;

    w_fmt(w, "\"app_oracle_record\":{\"audit_available\":%s,\"readback_sha256\":",
          in->audit_available ? "true" : "false");
    w_str(w, in->readback_sha256);
    w_fmt(w, ",\"schema\":\"app_oracle_record\",\"schema_version\":\"1.0.0\",\"seq\":%lu,"
             "\"staged_sha256\":", (unsigned long)in->seq);
    w_str(w, in->staged_sha256);
    w_fmt(w, ",\"staged_stream_sha256\":");
    w_str(w, in->staged_stream_sha256);
    w_fmt(w, ",\"write\":{\"envelopes\":[");
    for (i = 0; i < in->envelopes_n; i++) {
        if (i)
            w_fmt(w, ",");
        w_fmt(w, "{\"index\":%d,\"int_sts\":\"0x%08lx\"}", i,
              (unsigned long)(in->envelope_int_sts ? in->envelope_int_sts[i] : 0u));
    }
    w_fmt(w, "]}}");
}

static void w_arm(p3_w *w, const p3_wire_record_in *in)
{
    w_fmt(w, "\"arm\":{\"ctrl_after\":\"0x%08lx\",\"ctrl_before\":\"0x%08lx\","
             "\"fault_after\":%lu,\"key_loaded_observed\":%s,\"nonce_after\":"
             "\"%016llx\",\"nonce_before\":\"%016llx\",\"status_after\":\"0x%08lx\","
             "\"writes_issued\":%d}",
          (unsigned long)in->ctrl_after, (unsigned long)in->ctrl_before,
          (unsigned long)in->fault_after, in->key_loaded_observed ? "true" : "false",
          (unsigned long long)in->nonce_after, (unsigned long long)in->nonce_before,
          (unsigned long)in->status_after, in->writes_issued);
}

static void w_score(p3_w *w, const p3_wire_record_in *in)
{
    int i;

    w_fmt(w, "\"score\":{\"functional_readout\":");
    w_tables(w, in->readout);
    w_fmt(w, ",\"heartbeat\":{\"after\":%lu,\"before\":%lu},\"hw_candidate_commit\":",
          (unsigned long)in->hb_after, (unsigned long)in->hb_before);
    w_str(w, in->hw_candidate_commit);
    w_fmt(w, ",\"scores\":[");
    for (i = 0; i < P3_WIRE_SCORES; i++)
        w_fmt(w, i ? ",%lu" : "%lu", (unsigned long)in->scores[i]);
    w_fmt(w, "]}");
}

size_t p3_wire_loop_record(const p3_wire_record_in *in, char *out, size_t max)
{
    p3_w w;
    int first = 1;
    int i;

    w_init(&w, out, max);
    w_fmt(&w, "{\"evidence\":{");
    if (in->have_sign_refusal) {
        w_fmt(&w, "\"sign_refusal\":{\"finding_kinds\":[");
        for (i = 0; i < in->finding_kinds_n; i++) {
            if (i)
                w_fmt(&w, ",");
            w_str(&w, in->finding_kinds[i]);
        }
        w_fmt(&w, "],\"schema\":\"sign_refusal\",\"schema_version\":\"1.0.0\",\"seq\":%lu}",
              (unsigned long)in->seq);
        first = 0;
    }
    if (in->have_oracle) {
        if (!first)
            w_fmt(&w, ",");
        w_oracle(&w, in);
        first = 0;
    }
    if (in->have_arm) {
        if (!first)
            w_fmt(&w, ",");
        w_arm(&w, in);
        first = 0;
    }
    if (in->have_score) {
        if (!first)
            w_fmt(&w, ",");
        w_score(&w, in);
        first = 0;
    }
    if (in->have_sign_reply) {
        if (!first)
            w_fmt(&w, ",");
        w_sign_reply(&w, in);
    }
    w_fmt(&w, "},\"genome\":");
    w_str(&w, in->genome);
    w_fmt(&w, ",\"outcome\":");
    w_str(&w, in->outcome);
    w_fmt(&w, ",\"schema\":\"loop_record\",\"schema_version\":\"1.0.0\",\"seq\":%lu,"
             "\"verified\":\"%s\"}",
          (unsigned long)in->seq, in->audited ? "audited" : "replayed-only");
    return w_done(&w);
}

/* ------------------------------------------------------------------ audit ----------- */

size_t p3_wire_audit(uint32_t seq, uint32_t chunk, uint32_t chunks, uint32_t word_offset,
                     uint32_t word_count, uint32_t total_words, const char *span,
                     const char *words_b64, char *out, size_t max)
{
    p3_w w;

    w_init(&w, out, max);
    w_fmt(&w, "{\"chunk\":%lu,\"chunks\":%lu,\"schema\":\"app_audit_chunk\","
              "\"schema_version\":\"1.0.0\",\"seq\":%lu,\"span\":",
          (unsigned long)chunk, (unsigned long)chunks, (unsigned long)seq);
    w_str(&w, span);
    w_fmt(&w, ",\"total_words\":%lu,\"word_count\":%lu,\"word_offset\":%lu,\"words\":",
          (unsigned long)total_words, (unsigned long)word_count,
          (unsigned long)word_offset);
    w_str(&w, words_b64);
    w_fmt(&w, "}");
    return w_done(&w);
}

/* ------------------------------------------------------------------ closing control - */

size_t p3_wire_closing(uint64_t nonce_before, uint64_t nonce_after, uint32_t fault,
                       uint32_t status, char *out, size_t max)
{
    p3_w w;

    w_init(&w, out, max);
    w_fmt(&w, "{\"fault\":%lu,\"kind\":\"unsigned\",\"nonce_after\":\"%016llx\","
              "\"nonce_before\":\"%016llx\",\"status\":\"0x%08lx\"}",
          (unsigned long)fault, (unsigned long long)nonce_after,
          (unsigned long long)nonce_before, (unsigned long)status);
    return w_done(&w);
}

/* ------------------------------------------------------------------ summary --------- */

static const char *done_str(int done)
{
    return done ? "done" : "not_reached";
}

size_t p3_wire_summary(const p3_wire_summary_in *in, char *out, size_t max)
{
    p3_w w;

    w_init(&w, out, max);
    w_fmt(&w, "{\"audit\":{\"audited\":%lu,\"total\":%lu},\"closing\":{\"baseline\":\"%s\","
              "\"restore\":\"%s\",\"unsigned_control\":\"%s\"},\"counts\":{"
              "\"refused_by_gate\":%lu,\"scored\":%lu},\"crc_dropped\":%lu,"
              "\"drop_budget\":%lu,\"epoch_end\":{\"kind\":\"%s\",\"last_seq\":%lu,"
              "\"reason\":",
          (unsigned long)in->audited, (unsigned long)in->total,
          done_str(in->closing_baseline), done_str(in->closing_restore),
          done_str(in->closing_unsigned), (unsigned long)in->refused_by_gate,
          (unsigned long)in->scored, (unsigned long)in->crc_dropped,
          (unsigned long)in->drop_budget, in->kind, (unsigned long)in->last_seq);
    w_str(&w, in->reason ? in->reason : "");
    w_fmt(&w, "},\"schema\":\"session_summary\",\"schema_version\":\"1.0.0\",\"token\":");
    w_str(&w, in->token);
    w_fmt(&w, ",\"written_by\":\"app\"}");
    return w_done(&w);
}
