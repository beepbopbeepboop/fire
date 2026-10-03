# FORMAL_sweep_default_timeout_hides_a_crash_on_the_repos_own_files: the `tool` bucket now says what it does not know

**Area:** FORMAL (`tools/formal_sweep.py`, the `-t` default and its help text,
and the summary's `tool` block).

**Status 2026-10-03 (`work/formal10-6`): §3 is ANSWERED — the profile it asked
for exists, and it says the two files' cost is NOT the AST-walk-per-pass shape
this section names.** Measured on this tree with wall-clock timers (not
`cProfile`, whose overhead is per call and which ranks `iter_nodes` first for a
walker that is 6-8% of the real time): `struct_field_names` walks every method
body of a struct and is asked **743 times for a 172-line file**
(`std/builtin/int.mojo`, where `_self_field_names` is 2.51 s of 3.9 s), and
`_init_field_assignments` walks `__init__` **four times per (struct, field)**
from `frame_field_type_candidates` alone (`monomorphize.py`, 1.42 s of 8.9 s).
The cost is `#asks x #bodies`, not `#structs x #bodies`.

The measurement, the harness that produces it, and the next step are in
`bugs/PERF_formal_build_recomputes_a_per_struct_census_on_every_ask.md`. Two
things it settles that this file's §3 could not:

* **the "finer unit" alternative is the wrong one.** Sweeping per FUNCTION would
  make the unit smaller without making the per-unit cost smaller; the cost is in
  a table recomputed per ask, and a smaller unit asks it more often. The profile
  is the alternative that was worth taking and it has been taken.
* **the ceiling on `gimple_codegen.py` / `myinterpreter.py` is a NUMBER, and it
  is "however long a per-struct census takes, times every ask of it".** Whether
  that lands inside any `-t` is step 3 of the new doc, and it is the first
  measurement that could put those two files in a rate at all.

**What is still open here, unchanged: the §2 policy decision** — whether the
default stays 30 s for both populations (it does, and the help names the one
that needs more) or the tool grows a `-t per population` flag. That is a real
feature, this file says so, and the numbers for it are §2's tables below. It is
not a bug fix and nothing in this status claims otherwise.

**Status: the REPORTED half is FIXED (commit `e0dc0e0a`) — the `tool` bucket is
split by cause, each cause carries its share of the scope, and a timeout row
says the file's answer is UNKNOWN at this `-t` rather than absent, together with
the command that answers it. The DEFAULT ITSELF is unchanged, and §2 below is
the measurement that says why the proposed replacement cannot do the job it was
proposed for. The crash this doc was filed about (`AttributeError: 'str' object
has no attribute 'name'`) is fixed at the source too, in `7b1f2643`, so nothing
in this repo hides behind a `tool` row on that account any more.**

## What I ran

```
$ python3 tools/memslot.py --gb 8 --label sweep -- \
      python3 tools/formal_sweep.py -j 2 --no-stdlib --allow-concurrent \
      gimple_codegen.py generated_dispatch.py imports.py mlir.py \
      module_loader.py module_spec_gen.py monomorphize.py myinterpreter.py
  ...
  TOOL: imports.py  (timeout (> 30s))
```

At `-t 600`, the same file on the same tree, with nothing else changed:

```
  BACKEND-CRASH: imports.py  (the backend raised: AttributeError: 'str' object
                                  has no attribute 'name')
```

`AttributeError: 'str' object has no attribute 'name'` is a **compiler defect**,
not a coverage limit, and it was the same defect `test_dataclasses_formal.py`'s
corpus case was failing on for `formal/build.py` the whole time (now fixed, in
`7b1f2643`). So the default timeout was not merely slow on this file — it was
**hiding a crash that another suite in this repository was already reporting**,
and the only reason this slice found it is that it re-ran with a bigger `-t`.

## What I expect

A file that is slow to build is `tool`/timeout. A file that **crashes** is
`backend-crash`, and the sweep says so on every path that reaches the build. At
30 s the build never reaches the census that raises, so the class is decided by
which bound the run happened to hit first, and the crash is simply not in the
ledger.

That ordering is not a bug in itself — a timeout has to be able to stop a build,
and no default is a substitute for `-t`. What was a bug is that the report
**could not express the difference**: one lumped sentence said "N file(s) got no
verdict at all (timeout/unreadable/memory-killed/tool error) … a too-small `-t`
is the usual cause", over a bucket holding files that crash, files that do not
fit in the ceiling, and files the tool could not read. A reader had no way to
tell how much of the scope was unknown, or which files, or what would answer
them.

## What was done (`e0dc0e0a`)

`_report_tool_causes` — one shared reporter, called by the complete run's
summary and by an interrupted run's, because they answer the same question and
two copies would be two wordings for a reader to be told two things by:

```
  note: 4 of the 6 classified file(s) (66.7%) got no verdict at all and are in
  NO rate. Each one is a file this run says NOTHING about, which is not the same
  as a file it has cleared:
    timeout             1 file(s) (16.7% of the classified scope) — the build
      did not finish inside -t, so what it WOULD have answered is unknown at
      this -t. A file that turns out to crash says so in `backend-crash`
      instead, and that is never cached, so it re-measures every run; a file
      that is merely slow to build is the other reading
    memory-killed       1 file(s) (16.7% of the classified scope) — killed at
      this tool's 4 GB per-file ceiling — a real cost finding about that file
      (see bugs/PERF_memory_over_4gb_is_a_bug.md), NOT something a wider run
      fixes, and not cached, so re-running re-measures it
    …
  re-answer them with a larger -t: python3 tools/formal_sweep.py --arch arm64
  -t 90 t.py
```

Four properties worth naming, because each replaces something a reader could
previously get wrong:

* **the fraction is of the CLASSIFIED scope**, which is the denominator every
  count above it is over — an interrupted run has already said how much of the
  scope it never reached, so reporting against the whole scope would mix two
  different "unknown"s into one percentage;
* **`timeout` is the only cause that gets a command**, because it is the only one
  a reader can act on immediately; the suggested `-t` is twice the bound that
  just failed (or a minute more than it), never the bound that just failed, and
  the paths are named while there are eight or fewer and otherwise pointed at
  from the `timeout` rows already on the output;
* **`memory-killed` and `wrapper-died` keep their distinct wording**, because
  they are told apart by evidence (a breach is memcap saying the ceiling fired;
  the other is memcap saying nothing at all) and lumping them sends a reader
  looking for a memory bug in a build that was never measured against a ceiling;
* **`-t`'s help text and `CLASS_BLURB['tool']`** now say what a `tool` row is
  NOT — no claim in either direction about that file — because the old wording
  ("never as a pass or a finding") is true and useless: the failure mode was not
  a reader believing the row, it was a reader not being told what to do about
  it.

Tests: `TestReport.test_the_tool_bucket_is_split_by_cause_with_its_share_of_the_scope`,
`…_with_no_timeout_says_no_retry_command`,
`…_many_timed_out_files_name_the_rows_rather_than_a_long_line`, and the
interrupted-run report case, which now asserts the cause line and the ceiling
rather than a count. `test_formal_sweep.py` 92 tests OK.

## §1 — why the repo's own files are a second population

A stdlib module imports a few stdlib modules. A repository-root `.py` imports
**the repository's other root `.py` files**, so one file's build is the sum of
its import closure's builds. Measured on this slice:

| file | lines | verdict at `-t 30` | at `-t 900` |
|---|---|---|---|
| `imports.py` | 185 | timeout | **backend-crash** |
| `module_spec_gen.py` | 399 | `codegen/dependency` | `codegen/dependency` |
| `mlir.py` | 344 | `codegen` | `codegen` |
| `generated_dispatch.py` | 135 | `pass` | `pass` |
| `gimple_codegen.py` | 5 645 | timeout | timeout |
| `myinterpreter.py` | 5 572 | timeout | timeout |

`imports.py` is **185 lines** and takes over 30 s, while `generated_dispatch.py`
at 135 lines passes inside it. Line count is not the predictor.

## §2 — and why the closure-proportional `-t` cannot be the fix

The original proposal was "a per-closure default, not a per-file one", because
the honest predictor looked like the size of the file's import closure. Measured
on this tree with the tool's own resolver (`imported_modules` +
`resolve_module_path`, the pair `import_closure_digest` walks, so these are the
modules a build would compile):

| file | modules in closure | closure lines |
|---|---|---|
| `imports.py` | 67 | 119 812 |
| `monomorphize.py` | 67 | 119 812 |
| `reflect.py` | 67 | 119 812 |
| `gimple_codegen.py` | 67 | 119 812 |
| `myinterpreter.py` | 69 | 126 065 |
| `cas.py` | 9 | 7 943 |
| `module_loader.py` | 7 | 5 103 |
| `module_spec_gen.py` | 7 | 8 069 |
| `mlir.py` | 1 | 344 |
| `generated_dispatch.py` | 1 | 135 |

`imports.py`'s closure and `gimple_codegen.py`'s are the **same set of paths**:
the symmetric difference is empty, module for module. So the four files that
could not be told apart by line count — one that crashes inside 600 s, two that
pass inside 30 s, and the two that no `-t` answers — **share one closure of
identical size**, and a `-t` proportional to closure size cannot separate them.
It would raise the bound for `monomorphize.py` and `reflect.py`, which do not
need it (they finish inside 30 s, so the bound is not spent), and it would not
answer `gimple_codegen.py` or `myinterpreter.py` (§3).

What is left is that per-file wall time on this machine is set by the CPU share
the scheduler gives one build, not by the file: a single `std/bit/mask.mojo`
build measured in the b6 sweep took **3 m 37 s wall for 56 s of user CPU**
(`bugs/FORMAL_sweep_work_map_2026-10-02_b6.md` §1.2), and at `-j 6 -t 120` the
same sweep timed out **29 of its first 42 files**. A static default is therefore
a guess about the load, and the one thing that is not a guess is the file list.

**So the remaining decision, for whoever wants to make it, is a policy and not a
formula:** either the default stays 30 s and the population that needs more is
named in the help (it now is: "the much larger stdlib modules, and this
repository's own root files, which are a different population"), or the tool
grows a `-t per population` flag so a repo-root sweep and a stdlib sweep have
their own default and their coverage numbers are comparable by construction. The
second is a real feature; it is not a bug fix, and the numbers this doc's table
came from are the argument for it.

## §3 — the part that is not a timeout problem

`gimple_codegen.py` (5 645 lines) and `myinterpreter.py` (5 572 lines) time out
at `-t 30`, at `-t 900`, and — as of the original writing — were still running at
`-t 5400`. Both are **CPU-bound, not memory-bound**: the whole 8-file sweep
peaked at **0.3 GB** across 6 processes, and memcap's 4 GB per-file ceiling was
never approached. A bigger `-t` and a closure-proportional `-t` both leave them
exactly where they are.

So for those two the answer is not a number. Either

* **a finer unit** — construct coverage is a property of a file's *functions*,
  and the sweep's unit is a file; or
* **a profile** — 5 645 lines taking > 900 s against a 344-line file taking
  under 600 s is not a constant factor, and the AST-walk-per-pass shape in
  `formal/build.py` is the first thing to look at.

Both are recorded in the repo-b work map with the same numbers, so a reader who
wants them has the measurement rather than the question.

**The second one is DONE (2026-10-03) and the first one is the wrong fix.** The
profile is in `bugs/PERF_formal_build_recomputes_a_per_struct_census_on_every_ask.md`
with the harness in it, and it puts the cost in the per-struct tables rather than
in the AST walk: `struct_field_names` re-derives a struct's whole method-body
census on every ask (743 asks for a 172-line file), and `_init_field_assignments`
walks `__init__` four times per (struct, field) from `frame_field_type_candidates`
alone. `iter_nodes` — the walker this section named — is 6-8% of the real time,
which `cProfile`'s ranking hides because its overhead is per call.

So a finer unit makes it worse rather than better: the unit is not what is
expensive, the recomputation is, and a smaller unit asks for the same table more
often.