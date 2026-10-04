# CODEGEN: `ab-native` is disabled, not run — what fails, what would fix it, how to turn it back on

## Status (2026-09-30 — the test is REGISTERED and NOT RUN; its outcome is known and it is not cheap)

`ab-native` is the python-vs-native byte-parity A/B sweep
(`test_ab_native.py`): 27 built-in `--dump` snippets plus 3 `--dump-full`
sibling-import scenarios, 30 gated cases in all (`test_simple.mojo` is
informational and not counted). It was a known failure carrying
`expect=SELFHOST_TOKENIZE_BLOWUP`, and it ran in full on every gate to reach
that same verdict. Measured, from the 2026-09-30 gate:

| | |
|---|---|
| peak RSS of the whole tree | **20.5 GB** |
| memclass / reservation | `program` = **55 GB of a 96 GB machine-wide budget** |
| `excl` | **yes** — nothing else in the run started while it ran |
| verdict it produced | FAIL → EXPECTED, every time |

So one job whose answer was already written down cost 20 GB, took 55 GB of the
machine's reservation ledger, and made every other job in the run wait for it.
That is the policy in CLAUDE.md, "Known-failing tests": an expensive known
failure must not be run, and it must be `disabled=<bug doc>` with the doc as
the switch.

**It is now `disabled='bugs/CODEGEN_ab_native_fails.md'`** — this file. Still
registered, still in the `native` and `gate` buckets, still carrying its
measured peak (20.5 GB) and the class the ratchet assigns that peak
(`program`), so the day it is turned back on the numbers are already sized. Not
run: no process, no memcap, no reservation, no wall time, no peak.
`suite.reserved_gb(ab-native)` is 0 and
`python3 tools/suite.py --dry-run native` prints the 0 next to the name.

**The doc is the switch, and it is checked.** The repo's rule is that a fully
fixed bug's doc is DELETED, so the disappearance of this file is exactly the
event "the bug is fixed". `tools/suite.py`'s `disabled_problems()` refuses to
load the registry while this file is gone and says so by name:

```
disabled test ab-native: its bug doc bugs/CODEGEN_ab_native_fails.md is gone,
so the bug is fixed: turn the test back on
```

A typo in the marker (a doc that never existed) fails the same way with its own
message, and a job carrying both `expect=` and `disabled=` is refused outright.
The anti-rot is therefore mechanical rather than a matter of remembering: a
fix cannot land without re-enabling the test, and this test cannot stay off
forever. **When the divergence below is fixed, delete this file in the same
commit** — that is the whole re-enabling procedure; §3 is only for the case
where you want to run it *before* it passes.

What did **not** change: `deps=['mojoc']` is still a dep, so the `native`
bucket still builds the native compiler (3.7 GB measured, `small`) — that
build is the part of the bucket that is worth its cost, and it is also what any
future run of this test needs.

## 1. What actually fails

The recorded evidence, and its limits, stated plainly because the difference
matters for what to do next:

- **It is a byte-parity divergence, not a crash and not a memory verdict.**
  `./mojoc --dump-full` on a two-line program used to exit 139, and that
  segfault was fixed in `e7fc3ece` (2026-09-27) — `mojo_boxed_is_str` had been
  made to alias `_mojo_tagged_addr_ok` wholesale, so a misaligned `.rodata`
  literal stopped classifying as a string and the compiler fell into formatting
  addresses as decimal strings; the fix splits out `_mojo_ptr_shaped`
  (BLOW.md §1). Re-measured on that tree: the two-line program is exit 0 /
  12.1 MB / 94.6 M instructions. The marker that used to say "segfaults on any
  input" was measured false and corrected; what is left is the dump
  comparison.
- **It used to pass.** `bugs/CODEGEN_noshim_dumpfull_preexisting_divergence.md`
  records `check-ab-native` at **30 passed / 0 failed** on 2026-09-21, after
  nine rounds of self-hosted-only fixes. The `expect=` marker first appeared
  2026-09-26. So the current redness is a **regression in that window**, not a
  long-standing gap, and that is where to start: something between 2026-09-21
  and 2026-09-26 moved the compiled backend away from the python reference for
  at least one of the 30 cases.
- **Which case(s) differ is not recorded in the tree.** No run log is committed,
  and re-deriving it means the 20.5 GB run this doc exists to avoid — the last
  one to be reproduced by a session that had hours to spare. The first thing
  anybody fixing this needs is one run's output, and nothing else in this
  document can substitute for it.
- **The cost is the same blowup `native-dumpfull` still runs into.** Both
  corpora deliberately trigger the self-hosting bootstrap pre-pass (a genuine
  `do_imports=True` sibling-import compile, whose sources live in a per-run
  scratch directory under the worktree rather than the repo root since the
  2026-09-29 flake fix — see `test_ab_native.py`'s module docstring), and that
  pre-pass costs ~15-30 GB / ~15-25 s per call. It is localised, not fixed:
  `bugs/CODEGEN_bootstrap_resource_blowup.md` and BLOW.md §0.

## 2. What would make it pass

Two independent conditions, and the cheap one is worth doing first:

1. **Find the divergence.** `make mojoc && python3 test_ab_native.py`, run from
   the repo root (`mojoc` must run from there: both dump paths use `cwd=HERE`,
   so the compiler writes each case's `.ci/.tok/.ast/.pyi` into the repo root
   beside its tagged source name). The test's own `.mojo` sources go in a
   private per-process directory under `.tmp/` and no longer in the root — that
   was the writer half of the 2026-09-29 round-6 flake, and
   `test_ab_native.py`'s module docstring has the four constraints. It needs the
   binary and up to ~21 GB, and it prints, per case, `PASS <name>: IDENTICAL`
   or `FAIL <name>: DIFF at line N`, with the first differing line and four
   lines of context. Note that `python3 tools/suite.py ab-native` will **not**
   run the sweep — that is the marker working — but it does not cost nothing
   either: naming a test brings its `deps` with it (which is what a Make
   prerequisite means), so it would first build `mojoc`, 3.7 GB, `small` and
   exclusive. `--dry-run` shows the marker and starts nothing:
   `python3 tools/suite.py --dry-run ab-native` prints `2 tests, 1 jobs` — the
   job being `mojoc` — and then
   `ab-native  (DISABLED: not run, 0 jobs, reserves 0 GB)`. To run the sweep,
   invoke the test file directly as above, or flip the marker (§3). Write the
   failing case names into this doc. If the answer is "all 30 pass", the
   regression is already fixed and §3 is a two-line change.
2. **Fix the divergence class**, which is the real work and is tracked
   elsewhere: the compiled backend's emitted `.ci` must be byte-identical to
   the python reference's. Every instance found so far is documented in
   `bugs/CODEGEN_noshim_dumpfull_preexisting_divergence.md` (its per-class
   list, "A/B divergence list" and the dated entries) — that doc, plus
   `bugs/CODEGEN_bootstrap_resource_blowup.md` for the cost that makes the
   corpus expensive, is where the next step belongs.

Lowering the pre-pass cost is worth doing on its own account (it is
`bugs/PERF_memory_over_4gb_is_a_bug.md`'s headline), but note the honest
dependency direction: **fixing the memory does not by itself make this test
pass**, and it must not be treated as if it did. What it does is make running
the test cheap enough to stop guessing about it.

## 3. How to turn the test back on

While the divergence is still open, in one line in `tools/suite.py`:

```python
     disabled='bugs/CODEGEN_ab_native_fails.md',   →    expect=SELFHOST_TOKENIZE_BLOWUP,
```

…plus a reason that names the failing case(s) once they are known. That is
`expect=`, not `disabled=`: the anti-rot of an `expect=` marker (a test that
starts passing is reported as a FAILURE) is worth having again the moment the
test is affordable, and `disabled` cannot run it. Until then the direct
invocation is `python3 test_ab_native.py` — the registry deliberately does not
offer an override, because a flag that runs a disabled test is one more way for
a known-red 20 GB job to end up back on the critical path of every gate.

When the bug is genuinely fixed, do not turn the marker back on — **delete this
file**, and the registry check will tell the next person to drop the `disabled=`
line, which is the intended sequence. If the test is expensive even when it
passes, the right answer is to fix the cost first (§2), because a test nobody
can afford to run is a test nobody will notice regressing.

## 4. The other `expect=` jobs — measured, with a recommendation each

**Not changed by this work, on purpose.** `native-dumpfull` and
`bootstrap-stage2-dumps` fail for the same upstream reason and are the owner's
call; the table is here so the choice is one line each rather than a fresh
investigation. Read it with the threshold from CLAUDE.md: over ~4 GB (the
`bugs/PERF_memory_over_4gb_is_a_bug.md` line) or over a few minutes, an
`expect=` job is spending the machine to learn something already written down.

| job | measured peak | reserved | in a bucket? | wall time | recommendation |
|---|---|---|---|---|---|
| `native-dumpfull` | **31.3 GB** (largest job in the registry that completes) | `program` 55 GB | `gate`, `native` | ~126 s (BLOW.md §0, 2026-09-27) | **disable it too**, pointing at `bugs/CODEGEN_noshim_dumpfull_preexisting_divergence.md`. Same reasoning as `ab-native` and a worse ratio: 31.3 GB and 55 GB reserved for a known red. It is the one job whose run is also how the blowup's numbers get re-measured, so pair the disable with a standing instruction to re-run it by hand (`make check-native-dumpfull` / `python3 tools/suite.py native-dumpfull`) when that work moves — or, better, land the blowup fix first and decide again. |
| `bootstrap-stage2-dumps` | 0.5 GB **per item**, 47 items | `tiny` 4 GB each (24 at a time under the ledger) | `gate`, `bootstrap` | not recorded; a fanout, so bounded by the slowest item | **leave it as `expect=`.** 4 GB per item is at the floor class, and the fanout is 47 cheap jobs rather than one expensive one — under the 4 GB line, so by the stated threshold it belongs to the cheap side. Note what it costs in *time*: it is on the critical path of the whole `bootstrap` chain, and 47 recorded FAILs would buy nothing. If disabling it, note what a disabled dep does to its dependents: since DISABLED satisfies a dep, the 5 jobs downstream of it (`bootstrap-stage2-transitive`, `bootstrap-stage3-dumps`, `bootstrap-stage3-transitive`, `bootstrap-verify`, `bootstrap-validate`) would each have to be disabled as well, or `verify` would compare a fresh stage1 against a stage2 that was never dumped. |
| `x86-containers` | unmeasured | `small` 8 GB | **no bucket** | not recorded | none needed — leave it. It runs in nothing today. |
| `mutable-async-capture` | unmeasured | `small` 8 GB | **no bucket** | not recorded | none needed — leave it. |
| `transitive-closure-capture` | unmeasured | `small` 8 GB | **no bucket** | not recorded | none needed — leave it. |
| `gimple-async-runner` | unmeasured | `small` 8 GB | **no bucket** | not recorded | none needed — leave it. |
| `coro-future-await` | unmeasured | `small` 8 GB | **no bucket** | not recorded | none needed — leave it. |
| `async-void-return` | unmeasured | `small` 8 GB | **no bucket** | not recorded | none needed — leave it. |
| `taskgroup` | unmeasured | `small` 8 GB | **no bucket** | not recorded | none needed — leave it. |
| `async-with-lock-guard` | unmeasured | `small` 8 GB | **no bucket** | not recorded | none needed — leave it. |
| `nested-async-generic` | unmeasured | `small` 8 GB | **no bucket** | not recorded | none needed — leave it. |
| `coro-detached-async` | unmeasured | `small` 8 GB | **no bucket** | not recorded | none needed — leave it. |
| `async-runtime-scaffold` | unmeasured | `small` 8 GB | **no bucket** | not recorded | none needed — leave it. |
| `formal-struct` | 0.08 GB | `tiny` 4 GB | `proofs` | 43 s alone, 201 s beside the other seven | **leave it as `expect=`.** 0.08 GB is two hundredths of the 4 GB line, so by the stated threshold this is the cheap side and the anti-rot is worth more than the saving. 2 of 154 cases; `“`struct.pack` for a format naming 8 values was refused at the CALL SITE”` has the next step. |
| `formal-toplevel` | 0.04 GB | `tiny` 4 GB | `proofs` | not recorded (70 checks) | **leave it as `expect=`.** Same reasoning — and its doc records the *opposite* of the marker now (`“A struct construction with arguments in a module body now BUILDS”`: a case that builds where it asserted a refusal), so the burst of "marked expect=… but it PASSES" is exactly what should surface. |
| ~~`formal-module-attr`~~ | 0.07 GB | `tiny` 4 GB | `proofs` | 10.3 s | **no longer marked — GREEN, 18/18, and the marker is gone rather than relaxed.** A bracketed call to a private name was refused as a specialization whose brackets have nowhere to bind rather than as the export gap it is; the export rule is now asked first for a bracketed callee the defining module does not publish (`formal/build.py`'s `_bracketed_export_gap`). Both filings behind the old marker (`…_bracketed_call_to_a_private_name_is_refused_as_a_dangling_symbol.md`, `…_bracketed_private_name_refused_as_a_specialization.md`) are fixed and deleted. |

The last three are here because this table is the inventory of what a
`disabled=` decision would cost, and they arrived on master after it was
written — not because they belong in `ab-native`'s class. Of the six gated
`expect=` jobs, only `native-dumpfull` is anywhere near the 4 GB line, and that
is the point of the threshold: `disabled=` is for the jobs the machine cannot
afford, not for the red ones.

Two things the table says that the markers do not:

- **The eleven of the sixteen that were in no bucket at all are in buckets
  now** (2026-10-01). (Sixteen, not thirteen: the three `formal-*` host-module
  suites below arrived on master after this table was written, and each is
  `expect=` in `proofs`.) The eleven were registered, red and declared, and
  nothing ran them — a coverage hole rather than a cost problem, because their
  `expect=` markers were untested anti-rot. They are now the `coroutine`
  bucket's ten (`gimple-async-runner`, `coro-detached-async`,
  `async-with-lock-guard`, `mutable-async-capture`,
  `transitive-closure-capture`, `async-void-return`, `nested-async-generic`,
  `taskgroup`, `async-runtime-scaffold`, `coro-future-await`) and `x86`'s
  `x86-containers`, each measured first: 0.0-0.2 GB and 1.2-11.6 s for the ten
  (34.6 s total), ~4 minutes for `x86-containers`, which is why that one is in
  `x86` only. They are all on the cheap side of the threshold, which confirms
  `expect=` was the right marker for all eleven rather than `disabled=`. The
  part that says a marker on a test no gate runs cannot rot out is in CLAUDE.md,
  "Known-failing tests", and what stops the next one is
  `test_suite.py`'s `the buckets:` checks.
- **No duration is recorded for any of them.** `MEASURED_PEAK_GB` has rows only
  for jobs a gate ran while the peak table was being recorded, and the registry
  keeps no wall-time table; "wall time" above is from the registry comments and
  BLOW.md, and is otherwise genuinely unknown rather than small. If the owner
  wants a duration in this table, the cheap way is a `build/suite.log` from a
  gate that included them.

## Status (history)

- 2026-09-26 — `expect=SELFHOST_SEGV` added (the binary segfaulted on any input).
- 2026-09-27 — the segfault fixed in `e7fc3ece`; the marker corrected to
  `SELFHOST_TOKENIZE_BLOWUP` (pre-pass cost, not a crash).
- 2026-09-30 — `expect=` → `disabled=` (this file). Measured 20.5 GB, 55 GB
  reserved, `excl`; outcome known. Re-raised from RESOURCE-capped at 9.4 GB
  (2026-09-29) to a real FAIL by the 2026-09-30 gate's `program` class.
