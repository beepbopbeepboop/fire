# Why 32x32 and 64x64 MMA tiles are 6x and 17x slower than 16x16 — cause NOT established

**Status: OPEN. The measurement is solid and reproducible; the explanation is
NOT, and the two obvious explanations are both ruled out.** Recorded so nobody
builds the wrong fix on top of a plausible-sounding guess.

## The measurement

`test_llm/gemm_ilp_sweep.m`, TM=TN square, one simdgroup per tile, median of 15
with the spread printed. 4098^3, chosen because even 64x64 tiles still leave 512
threadgroups there:

| tile/simdgroup | accumulators | threadgroups | median ms | TFLOPS | spread |
|---|---|---|---|---|---|
| **16x16** | **4** | **8192** | **23.96** | **5.74** | 23.66–37.13 |
| 32x32 | 16 | 2048 | 148.51 | 0.93 | 146.42–160.34 |
| 64x64 | 64 | 512 | 403.03 | 0.34 | 385.26–405.77 |

The large-tile spreads are **tight** (146–160, 385–406), so this is not
run-to-run noise. Repeating at 2048^3 gives the same ordering at 10x.

## Ruled out: occupancy

Occupancy was the leading hypothesis and it is **false**. At 4096^3 a 64x64 tile
still yields 512 threadgroups, which is ample; and fixing the 16x16 tile and
varying only the problem size — i.e. varying parallelism with the tile and the
register count held constant — gives:

    1024^3   1.81 TFLOPS
    2048^3   6.87 TFLOPS
    4096^3   5.75 TFLOPS     <- falls again

More parallelism does not keep helping; it plateaus and then regresses.
**Split-K and stream-K are therefore the WRONG next step** — both exist to add
parallelism, and parallelism is not the constraint.

## Ruled out: bandwidth

Measured peak on this device is 307.8 GB/s (`test_llm/bandwidth.m`, float4
streaming copy; the scalar version only reaches 277). At 4096^3 the kernel moves
201 MB in 24 ms, which is 8.4 GB/s — 37x below peak. Not bandwidth.

## NOT established: register spilling

The obvious remaining explanation is that `acc[TM][TN]` stops fitting in registers
and spills to local memory, so every MMA reads and writes scratch. Two pieces of
evidence support it:

- the non-square grids **compute the wrong answer** (1x2, 2x1, 2x4, 4x2 all fail
  bit-exactness at up to 64/4096 elements), and a spilled `simdgroup_matrix` does
  not fault — `thread_elements()` silently reads something else;
- the collapse is monotonic in accumulator count, which is what pressure looks
  like.

But the arithmetic **contradicts it**: 16 accumulators is 16 x 2 floats per lane
= **32 registers**, and 64 is 128. Neither approaches the 255-register limit, so
plain spilling does not explain a 6x cliff at 32 registers. Something else is
going on — possibly the compiler failing to promote the 2-D `simdgroup_matrix`
array to registers at all rather than running out, which is a different bug with
a different fix.

## What would settle it

The Metal compiler emits AIR as **bitcode**, so the register allocation cannot be
read by grepping the output (`xcrun -sdk macosx metal -c f.metal -o f.air` gives
binary, and disassembling it yields host code). Needed: **textual AIR**, so the
`simdgroup_matrix` values can be seen as either registers or an `alloca` with
`addrspace(1)` traffic. Two ways to get it:

1. `xcrun -sdk macosx metal -c f.metal -S -o f.ll` (or whatever emits textual
   LLVM), if the driver supports it;
2. the pipeline's own occupancy/limit reporting at runtime —
   `MTLComputePipelineState.maxTotalThreadsPerThreadgroup` plus
   `[device supportsFamily:]` — which bounds the answer without the IR.

Until one of those lands, 16x16 is the empirically correct choice and is what
`mojo/middle/offload.py` emits. Do not "improve" it by enlarging the tile, and do
not start a split-K project on the strength of the occupancy story — that story
is disproved above.

## The "same slow feed, more work" hypothesis: TESTED, DISPROVEN

Proposed as a fix on the reasoning that if the operand FEED is the bottleneck,
fanning one loaded tile out to more consumers raises throughput without feeding
more. Implemented in `test_llm/gemm_fanout_probe.m`: a 64x64 output tile staged
once per k-step in threadgroup memory, read by 16 SIMDGROUPS each owning a 16x16
sub-tile and holding only FOUR accumulators — so reuse comes from SHARING, not
from per-thread register blocking. 2048^3, median of 15, all bit-exact at 512^3:

| kernel | TFLOPS |
|---|---|
| fan-out, TKS=8 | 5.74 |
| fan-out, TKS=32 | 5.95 |
| **16x16, no staging, no barriers** | **6.64** |

**Disproven: the staged, shared tile is ~10% SLOWER than doing nothing extra.**
The barriers and the threadgroup-memory round trip cost more than the DRAM traffic
they save.

The reason is that the premise is false. The 16x16 kernel moves 201 MB in 24 ms
= **8.4 GB/s against a measured 307.8 GB/s peak** — DRAM traffic is 37x under the
limit and is therefore not the constraint at all. What the kernel actually
saturates is the chip's *load-issue* rate (roughly 1.4 TB/s of requests, served
mostly by cache), which is a per-thread pipeline cost. Staging relocates that
traffic to shared memory and adds two barriers per k-step on top; it cannot
remove a cost it is not paying.

So the answer to "more consumers on the same feed" is: on this machine the feed
is not slow. Note also that `TKS` has a sharp optimum — 32 gives 5.95, but 8 and
64 both give ~5, because the barrier pair is amortised over only 4 MMAs at TKS=8
and the staged tile starts costing more than it saves at TKS=64.

## Two methodology errors this probe exposed, both mine

Worth recording because both produced confident nonsense:

1. **An unguarded `#define` made a "sweep" measure one config four times.**
   `-DTKS=32` could not override the file's own `#define TKS 8`, so four
   differently-labelled runs were the same kernel, and the differing times were
   read as a trend. Same shape as the earlier best-of-5 error: a knob that does
   not reach the thing being measured.
2. **A wrong kernel measured FASTER, twice.** The staging loop strided by
   `TN*32` while there were only `NREAD*32` threads, so at TKS=32 it initialised
   512 of 2048 staged elements and computed on garbage for the rest — 511 of
   262144 outputs wrong, and "11.50 TFLOPS", the best number seen in the whole
   project. The bit-exactness check caught both, which is the entire argument for
   running it on every configuration rather than only the one you trust.

Both apparent wins evaporated on the correctness check. **The best verified
number remains 9.01 TFLOPS (16x16, four accumulators, no staging).**
