# CODEGEN: bootstrap resource blowup and four remaining stage1/stage2 divergences

## Status (2026-09-25 — OPEN, measured; print/comptime fixes landed, native Stage 2 remains unstable)

A full `make bootstrap` completed after approximately 32 minutes. Peak memory
usage reached approximately 45 GB. The generated stage pipeline otherwise ran
through its per-file checks; the only verification failures were the following
stage1-versus-stage2 `.ci` comparisons:

```text
FAIL stage1 vs stage2: fire_compiler.ci
FAIL stage1 vs stage2: fire.ci
FAIL stage1 vs stage2: module_loader.ci
FAIL stage1 vs stage2: myinterpreter.ci
```

The reported stage1/stage2 comparison entries that passed in the same run
included `fire_main.ci`, `generated_dispatch.ci`, `hello.ci`, `mojo_failures.ci`,
and `mojo.ci`. No stage2-versus-stage3 failure was reported. The run therefore
reached the end of the bootstrap/verification path, unlike the earlier
whole-program self-host crashes.

The approximately 45 GB peak and 32-minute duration are now a first-class
bootstrap problem, separate from the correctness of the four remaining output
divergences. The existing container-lifetime work reduces ordinary compiled
program growth, but it does not make the compiler's self-hosting workload
small: each stage repeatedly parses, type-checks, lowers, and emits a large
transitive source closure in one process, while the self-hosted compiler also
constructs many AST and type-analysis containers.

## Scope

This document records the measurement and the remaining divergence set. It does
not claim that the four `.ci` files have the same root cause; they must be
compared independently after the resource issue is understood. The earlier
divergence investigation remains in
`CODEGEN_noshim_dumpfull_preexisting_divergence.md`.

## Optimization hypotheses to evaluate

1. Measure the current phase boundaries separately: Python reference generation,
   `gcc -fgimple`, per-file native dumps, transitive native dumps, and
   verification. Record elapsed time and peak RSS for each phase.
2. Determine whether the dominant work is repeated transitive import discovery,
   repeated AST/type analysis, repeated string-pool emission, or GCC input
   size. Compare work and output sizes for `fire.py` versus the stdlib dylib
   build, which already uses many small cached module units.
3. Add a bounded cache/process-local memoization experiment for immutable parsed
   modules, imported-module analyses, source scans, and generated module
   metadata. The cache key must include source path, mtime/size or content
   identity, compiler options, and the relevant self-host mode.
4. Prototype a split translation-unit build: compile independent module/object
   units in parallel, cache their objects, and link them with a thin driver.
   Start with the existing stdlib-dylib/module-cache boundaries rather than
   inventing a new scheduler.
5. Evaluate the formal-build path as a fast correctness-oriented backend when
   no proof is requested. It should remain a separate mode; it must not be used
   to claim that optimized GIMPLE output is byte-identical.
6. Use the tcc model as a design reference: incremental parsing and lowering,
   streaming/intermediate representations, fine-grained invalidation, and
   object-level reuse. The key target is eliminating repeated whole-closure
   work, not merely parallelizing the final GCC invocation.

## Native compiler path

The Python interpreter should be the recovery/oracle path, not the normal
inner-loop compiler. Keep one managed native `mojoc` binary rather than a
family of fast/debug binaries. Its normal build is `-O2 -g0`; debugging is an
explicit manual override such as `make mojoc MOJO_OPT='-Og -g3'`.

Proposed lifecycle:

1. Build the single `mojoc` binary from a known-good Python-generated `.ci`.
2. Verify it against the Python reference with the existing native
   dump/full-bootstrap checks before using it as the active compiler.
3. Use that one binary for ordinary per-file dumps, module builds, and the next
   compiler rebuild.
4. If it crashes, diverges, or exceeds a resource budget, discard/replace that
   binary by rebuilding it with Python; do not create another permanent binary
   variant.
5. Keep Python available for oracle comparisons, recovery, and the final
   correctness gate.

This is a two-tier build system: Python is slow but authoritative, while the
single optimized native compiler is the fast working compiler. A source/compiler
fingerprint should be stored alongside the managed binary so a stale compiler
cannot silently process a changed source tree.
## Optimization flag probe (2026-09-25)

The existing Stage 1 `fire.ci` was compiled with the same GCC 15 GIMPLE/runtime
inputs at three optimization levels, then used for a full native transitive
`--dump-full fire.py` run. These are compiler-binary measurements, not a full
three-stage bootstrap measurement.

| GCC flags | wall time | maximum RSS | macOS peak footprint | result |
|---|---:|---:|---:|---|
| `-O1` | 191.9 s | 60.2 GB | 93.7 GB | success |
| `-O2` | 185.3 s | 55.8 GB | 93.7 GB | success |
| `-O3` | 94.2 s | 61.2 GB | 95.6 GB | success |

`-O2` is a promising speed/memory compromise for ordinary native `mojoc`
work, but it is not yet a safe bootstrap default. A subsequent full
`make stage3` run rebuilt the same `-O2` Stage 2 compiler and trapped during the
Stage 2 transitive dump; an earlier run trapped during the Stage 3 transitive
dump. Direct debugger-driven `-O2` runs of the corresponding Stage 2 compiler
completed, so the failure is real path/state-dependent instability rather than
a simple compile failure. `BOOTSTRAP_OPT` therefore remains `-O0` by default,
with `make bootstrap BOOTSTRAP_OPT=-O2` retained for focused investigation.

The original `-O0` full-bootstrap baseline was approximately 32 minutes and
45 GB, so compiler-binary optimization remains the highest-value near-term
target. The one-off successful `-O2` runs do not prove the complete three-stage
bootstrap is reliable or faster: Stage 1 generation, repeated per-file work,
verification, and the Stage 3 run remain separate costs, and the optimized
native path needs a root-cause fix before bootstrap promotion.

## Native re-export failure investigation (2026-09-25)

The intermittent native `SIGTRAP`/timeout was narrowed to a self-hosting import
failure rather than an optimizer defect. `module_loader._mojo_type_to_c()`
uses a function-local `from gimple_codegen import _mojo_type`; in the
flattened whole-program closure, `_mojo_type` is also visible through its
canonical `mojo.middle.types` sibling, so the resolver can report it as
ambiguous. A qualified module-member call was not sufficient: the self-hosted
backend lowered that member as an unavailable stub.

An alias-based fix made the pre-update tree's Stage 2 closure complete in
820.35 seconds, but the current updated source reintroduced ambiguity under the
alias name and a uniquely named wrapper caused a native allocator failure.
Neither speculative `_mojo_type` workaround is retained. The selected
`print(double)` fix and the updated-source `sys.platform` guard are retained;
`make stage3` completes with them, but a subsequent full-gate run still
intermittently exits 133 (`SIGTRAP`) during the large native Stage 2 transitive
dump. The full quality gate is therefore not green, and the native memory
failure remains a separate blocker from the resource measurements above.

## Success criteria

- A phase profile identifies the largest time and memory contributors.
- A cache/object experiment reduces repeated work without changing stage output
  semantics or introducing stale-cache results.
- Peak RSS for a full bootstrap is materially below 45 GB, with an explicit
  target selected after profiling.
- Full bootstrap wall time is materially below 32 minutes, with a reproducible
  benchmark command and hardware/environment details.
- The four listed `.ci` divergences remain separately tracked and are not hidden
  by resource optimizations.
