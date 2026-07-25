# CODEGEN: a top-level `def` nested inside module-scope `if`/`else` is never actually compiled (link error)

## Background

Found as a side discovery while fixing `bugs/CODEGEN_conditional_toplevel_def_name_collision.md`
(commit `2577b4f`). That fix only addresses the case where the SAME
function name is defined in more than one sibling conditional branch (now
an honest, clean refusal-to-compile instead of a confusing C-level symbol
clash). This is the broader, still-open underlying gap that fix
deliberately did NOT attempt: even a SINGLE, non-duplicated top-level
`def` nested inside a module-scope `if`/`elif`/`else` is silently never
compiled at all.

## Repro

```python
import sys
if sys.platform == 'darwin':
    def greet():
        return "hi"

def f():
    print(greet())
f()
```

- `python3 mojo.py run repro.py` (interpreter): correct.
- `python3 mojo.py build repro.py -o out`: compiles "successfully" (no
  gcc error) but FAILS TO LINK: `Undefined symbols ... _greet` — the
  function body was never emitted at all.

## Root cause

`gimple_codegen.py`'s `gen_module` pre-passes (the module-level closure
scan, and the loop that calls `gen_func` on each top-level `FunctionDef`)
only ever walk *direct* top-level statements in the module's `stmts` list —
they never recurse into `IfStmt.then_body`/`.elifs`/`.else_body` looking
for nested `def`s. So a `def` inside a module-level `if`/`else` is never
recognized as a top-level function to compile at all. When something later
calls it, `_gen_stmt_FunctionDef`'s closure-based lowering path finds no
pre-pass `ClosureInfo` for it and just emits a
`/* TODO: closure 'NAME' (no pre-pass info) */` comment — i.e. the
function body is silently dropped — and the call site falls back to
emitting a bare `extern`-style declaration with no definition anywhere,
which then fails at LINK time (not compile time) with an undefined-symbol
error.

## Impact

Platform-conditional top-level function definitions (`if sys.platform ==
...: def f(): ... else: def f(): ...`, or even a single conditionally-defined
helper with no `else`) are a common real-world idiom — this is likely
affecting many real stdlib files with conditional top-level defs.

## Suggested fix

Needs its own investigation/design, not a quick patch: `gen_module`'s
top-level-function discovery needs to walk INTO module-level conditional
blocks (recursively, matching however deeply Python allows nesting
`if`/`elif`/`else` at module scope) and register any `def` found there as
a real top-level function to compile — presumably by hoisting it out to a
normal top-level C function (mangled distinctly if the same name recurs
across sibling branches, which is exactly the collision case
`2577b4f` now detects and refuses rather than silently mishandles). The
harder part is likely at CALL sites and at whatever decides which
conditional branch is "the one that runs" for a compiled (not interpreted)
program — real Python resolves this via whichever branch's `if` condition
is actually true at runtime, so a fully faithful compiled implementation
would need to either evaluate the condition and dispatch, or (if the
condition is itself resolvable at compile time, e.g. `sys.platform`, which
this compiler might already special-case elsewhere for other purposes —
worth checking) pick the correct branch statically for the target platform.
