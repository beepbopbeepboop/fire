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
