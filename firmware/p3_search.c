/* p3_search — the two-operator search behind D1 §4.1's interface (L6 prereg §2).
 *
 * The L5 reference sampler said "a real search replaces this file and nothing else"; this
 * is that replacement, and the interface grew exactly two things the L6 preregistration
 * requires: the schedule mode (identity-page flags bits 2–3) and the arm the candidate
 * ran in, which the record must name (§2.4). Determinism is the property everything
 * rests on: the same (master seed, index, mode) yields the same arm, pair seed and
 * genome here and in host/l6_operators.py / host/l6_schedule.py, bit for bit, over the
 * 256-pair corpus fixtures/l6_operator_corpus_v1.json (tests/test_firmware_twin.py).
 *
 *   schedule (Claim B's A,B,B,A rule, host/l6_schedule.py:arm_abba / pair_seed)
 *     candidates 2k and 2k+1 form pair k and share pair seed k; pair 0 runs A,B, pair 1
 *     runs B,A, alternating — neither arm systematically runs second. The pair seed is
 *     PAIR_SEED_RULE: upper 32 bits of the xorshift64 state after 4 steps from
 *     x0 = ((master<<32) | master) ^ (((pair+1) * golden) mod 2^64), x0 = golden if 0.
 *   random-safe (arm A)   P3_MUTATION_BITS addresses drawn uniformly without replacement
 *                         from the 292 whitelisted addresses — same universe, no map.
 *   map-guided  (arm B)   one LUT drawn uniformly from the map's P3_LUT_COUNT, then
 *                         P3_MUTATION_BITS of its mapped INIT positions without
 *                         replacement — same-LUT locality, the one thing the map knows.
 *
 * The generator is the PL's xorshift64 (p3_nonce_step): one implementation on both sides.
 * Uniform draws use the upper 32 bits with rejection below floor(2^32/n)*n, so nothing
 * here needs more than integer arithmetic. Only P3_WHITELIST's index space (the genome
 * bit order) is used; the operators never see an address, only a bit index.
 */

#include "p3_derive.h"
#include "p3_data.h"

#define P3_GOLDEN 0x9E3779B97F4A7C15ull
#define P3_WARMUP_STEPS 4
#define P3_ARM_RANDOM_SAFE 0
#define P3_ARM_MAP_GUIDED 1
#define P3_MODE_ABBA 0u
#define P3_MODE_A_FORCED 1u
#define P3_MODE_B_FORCED 2u

const char *const P3_ARM_NAME[2] = {"random_safe", "map_guided"};
const char *const P3_MODE_NAME[3] = {"abba", "random_safe_forced", "map_guided_forced"};

/* ------------------------------------------------------------------ schedule ------- */

uint32_t p3_pair_seed(uint32_t master_seed, uint32_t pair)
{
    uint64_t x = (((uint64_t)master_seed << 32) | (uint64_t)master_seed) ^
                 ((uint64_t)(pair + 1u) * P3_GOLDEN);
    int i;
    if (x == 0ull)
        x = P3_GOLDEN;
    for (i = 0; i < P3_WARMUP_STEPS; i++)
        x = p3_nonce_step(x);
    return (uint32_t)(x >> 32);
}

int p3_arm_abba(uint32_t index)
{
    uint32_t pair = index / 2u, second = index % 2u;
    int first_is_a = (pair % 2u) == 0u;
    return (first_is_a ^ (int)second) ? P3_ARM_RANDOM_SAFE : P3_ARM_MAP_GUIDED;
}

/* -1 for an unassigned mode: the caller refuses the session rather than guessing */
int p3_arm_for(uint32_t index, uint32_t mode)
{
    if (mode == P3_MODE_ABBA)
        return p3_arm_abba(index);
    if (mode == P3_MODE_A_FORCED)
        return P3_ARM_RANDOM_SAFE;
    if (mode == P3_MODE_B_FORCED)
        return P3_ARM_MAP_GUIDED;
    return -1;
}

/* ------------------------------------------------------------------ the generator -- */

typedef struct {
    uint64_t x;
} p3_rng;

static void rng_init(p3_rng *r, uint32_t seed32)
{
    uint64_t x = (((uint64_t)seed32 << 32) | (uint64_t)seed32) ^ P3_GOLDEN;
    int i;
    r->x = x ? x : P3_GOLDEN;
    for (i = 0; i < P3_WARMUP_STEPS; i++)
        r->x = p3_nonce_step(r->x);
}

static uint32_t rng_next32(p3_rng *r)
{
    r->x = p3_nonce_step(r->x);
    return (uint32_t)(r->x >> 32);
}

/* unbiased in [0, n): rejection below the largest multiple of n that fits in 32 bits */
static uint32_t rng_uniform(p3_rng *r, uint32_t n)
{
    uint64_t limit = ((1ull << 32) / n) * n;
    for (;;) {
        uint32_t v = rng_next32(r);
        if ((uint64_t)v < limit)
            return v % n;
    }
}

/* k distinct elements of pool[0..n) by partial Fisher–Yates; the draw order is the
 * host's (host/l6_operators.py:Rng.sample), and pool is permuted in place */
static void rng_sample(p3_rng *r, uint16_t *pool, uint32_t n, uint32_t k, uint16_t *out)
{
    uint32_t i;
    for (i = 0; i < k; i++) {
        uint32_t j = i + rng_uniform(r, n - i);
        uint16_t t = pool[i];
        pool[i] = pool[j];
        pool[j] = t;
        out[i] = pool[i];
    }
}

/* ------------------------------------------------------------------ the operators -- */

static void set_bit(uint32_t genome[P3_GENOME_WORDS], uint32_t bit)
{
    genome[bit / 32u] |= 1u << (bit % 32u);
}

void p3_op_random_safe(uint32_t seed32, uint32_t genome[P3_GENOME_WORDS])
{
    static uint16_t pool[P3_GENOME_BITS];
    uint16_t picked[P3_MUTATION_BITS];
    p3_rng r;
    uint32_t i;
    for (i = 0; i < (uint32_t)P3_GENOME_BITS; i++)
        pool[i] = (uint16_t)i;
    for (i = 0; i < (uint32_t)P3_GENOME_WORDS; i++)
        genome[i] = 0u;
    rng_init(&r, seed32);
    rng_sample(&r, pool, (uint32_t)P3_GENOME_BITS, (uint32_t)P3_MUTATION_BITS, picked);
    for (i = 0; i < (uint32_t)P3_MUTATION_BITS; i++)
        set_bit(genome, picked[i]);
}

void p3_op_map_guided(uint32_t seed32, uint32_t genome[P3_GENOME_WORDS])
{
    static uint16_t pool[P3_LUT_MAX_BITS];
    uint16_t picked[P3_MUTATION_BITS];
    p3_rng r;
    uint32_t i, lut, len, k;
    for (i = 0; i < (uint32_t)P3_GENOME_WORDS; i++)
        genome[i] = 0u;
    rng_init(&r, seed32);
    lut = rng_uniform(&r, (uint32_t)P3_LUT_COUNT);
    len = P3_LUT_LEN[lut];
    for (i = 0; i < len; i++)
        pool[i] = P3_LUT_BITS[lut][i];
    k = (uint32_t)P3_MUTATION_BITS < len ? (uint32_t)P3_MUTATION_BITS : len;
    rng_sample(&r, pool, len, k, picked);
    for (i = 0; i < k; i++)
        set_bit(genome, picked[i]);
}

/* ------------------------------------------------------------------ the interface -- */

/* Candidate `index` of a session with `master_seed` under `mode`: the arm from the
 * schedule, the pair seed from the pair, the genome from that arm's operator. Returns 0
 * and writes *arm_out (0 = random_safe, 1 = map_guided); -1 for an unassigned mode. No
 * stop condition of its own: the budget rules. */
int p3_search_next(uint32_t genome[P3_GENOME_WORDS], uint32_t master_seed, uint32_t index,
                   uint32_t mode, int *arm_out)
{
    int arm = p3_arm_for(index, mode);
    if (arm < 0)
        return -1;
    if (arm == P3_ARM_RANDOM_SAFE)
        p3_op_random_safe(p3_pair_seed(master_seed, index / 2u), genome);
    else
        p3_op_map_guided(p3_pair_seed(master_seed, index / 2u), genome);
    *arm_out = arm;
    return 0;
}
