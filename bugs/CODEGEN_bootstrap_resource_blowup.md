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

## Status (2026-09-27 — the SIGTRAP is currently UNREACHABLE, and it is NOT the same root cause as the three expected failures)

Fresh measurement, both from a `-O2` build of `fire.py`:

```
$ ./mojoc /tmp/tiny.mojo --dump          # a TWO-LINE program
Segmentation fault: 11                    # exit 139
```

`mojoc` crashes on *any* input, including a two-line program, so the
"large transitive dump SIGTRAPs" this document is about **cannot be
reached at all right now** — the run dies in `_walk_ast` at
`module_gen.py:860`, before any per-module work and long before the
transitive closure is walked. The `bootstrap` bucket reflects this
structurally: `bootstrap-stage2-dumps` is `expect=`-marked, and the four
steps that depend on it (`bootstrap-stage2-transitive` through
`bootstrap-verify`) are the gate's five "dependency did not pass" skips.

### Are they the same root cause? No — and the distinction matters

| | this doc's SIGTRAP | the three expected failures |
|---|---|---|
| exit | 133 (SIGTRAP) | 139 (SIGSEGV) |
| when recorded | 2026-09-25, on that day's binary | current, reproduced today |
| trigger | the LARGE transitive dump, path/state dependent | a TWO-LINE program |
| reproducibility | intermittent; the same binary completed under a debugger | 100% |

Different signal, different trigger, different reproducibility. A crash
on every input is strictly *earlier* than a crash on one large input, so
the current SIGSEGV masks this document's SIGTRAP rather than explaining
it. **This document's own measurements are therefore not currently
obtainable at all**, and none of them should be re-derived until the
binary survives a two-line program.

### What WAS established, and is the useful part of this entry

The SIGSEGV that masks it is now root-caused to one runtime predicate and
written up in full — three-link chain, lldb frames, measured faulting
address, and the candidate one-place fix — in
`CODEGEN_noshim_dumpfull_preexisting_divergence.md`'s 2026-09-27 entry.
Summary: `exprtypes.py:61`'s `_WALK_FIELD_NAMES_CACHE.get(type(node))`
lowers to a dict lookup whose KEY is `mojo_cstr_or_int_str(tag)`, and
`mojo_boxed_is_str`'s `v > 65536` threshold is far below the 2GiB
boundary its neighbour `mojo_read_type_tag_safe` already refuses to
dereference, so a 31-bit type tag is handed to `_str_hash` as a `char *`.

That fix is deliberately NOT applied (the `expect=` anti-rot rule would
turn three marked-for-failure steps into gate failures, and nothing
behind the first AST walk is measured). It is a prerequisite for this
document's work, not a substitute for it.

### The next bounded action, unchanged and still correct

Everything in "What to measure next" below still holds, and the order is
still right — with one amendment. The first step is now **"make the
binary survive a two-line program"**, not "bisect by commit":

1. Apply the `mojo_boxed_is_str` 31-bit-tag-range guard, and treat the
   resulting SELFHOST-CRASHED set as the real remaining work.
2. Only then re-take this document's phase profile. Note that its
   ~45 GB / ~32 min `make bootstrap` baseline is a **2026-09-25
   measurement taken on a binary that ran**; it is not the current
   machine's ceiling and not a pass/fail criterion anyone can check today.
3. The memory growth itself is still unexplained, and the
   flag-probe section's own conclusion stands: `-O1`/`-O2`/`-O3` barely
   differed in footprint (93.7/93.7/95.6 GB), so compiler-binary
   optimization is not the lever.

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


## Whole-program `--dump-full fire.py` reaches ~192 GB (2026-09-26)

**The memory growth is real and is the problem. The cause is NOT an
out-of-memory kill, and this section deliberately does not claim one** — see
"this is the second OOM misdiagnosis" below, which is the most useful thing in
it.

`make check-native-dumpfull` reports:

```text
Built: mojoc
./mojoc fire.py --dump-full produced NO fire.ci (exit -9)
```

`exit -9` is SIGKILL. **It was killed by hand** — the run was watched and
`kill -9`'d once it was clear the machine was in danger. The OS did not
intervene, and this is not an OOM:

- macOS does not account for this usefully. When memory runs out it does not
  reliably choose which process to kill, so the OOM response cannot be relied
  on to bound this run — or to be the thing that ends it.
- `ulimit`/`rlimit` provides no usable cap here, so the test cannot be given a
  memory budget to fail against.

So the exposure is real and the process has no bound and no backstop, but
**192 GB is a lower bound on what it wanted, not a measured peak.** It had not
finished when it was stopped. It is not a completed 192 GB compile.

### What the growth looks like against this doc's own measurements

Same workload — a full native transitive `--dump-full fire.py`:

| run | macOS peak footprint | result |
|---|---:|---|
| 2026-09-25 flag probe, `-O1` | 93.7 GB | success |
| 2026-09-25 flag probe, `-O2` | 93.7 GB | success |
| 2026-09-25 flag probe, `-O3` | 95.6 GB | success |
| 2026-09-25 full `make bootstrap` (`-O0`) | ~45 GB | success (32 min) |
| **2026-09-26 `--dump-full fire.py`** | **≥192 GB, killed by hand** | **no `fire.ci`** |

The flag probe completed just under 96 GB three optimization levels in a row;
this run passed 192 GB — **at least 2x the last known-completing footprint** —
and was still going. Direction of travel against this doc's own success
criterion ("peak RSS materially below 45 GB") is now ~4x the wrong way.

Worth noting for whoever picks this up: the flag probe found `-O1`/`-O2`/`-O3`
barely differ in footprint (93.7/93.7/95.6 GB), so **compiler-binary
optimization is not the lever** that section's conclusion suggested. And
because the run is cumulative over the transitive closure under a never-frees
allocator, a per-module regression is a strong candidate — a modest per-module
regression becomes a large whole-program delta, which is the shape of the 2x.

### This is the second OOM misdiagnosis in this area, and that is the lesson

The obvious reading of "silent death, enormous memory, no core file" is OOM. It
has now been wrong twice here, and both times it was wrong *in the same way* —
by inferring the cause from the symptom rather than establishing it:

1. `CODEGEN_noshim_dumpfull_preexisting_divergence.md` session 4 concluded OOM
   for a **single-module** repro and blamed the never-frees allocator. Session 5
   corrected it: the real cause was a NULL-pointer SIGSEGV (139), and the
   apparent silent death was an artifact of explicit `(…&)` backgrounding
   hiding the true exit status.
2. This one. A large, silent, uncapped run invites the same inference. Here the
   `exit -9` is a **manual** kill, so treating it as the OS's OOM response
   would be wrong in the same way — and the harness's own message (below)
   actively encourages exactly that inference.

**The rule this establishes: a SIGKILL here is evidence of nothing on its own.**
A manual `kill -9` and an OS kill are the same signal. Establish which by
running it in the foreground under a memory monitor (`memory_pressure`,
`vmmap`, or Activity Monitor), never under `(…&)`, and record peak RSS at
kill time rather than inferring a peak from the fact of death. The
`ulimit`/`rlimit` route that would normally settle this is unavailable, so
measurement is the only way.

The never-frees allocator was never exonerated — it was implicated in a case
that turned out to have a different cause, which is not the same as being
cleared. The session-4 recommendation ("free or reuse intermediate
allocations, or at least this walker's transient node lists, so the correct
traversal fits in available memory") stands, and is now urgent rather than
optional.

### The harness's message names a fixed bug, and argues against the right answer

Independent of the memory work, and cheap to fix:

```python
# test_native_dumpfull.py:75
f"(exit {native_rc}) - the known original SIGBUS in "
f"_rewrite_assign_stmt writes the correct file before crashing, "
f"so an ABSENT file is a worse regression, not the known issue"
```

- **The SIGBUS it names is fixed.** The whole-program `EXC_BAD_ACCESS` in
  `mojo_set_update`/`_rewrite_assign_stmt` was root-caused and fixed
  2026-09-20 — 8 real self-hosted-only bugs, found and verified via
  AddressSanitizer (`CLAUDE.md`, status as of 2026-09-20). Reporting a new
  failure as a regression of a fixed bug is worse than reporting nothing.
- **Its premise is inverted here.** "Writes the correct file before crashing,
  so an ABSENT file is a worse regression" argues that an absent file must be a
  *correctness* problem. This is resource exhaustion, so the message argues the
  reader out of the right answer — and the reader has no way to tell that from
  the text.
- **It discards the one signal that distinguishes the cases.** `-9` from
  SIGSEGV/SIGBUS/133, and the message collapses that difference instead of
  reporting it. It should say: absent file + SIGKILL is a resource failure, and
  here is the peak.

### Containment landed: a 55 GB ceiling, not an opt-in

`check-native-dumpfull` now runs under `tools/memcap.py`, which polls the
process tree's RSS and SIGKILLs it at `MEMLIMIT_GB` (default **55**, the
measured healthy peak), exiting 125:

```sh
make check-native-dumpfull                   # capped at 55 GB
make check-native-dumpfull MEMLIMIT_GB=96    # raise it
make check-native-dumpfull MEMLIMIT_GB=0    # NO cap; watch it
```

**A ceiling rather than a refusal**, because of the two facts above: macOS
will not reliably pick what to kill, and `ulimit`/`RLIMIT_AS` gives no usable
cap. What *does* work is killing the process we own — aiming the kill at a
child we spawned is deterministic, where relying on the OS is not. The ceiling
does not have to be tight to be worth having: the gap between a healthy peak
(~55 GB) and the 192 GB that needed a human is ~3.5x, which is ample room to
be conservative.

Three properties of the watchdog that matter, each because the failure it
avoids is the failure this whole area keeps making:

- **It sums the process TREE.** `mojoc` spawns `gcc -fgimple` children; a cap
  looking only at the parent would let the real cost hide in a child. Verified
  with a synthetic two-process hog.
- **It fails CLOSED.** If the watchdog itself throws, it kills the child rather
  than leaving it unmonitored. This is not hypothetical: the first version had
  exactly this bug (`out` instead of `out.stdout` on a `CompletedProcess`) and
  left a test hog running to 3 GB after the watchdog had already died. A safety
  tool that fails open is not a safety tool.
- **Exit 125 is reported as a resource failure, not a verdict.** The process was
  killed for memory *before finishing*, so the run says nothing about whether
  the native output was correct — which is precisely the confusion the stale
  harness message causes (above).

It is still **out of `make check`**, though now for a mundane reason rather than
a dangerous one: it is a multi-minute job that touches ~55 GB, which is a lot
to ask of a default gate. `CLAUDE.md`'s documented full gate does list
`check-native-dumpfull` as a required step, so restoring it is a deliberate
call, not an oversight.

`make wholeprogram-help` prints the above at the terminal.

### Attribution: the absent `fire.ci` is not the formal/x86-64 work

Preserved from the old `BUG.md`, which recorded this reasoning and would have
lost it in the move. It matters because `check-native-dumpfull` failing looks
like a codegen bug, and every one of these was checked rather than assumed:

- `mojoc` was **deleted and rebuilt from current sources** and still failed, so
  it is not a stale binary.
- `./mojoc fire.py --dump-full` compiles `fire.py` **alone**, and `fire.py` does
  not import `formal/`, so none of the x86-64 model / `formal/` changes are in
  its input graph at all.
- `git status` was clean for every `--dump-full` input (`fire.py`,
  `gimple_codegen.py`, `module_loader.py`, `mojo_compiler.py`, `runtime/`).
- The python3-interpreted reference still produced a correct ~37 MB `fire.ci`
  for the same source, so the divergence is **native-codegen-only** — which is
  the entire point of this check.

Two claims from the original entry are superseded and should not be carried
forward:

- It reported the failure as **`exit 0` with nothing written**, and later as
  **`exit -9`**. The `exit -9` was a **manual** kill (see the top of this
  section); the `exit 0` variant is not what it is now.
- It called the failure "the documented-in-wrong-direction" version of the
  SIGBUS in `CODEGEN_noshim_dumpfull_preexisting_divergence.md`. That SIGBUS is
  fixed, and an absent file here is a resource failure instead.

`make bootstrap`'s `verify` step failing on ~14 files is **not** re-recorded
here: it is already tracked, with the set shrinking over time, in
`CODEGEN_noshim_dumpfull_preexisting_divergence.md`. The only useful detail the
old entry added is that the set is not expected to be stable, because that doc
records `PYTHONHASHSEED`-dependent nondeterminism in the reference path itself.

### What to measure next

Do not start by optimizing anything — the 2x growth is unexplained, and
optimizing a curve whose slope is unknown optimizes the wrong term.

1. **Find what grew.** Bisect by commit over the ~40 since 2026-09-25
   (`git log --since=2026-09-25 -- mojo/ gimple_codegen.py runtime/`) using
   *single-module* dumps as a cheap proxy. Never re-run the whole-program dump
   unattended to do this.
2. **Profile by phase** (this doc's existing hypothesis 1): Python reference
   generation, `gcc -fgimple`, per-file native dumps, transitive native dump.
   Report peak RSS per phase, and specifically whether peak is in the
   *transitive* dump rather than per-file.
3. **Distinguish live-set from fragmentation** — an allocation-count probe in
   the runtime, or `leaks`/`vmmap` on the native binary. Answers whether the
   memory is genuinely reachable objects or a leak. Cheapest and most valuable
   of the three; do this first.
4. Only then decide between the never-frees fix and per-phase work reuse.

Peak must come back under ~96 GB (the last known-completing footprint) before
this gate can be un-gated.
