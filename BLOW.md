# BLOW.md — the memory blowup: a ~15.8 GB *constant*, not a growth curve

**STATUS (2026-09-27): the false-positive trigger is FIXED and verified
(§0.1-3) — a trivial/unrelated compile no longer pays this cost at all.
The tests this originally broke (`ab-native`, `native-dumpfull`) are
STILL RED for a real, different, unfixed reason — see §0's "NOT closed"
addendum before assuming this doc's job is done.**

Branch `crash`, at `8539ac0` plus the uncommitted segfault fix
(`runtime/fire_runtime.c`, `mojo/backend_gimple/emit_infra.py`). Every
number below was measured on this tree, in the foreground, with
`/usr/bin/time -l`. Nothing here is inferred from a symptom.

`bugs/CODEGEN_bootstrap_resource_blowup.md` is the long history (424
lines, incl. the ~192 GB `fire.py` run and the useful "a SIGKILL here is
evidence of nothing" rule). **This document supersedes its framing, not
its history** — see §4.

---

## 0. ROOT CAUSE, FOUND AND FIXED (2026-09-27)

**Confirmed and fixed. Three real, independent self-hosted codegen bugs
stacked on top of each other**, all inside the gate that decides whether a
compile should re-tokenize/re-parse this project's ENTIRE own source tree
before touching the actual input. Each was found by rebuilding `mojoc` with
a temporary `MOJO_DEBUG_SELFHOST_SEED=1`-gated `print(..., file=sys.stderr)`
and comparing the COMPILED binary's answer against the `python3 fire.py`
shim's answer for the same source — this project's single most common bug
shape (see CRASH.md, HOW-TO-DEBUG.html).

1. **`os.path.realpath()` had no codegen lowering at all.**
   `mojo/backend_gimple/emit_methods.py`'s `os.path.*` call dispatch has an
   explicit case for every sibling (`basename`, `dirname`, `abspath`,
   `expanduser`, `split`, `splitext`, `splitdrive`, `splitroot`, `join`,
   `exists`, `isdir`, `isabs`, `normpath`, `isfile`, `relpath`) — but none
   for `realpath`, even though the runtime helper it needs
   (`int64_t_realpath` in `runtime/fire_runtime.c`, real POSIX `realpath(3)`
   support) already existed and is already used by the neighboring
   `pathlib.Path.resolve()` case. A call that isn't one of those `elif`s
   falls through this entire `os.path.*` chain (its `func.obj` is the
   `os.path` `MemberExpr`, not a plain `IdentExpr`, so the generic
   "module.method(...)" dispatch just below doesn't catch it either) to the
   final scalar-receiver fallback, which stubs any unrecognized method to a
   literal `0`. **Every self-hosted `os.path.realpath(x)` call returned
   NULL, unconditionally, for any input** — confirmed as a general,
   self-host-independent compiler bug too: a plain compiled Mojo program
   calling `os.path.realpath` printed `0`/`0` (`python3 fire.py run` — the
   real interpreter — printed the correct paths; the default compile-and-
   run path did not). Fix: added the missing `elif outer_member ==
   'realpath'` case in `emit_methods.py`, wired to `int64_t_realpath`,
   exactly mirroring `basename`/`splitext`/`expanduser`, plus the matching
   `int64_t_realpath: ('char *', ['char *'])` entry in `gimple_codegen.py`'s
   function-signature table. **This fix alone did not close the bug** — see
   #2.

2. **`_SELFHOST_DIR` itself reads back as boxed `0` cross-module,
   self-hosted.** `mojo/backend_gimple/module_gen.py`'s
   `_is_selfhost_source_dir(_dir)` — which gates the whole-tree re-scan —
   compared `_dir == _SELFHOST_DIR` and `_rdir == _rsd` (realpaths of
   both), where `_SELFHOST_DIR` is a module-level global **defined in a
   different module** (`gimple_codegen.py`: `_SELFHOST_DIR =
   os.path.dirname(os.path.abspath(__file__))`). Even after fixing #1, a
   debug print showed `_SELFHOST_DIR` evaluating to the bare integer `0`
   inside the compiled binary, not a path string — a known, separately-
   documented class of gap (`mojo/middle/module_shared.py`'s
   `_selfhost_modglobal_is_pathcall`/`_seed_selfhost_module_globals` exist
   specifically to correct exactly this global's cross-module boxed
   representation) that this exact gate function cannot use, because
   deciding *whether to run* that correcting pre-pass is this function's
   own job — a chicken-and-egg gap. With `_SELFHOST_DIR` reading as the
   integer `0`, `_dir.startswith(_SELFHOST_DIR + os.sep)` became
   `_dir.startswith(os.sep)` — trivially **True** for every absolute path.
   Fix: stopped depending on `_SELFHOST_DIR` in this function entirely.
   The function's own docstring already argued the sibling-file check
   (`fire_compiler.py` living next to `_dir`, or found by walking up) is
   the robust, path-independent signal and the `_SELFHOST_DIR` equality
   checks are the weaker one (false for any vendored/downstream checkout)
   — so the fix is a deletion, not a workaround: the `_SELFHOST_DIR`-based
   disjuncts are gone, leaving only the sibling-file check + walk-up loop.

3. **The walk-up loop's own top-of-root candidate.** A smaller, independent
   latent bug found along the way: for an absolute `_rdir`
   (`os.path.realpath` always returns one), `_rdir.split(os.sep)[:1]`
   joined back is `''` (`'/tmp'.split('/')[:1] == ['']`), and
   `os.path.isfile(os.path.join('', 'fire_compiler.py'))` silently degrades
   into a **CWD-relative** check instead of a filesystem-root one — this
   was BLOW.md's *original, incomplete* hypothesis for the whole bug (it
   does reproduce the symptom when invoked from a CWD that has
   `fire_compiler.py`, i.e. every dev checkout, but #2's bug caused the
   same misclassification for literally any `_dir` regardless of CWD, so
   fixing only this loop was not sufficient — verified: it made no
   measured difference until #2 was also fixed). Fixed to `if not _cand:
   _cand = os.sep` — deliberately NOT `_cand = ... or os.sep`: self-hosted
   `str or str` on that exact line was measured to still take the
   empty-string branch, the same `and`/`or` mixed-operand-truthiness
   miscompilation class CRASH.md already documents.

**Verified fix, direct before/after on the identical rebuilt binary and
input** (`/tmp/tiny.mojo`, `./mojoc --dump-full`, invoked from the repo
root — the exact §3 repro below):

| | before | after |
|---|---:|---:|
| wall time | 13.25–14.05 s | **0.30 s** |
| peak RSS | 15.84 GB | **13.1 MB** |
| instructions retired | ~180 G | **101 M** |

~45x faster, >1200x less memory, ~1780x fewer instructions. Re-verified on
a second, independent rebuild after removing the debug instrumentation
(clean tree, no env vars) — identical numbers. Also verified the gate
still fires correctly for a genuine self-host compile
(`./mojoc --dump-full fire_compiler.py`) so the seeding pre-pass this gate
protects still runs when it's actually supposed to.

**NOT closed. §0.1 was necessary but not sufficient — do not delete this
doc or re-trust `ab-native`/`native-dumpfull` without reading this.**
Re-running `python3 tools/suite.py native --no-cache` after all three fixes
above: `ab-native` still RESOURCE-caps at **10.0 GB in 16s**,
`native-dumpfull` still fails (exit 1, 104s, no longer a segfault — a
different, unexamined failure). Root cause: `ab-native`'s
`DUMP_FULL_TESTS` corpus (`test_ab_native.py`) deliberately writes its
sibling-import test files **into the repo root** ("Files are written INTO
the repo root (not a temp dir), same path-sensitivity reason as
test_inline_source" — the test's own docstring), so `_is_selfhost_source_dir`
now CORRECTLY returns True for them — this is not a false positive. Direct
measurement of that exact, legitimately-triggered case
(`./mojoc abfulltest_driver.mojo --dump-full` with `abfulltest_driver.mojo`
+ `abfulltest_leaf.mojo` at the repo root, mirroring the test precisely):
**25.28 s / 32.9 GB / 360 G instructions** — worse than the original bug's
15.8 GB, because BOTH sibling modules are in the repo root, so the
expensive pass fires twice in one process. A `sample` profile of this run
shows the IDENTICAL hot stack as §0's original finding
(`mojo_cstr_region_eq` / `mojo_set_add_int` / `_set_grow` dominating), so
this is not a new bug introduced by the §0 fixes — **it is the same
underlying tokenize-the-whole-source-tree pass, which was always this
expensive per legitimate call; §0 only fixed it being triggered when it
shouldn't have been at all.** `native-dumpfull` (`--dump-full fire.py`/
`fire_compiler.py` directly) hits the identical pass by design every time.

This is, in other words, exactly `bugs/CODEGEN_bootstrap_resource_blowup.md`'s
original subject, now correctly isolated to the ONE case where it actually
applies (a genuine self-host compile) instead of firing on everything. §4's
"do not go looking for the per-module leak first" guidance still holds —
this isn't a leak, it's real per-call cost, likely the same degenerate
`MojoSet`/tokenizer hashing hypothesis (§6.3) applied to a fixed, large-ish
universe (this project's own ~100+ source files retokenized from scratch on
every triggering compile, with no working cross-process cache — even the
in-process `_SELFHOST_MODGLOBAL_CACHE` didn't save the SECOND sibling
module's call within the same process in the measurement above, which is
itself worth checking separately). **Next step for whoever picks this up:**
confirm with `sample`/instrumentation whether `mojo_set_add_int`/
`_set_grow`'s cost is genuinely O(n²) (hash collisions) or O(n·k) for a
large constant k, on the exact `py_tokenize` call inside
`_selfhost_struct_dict_field_val_types`/`_selfhost_module_scalar_globals`/
`_selfhost_homogeneous_tuple_ret_funcs` (all three run the same tokenize
loop over the same file list, uncached across each other within one
process — check whether that tripling is itself fixable first, independent
of the deeper hashing question).

`ab-native`'s and `native-dumpfull`'s `expect=SELFHOST_SEGV` markers (§5)
are stale in their STATED REASON (neither test segfaults anymore — the
original SIGSEGV is fixed) but the tests themselves are still red for the
reason above, so **do not just delete the markers** — update the reason
string to point at this section instead, or a new bug doc for the
tokenize-cost issue once it's actually fixed. Per CLAUDE.md's anti-rot
rule, a marker whose stated reason has gone stale but whose test still
fails needs its STRING corrected, not its presence removed.

Method notes for whoever picks this up next: lldb's `malloc`-breakpoint
approach (§7's original plan) was a dead end — a *conditional* breakpoint
on `malloc` stops the whole process on every single call system-wide to
evaluate the condition, and this workload makes enough malloc calls that
it would never have finished in practice. What worked: `sample <pid> <N>`
(macOS's built-in sampling profiler, zero ptrace stop-the-world overhead)
against a natively-running, un-instrumented `mojoc`, which named the hot
call stack (`_seed_selfhost_struct_dict_field_types` → `py_tokenize`) in
one 5-second sample. From there, a one-line CWD change
(`cd /tmp && ./mojoc --dump-full /tmp/tiny.mojo`, 0.01 s / 14.9 MB vs.
13.25 s / 15.84 GB from the repo root) was the confirming experiment that
pinned the gate function, and a plain `print(..., file=sys.stderr)` behind
an env var (rebuilding `mojoc` each time to see the COMPILED behavior, not
just the shim's) walked the rest of the way down to the exact broken
comparison. The shim and the compiled binary disagreeing on the same
source is this project's single most common bug shape (see CRASH.md,
HOW-TO-DEBUG.html) — confirm against both whenever a self-host-gated code
path is suspect.

---

## 1. The headline

The blowup is **not proportional to the input**. It is a fixed cost paid
on entering the compile path at all:

| invocation | peak RSS | instructions retired | wall |
|---|---:|---:|---:|
| `./mojoc --help` | **0.01 GB** | 0.1 G | 0.1 s |
| `./mojoc --version` | **0.01 GB** | 0.1 G | — |
| `./mojoc --dump-full` — 133 B source | **15.84 GB** | 180.0 G | 14.6 s |
| `./mojoc --dump-full` — 234 B source | **15.84 GB** | 180.0 G | — |
| `./mojoc --dump-full` — 436 B source | **15.84 GB** | 180.0 G | — |
| `./mojoc --dump-full` — 840 B source | **15.84 GB** | 179.9 G | 14.6 s |
| `./mojoc --dump-full` — 1655 B source | **15.85 GB** | 179.9 G | — |
| `./mojoc --dump-full` — 3287 B source | **15.87 GB** | 180.1 G | — |
| `./mojoc --dump-full build/mojo.mojo` (1206-module closure) | **15.84 GB** | 180.4 G | — |
| `./mojoc` — **no arguments** | **58.08 GB** | 1959.1 G | — |

Three things follow, and they are the whole finding:

1. **25x the source and a 6% different transitive closure move peak RSS
   by 0.03 GB.** 133 B and 3287 B both cost 15.84 GB. The closures were
   not the same either — `n1.ci` carried 1287 module lines, `mojo.ci`
   1206 — so "flat" is not an artifact of both inputs pulling an
   identical universe.
2. **`--help` is free (0.01 GB).** So this is *not* process startup, not
   dynamic linking, and not a giant static initialiser. The cost lands
   after argv parsing, inside compile-pipeline setup — before the input
   is meaningfully read.
3. **It is not even a hard floor.** The no-argument path reaches
   **58.08 GB** and 1959 G instructions, ~3.7x the constant. So
   whatever the 15.8 GB is, the default target multiplies it.

**180 G instructions in 14.6 s wall is ~12 G instr/s**, well above a
single core's ~3-4 G instr/s. `mojoc` is already running this work in
parallel. This is not a "make it faster" problem; it is a "this work
should not be happening" problem.

## 2. Why this is measurable now, and wasn't before

Until the segfault fix landed, `mojoc` died on **every** input including
a two-line program, so there was no completed run to measure. The fix
(`mojo_boxed_is_str` now using `_mojo_tagged_addr_ok`, plus two
mixed-type `or`/`and` rewrites in `_reset_func`) took
`bootstrap-stage2-dumps` from **45/45 segfaulting to 4/45**. The blowup
was always there; the crash was just upstream of it.

Gate peak memory went **10.4 GB → 40.4 GB** across that fix, entirely
because the jobs now run long enough to reach their real footprint
instead of dying at 72 s.

## 3. Reproduction

```sh
cd /Users/mrs/net/chatgpt/claude/mojo-reference2   # branch `crash`
# a 133-byte program that does one addition
printf 'def f1(a, b):\n    return a + b\n\ndef main():\n    print(f1(1, 2))\n' > /tmp/tiny.mojo
/usr/bin/time -l ./mojoc --dump-full /tmp/tiny.mojo
#   -> "maximum resident set size" ~ 17,011,359,744  (15.84 GB)
#   -> "instructions retired"        ~ 180,000,000,000
#   -> "peak memory footprint"        ~ 17,013,322,064
/usr/bin/time -l ./mojoc --help      # -> ~10,000,000 (0.01 GB), 0.1 G instr
/usr/bin/time -l ./mojoc             # -> 58.08 GB, 1959.1 G instr  (NO input file)
```

The probe writes `<name>.ci` into the repo root — delete it afterwards.
The synthetic ladder used for the curve was N copies of a 5-line
function plus a `main()` that calls one of them, N ∈ {1,2,4,8,16,32}.

## 4. What this does to the existing doc's framing

`CODEGEN_bootstrap_resource_blowup.md` argues the shape of the problem
is **cumulative over the transitive closure under a never-frees
allocator**, so that "a modest per-module regression becomes a large
whole-program delta". Its own numbers for that claim: 93.7 / 93.7 /
95.6 GB for the flag probe, ~45 GB for a full `make bootstrap`, and
**≥192 GB** for `--dump-full fire.py`.

**Those cannot be explained by per-module growth, because the per-module
cost is ~0.** A 1206-module closure and a 1-module closure both cost
15.84 GB. If 15.8 GB is a fixed constant, then 192 GB is ~12x it, and
the ~12x needs its own explanation — it is not "a modest per-module
regression".

So, specifically:

- **Do not go looking for the per-module leak first.** It is not where
  15.8 GB is. (The session-4 recommendation to free intermediate
  allocations is not *wrong* — the never-frees allocator was never
  exonerated, only implicated in a case that turned out to have another
  cause — but it is very unlikely to be the 15.8 GB.)
- **The `-O1`/`-O2`/`-O3` flag probe is a dead end** for this constant,
  and its own conclusion already said so (93.7/93.7/95.6 GB).
- **Re-measure the 192 GB claim** with the §3 method before building on
  it. It was taken from a *manually `kill -9`'d* background run, and
  that doc's own hard-won rule is that a SIGKILL there is evidence of
  nothing — a manual kill and an OS kill are the same signal, and
  192 GB was explicitly recorded as "a lower bound on what it wanted,
  not a measured peak".

## 5. Gate consequences, right now

| step | memclass | ceiling | measured | verdict |
|---|---|---:|---:|---|
| `ab-native` | `small` | **8 GB** | 9.4 GB | RESOURCE-capped |
| `native-dumpfull` | `program` | 55 GB | **40.4 GB** | child exit 1 (not capped) |
| suite total | | | 40.4 GB | was 10.4 GB pre-fix |

**`ab-native` cannot pass as configured, for a reason that has nothing to
do with the A/B corpus.** Its `mem='small'` ceiling is 8 GB, and the
compiler's *fixed* cost is 15.84 GB. Every case in it exceeds the
ceiling before compiling anything. Either the constant comes down, or
`small` is the wrong class for a job that runs the real compiler — but
note the trap: `MEMLIMIT_GB` raises ceilings, so "just raise it" makes
the run slower without making it correct, and `ab-native` is supposed to
be the *cheap* A/B check.

Per `tools/suite.py`'s own rules, a RESOURCE verdict is reported
separately from a failure **on purpose** and the `expect=` anti-rot rule
**explicitly does not forgive it**. So `ab-native`'s `expect=SELFHOST_SEGV`
marker now produces a hard gate failure, while its *stated reason* — "the
self-hosted compiler segfaults on ANY input (exit 139 on a two-line
program)" — is false on both counts: it no longer segfaults, and it is
capped, not crashing.

## 6. Hypotheses, ranked

Unproven. Ordered by how well each explains "a constant, paid before the
input matters".

1. **Eager whole-stdlib elaboration / registry population at pipeline
   entry.** A 15.8 GB / 180 G-instruction fixed cost that is
   input-independent is the signature of building something for *every*
   module or *every* type in the universe rather than for what was asked
   for. The stdlib is 664 files; if the pipeline materialises an
   elaborated form of all of them (or a cross-product of types ×
   methods) before touching the target, that is exactly this number.
2. **A fixed-size arena or table whose bound is wrong by a large
   factor.** One `malloc`/`calloc`/reserve of a constant miscomputed by
   3-4 orders of magnitude would produce a flat, input-independent
   footprint. Cheap to check, and it would also explain the flat
   instruction count if the cost is touching (zeroing) the region.
3. **Quadratic behaviour over a *fixed* universe** — e.g. all builtin
   types against all methods. Quadratic in a constant is still a
   constant, and 180 G instructions is a very plausible N².
4. Something in the runtime's own initialisation — but `--help` is free,
   so it must be reached lazily from the compile path, not from
   `main()`. Note `runtime/fire_runtime.c` is now in the picture: a
   never-frees registry that pre-allocates is consistent with #1.

Note what the flat *instruction* count rules out: the 15.8 GB is not
being produced by a workload that varies with the input at all. A
leak would show growth; a re-parse would show growth; only a constant
computation gives this.

## 7. Next bounded actions

1. **Localise it in one run, not by bisecting.** Put an RSS probe at
   each phase entry of the compile pipeline — `getrusage(RUSAGE_SELF)`
   `ru_maxrss`, or `task_info` `phys_footprint` on macOS for a truer
   number — and print phase name + running peak. The cost is provably
   between argv parsing (`--help` is free) and codegen. One run with
   20 probes beats 20 runs.
2. **Then bisect *within* whatever phase that names**, still by probe
   rather than by rebuild.
3. **Check the no-arg 58 GB path separately.** It is 3.7x the constant,
   so it is either a different code path or the same one with a bigger
   universe. Which one it is, tells you whether the constant is a floor
   or a unit.
4. **Re-measure `fire.py` in the foreground** with `/usr/bin/time -l`,
   per §3. If it really is ~192 GB against a 15.8 GB constant, the ratio
   is the next real clue and it is currently unaccounted for.
5. Only after 1-4: decide whether `small`/`program` ceilings in
   `tools/suite.py` are still the right numbers, and correct the three
   now-false `expect=SELFHOST_SEGV` reason strings.

## 8. Caveats on the measurements

- `/usr/bin/time -l` numbers are for the `./mojoc` process itself. The
  runner's `memcap` numbers (`ab-native` 9.4 GB, `native-dumpfull`
  40.4 GB) are **tree** totals and say "across up to 3 procs", so those
  include the `gcc` children. Do not compare the two sets directly.
- `ru_maxrss`/peak RSS is a high-water mark, so it cannot distinguish
  "allocated 15.8 GB and held it" from "allocated and freed 15.8 GB
  repeatedly". The flat *instruction* count suggests the latter is
  unlikely, but a probe (§7.1) settles it.
- macOS `peak memory footprint` tracked `maximum resident set size` to
  within 0.01% in these runs, so either is usable.
- The sibling checkout `/Users/mrs/net/chatgpt/claude/mojo-reference` was
  running `test_formal.py` concurrently during some of these
  measurements. It is a separate process tree and does not affect
  per-process RSS, but wall times here are not clean.
