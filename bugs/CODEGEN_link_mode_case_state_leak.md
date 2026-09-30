# `linkmode` / `bare_submodule_import_call` fails in this worktree and not in an identical one

## Status

**Open, unattributed.** Found by `make check` on 2026-09-29 while landing
module-global state (`construct:module-level-state`). Nothing in this branch's
diff plausibly causes it and I could not reproduce it away — recorded here
rather than dropped, because `make check` is red and "I think it is unrelated"
is not an answer.

## The failure

    ✗ bare_submodule_import_call: rc=0 stdout='0\n'
    Results: 7 passed, 1 failed

`test_link_mode.py:110`. The case builds

    pkg2/base2.py:  def doubleval(x): return x * 2
    pkg2/main.py:   from . import base2 ; print(base2.doubleval(21))

and requires `stdout == '42'`. It gets `0` — the shape of the bug it was written
to prevent (`bugs/CODEGEN_link_mode_module_qualified_call_silent_wrong_value.md`,
"now fixed and removed"). The binary links, runs, and exits 0.

## What was ruled out

| hypothesis | test | result |
|---|---|---|
| my `formal/` diff | worktree at `HEAD~1` + my six `formal/` files, full file run | **8 passed, 0 failed** |
| a stale module cache | fresh `TMPDIR` | still fails |
| stale `build/` | `build/` moved aside, recreated | still fails |
| stale `__pycache__` | all of them removed | still fails |
| the new test file | `test_formal_globals.py` copied into the passing worktree | still **8 passed** |
| the test itself | `git diff HEAD~1 HEAD -- test_link_mode.py` | byte-identical |

`diff -rq` between the failing tree and the passing one (excluding `.git`,
`__pycache__`, `build`, `bugs`, `*.o`, `*.ci`) leaves exactly three entries:
`TASK.md`, `work.log` and `tools/suite.py`. The first two cannot matter; the
third is this branch's registry addition and is inert to this test.

The single-case run is the other half of the shape and is worth stating, because
it is what makes this confusing: `test_bare_submodule_import_call()` called
alone passes **3/3** in the same tree where the whole-file run fails **3/3**.
So it is not the case in isolation — something a *previous* case in the file
leaves behind does it.

## What is left

State leaking between cases inside one `test_link_mode.py` process. The
earlier cases in the file build their own packages into `tempfile` directories,
so the candidate is whatever the compiled pipeline writes OUTSIDE one: a module
cache, a symbol table, or a directory the link-mode path derives from the
process's cwd (`test_link_mode.py:45`).

## Next step

1. Bisect the eight cases in the file by running prefixes of `main()` under the
   failing tree until a prefix reproduces the single-case failure. That names the
   culprit directly and is one run per prefix.
2. Whatever the prefix's last build leaves behind is the thing to clear between
   cases — most likely a content-addressed module cache keyed on something that
   does not include the package name, so two cases build the same key and the
   second gets the first's object.
3. Re-run `make check` twice. A leak like this is order- and timing-sensitive,
   so one green run is not evidence; two is.

Do this before trusting any further `make check` result from this worktree: a
gate that flips on state from an earlier case cannot distinguish a real
regression from the leak.
