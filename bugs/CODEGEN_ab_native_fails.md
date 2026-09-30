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
commit** — that is the whole re-enabling procedure, and step 4 below is only
for the case where you want to run it *before* it passes.

What did **not** change: `deps=['mojoc']` is still a dep, so the `native`
bucket still builds the native compiler (3.7 GB measured, `small`) — that
build is the part of the bucket that is worth its cost, and it is also what any
future run of this test needs.

## 1. What actually fails

The recorded evidence, and its limits, stated plainly because the difference
matters for what to do next:

- **It is a byte-parity divergence, not a crash and not a memory verdict.**
  `mojo_boxed_is_str`'s 31-bit-tag-range bug — the segfault on any input
  including a two-line program — was fixed in `e7fc3ece` (2026-09-27), and
  `./mojoc --dump-full` on a two-line program is now exit 0 / 12.1 MB / 94.6 M
  instructions. The marker that used to say "segfaults on any input" was
  measured false and corrected; what is left is the dump comparison.
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
  `do_imports=True` sibling-import compile with files placed at the repo root —
  see `test_ab_native.py`'s `DUMP_FULL_TESTS` docstring), and that pre-pass
  costs ~15-30 GB / ~15-25 s per call. It is localised, not fixed:
  `bugs/CODEGEN_bootstrap_resource_blowup.md` and BLOW.md §0.

## 2. What would make it pass

Two independent conditions, and the cheap one is worth doing first:

1. **Find the divergence.** `make mojoc && python3 test_ab_native.py`, run from
   the repo root (it writes its corpus into the root on purpose, and `mojoc`
   must run from there). It needs the binary and up to ~21 GB, and it prints,
   per case, `PASS <name>: IDENTICAL` or `FAIL <name>: DIFF at line N`, with
   the first differing line and four lines of context. Note that
   `python3 tools/suite.py ab-native` will **not** run it — that is the
   marker working, and the run says `1 disabled` and exits 0 — so run the test
   file directly, or flip the marker (§3). Write the failing case names into
   this doc. If the answer is "all 30 pass", the regression is already fixed
   and §3 is a two-line change.
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
| `bootstrap-stage2-dumps` | 0.5 GB **per item**, 47 items | `tiny` 4 GB each (24 at a time under the ledger) | `gate`, `bootstrap` | not recorded; a fanout, so bounded by the slowest item | **leave it as `expect=`.** 4 GB per item is at the floor class, and the fanout is 47 cheap jobs rather than one expensive one — under the 4 GB line, so by the stated threshold it belongs to the cheap side. Note what it costs in *time*: it is on the critical path of the whole `bootstrap` chain, and 47 recorded FAILs would buy nothing. If disabling it, the 5 dependents (`bootstrap-stage2-transitive` … `bootstrap-verify`) would then have to be disabled too, since a disabled dep no longer skips its dependents. |
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

Two things the table says that the markers do not:

- **Eleven of the thirteen are in no bucket at all.** They are registered, they
  are red, they are declared — and nothing runs them, which is a coverage hole
  rather than a cost problem: their `expect=` markers are currently untested
  anti-rot. Adding them to a bucket (an `abtest` bucket, say) is what makes the
  markers mean something, and it is cheap. Note the flip side: the day they
  join a bucket they are on the cheap side of the threshold, so `expect=` is the
  right marker for all eleven, not `disabled=`.
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
