/* p3_twin — the host driver that proves `p3_derive.c` equals the Python reference.
 *
 * Host-only: compiled with the host gcc, never for the board. It exposes the pure layer
 * on stdin/stdout so `tests/test_firmware_twin.py` can drive the whole pinned corpus
 * (N = 256) and compare bit for bit. Modes:
 *
 *   derive   < genome-hex lines   -> "<candidate_sha256> <sequence_sha256>"
 *   parse    < genome-hex lines   -> "ok" | "parse-failed"   (build → parse → compare)
 *   nonce    < 16-hex lines       -> the stepped nonce
 *   crc32    < ascii lines        -> crc32 of the line body
 *   b64      < hex lines          -> base64url of those bytes
 *   page     < 24 hex words/line  -> "<token> <uboot_epoch> <carrier_sha256> <nonce> …"
 *   ecc      < 101 hex words/line -> the frame's ECC after an update
 *   b64d     < base64url lines    -> the decoded bytes as hex, or "bad-b64"
 *   rbcmd    < far hex lines      -> the 43-word readback command stream, hex
 *   cleanup  < (any line)         -> the 5-word cleanup stream, hex
 *   pairseed < "master pair" lines  -> the 32-bit pair seed (hex)           [L6 §2]
 *   arm      < "index mode" lines   -> the arm name, or "unassigned-mode"   [L6 §2]
 *   candidate < "master index mode" -> "<arm> <pair_seed hex> <genome hex>" [L6 §2]
 */

#include "p3_derive.h"
#include "p3_data.h"

/* the two-operator search (p3_search.c), linked in for the corpus twin */
extern const char *const P3_ARM_NAME[2];
uint32_t p3_pair_seed(uint32_t master_seed, uint32_t pair);
int p3_arm_for(uint32_t index, uint32_t mode);
int p3_search_next(uint32_t genome[P3_GENOME_WORDS], uint32_t master_seed, uint32_t index,
                   uint32_t mode, int *arm_out);

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static uint32_t frames[P3_TARGET_FRAMES][P3_FRAME_WORDS];
static uint32_t frames5[P3_ENVELOPE_FRAMES][P3_FRAME_WORDS];
static uint32_t stream[P3_ENVELOPE_COUNT][P3_STREAM_WORDS];

static int mode_derive(char *line, int check_parse)
{
    uint32_t genome[P3_GENOME_WORDS];
    uint8_t digest[32];
    char hex[65], seq_hex[65];
    p3_sha256 c;
    int e;

    if (p3_genome_from_hex(line, genome) != 0) {
        printf("bad-genome\n");
        return 0;
    }
    p3_derive_frames(genome, frames);
    for (e = 0; e < P3_ENVELOPE_COUNT; e++)
        p3_build_stream(e, P3_CFRAMES(frames), stream[e]);

    if (check_parse) {
        /* build → parse → the four target frames must come back identical, and the
         * flush frame must be the pinned base one (the parser is what link 2 uses) */
        for (e = 0; e < P3_ENVELOPE_COUNT; e++) {
            uint32_t far_set;
            int k;
            if (p3_parse_stream(stream[e], &far_set, frames5) != 0) {
                printf("parse-failed\n");
                return 0;
            }
            if (far_set != P3_ENVELOPE[e].far_set) {
                printf("far-mismatch\n");
                return 0;
            }
            for (k = 0; k < 4; k++)
                if (memcmp(frames5[k], frames[P3_ENVELOPE[e].target[k]],
                           sizeof(frames5[k])) != 0) {
                    printf("frame-mismatch\n");
                    return 0;
                }
            if (memcmp(frames5[4], P3_BASE_FLUSH[P3_ENVELOPE[e].flush], sizeof(frames5[4])) != 0) {
                printf("flush-mismatch\n");
                return 0;
            }
        }
        printf("ok\n");
        return 0;
    }

    p3_frames_hash(P3_CFRAMES(frames), digest);
    p3_hex(digest, 32, hex);
    p3_sha256_init(&c);
    for (e = 0; e < P3_ENVELOPE_COUNT; e++)
        p3_sha256_words(&c, stream[e], P3_STREAM_WORDS);
    p3_sha256_final(&c, digest);
    p3_hex(digest, 32, seq_hex);
    printf("%s %s\n", hex, seq_hex);
    return 0;
}

static int read_words(char *line, uint32_t *out, int n)
{
    char *p = line;
    int i;
    for (i = 0; i < n; i++) {
        unsigned long v;
        char *end;
        v = strtoul(p, &end, 16);
        if (end == p)
            return -1;
        out[i] = (uint32_t)v;
        p = end;
    }
    return 0;
}

int main(int argc, char **argv)
{
    char line[8192];
    const char *mode = argc > 1 ? argv[1] : "derive";

    while (fgets(line, sizeof(line), stdin)) {
        size_t n = strlen(line);
        while (n && (line[n - 1] == '\n' || line[n - 1] == '\r'))
            line[--n] = 0;
        if (!n)
            continue;
        if (!strcmp(mode, "derive")) {
            mode_derive(line, 0);
        } else if (!strcmp(mode, "parse")) {
            mode_derive(line, 1);
        } else if (!strcmp(mode, "nonce")) {
            unsigned long long v = 0;
            sscanf(line, "%llx", &v);
            printf("%016llx\n", (unsigned long long)p3_nonce_step((uint64_t)v));
        } else if (!strcmp(mode, "crc32")) {
            printf("%08x\n", p3_crc32((const uint8_t *)line, n));
        } else if (!strcmp(mode, "b64")) {
            uint8_t raw[2048];
            char out[4096];
            size_t i, m = n / 2;
            for (i = 0; i < m && i < sizeof(raw); i++) {
                unsigned int b;
                sscanf(line + 2 * i, "%2x", &b);
                raw[i] = (uint8_t)b;
            }
            p3_base64url(raw, m, out);
            printf("%s\n", out);
        } else if (!strcmp(mode, "page")) {
            uint32_t w[P3_PAGE_WORDS];
            p3_identity_page id;
            if (read_words(line, w, P3_PAGE_WORDS) != 0 || p3_parse_identity_page(w, &id) != 0) {
                printf("page-refused\n");
                continue;
            }
            printf("%s %u %u %s %016llx %08x %u %u %u\n", id.token, id.uboot_epoch,
                   id.app_image_sha_lo32, id.carrier_sha256,
                   (unsigned long long)id.nonce_seen, id.status_seen, id.seed, id.budget,
                   id.flags);
        } else if (!strcmp(mode, "b64d")) {
            uint8_t raw[4096];
            char out[8193];
            size_t m = p3_base64url_decode(line, raw, sizeof(raw));
            if (m == 0) {
                printf("bad-b64\n");
                continue;
            }
            p3_hex(raw, m, out);
            printf("%s\n", out);
        } else if (!strcmp(mode, "rbcmd")) {
            uint32_t cmd[P3_READBACK_CMD_WORDS];
            unsigned long far = strtoul(line, NULL, 16);
            int i;
            p3_build_readback_command((uint32_t)far, cmd);
            for (i = 0; i < P3_READBACK_CMD_WORDS; i++)
                printf("%08x%s", cmd[i], i + 1 == P3_READBACK_CMD_WORDS ? "\n" : " ");
        } else if (!strcmp(mode, "cleanup")) {
            uint32_t cmd[P3_CLEANUP_WORDS];
            int i;
            p3_build_cleanup_command(cmd);
            for (i = 0; i < P3_CLEANUP_WORDS; i++)
                printf("%08x%s", cmd[i], i + 1 == P3_CLEANUP_WORDS ? "\n" : " ");
        } else if (!strcmp(mode, "pairseed")) {
            unsigned long master = 0, pair = 0;
            if (sscanf(line, "%lx %lu", &master, &pair) != 2) {
                printf("bad-args\n");
                continue;
            }
            printf("%08x\n", p3_pair_seed((uint32_t)master, (uint32_t)pair));
        } else if (!strcmp(mode, "arm")) {
            unsigned long index = 0, smode = 0;
            int arm;
            if (sscanf(line, "%lu %lu", &index, &smode) != 2) {
                printf("bad-args\n");
                continue;
            }
            arm = p3_arm_for((uint32_t)index, (uint32_t)smode);
            printf("%s\n", arm < 0 ? "unassigned-mode" : P3_ARM_NAME[arm]);
        } else if (!strcmp(mode, "candidate")) {
            unsigned long master = 0, index = 0, smode = 0;
            uint32_t genome[P3_GENOME_WORDS];
            char hex[P3_GENOME_WORDS * 8 + 1];
            int arm;
            if (sscanf(line, "%lx %lu %lu", &master, &index, &smode) != 3) {
                printf("bad-args\n");
                continue;
            }
            if (p3_search_next(genome, (uint32_t)master, (uint32_t)index, (uint32_t)smode, &arm) != 0) {
                printf("unassigned-mode\n");
                continue;
            }
            p3_genome_to_hex(genome, hex);
            printf("%s %08x %s\n", P3_ARM_NAME[arm], p3_pair_seed((uint32_t)master, (uint32_t)index / 2u), hex);
        } else if (!strcmp(mode, "ecc")) {
            uint32_t f[P3_FRAME_WORDS];
            if (read_words(line, f, P3_FRAME_WORDS) != 0) {
                printf("bad-frame\n");
                continue;
            }
            p3_frame_update_ecc(f);
            printf("%08x\n", f[0x32]);
        } else {
            fprintf(stderr, "unknown mode %s\n", mode);
            return 2;
        }
        fflush(stdout);
    }
    return 0;
}
