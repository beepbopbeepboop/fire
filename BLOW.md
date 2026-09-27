# BLOW.md — the memory blowup: a ~15.8 GB *constant*, not a growth curve

Branch `crash`, at `8539ac0` plus the uncommitted segfault fix
(`runtime/fire_runtime.c`, `mojo/backend_gimple/emit_infra.py`). Every
number below was measured on this tree, in the foreground, with
`/usr/bin/time -l`. Nothing here is inferred from a symptom.

`bugs/CODEGEN_bootstrap_resource_blowup.md` is the long history (424
lines, incl. the ~192 GB `fire.py` run and the useful "a SIGKILL here is
evidence of nothing" rule). **This document supersedes its framing, not
its history** — see §4.

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
