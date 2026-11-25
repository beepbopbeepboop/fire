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
