# GATE red: 23 landing-gate jobs red on the `recover-land` round (2026-11-02)

## Status (2026-11-02, OPEN; gate jobs turned OFF to land the round)

The `recover-land` round (branch `work/recover-land`, base `8b69d5a8b`, 5 commits: `b40c29983`, `cde5f1c22`,
`1a78626a4`, `d49532053`, `417108eed`) gated RED on `make gate` with 23 jobs failing. Master had moved to
`474b08bca` since the base, so this report does not establish that the round is clean on current master.

Failing jobs, as reported by `tools/integrate.py --only recover-land` (gate log `work-integ/gate.log`, 51 passed,
23 failed, 11 skipped, 220 jobs, 7062 s):

    async-void-return, bootstrap-stage1-transitive, coro, coro-detached-async, coro-future-await, doc-refs,
    doc-refs-stale-verdicts, formal-sweep-truth, formal-sys, gimple, gimplegenerators, gimplerunner,
    globcompiled, linkmode, modcache, mojoc, runtimediff, runtimedylib, runtimere, selfhost, silentnoop,
    sqliteruntime, suite-self-test

### What was checked (the only checks made; the rest were not run)

- `test_gimple.py` on master `ba2ddd500` (425 passed, 4 failed) and on master plus `581cd068b` (425 passed,
  4 failed). The same 4 fail in both:
  - `a_character_is_an_immortal_table_entry_not_a_slice` (missing `mojo_char_at_str (`)
  - `for_over_str`
  - `a_diamond_import_does_not_give_an_imported_function_a_void_prototype [single-TU]` (`gcc -fgimple failed`)
  - `two_modules_one_same_named_function_keep_their_own_return_types` (`gcc -fgimple failed`)
  So the gimple failures predate the recovery round; `581cd068b` is not their cause.
- `suite.py coro doc-refs` on master `ba2ddd500`: `coro` FAILS (exit 1). No recovery commit touches
  `mojo/middle/coro.py`. `doc-refs` passes on master.
- The most repeated gate error is `module 'mojo.middle.coro' has no attribute 'module_qualifier'`. `coro.py` has
  `module_qualifier` imported lazily inside `lower()` to break an import cycle. Its origin is not yet established.
- `doc-refs`: `tools/dangling_doc_refs.py --ratchet` passes in the integration tree now. Its gate failure did not
  reproduce, and the cause is unexplained.
- Not checked on master: the other 19 jobs (`formal-sys`, `gimplerunner`, `selfhost`, `linkmode`, ...).

### Decision

The round is landed with these 23 jobs turned OFF (`tools/gates.json`, `control.py gate off`, worker
`integrator`). Nothing was landed by hand; the integrator merges and gates. The OFF entry is one anchored regex
over exactly these 23 job names, and `suite.py gate --skip` drops exactly these 23 (checked with a registry
dry run). `bootstrap-verify`, `bootstrap-validate` and the other gate jobs still run.

Consequence: the compiled path (`gimple`, `gimplerunner`, `gimplegenerators`, `selfhost`, `mojoc`, `linkmode`,
`bootstrap-stage1-transitive`) is NOT covered by the gate for this landing. CLAUDE.md requires a full gate for
compiled-path changes; this landing does not meet that requirement, by the owner's instruction.

### Next steps

1. Re-enable each job when its failure is fixed: `python3 tools/control.py gate on '<pattern>'`, then remove this
   doc in the same commit.
2. Triage the 4 gimple failures and `coro` against master, one at a time. `coro` is the one to start with: it is red
   on master without any recovery commit.
3. Find the source of `module 'mojo.middle.coro' has no attribute 'module_qualifier'`.
4. Explain why `doc-refs` went red in the gate and not on rerun.
5. Rerun the recovery round's landing on current master once the OFF jobs are triaged, so the gate on the merged
   tree is not the one that was red here.
