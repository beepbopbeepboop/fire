# Why 32x32 and 64x64 MMA tiles are 6x and 17x slower than 16x16 — cause NOT established

**Status: OPEN. The measurement is solid and reproducible; the explanation is
NOT, and the two obvious explanations are both ruled out.** Recorded so nobody
builds the wrong fix on top of a plausible-sounding guess.

## Status 2026-10-02 (`work/bugs4-9-c`): the TEXTUAL-AIR blocker is narrowed,
## and could not be taken the last step on this machine

The "What would settle it" section below ends by saying the tooling is not
there, and names two things that would change that. One of them is wrong, the
other is right but blocked here — and both are worth correcting, because
"nobody has the tooling" is the sentence that stops the next person from trying.

**Verified on this machine, 2026-10-02 (metal 32023.921, Xcode
`XcodeDefault.xctoolchain`):**

| claim | verdict |
|---|---|
| a Metal-capable `llvm-dis` is not present | **TRUE.** No `llvm-dis` in `xcrun --find`, in the default toolchain's `usr/bin` (which has `llvm-objdump`, `llvm-nm`, `llvm-size`, `llvm-cov`, `llvm-dwarfdump` and no `llvm-dis`), and none in `/usr/local/opt/llvm` or `/opt/homebrew/Cellar/llvm`. |
| `-Xmetal save-temps` is not supported | **TRUE, and it is worse than unsupported — it is silently ignored:** `metal: warning: argument unused during compilation: '-Xmetal' [-Wunused-command-line-argument]`, and no intermediate appears. A flag that warns instead of failing is the kind of thing that reads as "no output" and gets reported as "the tool does not work". |
| …so textual AIR is unreachable | **WRONG.** `metal --help` documents `-save-temps` — "Save intermediate compilation results", both as a bare flag and as `-save-temps=<value>` — and it works: compiling leaves `f-<hash>.bc.tmp` in the cwd. A `.bc` is an LLVM bitcode file, and the one `llvm-dis` would read. So the missing tool is not missing; it is `llvm-dis`, and `-save-temps` is the flag that feeds it. |
| reading it back | **UNTESTED, and the reason is machine-specific.** `xcrun -sdk macosx metal -c tiny.metal -o tiny.air -save-temps` cannot compile ANY Metal source on this box: the cryptex-mounted `MetalToolchain-v27.1.266.1.X6riMW` header set is incomplete (`metal_types:12: 'metal_config' file not found`, plus `metal_extended_vector` and `metal_packed_vector`), 156 errors for `-sdk macosx` and `-sdk iphoneos` at every `-std` from default to `metal3.2`. The `xcrun metal` path is a dead end here, which is why the saved `.bc.tmp` is 0 bytes — the compile failed, so there was nothing to save. The project's own benchmarks never notice: `test_llm/gemm_ilp_sweep.m` compiles its MSL at RUNTIME through `newLibraryWithSource:`, which leaves no intermediate on disk (and has a `GEMM_DUMP` env var precisely because it must dump the MSL text to be sure it matches what was compiled). |

**The one lead, and it is only a lead:** the bundled `clang` accepts an AIR
bitcode path and emits nothing but a triple warning
(`clang: warning: overriding the module target triple with arm64-apple-macosx26.0.0`),
so `clang -S -emit-llvm -x ir f-<hash>.bc.tmp -o f.ll` is worth trying on a
machine whose `metal` driver works. **This has NOT been shown to read Apple's
AIR:** the only file available here was the 0-byte one, and an empty module
proves nothing about a real one. It is a lead because the tool accepted the file
and its warning is about the triple rather than about the bitstream; it is not a
result because nothing non-empty was ever parsed.

So the next step is unchanged in shape and different in spelling: **get a
non-empty `f-<hash>.bc.tmp` from a Metal source this machine can compile, then
try `clang -S -emit-llvm -x ir` on it** (or install `llvm`, which does ship
`llvm-dis`, and use that). Until one of those works, the cause below remains
NOT established and 16x16 remains the empirically correct choice.

## Earlier status: OPEN, cause not established

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

## Every resource explanation is now ruled out by measurement

Four hypotheses tested and eliminated. Each was the most plausible one at the
time, and each died to a measurement rather than to reasoning:

| hypothesis | test | verdict |
|---|---|---|
| not enough cores | two concurrent processes at 4096^3 | **disproved** — each takes ~2x longer (24 ms -> 68 ms), wall 2.08x for 2x work. One process already commits the machine. |
| not enough bandwidth | 201 MB in 24 ms vs measured 307.8 GB/s peak | **disproved** — 8.4 GB/s, 37x under. |
| register spilling | `[ps maxTotalThreadsPerThreadgroup]` per config | **disproved** — 1024 (the full device max) for TM=TN=1, 2, 4 AND 8. 64 accumulators is 128 registers and still allows full occupancy. |
| L2 capacity / cache reuse | repeat the sweep at 512^3, which is 3 MB and fits in L2 | **disproved** — the ordering and the ~4x collapse are IDENTICAL at 512^3 (8x8 0.59, 16x16 0.74, 32x32 0.21, 64x64 0.12 TFLOPS). Nothing is being evicted. |

And staged sharing does not help either — see the fan-out section: 5.95 vs 6.64
TFLOPS for no staging at all.

So the collapse is **intrinsic to the MMA grid size** and is not occupancy, not
bandwidth, not registers, not cache, and not fixable by staging. The remaining
candidate is the MMA issue path itself: per k-step the grid issues TM+TN fragment
loads for TM*TN MMAs, a ratio of 0.5 / 1.0 / 2.0 / 4.0 for 1x1 / 2x2 / 4x4 /
8x8 — which says bigger grids should be BETTER, and they are 4x worse. That
inversion is the thing left to explain.

## What would settle it

The Metal compiler emits AIR as **bitcode**, so the register allocation cannot be
read by grepping the output (`xcrun -sdk macosx metal -c f.metal -o f.air` gives
binary, and disassembling it yields host code). Needed: **textual AIR**, so the
`simdgroup_matrix` values can be seen as either registers or an `alloca` with
`addrspace(1)` traffic. Two ways to get it:

1. ~~the pipeline's occupancy reporting~~ — DONE, and it disproved spilling.
   `[ps maxTotalThreadsPerThreadgroup]` returns 1024, the device max, for every
   grid from 1x1 to 8x8. This is now a permanent part of the benchmark.
2. **Textual AIR — ATTEMPTED, partly undone.** `xcrun -sdk macosx metal -c
   f.metal -o f.air` and `-emit-llvm` both emit LLVM **bitcode** (magic
   `0x0B17C0DE`), and Xcode's `llvm-objdump` rejects it as "not a valid
   object file". Grepping the bytes yields host-looking garbage, which is how an
   hour went into looking for a name-mangling bug that does not exist.
   **Re-checked 2026-10-02, and the conclusion "the tooling is not there" is too
   strong** — see the Status at the top of this doc: `llvm-dis` really is
   absent and `-Xmetal -save-temps` really is a silent no-op, but the driver's
   own documented `-save-temps` DOES save the intermediate bitcode, and there is
   one bundled tool that may read it back. What is still true is the operational
   half: on this machine `xcrun metal` cannot compile any Metal source at all
   (incomplete cryptex-mounted header set), so the saved bitcode is empty and the
   question is unanswered. Anyone repeating this wants, in order: a `metal` that
   can compile, then `-save-temps`, then `llvm-dis` (or `clang -S -emit-llvm -x
   ir` as the fallback).

Until then 16x16 is the empirically correct choice and is what
`mojo/middle/offload.py` emits. Do not "improve" it by enlarging the tile, and do
not start a split-K project on the strength of the occupancy story — disproved
above. The most promising remaining lead is the MMA issue path, not any resource.

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
