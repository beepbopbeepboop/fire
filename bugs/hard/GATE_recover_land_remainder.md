SPLIT: GATE_recover_land_remainder-part1, GATE_recover_land_remainder-part4

# GATE: recover-land backlog remainder — OFF entry owner doc

## Status (2026-11-13, OPEN; remainder untriaged on current HEAD)

The OFF entry in `tools/gates.json` matching

    ^(mojoc|selfhost)$

previously named the deleted `bugs/mid/GATE_red_recover_land_2026-11-02` doc, which was removed
in `d44f44787` ("Fixed root cause (coro.module_qualifier missing as module
attribute)") while the OFF entry was left pointing at the deleted path. That
left 23 gated jobs skipped with no owning doc.

This doc re-establishes the owner for that OFF entry. The live remainder has
**not** been fully re-triaged on this HEAD: `build/suite.log` is not present in
this worktree and re-running all 23 jobs (including compiled-path/bootstrap
coverage such as `selfhost`, `mojoc`, `linkmode`, `bootstrap-stage1-transitive`)
is outside a light worker's budget. Treat every job in the pattern as still part
of the backlog until individually verified green and removed from the entry.

### 2026-11-18: `formal-sweep-truth` and `formal-sys` are green; both re-enabled

`work/bug-gate-recover-land-remainder-part3` verified this pair, and its landing
went stale while master re-enabled the same jobs from its own evidence:

- `python3 test_formal_sys.py` — `PASS=13 FAIL=0`; re-enabled in `2df09657e`.
  Re-run on this branch, same result.
- `python3 test_formal_sweep_truth.py` — `145 tests OK (skipped=10)` on this
  branch. It was red on master for two reasons, both fixed in `efb44e0a4`: the
  scratch-dir guard named a hard-coded `/tmp` in `tools/test_claim_release.py`,
  and `AXIOM_CLOSURE` still pinned the 2026-11-08 census (`Contracts` 9,
  `ProofLibSteps2` 11, `ProofLibSteps8` 6, `Refine` 32). Re-enabled in the same
  commit.

The branch therefore lands no `tools/gates.json` change: both names are already
out of the OFF entry on master, and its stale copy of the pattern must not
re-add `doc-refs`/`doc-refs-stale-verdicts`, which `fb746c0b1` turned back on.
What it does land is the pinning test (`test_gates_off_entries_name_a_doc.py`)
and the deletion of the part-3 backlog doc with its evidence.
The remaining jobs in the pattern are still untriaged.

### 2026-11-18: the runtime and utility jobs are green; all six re-enabled

`work/bug-land-gate-recover-land-remainder-par-3` assessed the part-5 branch
(`work/bug-gate-recover-land-remainder-part5`) against today's HEAD and
landed its runtime half, adapted:

- `python3 test_runtime_diff.py` — 69 passed, 0 failed.
- `python3 test_runtime_dylib.py` — 130 passed, 0 failed (the `fire_ssl.c`
  row is skipped: openssl/ssl.h is not installed on this machine).
- `python3 test_runtime_re.py` — engine vs CPython 48/48 + the compiled
  program matches.
- `python3 test_silent_noop_iter.py` — 28 passed, 0 failed.
- `python3 test_sqlite3_runtime.py` — 66 passed, 0 failed.
- `python3 test_suite.py` — green on this HEAD (the suite-self-test job).

`runtimediff`, `runtimedylib`, `runtimere`, `silentnoop`, `sqliteruntime` and
`suite-self-test` are out of the OFF entry, pinned by
`test_gates_runtime_jobs_not_off.py` (registered as `gates-runtime-not-off`,
in the check bucket), which fails if any of the six names an OFF entry again.
The part-5 backlog doc `GATE_recover_land_remainder-part5` (deleted) went with
this evidence.

Still OFF, still this doc's backlog: `mojoc`, `selfhost`. The part-5 branch's
`test_suite.py` UNREGISTERED declarations were dropped instead of landed:
all eight files are registered as named jobs on master, so declaring them
UNREGISTERED would trip the estate audit both ways.

### 2026-11-18: the five gimple codegen jobs are green; all five re-enabled

`gimplegenerators`, `gimplerunner`, `globcompiled`, `linkmode` and `modcache`
are green on current HEAD and have left the pattern (measured with
`tools/memslot.py --gb 8`):

- `test_gimple_generator_runner.py` — 515 passed, 0 failed
- `test_gimple_runner.py` — 634 passed, 0 failed
- `test_glob_compiled.py` — PASS (13 lines identical to CPython)
- `test_link_mode.py` — 56 passed, 0 failed
- `test_module_cache.py` — 183 passed, 0 failed

The last two reds were fixed on master after the gimple triage branch was cut:
`28b1029c0` re-records the coroutine PAD cleanup checkpoint on resume (the
`@contextmanager` `finally` UAF,
`gimple_user_contextmanager_param_restore_finally`), and `1a07cc096` links
and runs the elaborated `slice4` overload (the modcache failure).
`test_gates_gimple_jobs_not_off.py` pins that no OFF pattern matches the five
again, and the bootstrap pin now lists only `mojoc` as still owned by this
entry.

## Original context (carried over from the deleted `GATE_red_recover_land_2026-11-02` doc)

The `recover-land` round (branch `work/recover-land`, base `8b69d5a8b`) gated RED
on 2026-11-02 with 23 jobs failing. Known observations from that report:

- `gimple` had 4 pre-existing failures on master at the time of that report.
- `coro` failed on master without recovery commits; `doc-refs` passed on rerun
  but failed in the gate (cause unexplained in that report).
- Repeated error seen: `module 'mojo.middle.coro' has no attribute 'module_qualifier'`.
- `bootstrap-verify` / `bootstrap-validate` were reported as still running while
  these 23 were OFF.

## Next step

1. Re-run each job in the pattern (or consult a fresh full gate log) on current
   master/HEAD and narrow the OFF entry to jobs that are still red.
2. For each job proven green, remove it from the regex (or `gate on` when empty)
   in the same commit as the evidence.
3. Split unrelated failures into separate bug docs with their own OFF entries if
   needed, keeping every OFF entry's `doc` pointing at an existing file.

## Done when

`python3 tools/memslot.py --gb 8 --label gate-off-doc -- python3 -m unittest test_gates_off_entries_name_a_doc.py -v`
passes, proving every `tools/gates.json` OFF entry names an existing doc and
worker (so the recover-land entry is owned by a live doc, not a deleted path).