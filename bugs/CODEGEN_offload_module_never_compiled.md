# `mojo/middle/offload.py` has never been compiled — it was being silently dropped

**Status: OPEN, unfixed.** Found 2026-10-01 while merging `origin/master`
into the branch that had fixed the self-host build.

## What happened

`mojo/middle/offload.py` is the metal branch's GPU-offload pass — loop
fusion, GEMM recognition, per-buffer launch lengths, ~2000 lines. It is in
`mojoc`'s own compile closure. It compiled cleanly for a long time, and it
compiled **nothing**: `mojo/backend_gimple/module_gen.py` has a local named
`_lens` that is a `dict` in one function and a `set` in another, the compiled
path froze the name as the set, and `module_gen`'s own compile raised. The
exception destroyed the code `module_gen` had already inlined — which
included all four GPU modules — while their `_sub_toplevels` registrations
survived. So the closure carried four forward declarations and no bodies, and
`fire1` failed at LINK naming four modules that had never failed at anything.

Both halves are fixed (see
`bugs/CODEGEN_module_toplevel_undefined_in_selfhost.md`). Fixing them put
`offload.py`'s code into the closure for the first time, and it does not
compile.

## The three errors

    offload.py:1621:9: error: '_t32' undeclared (first use in this function)
    offload.py:1747:8: error: assignment to 'int64_t' from 'int64_t *'
    offload.py:1747:15: error: assignment to 'int64_t *' from 'int64_t'

Two shapes.

**1. `_t32` undeclared**, inside the module-level GENERATOR `_walk_stmts`
(`offload.py:1607`), in this loop:

    for attr in ('body', 'then_body', 'else_body', 'elifs', 'args',
                 'operands', 'left', 'right', 'value', 'target'):
        child = getattr(x, attr, None)

A loop temp is used with no declaration line emitted for it. The same shape
— `for x in <tuple literal of strings>` — compiles fine outside a generator
body, so this reads as a generator-body lowering gap rather than a general one.
`_walk_stmts` is also never lowered to an A3 `__mgco__*_body`: there is no
such symbol in the generated C, so it takes a different route whose
per-function temp declarations are incomplete.

**2/3. `fusable`'s return type is inferred two ways.** One function, both
directions of one assignment reported, so the two sides disagree:

    def fusable(st) -> 'gctypes.ExprStmt | None':      # a STRING annotation
        if <not fusable>: return None
        ...
        return gctypes.ExprStmt(...)                   # a struct construction

    def walk(items) -> list:
        for st in (items or ()):
            fused = fusable(st)                        # line 1747

`ExprStmt *` and `int64_t` for the same callee. `walk` is itself a closure
inside `rewrite_gemm`, and `fusable` is a closure inside that, so this is a
nested-closure return-type inference question, not a flat one.

## Why this matters more than three errors

The failure mode was invisible in the most expensive way available: the
module that owns GPU auto-offload was absent from the compiler, every
Metal/GPU benchmark still passed (they run through the python-hosted path),
and the only symptom was a link error pointing at four innocent modules.
Anything that reads `fire1`'s behaviour and not its build log would have
concluded the offload pass was there.

The general lesson, which is the one worth keeping: a shared list that the
emitter reads at the END to write declarations must be part of the failed
attempt's rollback. `module_gen._sub_toplevels` was not, and the gap turned
one module's compile error into four modules' link errors. That is fixed.

## Next step

Two independent questions, in the order they are cheaper:

1. the generator-body temp declaration (`_t32`), since an undeclared
   identifier is a codegen bug rather than a modelling gap and the shape is
   narrow;
2. `fusable`'s return type — whether a STRING annotation naming
   `gctypes.X | None` resolves for a closure nested two deep, and whether the
   `None` branch or the struct-construction branch is the one that should
   win.

Until both are answered, `mojoc` built from this closure either fails to
build (with the fix) or silently lacks the offload pass (without it). The
first is the correct state; do not trade it back.

## Where

* the module: `mojo/middle/offload.py` — `_walk_stmts` (line 1607),
  `fusable` (line 1718), the `fused = fusable(st)` call (line 1747)
* the masking bug and its two fixes:
  `bugs/CODEGEN_module_toplevel_undefined_in_selfhost.md`,
  `mojo/backend_gimple/module_gen.py` (the `_lens` pair),
  `mojo/backend_gimple/emit_resolve.py` (`_compile_imported_module`'s
  rollback)