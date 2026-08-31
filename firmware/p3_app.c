/* p3_app — the standalone application: the board half of D1 (`docs/d1_standalone_spec.md`).
 *
 * ─── STANDING OF THIS FILE ────────────────────────────────────────────────────────────
 * COMPILED, NOT BOARD-RUN. As of the L5 build (docs/l5_findings.md) this file is
 * cross-compiled for cortex-a9 into firmware/bsp/out/p3_app.elf with the pinned xPack
 * arm-none-eabi-gcc 14.2.1 against a hand-assembled standalone BSP: it links clean with no
 * undefined symbols and compiles -Wall -Wextra clean. It has NEVER been run on the board.
 * What IS proven host-side is `p3_derive.c` — every hash, the derive function, the stream
 * builder and parser, the pinned readback command stream, base64url, the nonce model and
 * the identity page — against the Python reference over the whole pinned corpus (N = 256)
 * and its fixtures. This file is deliberately thin for that reason: HAL plus state machine,
 * checked by source audit (`tests/test_firmware_audit.py`), not by execution.
 * ──────────────────────────────────────────────────────────────────────────────────────
 *
 * It mirrors `host/l5_refloop.py` step for step; where the two disagree the Python is the
 * specification. The session:
 *
 *   identity (§3b) → opening baseline → [ propose → notary → stage → link 2 → DMA →
 *   link 3 → ARM → score ]* → closing baseline (= restore) → closing unsigned ARM (§4.0)
 *
 * ending in exactly one of COMPLETED / STOPPED / PROTOCOL (§3c). CRASHED is the watchdog's
 * and by definition leaves nothing behind but what the collector already received.
 */

#include "p3_data.h"
#include "p3_derive.h"
/* The wire serialisation lives in its own pure unit so the host contract test can compile
 * it and feed the bytes this application emits to the real validator
 * (tests/test_firmware_wire_contract.py). Nothing below builds a payload by hand. */
#include "p3_wire.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* BSP: standalone_v9_4 with the console UART as stdout. `outbyte`/`inbyte` are the only
 * console primitives used, so no UART register appears in this file. */
#include "xil_io.h"
#include "xil_mmu.h"
#include "xparameters.h"
#include "xscuwdt.h"

extern void outbyte(char c);
extern char inbyte(void);

/* ───────────────────────────────── memory map (docs/l5_design.md §2) ───────────────── */

#define P3_CMD_BUF 0x10200000u   /* readback command buffer, 43 words       */
#define P3_DST_BUF 0x10300000u   /* readback destination buffer, 202 words  */
#define P3_WR_BUF 0x10400000u    /* staging, 3 x 534 words (psmap's WR_BUF) */
#define P3_PAGE_ADDR 0x10440000u /* identity page, 24 words                 */
#define P3_RING_ADDR 0x10800000u /* evidence ring, W entries                */
#define P3_RING_W 512
#define P3_DROP_BUDGET 16 /* manifests/l5_manifest.json protocol.crc_drop_budget_per_session */

#define P3_MB (1024u * 1024u)
#define P3_NONCACHEABLE 0x14de2u /* Xil_SetTlbAttributes: strongly-ordered, non-cacheable */
#define P3_SENTINEL 0xA5A5A5A5u
#define P3_WDT_LOAD 0u /* PINNED IN THE L5 MANIFEST: 3 x heartbeat at the private-timer
                        * clock. Left zero here on purpose — a guessed period is worse
                        * than an obviously unset one, and the value is a build input. */

/* ───────────────────────────── the PL's AXI window (L1 map) ───────────────────────── */

#define P3_AXI_BASE 0x43C00000u
#define P3_CTRL 0x2000u
#define P3_STATUS 0x2004u
#define P3_FAULT 0x2008u
#define P3_SCORE0 0x2010u
#define P3_HEARTBEAT 0x2028u
#define P3_NONCE_LO 0x202Cu
#define P3_NONCE_HI 0x2030u
#define P3_PAYLOAD0 0x2100u /* 20 write-only staging words */
#define P3_TAG0 0x2150u     /* 4 write-only tag words      */
#define P3_HW_COMMIT0 0x2200u
#define P3_READOUT0 0x2240u

/* The MAC key register is provisioned by the gate signer over the JTAG DAP mem-AP and is
 * absent from this map BY CONSTRUCTION: no constant here names it, and `axi_write()`
 * refuses any offset it does not recognise. `tests/test_firmware_audit.py` asserts that no
 * line of this file names those offsets. */

#define P3_ST_FAULT 1u
#define P3_ST_CFG_VALID_HW 2u
#define P3_ST_RECOVERY 7u
#define P3_ST_ALIVE 8u
#define P3_ST_KEY_LOADED 11u
#define P3_ST_RESERVED 0xF8000000u
#define P3_ARM_STROBE (1u << 6)

#define SLCR_PSS_IDCODE 0xF8000530u /* READ ONLY — this application writes no SLCR word */
#define P3_IDCODE_MASK 0x0FFFFFFFu

/* ───────────────────────────── DEVCFG (zynq-psmap §8a, verbatim) ──────────────────── */

#define DEVCFG_BASE 0xF8007000u
#define DEVCFG_CTRL (DEVCFG_BASE + 0x000u)
#define DEVCFG_INT_STS (DEVCFG_BASE + 0x00Cu)
#define DEVCFG_DMA_SRC_ADDR (DEVCFG_BASE + 0x018u)
#define DEVCFG_DMA_DEST_ADDR (DEVCFG_BASE + 0x01Cu)
#define DEVCFG_DMA_SRC_LEN (DEVCFG_BASE + 0x020u)
#define DEVCFG_DMA_DEST_LEN (DEVCFG_BASE + 0x024u)

#define PCAP_ENDPOINT 0xFFFFFFFFu
#define DMA_HOLD_TAG 0x1u
#define INT_STS_D_P_DONE (1u << 12)
#define INT_STS_DMA_DONE (1u << 13)
#define INT_STS_ERROR_MASK 0x00F4C840u
#define INT_STS_CLEAR_MASK (INT_STS_ERROR_MASK | INT_STS_D_P_DONE | INT_STS_DMA_DONE)
#define CTRL_PCAP_MASK 0x0C000000u /* PCAP_PR | PCAP_MODE */
#define DMA_SPIN_LIMIT 1000000

/* The FOUR legal DMA transactions (psmap §6a: the unit of adjudication is the whole
 * transaction, never a field). This application issues nothing else. */
typedef struct {
    uint32_t src, dst, src_len, dst_len;
} p3_dma;

static const p3_dma DMA_WRITE_ENVELOPE = {P3_WR_BUF | DMA_HOLD_TAG, PCAP_ENDPOINT,
                                          P3_STREAM_WORDS, 0};
static const p3_dma DMA_READ_COMMAND = {P3_CMD_BUF | DMA_HOLD_TAG, PCAP_ENDPOINT,
                                        P3_READBACK_CMD_WORDS, 0};
static const p3_dma DMA_READ_FRAME = {PCAP_ENDPOINT, P3_DST_BUF | DMA_HOLD_TAG, 0,
                                      P3_READBACK_WORDS};
static const p3_dma DMA_READ_CLEANUP = {P3_CMD_BUF | DMA_HOLD_TAG, PCAP_ENDPOINT,
                                        P3_CLEANUP_WORDS, 0};

/* ───────────────────────────────── epoch taxonomy (§3c) ───────────────────────────── */

typedef enum { P3_RUNNING = 0, P3_COMPLETED, P3_STOPPED, P3_PROTOCOL } p3_end_kind;

static const char *const END_NAME[] = {"RUNNING", "COMPLETED", "STOPPED", "PROTOCOL"};

static struct {
    p3_end_kind kind;
    const char *reason;
    uint32_t seq;
    p3_identity_page page;
    uint32_t frames[P3_TARGET_FRAMES][P3_FRAME_WORDS];
    uint32_t readback[P3_TARGET_FRAMES][P3_FRAME_WORDS];
    uint32_t scored, refused, audited;
    int audit_requested;       /* an AUDITREQ arrived in this candidate's exchange */
    int audit_served;          /* the host asked and we served raw words for … */
    uint32_t audit_served_seq; /* … this candidate (rule ix: the mark means served) */
    uint32_t crc_dropped;
    uint32_t envelope_int_sts[P3_ENVELOPE_COUNT];
    int closing_restore, closing_baseline, closing_unsigned;
    int have_last_reply;
    char last_commit[65];
    char last_tables[6][17];
    XScuWdt wdt;
} S;

static void p3_stop(p3_end_kind kind, const char *reason)
{
    if (S.kind == P3_RUNNING) { /* the first cause is the one recorded */
        S.kind = kind;
        S.reason = reason;
    }
}

/* ───────────────────────────────── register access ────────────────────────────────── */

static int axi_readable(uint32_t off)
{
    if (off == P3_STATUS || off == P3_FAULT || off == P3_HEARTBEAT || off == P3_NONCE_LO ||
        off == P3_NONCE_HI)
        return 1;
    if ((off & 3u) != 0u)
        return 0;
    if (off >= P3_SCORE0 && off < P3_SCORE0 + 6u * 4u)
        return 1;
    if (off >= P3_HW_COMMIT0 && off < P3_HW_COMMIT0 + 8u * 4u)
        return 1;
    if (off >= P3_READOUT0 && off < P3_READOUT0 + 12u * 4u)
        return 1;
    return 0;
}

static int axi_writable(uint32_t off)
{
    if (off == P3_CTRL)
        return 1;
    if ((off & 3u) != 0u)
        return 0;
    if (off >= P3_PAYLOAD0 && off < P3_PAYLOAD0 + 20u * 4u)
        return 1;
    if (off >= P3_TAG0 && off < P3_TAG0 + 4u * 4u)
        return 1;
    return 0;
}

/* An undecoded access is SLVERR and, on this board, a data abort (zynq-psmap P2), so the
 * allowlist is checked at the accessor rather than trusted from the call sites. */
static uint32_t axi_read(uint32_t off)
{
    if (!axi_readable(off)) {
        p3_stop(P3_STOPPED, "STOP_AXI: read outside the pinned map");
        return 0;
    }
    return Xil_In32(P3_AXI_BASE + off);
}

static void axi_write(uint32_t off, uint32_t value)
{
    if (!axi_writable(off)) {
        p3_stop(P3_STOPPED, "STOP_AXI: write outside the pinned map");
        return;
    }
    Xil_Out32(P3_AXI_BASE + off, value);
}

static uint64_t pl_nonce(void)
{
    uint32_t lo = axi_read(P3_NONCE_LO);
    uint32_t hi = axi_read(P3_NONCE_HI);
    return (uint64_t)lo | ((uint64_t)hi << 32);
}

/* ─────────────────────────────────── console framing (§5b) ────────────────────────── */

static char g_line[8192];   /* one inbound line            */
static char g_json[4096];   /* one decoded payload         */
static char g_payload[4096];/* one outbound payload, plain */
static char g_encoded[6144];/* one outbound payload, b64   */
static char g_body[7168];   /* one outbound line body      */

static void put_str(const char *s)
{
    while (*s)
        outbyte(*s++);
}

static void kick_watchdog(void)
{
    if (S.page.flags & 2u)
        XScuWdt_RestartWdt(&S.wdt); /* main loop only, after a framed line (§6a) */
}

/* `P3L5 <type> <seq> <token(32 hex)> <payload> <crc32>` — the FULL token in every line.
 * The framing itself is p3_wire's, so the host contract test judges these exact bytes. */
static void send_frame(const char *type, uint32_t seq, const char *payload)
{
    size_t n = p3_wire_line(type, seq, S.page.token, payload, g_body, sizeof(g_body));

    if (n == 0u) {
        p3_stop(P3_PROTOCOL, "PROTOCOL_FRAME: outbound line too long");
        return;
    }
    put_str(g_body);
    kick_watchdog();
}

/* Encodes `plain_len` bytes of g_payload and sends them as one frame. A builder that
 * overflowed returns 0 and we refuse to emit a truncated line rather than call it evidence. */
static void send_payload(const char *type, uint32_t seq, size_t plain_len)
{
    if (plain_len == 0u) {
        p3_stop(P3_PROTOCOL, "PROTOCOL_FRAME: payload builder overflowed");
        return;
    }
    p3_base64url((const uint8_t *)g_payload, plain_len, g_encoded);
    send_frame(type, seq, g_encoded);
}

/* A liveness beat at every progress point of a candidate. The collector calls three
 * heartbeat intervals of silence a CRASH (§3c), and a candidate is otherwise silent from
 * the sign reply until its record. This is deliberately driven by PROGRESS, not by a
 * clock: the global timer's rate follows CPU_6x4x, which is still an assumption until the
 * pre-board CPU_CLK_CTRL read, and liveness must not depend on an unverified constant. */
static void heartbeat(void)
{
    if (S.kind == P3_RUNNING)
        send_frame("HB", S.seq, "-");
}

static int recv_line(char *out, size_t max)
{
    size_t n = 0;
    for (;;) {
        char c = inbyte();
        if (c == '\n')
            break;
        if (c == '\r')
            continue;
        if (n + 1 >= max)
            return -1;
        out[n++] = c;
    }
    out[n] = 0;
    return (int)n;
}

/* Verifies magic, CRC, token and seq; writes the frame's type into `type_out` and returns
 * the payload field (still base64url). Mutates `line`. */
static const char *parse_frame(char *line, uint32_t want_seq, char *type_out, size_t type_max)
{
    char *last = strrchr(line, ' ');
    char expect[16];
    char *f[5];
    size_t i, k = 0;
    if (!last)
        return NULL;
    *last = 0; /* the CRC covers everything before the final field */
    snprintf(expect, sizeof(expect), "%08lx",
             (unsigned long)p3_crc32((const uint8_t *)line, strlen(line)));
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
    if (strtoul(f[2], NULL, 10) != (unsigned long)want_seq)
        return NULL;
    if (strcmp(f[3], S.page.token) != 0)
        return NULL;
    snprintf(type_out, type_max, "%s", f[1]);
    return f[4];
}

/* ─────────────────────────── minimal JSON field extraction ────────────────────────── */
/* The relay emits canonical compact JSON (sorted keys, no spaces) whose schema is pinned
 * in docs/contracts.md, so a key scan suffices — and every field is length- and
 * alphabet-checked rather than trusted. */

static int is_lower_hex(char c) { return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'); }

static int json_hex(const char *json, const char *key, char *out, size_t len)
{
    const char *p = strstr(json, key);
    size_t i;
    if (!p)
        return -1;
    p += strlen(key);
    for (i = 0; i < len; i++) {
        if (!is_lower_hex(p[i]))
            return -1;
        out[i] = p[i];
    }
    out[len] = 0;
    return p[len] == '"' ? 0 : -1;
}

/* the six tables are one JSON array; they must be walked in order, not searched for */
static int json_tables(const char *json, char tables[6][17])
{
    static const char key[] = "\"expected_tables\":[";
    const char *p = strstr(json, key);
    int i, k;
    if (!p)
        return -1;
    p += sizeof(key) - 1;
    for (i = 0; i < 6; i++) {
        if (*p++ != '"')
            return -1;
        for (k = 0; k < 16; k++) {
            if (!is_lower_hex(p[k]))
                return -1;
            tables[i][k] = p[k];
        }
        tables[i][16] = 0;
        p += 16;
        if (*p++ != '"')
            return -1;
        if (i < 5 && *p++ != ',')
            return -1;
    }
    return *p == ']' ? 0 : -1;
}

/* ───────────────────────────────── DMA (the four tuples) ──────────────────────────── */

static int devcfg_wait_done(void)
{
    int spins;
    for (spins = 0; spins < DMA_SPIN_LIMIT; spins++) {
        uint32_t sts = Xil_In32(DEVCFG_INT_STS);
        if (sts & INT_STS_ERROR_MASK) {
            p3_stop(P3_STOPPED, "DEVCFG error bit after a DMA");
            return -1;
        }
        if (sts & INT_STS_D_P_DONE) /* D_P_DONE: the DMA *and* PCAP; DMA_DONE alone is not */
            return 0;
    }
    p3_stop(P3_STOPPED, "DEVCFG D_P_DONE never asserted");
    return -1;
}

static int devcfg_dma(const p3_dma *t, uint32_t src_override)
{
    if ((Xil_In32(DEVCFG_CTRL) & CTRL_PCAP_MASK) != CTRL_PCAP_MASK) {
        p3_stop(P3_STOPPED, "DEVCFG CTRL is not in the required PCAP mode");
        return -1;
    }
    Xil_Out32(DEVCFG_INT_STS, INT_STS_CLEAR_MASK);
    if (Xil_In32(DEVCFG_INT_STS) & INT_STS_D_P_DONE) {
        p3_stop(P3_STOPPED, "DEVCFG INT_STS would not clear");
        return -1;
    }
    /* the four registers in the pinned order; the DEST_LEN write queues the command */
    Xil_Out32(DEVCFG_DMA_SRC_ADDR, src_override ? src_override : t->src);
    Xil_Out32(DEVCFG_DMA_DEST_ADDR, t->dst);
    Xil_Out32(DEVCFG_DMA_SRC_LEN, t->src_len);
    Xil_Out32(DEVCFG_DMA_DEST_LEN, t->dst_len);
    return devcfg_wait_done();
}

/* ───────────────────────────────── identity (§3b) ─────────────────────────────────── */

static int establish_identity(void)
{
    uint32_t page[P3_PAGE_WORDS];
    uint32_t st;
    int i;
    for (i = 0; i < P3_PAGE_WORDS; i++)
        page[i] = Xil_In32(P3_PAGE_ADDR + 4u * (uint32_t)i);
    if (p3_parse_identity_page(page, &S.page) != 0) {
        p3_stop(P3_STOPPED, "identity page magic/layout/checksum refused");
        return -1;
    }
    /* Every check is evaluated and reported, then the epoch stops if any of them fired.
     * The refused identity is still evidence, so IDENT is emitted either way — and it is
     * emitted at all, which the first L5 attempt could not do: validate_standalone_run_log
     * requires app_identity and this application never sent one. */
    {
        p3_wire_identity_in in;
        const char *findings[5];
        uint64_t nonce = pl_nonce();
        int nf = 0;
        uint32_t idcode = Xil_In32(SLCR_PSS_IDCODE);

        st = axi_read(P3_STATUS);
        if ((idcode & P3_IDCODE_MASK) != (P3_IDCODE & P3_IDCODE_MASK))
            findings[nf++] = "PSS_IDCODE is not this part";
        if ((st & P3_ST_RESERVED) || !((st >> P3_ST_ALIVE) & 1u))
            findings[nf++] = "STATUS is not the P3 carrier answering";
        if (!((st >> P3_ST_KEY_LOADED) & 1u))
            findings[nf++] = "key_loaded is 0: not the provisioned carrier instance";
        if (((st >> P3_ST_FAULT) & 1u) || ((st >> P3_ST_RECOVERY) & 1u))
            findings[nf++] = "fault/recovery before start";
        /* the nonce echo: a reconfiguration since the host's last look would have reset it */
        if (nonce != S.page.nonce_seen)
            findings[nf++] = "the nonce is not the host's last observation";

        memset(&in, 0, sizeof(in));
        in.pss_idcode = idcode;
        in.token = S.page.token;
        in.uboot_epoch = S.page.uboot_epoch;
        in.carrier_sha256 = S.page.carrier_sha256;
        in.nonce_at_start = nonce;
        in.status_at_start = st;
        in.fclk0_hz_decoded = S.page.fclk0_hz;   /* host-supplied, echoed (p3_derive.h) */
        in.app_epoch = 0;
        in.findings = nf ? findings : NULL;
        in.findings_n = nf;
        send_payload("IDENT", 0, p3_wire_identity(&in, g_payload, sizeof(g_payload)));

        if (nf)
            p3_stop(P3_STOPPED, "identity refused");
    }
    return S.kind == P3_RUNNING ? 0 : -1;
}

/* ────────────────────────── one candidate (§4.2 – §4.6) ───────────────────────────── */

static uint32_t hex_nibble(char c) { return (uint32_t)((c <= '9') ? c - '0' : c - 'a' + 10); }

static void hex_to_words_be(const char *hex, uint32_t *out, int words)
{
    int i, j;
    for (i = 0; i < words; i++) {
        uint32_t w = 0;
        for (j = 0; j < 8; j++)
            w = (w << 4) | hex_nibble(hex[8 * i + j]);
        out[i] = w;
    }
}

static uint64_t hex_to_u64(const char *hex)
{
    uint64_t v = 0;
    int i;
    for (i = 0; i < 16; i++)
        v = (v << 4) | (uint64_t)hex_nibble(hex[i]);
    return v;
}

static int stage_streams(void)
{
    uint32_t words[P3_STREAM_WORDS];
    int e, i;
    for (e = 0; e < P3_ENVELOPE_COUNT; e++) {
        p3_build_stream(e, P3_CFRAMES(S.frames), words);
        for (i = 0; i < P3_STREAM_WORDS; i++)
            Xil_Out32(P3_WR_BUF + (uint32_t)e * 4u * P3_STREAM_WORDS + 4u * (uint32_t)i,
                      words[i]);
    }
    return 0;
}

/* link 2: re-read the staged streams FROM DDR and hash what is actually there */
static int link2_witness(char *staged_hex, char *stream_hex)
{
    uint32_t frames5[P3_ENVELOPE_FRAMES][P3_FRAME_WORDS];
    uint32_t reread[P3_TARGET_FRAMES][P3_FRAME_WORDS];
    uint32_t words[P3_STREAM_WORDS];
    uint8_t digest[32];
    p3_sha256 c;
    int e, k, i;
    p3_sha256_init(&c);
    for (e = 0; e < P3_ENVELOPE_COUNT; e++) {
        uint32_t far_set;
        for (i = 0; i < P3_STREAM_WORDS; i++)
            words[i] = Xil_In32(P3_WR_BUF + (uint32_t)e * 4u * P3_STREAM_WORDS +
                                4u * (uint32_t)i);
        p3_sha256_words(&c, words, P3_STREAM_WORDS);
        if (p3_parse_stream(words, &far_set, frames5) != 0 || far_set != P3_ENVELOPE[e].far_set) {
            p3_stop(P3_STOPPED, "STOP_LINK2: the staged stream does not parse");
            return -1;
        }
        for (k = 0; k < 4; k++)
            memcpy(reread[P3_ENVELOPE[e].target[k]], frames5[k], sizeof(frames5[k]));
    }
    p3_sha256_final(&c, digest);
    p3_hex(digest, 32, stream_hex);
    p3_frames_hash(P3_CFRAMES(reread), digest);
    p3_hex(digest, 32, staged_hex);
    return 0;
}

static int write_envelopes(void)
{
    int e;
    for (e = 0; e < P3_ENVELOPE_COUNT; e++) {
        if (devcfg_dma(&DMA_WRITE_ENVELOPE,
                       (P3_WR_BUF + (uint32_t)e * 4u * P3_STREAM_WORDS) | DMA_HOLD_TAG) != 0)
            return -1;
        /* per-envelope DMA status, reported in the oracle self-report (spec §7) */
        S.envelope_int_sts[e] = Xil_In32(DEVCFG_INT_STS);
        heartbeat();
    }
    return 0;
}

/* link 3: the pinned three-command readback of one frame (psmap §8a) */
static int readback_frame(int index)
{
    uint32_t cmd[P3_READBACK_CMD_WORDS];
    uint32_t clean[P3_CLEANUP_WORDS];
    int i;
    for (i = 0; i < P3_READBACK_WORDS; i++)
        Xil_Out32(P3_DST_BUF + 4u * (uint32_t)i, P3_SENTINEL);
    for (i = 0; i < P3_READBACK_WORDS; i++)
        if (Xil_In32(P3_DST_BUF + 4u * (uint32_t)i) != P3_SENTINEL) {
            /* not confirmed present ⇒ the read is not attempted (psmap §7.5) */
            p3_stop(P3_STOPPED, "STOP_LINK3: the sentinel prefill did not verify");
            return -1;
        }
    p3_build_readback_command(P3_TARGET_FARS[index], cmd);
    for (i = 0; i < P3_READBACK_CMD_WORDS; i++)
        Xil_Out32(P3_CMD_BUF + 4u * (uint32_t)i, cmd[i]);
    if (devcfg_dma(&DMA_READ_COMMAND, 0) != 0)
        return -1;
    if (devcfg_dma(&DMA_READ_FRAME, 0) != 0)
        return -1;
    p3_build_cleanup_command(clean);
    for (i = 0; i < P3_CLEANUP_WORDS; i++)
        Xil_Out32(P3_CMD_BUF + 4u * (uint32_t)i, clean[i]);
    if (devcfg_dma(&DMA_READ_CLEANUP, 0) != 0)
        return -1;
    /* words [0:101] are the pad frame and are not adjudicated; [101:202] is the target */
    for (i = 0; i < P3_FRAME_WORDS; i++)
        S.readback[index][i] = Xil_In32(P3_DST_BUF + 4u * (uint32_t)(P3_FRAME_WORDS + i));
    return 0;
}

static int link3_witness(char *readback_hex)
{
    uint8_t digest[32];
    int i;
    for (i = 0; i < P3_TARGET_FRAMES; i++) { /* all twelve read before judging: L3 #1's lesson */
        if (readback_frame(i) != 0)
            return -1;
        heartbeat(); /* twelve PCAP readbacks is the session's longest silent stretch */
    }
    p3_frames_hash(P3_CFRAMES(S.readback), digest);
    p3_hex(digest, 32, readback_hex);
    return 0;
}

/* the ARM transaction: 24 staged words then the strobe. The tag is the notary's; this
 * application cannot produce one — it holds no key and has no path to the key register. */
static int arm_attempt(const char *commit_hex, const char tables_hex[6][17],
                       const char *tag_hex, uint64_t *nonce_before, uint64_t *nonce_after,
                       uint32_t *status, uint32_t *fault)
{
    uint32_t words[24];
    uint8_t tag[16];
    uint64_t t0 = 0, t1 = 0;
    int i;
    uint32_t st = axi_read(P3_STATUS);
    if (((st >> P3_ST_FAULT) & 1u) || ((st >> P3_ST_RECOVERY) & 1u)) {
        p3_stop(P3_STOPPED, "STOP_AXI: fault set before the ARM");
        return -1;
    }
    *nonce_before = pl_nonce();
    hex_to_words_be(commit_hex, words, 8);
    for (i = 0; i < 6; i++) {
        uint64_t t = hex_to_u64(tables_hex[i]);
        words[8 + 2 * i] = (uint32_t)(t >> 32);
        words[9 + 2 * i] = (uint32_t)t;
    }
    for (i = 0; i < 16; i++)
        tag[i] = (uint8_t)((hex_nibble(tag_hex[2 * i]) << 4) | hex_nibble(tag_hex[2 * i + 1]));
    for (i = 7; i >= 0; i--) { /* the tag's two 64-bit LITTLE-endian halves, high word first */
        t0 = (t0 << 8) | tag[i];
        t1 = (t1 << 8) | tag[8 + i];
    }
    words[20] = (uint32_t)(t0 >> 32);
    words[21] = (uint32_t)t0;
    words[22] = (uint32_t)(t1 >> 32);
    words[23] = (uint32_t)t1;

    for (i = 0; i < 20; i++)
        axi_write(P3_PAYLOAD0 + 4u * (uint32_t)i, words[i]);
    for (i = 0; i < 4; i++)
        axi_write(P3_TAG0 + 4u * (uint32_t)i, words[20 + i]);
    axi_write(P3_CTRL, P3_ARM_STROBE);

    *status = axi_read(P3_STATUS);
    *fault = axi_read(P3_FAULT);
    *nonce_after = pl_nonce();
    if (*nonce_after == *nonce_before) {
        p3_stop(P3_STOPPED, "the nonce did not step: the PL did not consume this ARM");
        return -1;
    }
    return 0;
}

/* ───────────────────────────────── the session ────────────────────────────────────── */

/* The search is out of D1's scope; only its interface is fixed (§4.1). The reference
 * sampler lives in p3_search.c and returns non-zero at its own stop condition. */
extern int p3_search_next(uint32_t genome[P3_GENOME_WORDS], uint32_t seed, uint32_t index);

/* ───────────────────────────── audit-on-request (§4.7) ────────────────────────────── */

/* The raw words behind one candidate's self-report: the three re-read staging streams
 * followed by the twelve readback frames, in that fixed order. The collector recomputes
 * both link-2 hashes and the link-3 hash from them and compares with the compact record. */
#define P3_AUDIT_STREAM_WORDS (P3_ENVELOPE_COUNT * P3_STREAM_WORDS)
#define P3_AUDIT_FRAME_WORDS (P3_TARGET_FRAMES * P3_FRAME_WORDS)
#define P3_AUDIT_WORDS (P3_AUDIT_STREAM_WORDS + P3_AUDIT_FRAME_WORDS)
#define P3_AUDIT_CHUNK 384 /* 1536 B raw -> 2048 B base64, well inside g_payload */

static uint8_t g_chunk[P3_AUDIT_CHUNK * 4];
static char g_words_b64[P3_AUDIT_CHUNK * 4 * 2];

static uint32_t audit_word(uint32_t i)
{
    if (i < (uint32_t)P3_AUDIT_STREAM_WORDS)
        return Xil_In32(P3_WR_BUF + 4u * i);
    i -= (uint32_t)P3_AUDIT_STREAM_WORDS;
    return S.readback[i / P3_FRAME_WORDS][i % P3_FRAME_WORDS];
}

/* `with_readback` is 0 for a candidate that ended at link 2: its staging streams exist but
 * its readback frames do not, and serving stale frames as if they were this candidate's
 * would be worse than serving none. The `span` field says which it is, so a short audit is
 * never mistaken for a full one. */
static void serve_audit(int with_readback)
{
    uint32_t total = with_readback ? (uint32_t)P3_AUDIT_WORDS
                                   : (uint32_t)P3_AUDIT_STREAM_WORDS;
    const char *span = with_readback ? "streams+readback" : "streams";
    uint32_t chunks = (total + P3_AUDIT_CHUNK - 1) / P3_AUDIT_CHUNK;
    uint32_t c;

    for (c = 0; c < chunks && S.kind == P3_RUNNING; c++) {
        uint32_t off = c * (uint32_t)P3_AUDIT_CHUNK;
        uint32_t count = total - off;
        uint32_t i;
        size_t b64n;

        if (count > (uint32_t)P3_AUDIT_CHUNK)
            count = (uint32_t)P3_AUDIT_CHUNK;
        for (i = 0; i < count; i++) { /* big-endian, as the host decodes them */
            uint32_t w = audit_word(off + i);
            g_chunk[4 * i] = (uint8_t)(w >> 24);
            g_chunk[4 * i + 1] = (uint8_t)(w >> 16);
            g_chunk[4 * i + 2] = (uint8_t)(w >> 8);
            g_chunk[4 * i + 3] = (uint8_t)w;
        }
        b64n = p3_base64url(g_chunk, count * 4u, g_words_b64);
        if (b64n == 0u) {
            p3_stop(P3_PROTOCOL, "PROTOCOL: the audit chunk did not encode");
            return;
        }
        send_payload("AUDIT", S.seq,
                     p3_wire_audit(S.seq, c, chunks, off, count, total, span, g_words_b64,
                                   g_payload, sizeof(g_payload)));
    }
    if (S.kind == P3_RUNNING) {
        S.audit_served = 1;
        S.audit_served_seq = S.seq;
    }
}

/* One candidate's record, built by p3_wire so it carries `seq`, `verified` and the nested
 * `evidence` the validator requires — the shape the flat payload this replaced never had.
 * `rec` is populated as the transaction proceeds; `outcome` selects which members the
 * validator will then insist on. */
static void emit_record(p3_wire_record_in *rec, const char *outcome)
{
    rec->outcome = outcome;
    /* `audited` means the host ASKED and this application SERVED the raw words for this
     * candidate — never merely that auditing was configured. A record that claimed the
     * mark without the words would be exactly the self-report rule (ix) exists to bound. */
    rec->audited = (S.audit_served && S.audit_served_seq == rec->seq);
    if (rec->audited)
        S.audited++;
    send_payload("REC", rec->seq, p3_wire_loop_record(rec, g_payload, sizeof(g_payload)));
}

/* returns 0 to continue the session, -1 when the epoch has ended */
static int run_candidate(const uint32_t genome[P3_GENOME_WORDS], int is_baseline)
{
    char genome_hex[P3_GENOME_WORDS * 8 + 1];
    char type[16];
    char commit[65], tag[33], staged[65], stream_h[65], readback[65];
    char tables[6][17];
    p3_wire_record_in rec;
    const char *payload;
    size_t jn;
    uint64_t nonce_before, nonce_after;
    uint32_t status, fault, hb_before;
    int i, n;

    S.seq++;
    p3_genome_to_hex(genome, genome_hex);
    memset(&rec, 0, sizeof(rec));
    rec.seq = S.seq;
    rec.genome = genome_hex;
    send_payload("SIGNREQ", S.seq,
                 p3_wire_sign_request(S.page.token, 0, S.seq, genome_hex, pl_nonce(),
                                      g_payload, sizeof(g_payload)));
    if (S.kind != P3_RUNNING)
        return -1;

    /* The host may attach `AUDITREQ` to this exchange (§4.7) before answering. It is read
     * here, BEFORE this candidate is staged, so the raw words it will be asked for do not
     * yet exist and cannot be fabricated to fit a record; they are served after link 3 and
     * before the record, which is why `verified` can be truthful at emission.
     * Honest limitation: because the request arrives in advance, this is weaker than a
     * surprise post-hoc audit at rates below 100%. Session 1 audits every candidate, so
     * every record it emits is backed by served words. */
    S.audit_requested = 0;
    for (;;) {
        n = recv_line(g_line, sizeof(g_line));
        if (n < 0) {
            p3_stop(P3_PROTOCOL, "PROTOCOL_FRAME: the reply line is too long");
            return -1;
        }
        payload = parse_frame(g_line, S.seq, type, sizeof(type));
        if (!payload) {
            p3_stop(P3_PROTOCOL, "PROTOCOL: the notary reply did not verify");
            return -1;
        }
        if (strcmp(type, "AUDITREQ") != 0)
            break;
        S.audit_requested = 1;
    }
    if (!strcmp(type, "SIGNREF")) {
        /* a gate refusal is DATA, not a channel failure (§3c): the session continues.
         * NOT audited, and deliberately so: nothing was staged, so no raw words exist, and
         * this record makes no oracle self-report to check. Its evidence is the notary's
         * OWN refusal, which the host already holds and rule (vii) cross-checks — a
         * stronger corroboration than an audit, not a weaker one. */
        static const char *const refused_kind[] = {"gate_refusal"};
        S.refused++;
        rec.have_sign_refusal = 1;
        rec.finding_kinds = refused_kind;
        rec.finding_kinds_n = 1;
        emit_record(&rec, "REFUSED_BY_GATE");
        return 0;
    }
    if (strcmp(type, "SIGNOK") != 0) {
        p3_stop(P3_PROTOCOL, "PROTOCOL: unexpected reply type");
        return -1;
    }
    jn = p3_base64url_decode(payload, (uint8_t *)g_json, sizeof(g_json) - 1u);
    if (jn == 0u) {
        p3_stop(P3_PROTOCOL, "PROTOCOL: the reply payload is not base64url");
        return -1;
    }
    g_json[jn] = 0;
    if (!strstr(g_json, "\"schema\":\"sign_reply\"") ||
        json_hex(g_json, "\"commit\":\"", commit, 64) != 0 ||
        json_hex(g_json, "\"tag\":\"", tag, 32) != 0 || json_tables(g_json, tables) != 0) {
        p3_stop(P3_PROTOCOL, "PROTOCOL: the reply is not a well-formed sign_reply");
        return -1;
    }

    rec.have_sign_reply = 1;
    rec.commit = commit;
    rec.tag = tag;
    for (i = 0; i < 6; i++)
        rec.tables[i] = tables[i];

    p3_derive_frames(genome, S.frames);
    stage_streams();
    heartbeat();
    if (link2_witness(staged, stream_h) != 0)
        return -1;
    if (strcmp(staged, commit) != 0) { /* the binding, BEFORE any DMA */
        p3_stop(P3_STOPPED, "STOP_LINK2: staged frames are not the signed commit");
        /* The staging streams exist, so this refusal is auditable and IS audited: the
         * application is asserting `staged != commit` and the host would otherwise have to
         * take that on trust. The readback frames do not exist, hence a "streams" span. */
        if (S.audit_requested)
            serve_audit(0);
        emit_record(&rec, "STOP_LINK2");
        return -1;
    }
    /* link 2 held: the oracle self-report can now be filled in. `readback` is still empty
     * and is set after link 3; the validator refuses an ARM without readback == commit. */
    rec.have_oracle = 1;
    rec.staged_sha256 = staged;
    rec.staged_stream_sha256 = stream_h;
    rec.readback_sha256 = readback;
    rec.envelopes_n = P3_ENVELOPE_COUNT;
    rec.envelope_int_sts = S.envelope_int_sts;
    rec.audit_available = 1;
    memset(readback, '0', 64); /* the schema wants 64 hex; link 3 overwrites it below */
    readback[64] = 0;
    if (write_envelopes() != 0)
        return -1;
    if (link3_witness(readback) != 0)
        return -1;
    /* the words exist now, so an audit promised in this exchange is served BEFORE the
     * record that will claim it — including on the STOP_LINK3 path, where the raw words
     * are exactly what a reviewer would want */
    if (S.audit_requested)
        serve_audit(1);
    if (strcmp(readback, commit) != 0) {
        p3_stop(P3_STOPPED, "STOP_LINK3: the fabric did not read back as the candidate");
        emit_record(&rec, "STOP_LINK3");
        return -1;
    }
    hb_before = axi_read(P3_HEARTBEAT);
    if (arm_attempt(commit, (const char(*)[17])tables, tag, &nonce_before, &nonce_after,
                    &status, &fault) != 0)
        return -1;
    rec.have_arm = 1;
    rec.nonce_before = nonce_before;
    rec.nonce_after = nonce_after;
    rec.status_after = status;
    rec.fault_after = fault;
    rec.key_loaded_observed = (int)((status >> P3_ST_KEY_LOADED) & 1u);
    if (!((status >> P3_ST_CFG_VALID_HW) & 1u)) {
        emit_record(&rec, "REFUSED_BY_PL");
        /* the fault code names the check that fired, not its cause (spec §4.6) */
        p3_stop(P3_STOPPED, "the PL refused the ARM");
        return -1;
    }
    {
        /* The PL's OWN witness of what it bound. These are read back from the hardware,
         * never echoed from the signed reply: rules (ii) and (iii) compare them with the
         * signed commit and tables, and an echo would make both checks vacuous. */
        char readout[6][17];
        char hw_commit[65];
        rec.have_score = 1;
        for (i = 0; i < 8; i++)
            snprintf(hw_commit + 8 * i, 9, "%08lx",
                     (unsigned long)axi_read(P3_HW_COMMIT0 + 4u * (uint32_t)i));
        rec.hw_candidate_commit = hw_commit;
        for (i = 0; i < 6; i++) {
            uint32_t hi = axi_read(P3_READOUT0 + 4u * (uint32_t)(2 * i));
            uint32_t lo = axi_read(P3_READOUT0 + 4u * (uint32_t)(2 * i + 1));
            snprintf(readout[i], sizeof(readout[i]), "%08lx%08lx",
                     (unsigned long)hi, (unsigned long)lo);
            rec.readout[i] = readout[i];
            rec.scores[i] = axi_read(P3_SCORE0 + 4u * (uint32_t)i);
        }
        rec.hb_before = hb_before;
        rec.hb_after = axi_read(P3_HEARTBEAT);
        emit_record(&rec, "SCORED");
    }
    S.scored++;
    memcpy(S.last_commit, commit, sizeof(commit));
    memcpy(S.last_tables, tables, sizeof(tables));
    S.have_last_reply = 1;
    if (is_baseline)
        S.closing_baseline = 1;
    return 0;
}

/* the closing control: the last signed candidate's payload with a ZERO tag must be refused
 * (§4.0). The fault it raises is sticky, which is why it is the last device operation. */
static void closing_unsigned_control(void)
{
    static const char zero_tag[] = "00000000000000000000000000000000";
    uint64_t nb, na;
    uint32_t status, fault;
    if (!S.have_last_reply) {
        p3_stop(P3_STOPPED, "no signed candidate to build the closing control from");
        return;
    }
    if (arm_attempt(S.last_commit, (const char(*)[17])S.last_tables, zero_tag, &nb, &na,
                    &status, &fault) != 0)
        return;
    if ((status >> P3_ST_CFG_VALID_HW) & 1u) {
        p3_stop(P3_STOPPED, "KILL: the closing unsigned ARM validated");
        return;
    }
    /* Its own frame type, not a loop_record: "CLOSING_CONTROL" is not a LOOP_OUTCOME and
     * the validator reads this from the log's `closing_negative` key (§4.0, rule viii). */
    send_payload("CLOSE", S.seq,
                 p3_wire_closing(nb, na, fault, status, g_payload, sizeof(g_payload)));
    S.closing_unsigned = 1;
}

static void emit_summary(void)
{
    p3_wire_summary_in in;

    memset(&in, 0, sizeof(in));
    in.token = S.page.token;
    in.kind = END_NAME[S.kind];
    in.reason = S.reason ? S.reason : "";
    in.last_seq = S.seq;
    in.scored = S.scored;
    in.refused_by_gate = S.refused;
    in.closing_restore = S.closing_restore;
    in.closing_baseline = S.closing_baseline;
    in.closing_unsigned = S.closing_unsigned;
    in.audited = S.audited;
    in.total = S.scored + S.refused;
    in.crc_dropped = S.crc_dropped;
    in.drop_budget = P3_DROP_BUDGET;
    send_payload("TERM", S.seq + 1u, p3_wire_summary(&in, g_payload, sizeof(g_payload)));
}

int main(void)
{
    uint32_t genome[P3_GENOME_WORDS];
    uint32_t blank[P3_GENOME_WORDS];
    uint32_t i;

    /* The DDR this instrument uses is mapped strongly-ordered and NON-CACHEABLE before it
     * is touched. Staging through the D-cache is the defect the L3 diagnostic session found
     * (docs/l3_findings.md): the DMA read stale DDR while the re-read "confirmed" the
     * cached copy. Per-operation flushes are the version of that fix which is silently
     * wrong the first time one call is missed — so no cache maintenance appears below. */
    Xil_SetTlbAttributes(P3_CMD_BUF, P3_NONCACHEABLE);
    Xil_SetTlbAttributes(P3_DST_BUF, P3_NONCACHEABLE);
    Xil_SetTlbAttributes(P3_WR_BUF, P3_NONCACHEABLE);
    Xil_SetTlbAttributes(P3_PAGE_ADDR, P3_NONCACHEABLE);
    for (i = 0; i < 8u * P3_MB; i += P3_MB)
        Xil_SetTlbAttributes(P3_RING_ADDR + i, P3_NONCACHEABLE);

    memset(&S, 0, sizeof(S));
    S.kind = P3_RUNNING;

    if (establish_identity() != 0) {
        emit_summary();
        return 0;
    }

    /* the watchdog is armed only once identity holds, and is kicked from this loop alone */
    if (S.page.flags & 2u) {
        XScuWdt_Config *cfg = XScuWdt_LookupConfig(XPAR_PS7_SCUWDT_0_DEVICE_ID);
        XScuWdt_CfgInitialize(&S.wdt, cfg, cfg->BaseAddr);
        XScuWdt_LoadWdt(&S.wdt, P3_WDT_LOAD);
        XScuWdt_Start(&S.wdt);
    }

    memset(blank, 0, sizeof(blank)); /* the blank genome IS the pinned base */

    if (run_candidate(blank, 1) == 0) { /* opening baseline = the session's positive control */
        for (i = 0; S.kind == P3_RUNNING && (S.page.budget == 0u || i < S.page.budget); i++) {
            /* the stop condition is checked BEFORE a candidate is proposed, so a normal
             * end always reaches the closing brackets (§4.0) */
            if (p3_search_next(genome, S.page.seed, i) != 0)
                break;
            if (run_candidate(genome, 0) != 0)
                break;
        }
        if (S.kind == P3_RUNNING) {
            if (run_candidate(blank, 1) == 0) { /* closing baseline = restore + score */
                S.closing_restore = 1;
                closing_unsigned_control();
            }
            if (S.kind == P3_RUNNING)
                p3_stop(P3_COMPLETED, "budget");
        }
    }

    if (S.kind == P3_STOPPED && !S.closing_restore) {
        /* the mandatory finally: restore the base — a WRITE, never an ARM after a sticky
         * fault (§4.0). A failure here changes nothing that is already true of the epoch. */
        p3_derive_frames(blank, S.frames);
        if (stage_streams() == 0 && write_envelopes() == 0)
            S.closing_restore = 1;
    }
    emit_summary();
    return 0;
}
