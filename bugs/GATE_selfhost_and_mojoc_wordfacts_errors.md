# GATE: `make gate` fails in `mojoc` and `selfhost` with gcc errors (WordFacts)

Found 2026-11-24 by `make gate` on a clean export of `4a4dca532` (306 jobs: 150 passed, 2 failed,
10 skipped, 6 disabled; 1656 s; peak 13.2 GB in `mojoc`).

## Symptoms

- `mojoc`: `build_config.py:840:48: error: unknown type name 'WordFacts'` (and 840-845, more lines).
  The generated code for a module refers to `WordFacts *`, but no typedef is in its translation unit.
- `selfhost`: `self-host compile/link regressed (GCC error, ICE, undefined symbol, or the produced
  binary cannot compile)`, the same family.

## What is known

- `WordFacts` is defined in `mojo/middle/valueinfo.py` (stage 5b). `gimple_codegen.py` pins
  `WordFacts_carry`, `WordFacts_bind_box`, `WordFacts_bind_tagged` with `WordFacts *` parameters
  (lines ~590-597) for the self-hosted compile; `methods_shared.py:131` emits selfhost-only forward
  declarations for it.
- The closure translation unit (`tools/selfhost_ci.py` + `gcc-mp-15 -O0 -fgimple`) has the same
  three `MojoList * + double` errors as before, and `WordFacts` appears 41 times in its source, at both
  `c37952511` (before the attribute-read commit) and `29c0435bf` (after it). So the closure TU does not
  show the `WordFacts` error, and the attribute-read commit is not its cause.
- An external `-Os` closure build (the user's log) shows the three `MojoList * + double` errors and no
  `WordFacts` error. So the failure is specific to the `mojoc` / `selfhost` build paths.

## Pending

- Whether it predates this session: the same two jobs on a clean export of `91140cc58` (the session's
  starting commit). Run: `python3 tools/suite.py -j1 mojoc selfhost` in that export. Record the result
  here: if they fail there too, it predates the session and is not caused by the solver work.
- Then: reproduce `WordFacts` as an oracle census (the closure gcc census with a `WordFacts` count),
  and find which generated module refers to `WordFacts *` without a typedef.

## Pre-session result (2026-11-24, on `91140cc58`, the session's starting commit)

Run: `python3 tools/suite.py -j1 mojoc selfhost` in a clean export of `91140cc58`.

- BOTH jobs still FAIL there: `mojoc` exit 2 (819 s, peak 13.5 GB; memcap `child exit 1`), `selfhost`
  `self-host compile/link regressed`.
- The `WordFacts` error is NOT in that run. `WordFacts` appears only as an unused-function warning
  (`_mojo_elem_repr_WordFacts`). So the `unknown type name 'WordFacts'` failure seen at `4a4dca532` is
  not what the old commit fails on.
- The old commit's `mojoc` failure is a different, not-yet-identified error; the captured log has no
  `file:line:col: error:` line for it (the failing `child exit 1` is after the gcc warnings).

Conclusion: the gate's `selfhost` / `mojoc` failures are NOT new with this session's `WordFacts`
change, but the specific error changed. Both failures exist before the session. Next: identify the
`child exit 1` error in `mojoc` on `91140cc58` (run the mojoc job's command directly, not through
memcap, and keep its stderr), and separately the `WordFacts` error at HEAD.

## Direct `mojoc` builds (2026-11-24): the fix measured, and the gate difference

The gate's `mojoc` job runs `$(PYTHON) fire.py build fire.py -O2 -g0 -o mojoc` under memslot. The same
command was run directly, with `/opt/homebrew/bin/python3` (the same interpreter the gate's PATH resolves):

- `91140cc58` (session start): 41 gcc error lines, mostly `assignment to 'int64_t' from 'MojoList *' /
  'char *' makes integer from pointer` in `emit_methods.py` (the import-cycle back-edge family).
  Exit 1.
- `4a4dca532` (HEAD of the gate export): 3 gcc error lines, all `invalid operands to binary + (have
  'MojoList *' and 'double')` (coro.py:7714, elab_intu.py:4166/4169; the out-of-scope family). Exit 1.
  (A fourth match was a docstring echo, not a compile error.)

So the session's solver work removed the back-edge family from `mojoc` (41 -> 3). The `WordFacts`
unknown-type errors reported by the GATE's `mojoc` job did NOT reproduce in the direct build. The gate
job's errors start right after its `memcap: mojoc` header, so the gate builds `mojoc` in a different
environment from the direct command. Next: diff the suite's environment for the `mojoc` job against the
shell (suite.py's env setup for `driver='make'` jobs, and the memslot wrapper), and rerun the gate job
alone with that environment.
