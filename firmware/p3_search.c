/* p3_search — the reference sampler behind D1 §4.1's interface.
 *
 * The search algorithm is NOT part of D1: the specification fixes only this interface, so
 * that the loop, the interlock and the evidence can be reviewed without the search being
 * settled. What is here is deliberately the simplest thing that satisfies the contract —
 * a deterministic sampler over the 292 whitelisted content bits, seeded by the host in the
 * same U-Boot epoch (deterministic/test mode, review #2's Q6: L5 does not claim autonomous
 * discovery). A real search replaces this file and nothing else.
 *
 * Determinism is the property the replay depends on: the same seed and the same index
 * must yield the same genome on the board as on the host, so `host/l5_refloop.py`'s
 * rehearsal and the board run walk the same candidates.
 */

#include "p3_derive.h"

/* the same 64-bit xorshift the PL uses for its nonce — one implementation, one behaviour */
int p3_search_next(uint32_t genome[P3_GENOME_WORDS], uint32_t seed, uint32_t index)
{
    uint64_t x = ((uint64_t)seed << 32) ^ (uint64_t)(index + 1u) ^ 0x9E3779B97F4A7C15ull;
    int i;
    if (x == 0u)
        x = 0x9E3779B97F4A7C15ull; /* the xorshift's one dead state */
    for (i = 0; i < P3_GENOME_WORDS; i++) {
        x = p3_nonce_step(x);
        genome[i] = (uint32_t)(x >> 16); /* the low bits of a xorshift are the weakest */
    }
    genome[P3_GENOME_WORDS - 1] &= 0xFu; /* bits 292..319 are not part of a genome */
    return 0;                            /* no stop condition of its own: the budget rules */
}
