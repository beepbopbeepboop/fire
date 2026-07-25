# CODEGEN: two top-level `def NAME(...):` under mutually-exclusive `if`/`else` branches collide

## Repro

```python
import sys
if sys.platform == 'win32':
    def wait(x):
        return x + 1
else:
    def wait(x):
        return x + 2

def f():
    print(wait(5))
f()
```

- `python3 mojo.py run repro.py` (interpreter): correct — prints `7` (the
  `else` branch's definition, since that's the one actually executed on
  this platform).
- `python3 mojo.py build repro.py -o out`: fails to compile:
  ```
  repro.py:11:9: error: conflicting types for 'wait'; have 'int64_t()' {aka 'long long int()'}
  ```

Real stdlib trigger: `Lib/multiprocessing/connection.py` defines
`def wait(object_list, timeout=None):` twice at module level — once inside
an `if sys.platform == 'win32':` block (~line 1086) and once inside the
matching `else:` (~line 1176), each providing a platform-specific
implementation of the same public module function. This is a common,
legitimate Python idiom for platform-conditional top-level function
definitions (`bugs/COMPILE_FAIL_multiprocessing_connection.md`).

## Root cause

Real Python resolves this naturally at runtime: whichever `if`/`else`
branch actually executes is the only one that runs its `def` statement,
rebinding the module-level name `wait` to that one function object — the
other branch's `def` never executes, so there's only ever one `wait` in
scope at a time.

This compiler's codegen path appears to compile EVERY top-level `def`
statement it finds into a distinct top-level C function, regardless of
which conditional branch (`if`/`elif`/`else`) it's textually nested inside
— so both `def wait(x):` bodies get lowered into C functions that both want
the same top-level (unmangled, since it's a module-level function, not a
method) C symbol name `wait`, causing a redefinition/conflicting-types
error at the C level. The interpreter path is unaffected because it
naturally only ever registers whichever branch's `def` statement actually
executes, matching real Python semantics.

## Suggested fix

Not yet planned — needs investigation into how `gimple_codegen.py` currently
discovers/enumerates top-level function definitions to compile (does it
walk the whole module body unconditionally regardless of surrounding
`if`/`else` nesting, or does it already have some notion of "which branch
is live"?). Given real code commonly uses this exact idiom for
platform-specific implementations of the same function name, a reasonable
fix direction: when compiling top-level functions, either (a) mangle
functions found inside conditional branches distinctly per-branch and have
call sites dispatch based on the same condition (matching real semantics
exactly, but potentially complex), or (b) since this codegen already
falls back to interpreting modules it can't fully compile (the documented
"skip module, fall back to source" mechanism referenced in CLAUDE.md), a
simpler and likely acceptable interim stance might be picking a single
"winning" definition using some fixed, deterministic rule (e.g. last one
wins, matching sequential top-to-bottom module execution when only one
branch is taken) — investigate which of these directions best fits how
this codegen already handles similar control-flow-dependent top-level
constructs elsewhere, and use judgment on scope vs. correctness per
CLAUDE.md ("never pick the simple/quick fix... pick the production-quality
approach") balanced against not over-engineering a narrow real-world case.
