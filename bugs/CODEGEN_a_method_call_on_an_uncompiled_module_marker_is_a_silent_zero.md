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

## Status (2026-10-04, `work/bugs6-1`): the SILENT half is gone for good and
## the `math` members are FIXED; what is left is `signal`, the constants, and
## the census

The silent half was already closed before this branch started —
`work/bugs4-9`'s argparse fix routes ANY method call on an uncompiled module
marker through `mojo_module_not_compiled`, which raises. Measured on this
branch's base, every member below raised.

**`math.<fn>` now works** (`_MODULE_MEMBER_LIBC` in
`mojo/backend_gimple/emit_methods.py`, consulted by `module_member_libc` at the
marker site before the raise). `<math.h>` is already in every generated
preamble and `_LIBC_SIGS` already pinned most of these symbols for argument
coercion, so the call is a libc call wearing a module's name and lowering it
as one is the whole implementation. 28 members, measured against CPython:

    math.floor(1.5) 1     math.sqrt(2) 1.4142135623730951
    math.ceil(1.2)  2     math.fabs(-2.5) 2.5
    math.trunc(-1.7) -1   math.pow(2, 10) 1024.0
    math.floor(-1.5) -2   math.hypot(3, 4) 5.0
    math.log10(1000) 3.0  math.copysign(3, -1) -3.0

`floor` / `ceil` / `trunc` are the only three that are NOT a plain rename, and
the table says so: Python's return an `int` and C's return a `double`, so each
carries a truncate flag or `print(math.floor(1.5))` prints `1.0`. The cast
goes through a temp — a cast applied inline to a call's own operand is
`invalid operand in unary operation` under `-fgimple`, the same constraint
`Span(<list>)` and a nested cast work around elsewhere in this tree.

Pinned by `test_gimple_runner.py`'s `gimple_math_module_members_lower_to_libm`
(the negative, `gimple_math_non_libm_member_still_raises`, is `math.gcd`: an
INTEGER member that is not libm at all, and the honest answer for it is still
the named raise, which is why the table's absence is a decision rather than a
gap).

### What is deliberately NOT in the table, each for its own reason

* **A module CONSTANT** (`math.pi`, `math.e`). It is a value, not a call, and
  reaches a different site — an attribute read, which still raises
  `AttributeError: pi`. A constant needs its own mechanism, not a lowered call.
* **The INTEGER members** (`math.gcd`, `math.factorial`, `math.comb`): not
  libm at all.
* **Anything with a non-libm implementation.** A member absent from the table
  is a named failure, which is the correct answer for a member it cannot
  honour.
* **`signal.signal` / `signal.SIGTERM`** — unchanged, and still the one member
  that wants its own decision rather than a drive-by. `SIGTERM` is already
  genuinely fixed; the CALL needs a handler registration and a dispatch table
  in the runtime, which is a feature.

## The next step, exactly

Per member, in the same shape `os` already uses, and each one is small:

1. ~~**`math.floor` / `ceil` / `sqrt` / `fabs` / `pow` …**~~ — DONE, at the
   marker site rather than in `ast_rewriter` (which would have had to know the
   member table anyway, and the marker check already runs there). The rewrite
   the original text proposed is the same shape and reaches the same place.
2. **`signal.signal`** — needs a real handler registration and a dispatch table
   in the runtime, which is a feature rather than a rewrite, so this one wants
   its own decision.
3. **A corpus sweep to size what is left.** This is now the whole of the
   remaining work on this doc, and the table it should produce is smaller than
   the one above: for every `import M` in `Lib/`, the `M.<lowercase>` members
   the tree calls, checked against `_MODULE_MEMBER_LIBC` (now the only source
   of truth for "a member of an uncompiled module that WORKS") and against the
   compile-time-handled table. The deliverable is the list of what still
   raises, which is a named failure for each of them rather than a silent 0 —
   so the sweep is a census of `mojo_module_not_compiled` messages, and
   `compile_stdlib.py`'s per-file stderr is where to read them.
4. **The original step 1**, kept for the record and now narrower:
   `compile_stdlib.py`'s per-file errors and `test_abi_full.py` /
   `test_py314_full.py` are where "a stdlib call that silently returned 0"
   would have shown up as a *passing* file with wrong output, which no existing
   harness compares. With the silent half closed, every remaining member is a
   named raise, so the same sweep reads off the messages instead of needing a
   CPython comparison per member.

## Coverage

* `test_gimple_runner.py`'s `gimple_module_marker_call_raises` and
  `gimple_module_marker_call_is_catchable` cover the LOUD half (argparse).
* `gimple_math_module_members_lower_to_libm` and
  `gimple_math_non_libm_member_still_raises` cover the member table in both
  directions: every member it names answers CPython, and a member it does not
  still names itself.
* The original note that "prints 0 and exits 0" is indistinguishable from
  correct without a CPython comparison still stands, and it is why the new rows
  are compile-and-EXECUTE rows with CPython expected strings rather than
  `test_gimple.py` shape checks. `test_interp_oracle.py` remains the suite whose
  job this whole family was.