# `test_gimple_runner.py` on the merged bug-batch tree: what was red then, what is red now, and what is still open

**Area:** CODEGEN / TESTS. Filed 2026-10-02 on `work/bugs4-2` by a worker
measuring narrow runs of `gimplerunner` and `silentnoop`. **Re-measured
2026-10-04; every numbered item below is FIXED, and the file's own remaining
question is answered.** Kept rather than deleted because two of its
conclusions are still load-bearing and neither is visible anywhere else.

## What the doc said, and what is true now

It reported seven red cases and named three one-liners as merge accidents:

| item | then | now |
|---|---|---|
| `gimple_bytes_*` × 4 — `AttributeError: 'GimpleGen' object has no attribute '_emit_dict_int_value_store'` | red | **fixed** (`64dcde32`) |
| `gimple_dict_of_bool_values` — `implicit declaration of function 'mojo_mark_dict_bool_values'` | red | **fixed**: the runtime replaced the whole-dict pair with per-slot `mojo_dict_set_bool`; no call site spells the old name any more (only comments do) |
| `gimple_bool_annotated_struct_field` | red, wrong output AND a `gcc -fgimple` failure | **passes** |
| `gimple_tuple_dict_key_is_content_keyed` | red | passes on its own; see `bugs/CODEGEN_dict_comprehension_repr_is_separately_broken.md` for the neighbouring defect |
| `gimple_sorted_string_key_runtime_built` | red | covered by `CODEGEN_sorted_key_of_runtime_built_strings_sorts_by_address.md` (bugs4-5's claim) |
| `gimple_char_scan_allocates_nothing_per_character` | peak RSS 246.7 MB vs a 60 MB limit | covered by bugs4-9's two PERF docs |

So the seven became four, and those four are `gimplerunner`'s declared
`expect='4 of 378: …'` marker — pointing at
`MERGE_bugs4_gimplerunner_four_remaining.md`, which is where each one's
measurement lives. That is the state this doc's first half was reaching for:
the reds were declared, counted and attributed rather than absorbed.

**What was added for the merge-drop class, because it had no check at all.**
`gimple_codegen.py`'s `GimpleGen` is only the delegating half of one API whose
other half lives in `mojo/backend_gimple/*`; the two halves are edited
separately and a missing delegate is an `AttributeError` during codegen that
no artifact, no link error and no exit code reports. `test_suite.py`'s "the
backend never calls a gen method GimpleGen does not have" now walks every
`gen.X(...)` CALL in the backend and requires it to resolve. Measured: 302 such
calls, 0 unresolved; removing the delegate again makes the check fail on all
six sites.

## `silentnoop`'s TIMEOUT — the one item that was open, now fixed

It was registered at `timeout=900` while the job needs **1122 s alone**
(18m42s, 26 cases, nothing else running — measured on this tree and on a
pristine `git archive` copy of the merge base, 1122 s and 1125 s). A timeout
is a failure in its own class: `TIMEOUT` is reported under `FAILED:` and is
deliberately not something an `expect=` marker can forgive, because a job
killed at its timeout has reported nothing.

`tools/suite.py` now registers it at **1500 s**, with the measurement written
down beside it and where the time goes: 4m36s of user CPU inside 18m42s of
wall is 24% of one core, so the job is WAITING-bound — its subprocesses
(gcc, the compiled binaries) — not computing. Making it cheaper is a separate
project; the registration was the thing that was wrong.

## `selfhost` — measured, and NOT what this doc said

The doc reported `selfhost` "deeply red" with two runs that "do not even fail
the same way", and warned that "my list is shorter is not a result". That
warning was right and is kept. Re-measured 2026-10-04:

* the three STATIC checks all pass — 62 modules, every generator/async
  lowered in place or its module refused whole; the dylib module path refuses
  an unlinkable `generated_cpp`; 1549 functions with 1 pinned C prototype, all
  matching;
* the BUILD half fails, with exactly **two** gcc errors, both of the same
  class and neither in a file this branch's changes touched the typing of:

      mojo/middle/coro.py:3483:1: error: non-trivial conversion in 'var_decl'
      myinterpreter.py:2461:1: error: non-trivial conversion in 'var_decl'

  `non-trivial conversion in 'var_decl'` is the "a bare `int` literal assigned
  to an `int64_t`" class, and the one site this tree already fixed
  (`_gen_stmt_ComptimeForStmt`'s induction variable, routed through
  `_safe_coerce_emit`) is a different statement.

So the honest statement is a count and a file list, not a verdict: the
compile/link half is red on two `non-trivial conversion` sites, the analysis
half is green, and the doc's "464 errors vs 65, and the two runs do not even
fail the same way" measurement is superseded. Whoever picks this up should
re-run the baseline with `module_gen.py`'s `'<='` failure bypassed before
comparing error lists — that is still the right next step, and this section is
the measurement to compare against.