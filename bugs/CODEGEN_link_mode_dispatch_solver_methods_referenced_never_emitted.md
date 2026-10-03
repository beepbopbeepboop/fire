# Link mode: a struct method reached through a TRANSITIVELY imported module is auto-stubbed as `int64_t f (...)`, and the real definition then conflicts

**State: the reported symptom is FIXED and it was not the one in the title.
Found 2026-10-02 on `work/master-selfhost-fix3` at 797e97c1, while fixing the
self-host closure's three `gcc` errors in `mojo/middle/offload.py` (that work
is done; see `git log --oneline e3779dba..HEAD`). Diagnosed and fixed
2026-10-02 on `work/bugs4-3-c`.** Pre-existing: nothing in that branch touched
`mojo/middle/solvers.py`, struct-method emission, or link mode.

Same FAILURE MODE as the two `<module>_toplevel` families that were in the
now-deleted `bugs/CODEGEN_module_toplevel_undefined_in_selfhost.md` (deleted
2026-10-02 with both fixed): a symbol the closure declares and calls, with no
matching definition anywhere in the link. A different symbol set, a different
module and a different entry point.

## What the report said, and what is actually there

The original report is kept verbatim below because its *fixture* is the
expensive part and the cheap part is what turned out to be wrong. Its
conclusion — "the emission side drops the METHOD BODIES of a struct whose
layout and forward declarations it emitted" — does not hold. What the root
emits for a struct method that the DEFINING module also emits is a *bare
variadic forward declaration*, and the definition is present:

    int64_t lm_helper_Thing_show (...);                          <- the ROOT's auto-stub
    int64_t lm_helper_Thing_show (Thing *);                      <- forward decl
    int64_t __GIMPLE lm_helper_Thing_show (Thing * self) { ... } <- the real body

A variadic declaration and a typed definition of the same symbol are a hard
compile error, not a missing body:

    lm/helper.py:4:9: error: conflicting types for 'lm_helper_Thing_show';
        have 'int64_t(Thing *)' {aka 'long long int(Thing *)'}
    lm/main.py:377:9: note: previous declaration of 'lm_helper_Thing_show'
        with type 'int64_t()' {aka 'long long int()'}

## The cheap reproduction (no whole-closure compile needed)

The original report needed `driver.compile_program` over a program importing
`fire_compiler` — the compiler's own source, which is the expensive way to ask
this question. Three modules reproduce it in under a second:

    # lm/helper.py
    class Thing:
        def __init__(self, value):
            self.value = value
        def show(self):                 # a NON-DUNDER method, see below
            return self.value

    # lm/mid.py
    from lm.helper import Thing
    def make(n):
        return Thing(n)

    # lm/main.py
    import lm.mid
    def main():
        t = lm.mid.make(7)
        print(t.show())
    main()

    driver.compile_program(lm/main.py, <its text>, output=prog, run=False)

`lm/__init__.py` empty. Before: rc != 0, `conflicting types` on every call
site. After: rc 0, the binary prints `7`, matching CPython.

Both properties are load-bearing, and a `__init__`-only or a two-module
fixture would have proved nothing:

* **three modules deep.** The root's call site is lowered before the defining
  module is inlined into the same translation unit, so neither of the auto-
  stub's two `func_return_types` lookups can answer "this method WILL be
  defined here" — measured at the call site, neither `lm_helper_Thing_show`
  nor `Thing_show` is in `func_return_types` yet.
* **a non-dunder method.** `__init__` goes through a different mangling path
  (`lm_helper_Thing___init__`) and was already fine.

## Cause

`emit_methods.py`'s struct-method auto-stub emits
`#ifndef _MOJO_STUB_<Struct>_<method> / #define _MOJO_STUB_<Struct>_<method> /
int64_t <mangled> (...); / #endif` into `_elaborated_externs`, and its
condition asks only `func_return_types` / `_KNOWN_SIGS` / `_auto_stubbed`.

The guard is defined BY the stub, so nothing can suppress it afterwards — and
the struct-typedef pass's own guard is `_MOJO_STUB_<Struct>` (no method name),
so it could never have suppressed this one either. The stub's own comment
describes the gap it was written for ("a same-struct call from one overload's
body into a not-yet-processed sibling overload only has the bare key available
at this point, since the suffixed key is only set when THAT overload's own
definition is emitted"); the answer is that the question is not about keys at
all, it is about whether a StructDef with this method exists in this
translation unit.

## The fix

One more condition on the auto-stub, and it is the table that already answers
the question: `_struct_method_names[struct_name]` holds the methods of every
StructDef registered in this compile (shared with every nested temp_gen, so a
transitively imported module's struct answers for a root call site), and
`gen_module_impl`'s StructDef arm emits one body per method of every StructDef
in its statements. So "this method is in that table" and "this TU emits the
body" are the same statement.

`_emitted_structs` is NOT the table for this and a first attempt using it was
wrong: it is populated by the struct-typedef pass, which runs AFTER function
emission, so it is still empty at the call site. Measured: with
`_emitted_structs` the stub was emitted unchanged.

## Verification

* `test_link_mode.py` 16/0, the new case being
  `transitive_struct_method_is_not_variadic_stubbed` (16 before it: 15 + 1).
* `test_gimple.py` 372/0, `test_gimple_runner.py` 308/10 with the same nine
  failing NAMES as before the change, `test_gimple_generator_runner.py` 380/0.
* self-host closure `.ci`: 13 distinct gcc errors before, 13 after, none
  added and none removed.

## The original report, verbatim

Kept because the fixture is the expensive half and the *shape* of the closure
it needed is a real datapoint for whoever asks the next question here.

### What I ran

A two-file program compiled through `driver.compile_program` (LINK mode,
`do_imports=True` + `link_imports=True`), where the root imports
`fire_compiler` — i.e. the compiler's own source as a compiled program's
closure:

    # helper.py
    class Thing:
        def __init__(self, value):
            self.value = value

    class Alias:
        def __init__(self, value):
            self.value = -1

    # prog.py
    import helper as h

    def build(n):
        Alias = h.Thing
        node = Alias(value=n)
        print(node.value)
        return node.value

    def main():
        build(7)

    main()

    driver.compile_program(prog, src, output=exe, run=False)

### What I saw

`compile_program` returns `None`: the generated C compiles (0 gcc errors)
and the LINK fails.

    link failed: Undefined symbols for architecture arm64:
      "_mojo_middle_solvers_DispatchSolver__emit", referenced from:
          _mojo_backend_gimple_emit_stmts__with_emit_exits_902184 in 66016b3.o
      "_mojo_middle_solvers_DispatchSolver__emit_call", ... (same)
      "_mojo_middle_solvers_DispatchSolver__new_temp", ...
      "_mojo_middle_solvers_DispatchSolver__signature_ctypes", referenced from:
          _mojo_backend_gimple_emit_funcs__local_def_pts_751315 in 66016b3.o
      "_mojo_middle_solvers_DispatchSolver__struct_method_csym", ...

### What I confirmed about it

In the generated `client.c` (45 MB, saved from the failing run):

- `typedef struct DispatchSolver {` IS emitted (line ~1922), so the struct
  itself was registered;
- `int64_t mojo_middle_solvers_DispatchSolver__emit (...);` IS declared
  (line ~1025646) and IS called (lines ~1090189, ~1090430) — five
  references;
- there is NO definition anywhere in the file.

So this is the emission side dropping the METHOD BODIES of a struct whose
layout and forward declarations it emitted, in link mode, for a module
reached transitively (`mojo/middle/solvers.py` is four levels down:
`fire_compiler` -> ... -> `gimple_codegen` -> `mojo/middle/solvers.py`).
The same closure compiled through `compile_to_gimple(do_imports=True)`
(the `selfhost` / `mojoc` / `bootstrap-stage2-cc` path) DOES define them,
which is why the self-host jobs are green and this only shows up through
`driver.compile_program`.

### Its own proposed next step

`gen_module_impl`'s struct-method emission loop, in the link-mode
(`link_imports=True`) configuration: compare the set of `ci.methods` /
`_struct_method_overload_ids` entries it walks against the
`_all_closures` / `_method_mangled_names` marks for a transitively
imported module, and find where a method that reached the forward-
declaration pass is dropped before the body pass.

**Superseded**: nothing is dropped, and the cheap fixture above is where the
answer was. What this section still contributes is the "link mode only"
fact — the same closure through `compile_to_gimple(do_imports=True)` is fine,
because with `do_imports=True` and no `link_imports` the root's own
preamble is assembled after the imported modules' code, so the auto-stub's
guard is defined before the real definition is appended and the `(#ifndef)`
suppresses it. Whether the 797e97c1 run additionally had a missing-body
problem on top of this one is **not established**: it needs the whole-closure
compile, which is out of scope for the fix that landed.

## Suite-bucket note

`linkmode` (`test_link_mode.py`), and the same emission path is exercised by
`gimple` (`test_gimple.py`) and `selfhost`.