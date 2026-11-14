# A function-body `from X import Y as Z` binds `Z` when `Y` is a class (part 2)

Part 2 of 5 of `bugs/hard/GATE_red_recover-land_2026-11-02.md`. Class: easy —
one registration in `_gen_stmt_FromImportStmt`, reusing the existing
`_register_imported_symbol` / `_resolved_export_entry` path. This is the parent
doc's `MojoParser` stub.

## Measured (2026-11-13, this tree)

    # m.py
    class Thing:
        def __init__(self, v):
            self.v = v
    # u.py
    def f():
        from m import Thing as Alias
        t = Alias(3)
        print(t.v)
    f()

`compile_to_gimple(u_src, do_imports=True, filename=<u>)` emits one weak stub
named `Alias` (the binary happens to print `3` because `Alias(3)` was also
resolved via the constructor path, so the stub is dead here — but it matches
the gate's `unavailable in compiled mode` reject and it is the name the parent
doc's closure dump reported). The same alias used as a VALUE is not merely
dead:

    def f():
        from m import Thing as Alias
        g = Alias
        print(g)

compiled prints `<function Alias at 0x…>`; CPython prints
`<class 'm.Thing'>`.

The failure is specific to a **function-body** import:
`from m import Thing as Alias` at module level compiles clean, and a
function-body import of a *function* alias compiles clean too (both measured).
`myinterpreter.py:5255` is the real case:
`from fire_compiler import py_tokenize, Parser as MojoParser`, then
`self.scope.define('Parser', MojoParser)` — a class alias imported inside a
function body and used as a value.

## Goal

`_gen_stmt_FromImportStmt` (in `mojo/backend_gimple/emit_funcs.py:300`) registers
the alias under the ALIAS name with the imported name's real identity — for a
class, the same class-value representation a direct class reference gets today
(whatever `class-as-value` currently lowers to; see "Not this part"), and for a
function, the defining function's signature/home — so that

- `Alias(...)` lowers exactly as `Thing(...)` would,
- `g = Alias` is not a call to a weak stub, and
- a later call through `g` is at least the same code the direct spelling gets.

Register the alias as well as the original name; do not rename the original
(the two coexist in one body: `from m import Thing, Thing as Alias`).

## Acceptance

- The constructor probe compiles with zero `unavailable in compiled mode` and
  prints `3`, exit 0.
- The value probe compiles with zero stubs, and `print(g)` prints the same
  class-value text the direct name `Thing` prints in the same program (add
  both prints to the test, so a future class-value change cannot silently
  re-diverge them).
- The existing function-alias shape (`from m import helper as alias; alias(1)`)
  stays green — no regression in the module-level spelling, no double
  definition of `helper`.
- `from m import Thing, Thing as Alias` binds both names in one body.

## Done when

File: `test_function_body_alias_class_import.py` (repo root; created by this
part).

Command: `python3 test_function_body_alias_class_import.py`

It writes `m.py` and the probe module under `$TMPDIR`, compiles with
`do_imports=True`, asserts zero `unavailable in compiled mode`, builds with
`build_config.find_gcc()` and compares stdout with CPython's for both the
constructor and the value spelling. Red today: 1 stub in each probe, and the
value probe prints `<function Alias at 0x…>`.

## Where to start

- `mojo/backend_gimple/emit_funcs.py:300` `_gen_stmt_FromImportStmt` — the
  per-name loop; the class case currently falls through to the bare
  no-signature registration tail.
- `gimple_codegen.py:5078` `_register_imported_symbol` (takes
  `original_name`), and `_resolved_export_entry` /
  `_local_sibling_module_exports` for the defining module's entry.
- `myinterpreter.py:5255` — the real `MojoParser` case that must compile.

## Not this part

- `class-as-value` in general is a pre-existing, separately documented feature
  gap (see `emit_exprs.py:2317-2324`). Measured today on this tree:
  `k = A; print(k); k(7)` in one module prints `65` and then dies with
  `Bus error: 10` (exit 138) where CPython prints the class and `7`. Part 2
  only removes the weak stub and makes the alias agree with the direct
  spelling; it does not build a class-object model.
- `issubclass` is part 4.
