# CODEGEN: a method call on a bare-imported module this compile cannot resolve is a silent 0

**Found 2026-10-02 by `bugs4-9` while fixing
`bugs/RUNTIME_argparse_is_stubbed_so_parse_args_consumers_crash.md`.** That fix
made the *marker* case raise; this doc is the residue, and it is a family, not
a case.

## What was run

```python
import math
def main():
    print(math.floor(1.5))
main()
```

| | output | exit |
|---|---|---|
| `python3` | `1` | 0 |
| compiled, before the argparse fix | `0` | **0** |
| compiled, after it | `NotImplementedError: math.floor: module 'math' is not compiled into this binary` | 1 |

The middle row is the bug. `import math` binds a module MARKER (an `int64_t`
global initialised to 0, because `module_loader.can_resolve_module_path('math')`
is false on this checkout — there is no source under its `STDLIB_PATH`), and
`math.floor(...)` reached `mojo/backend_gimple/emit_methods.py`'s generic scalar
passthrough, which returns the receiver unchanged. So the call "succeeded", the
program printed `0`, and it exited 0.

`signal.signal(2, print)` was the same shape and printed `1`.

## Why this is not a crash and is therefore worse than one

A segfault is loud. This is a program that runs to completion, exits 0, and
prints a plausible number. Every check that is not a value comparison — an exit
code, a smoke test, "does it print something" — passes. `test_runtime_diff.py`
misses it by construction (both engines are wrong the same way), and
`test_interp_oracle.py` sees it (it diffs against CPython), which is how the two
real interpreter bugs CLAUDE.md records were found.

## Scope: it is now loud, and that is deliberate

`work/bugs4-9`'s argparse fix routes ANY method call on an uncompiled module
marker through `mojo_module_not_compiled`, which raises. `math.floor` and
`signal.signal` are therefore named failures rather than silent wrong answers
now. **That is the intended end state for this doc too** — the remaining work is
not "make it loud" but "make it work", member by member.

`os` is NOT in this family and is the reason the fix is safe to make general:
ast_rewriter rewrites the `os` surface (`os.environ`, `os.path.*`,
`os.sep`, …) before `_lower_method_call` ever sees it, so `os.getcwd()` still
works and is untouched.

## The next step, exactly

Per member, in the same shape `os` already uses, and each one is small:

1. **`math.floor` / `ceil` / `sqrt` / `fabs` / `pow` …** — pure libm. There is
   already a `_LIBC_SIGS` table (consulted by `_emit_call`'s argument coercion
   and by the self-emitted extern/prototype), so the work is an
   `ast_rewriter`-level rewrite of `math.<fn>` onto the libm symbol, the same
   mechanism `os.path.isdir` and `os.unlink` already use. Start with
   `math.floor`/`ceil`/`sqrt` and measure.
2. **`signal.signal` / `signal.SIGTERM`** — the `SIGTERM` half is already
   genuinely fixed (the emit_exprs comment about `signal` records the earlier
   mix-up with a real zero-arg function of the same name); the CALL is not.
   `signal.signal` needs a real handler registration and a dispatch table in
   the runtime, which is a feature rather than a rewrite — so this one wants its
   own decision, not a drive-by.
3. **A corpus sweep to size the family.** `compile_stdlib.py`'s per-file errors
   and `test_abi_full.py` / `test_py314_full.py` are where "a stdlib call that
   silently returned 0" would show up as a *passing* file with wrong output,
   which no existing harness compares. A cheap first pass: for every
   `import M` in `Lib/`, list the `M.<lowercase>` members the tree calls, and
   check each against `_LIBC_SIGS` / the `os`-style rewrite table. The list is
   the deliverable even if none of the members are fixed yet.

## Coverage

* `test_gimple_runner.py`'s `gimple_module_marker_call_raises` and
  `gimple_module_marker_call_is_catchable` cover the LOUD half (argparse).
* Nothing covers the silent half, because "prints 0 and exits 0" is
  indistinguishable from correct without a CPython comparison — which is
  `test_interp_oracle.py`'s job, and the reason a family like this can sit
  unnoticed. The right regression test for any member fixed under this doc is a
  `test_runtime_diff.py` case (which has CPython as a third opinion), not a
  `test_gimple.py` shape check.