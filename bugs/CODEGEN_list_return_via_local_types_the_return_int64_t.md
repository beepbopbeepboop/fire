# BUG: a function that returns a `MojoList *` it built in a local is typed `int64_t`, so the caller prints the pointer's address and iterating it SEGFAULTS

**State: OPEN — not fixed, no code change.** Found 2026-09-29 while
working `bugs/hard/CODEGEN_struct_kwargs_and_inline_unpack.md`; it is a
different subsystem (return-type inference, not `struct`) and is left for
whoever owns that.

## What I ran

On the branch `work/hard-struct-kwargs` at `10023b8` (master's tip at the
time), via `gimple_codegen.compile_to_gimple` + `gcc -fgimple` +
`runtime/fire_runtime.c` (the `.tmp/probe.py` harness this session used —
reproduce with `python3 fire.py build` on the `.mojo` sources below, or
copy them into a `test_gimple_stdout` case):

    fn f() -> DynamicVector:
        var t = struct.unpack('<HH', b'\x04\x00\x05\x00')
        return t

    fn main():
        var b = f()
        print(b)
        print(b[0])
        for y in b:
            print(y)

## What I saw

    4308150016        <- CPython: (4, 5)
    4
    [exit -11]        <- SIGSEGV in the loop; CPython: 4 / 5

Confirmed pre-existing, not a regression: the same program compiled from
`10023b8` in a scratch `git archive` of that commit behaves identically.
It is also NOT `struct`-specific — the same crash comes from an ordinary
list, with or without a return annotation:

    fn f() -> DynamicVector:
        return [1, 2, 3]

    fn h(x: Int) -> DynamicVector:
        var r = [x, x + 1]
        return r

    fn main():
        var b = f()
        print(b)
        for y in b: print(y)
        var c = h(7)
        print(c)
        for z in c: print(z)

    4384512224
    [exit -11]

A direct `return <container call>` is FINE — `def f(): return
struct.unpack(...)` types its return as `MojoList *` and prints
`(7, 0.5)`. It is specifically **a local, bound from a container-producing
call, then returned by name**.

## Mechanism (as far as I traced it)

`mojo/middle/infra_infer.py`'s `_infer_return_type_core` joins the types
`_collect_return_types` infers for each `return` expression, and a bare
`IdentExpr` in a `return` is typed through `gen.var_types`. That table is
seeded for return inference by `_container_literal_locals`
(`infra_infer.py`), whose own docstring is explicit about why this matters:

> a container is a real pointer, so guessing wrong is not a small
> imprecision but a pointer coerced through a scalar slot … a caller that
> treats the value as a scalar gets an address.

Two gaps in that seed, both reachable from the repro above:

1. **Only `AssignStmt` targets are considered** — `note()` does
   `isinstance(n, gimple_ctypes.AssignStmt)`. `var t = <call>` parses as a
   **`VarDecl`**, so the local is invisible to the seed and the `return t`
   falls through to the `int64_t` default.
2. **Only container LITERALS are recognised** —
   `_CONTAINER_LITERAL_CTYPES` maps `ListExpr`/`TupleExpr`/`DictExpr`/
   `SetExpr`, and `note()` adds a string literal. A local bound from a CALL
   whose registered return type is already a container pointer
   (`gen.func_return_types[callee] == 'MojoList *'`) is not, so even the
   `AssignStmt` spelling misses.

The consequence downstream is a cascade, not one bad signature. With
`func_return_types['f'] == 'int64_t'`:

* the call site types the result `int64_t` and records no
  `_actual_types[... ] = 'MojoList *'`, so `print(b)` falls to the generic
  numeric path and sprintf's the pointer (`printf_fmt('int64_t')` is `%ld`)
  — the address as a decimal, exit 0;
* `b[0]` happens to work, because the subscript branch coerces a boxed
  `int64_t` to `MojoList *` before calling `mojo_list_get_int`;
* `for y in b` is the crash: `_gen_for_iter`'s
  `mojo_is_registered_dict`/`_list` dual dispatch has neither a real type
  nor a tracked element type for `b`, so the generated C declares `y` as
  `char *` and walks a `MojoDictIter` over a `MojoList`.

## Why this is worth more than its "print the address" surface

The `print` half is a silent wrong value with exit 0 — the class
`bugs/hard/` exists for. The `for` half is a **segfault**, which is worse
than either of the two failure modes CLAUDE.md's rules rank above it, and
it fires on an ordinary `[1, 2, 3]` return, not on an exotic shape. Real
library code returns lists from helpers constantly.

## Exact next step

In `mojo/middle/infra_infer.py`:

1. make `note()` accept a `VarDecl` target the same way it accepts an
   `AssignStmt` one (first-binding-wins, same rule), and
2. add a case for a local bound from a `CallExpr` whose callee is in
   `gen.func_return_types` with a container pointer return type.

Then check the blast radius before landing it: this changes the C
signature of every such function, and CLAUDE.md's rule for a change that
is supposed to be behaviour-preserving asks for byte-identical generated C
on a large succeeding case — which this will NOT be, so the gate's
`stdlib-dylib` skip count and `stdlib-syntax` unexpected-failure count are
the two verdicts to read, not just the exit code. There is already a
`test_gimple_runner.py` case for the WORKING direct-return shape
(`gimple_struct_ctor_result_returned_from_function`) to extend, and that
file runs in **no `tools/suite.py` bucket** (see the note in
`bugs/hard/README.md`), so it will not catch a regression on its own.

Note for whoever takes it: `bugs/hard/CODEGEN_struct_kwargs_and_inline_unpack.md`
covers the per-slot-kinds mechanism, and its cross-function half
(`_return_maybe_kinds` in `mojo/backend_gimple/module_gen.py`) is
ALREADY in place and correct — `def f(): return struct.unpack('<if', b)`
round-trips a mixed format through a function boundary, boxed reads
included. The fix here is not needed for that; it is needed for the
`var t = …; return t` shape, where the return type never becomes
`MojoList *` in the first place.
