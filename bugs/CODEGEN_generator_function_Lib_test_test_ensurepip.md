# CODEGEN_generator_function: Lib/test/test_ensurepip.py

## Status (updated 2026-08-26 -- re-verified at current master `e60b9cd`, unchanged)

Independent fresh re-verify, this session, against current master
`e60b9cd` (122 commits past the `a913ab8` branch point the entry
immediately below was checked against). Ran
`compile_to_gimple_with_cpp(do_imports=False)` directly: byte-for-byte
identical `RuntimeError` — `fake_pip: unsupported statement in
generator body: StructDef`. The 3-piece design already scoped (struct
discovery never walks generator bodies; class-attribute seeding only
understands module-globals RHS; construction requires an explicit
`__init__`) still accurately describes what a real fix needs — nothing
in the 122 intervening commits touches any of the three. Still
feature-sized; untouched.

## Status (updated 2026-08-26 -- re-verified, unchanged)

Fresh re-verify against this worktree (branched from master `a913ab8`).
Isolated compile (`do_imports=False`): byte-for-byte identical refusal
— `fake_pip: unsupported statement in generator body: StructDef`. The
3-piece design scoped in the 2026-08-12 entry (struct discovery never
walks generator bodies; class-attribute seeding only understands
module-globals RHS, not enclosing-generator locals; construction
requires an explicit `__init__`) is still the accurate accounting of
what a real fix needs — nothing landed since touches any of the three.
Still feature-sized; untouched.

## Status (updated 2026-08-25 -- re-verified, unchanged)

Re-ran `python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/
test/test_ensurepip.py` fresh against current master (past the
struct-method cross-call scalar contract "Pass 1.3e",
generator-consumption-ordering fixed-point retry + defaults-aware arg
padding, `**kwargs`-forward slot-alignment fix, and coroutine-body
`int()`/`float()` builtin support landed since the 2026-08-24 entry
below). The whole-program build didn't finish within this session's
safety-wrapped time budget (large transitive import graph), but the
per-function debug log shows the identical refusal byte-for-byte before
the watcher killed it: `generator 'fake_pip' not eligible for C++
coroutine path, falling back to honest refusal: unsupported statement
in generator body: StructDef` (confirmed at both pass 1 and the pass-2
retry). None of the intervening fixes touch nested-class-definition
discovery/hoisting inside a generator body. Still feature-sized;
untouched.

## Status (updated 2026-08-24 -- re-verified, unchanged)

Re-checked this session while triaging the C3 cluster. The blocker (`class FakePip(): ...` defined INSIDE a generator body -- nested-struct-definition discovery/hoisting, a 3-piece design change already scoped in the 2026-08-12 update below) is unaffected by this session's two landed fixes (stdin/stdout/stderr field-name escaping; more char* string methods in coroutine bodies). Still feature-sized; untouched.


## Status (updated 2026-08-23 — STILL-OPEN)

Re-ran the repro: identical `unsupported statement in generator body:
StructDef` refusal on fake_pip. Unchanged; the three-piece scoped design
recorded above stands. One adjacent enabler DID land this session (class-
body conditional methods are now hoisted at parse time), but nested
class DEFINITION inside a generator BODY remains unsupported. Gate verification (2026-08-23): `test_gimple.py` 250 passed / 0 failed;
`test_module_cache.py` 76 / 0; `make check-selfhost` clean; from-scratch
stdlib dylib rebuild EXIT=0 with **0** `skip <module>:` lines — matching
the pre-change baseline of exactly 0 skips.

## Status (updated 2026-08-12 — re-verified, still not attempted; scoped a concrete design for a real fix)

Re-verified against current master with a real `MOJO_DEBUG=1 python3
mojo.py build`: still reproduces byte-for-byte identically (same
`unsupported statement in generator body: StructDef` refusal on
`fake_pip`).

Went one step further than prior sessions to pin down exactly what a real
fix needs, rather than re-stating "needs design work" abstractly. The
nested class is not just an unhandled AST node — its one field is
assigned from the ENCLOSING FUNCTION's own local/parameter
(`__version__ = version`, where `version` is `fake_pip`'s own defaulted
parameter), i.e. this is a fresh class object constructed and populated
from a runtime closure value each time the `class FakePip(): ...`
statement executes, not a static type declaration. Concretely, three
separate pieces of existing machinery would all need extending, not one:

1. **Struct discovery never sees it.** `gen_module`'s `all_struct_defs =
   stmts + (imported_stmts if ...)` (currently ~line 30257) only walks
   TOP-LEVEL statements — a `StructDef` nested inside a generator's body
   is invisible to every downstream struct-registration pass
   (`struct_field_types`, `_class_attrs`, `_struct_has_init`, etc.). A
   real fix needs a pre-pass that walks generator/function bodies (via
   the existing `_walk_ast` helper) specifically for nested `StructDef`
   nodes and hoists them into that same top-level struct-discovery list
   before the rest of `gen_module`'s pipeline runs — mirroring how a
   nested `FunctionDef` inside a generator body is already handled
   elsewhere as "compiled separately" (`_cpp_stmt`'s own `FunctionDef`
   case, which just returns `[]` and relies on a SEPARATE closure-lifting
   pass already having hoisted it to module scope by the time the
   generator body compiles).
2. **Class-attribute seeding only understands MODULE GLOBALS as the RHS.**
   The one existing mechanism that seeds a constructed struct's
   class-attribute fields at allocation time (`_class_attrs.get(fname,
   {})` + `_global_var_types.get(gname, ...)`, used both by the ordinary
   path's `_alloc_{struct}` helper at gimple_codegen.py:35177 and the
   generator-body struct-construction path added for
   `CODEGEN_generator_function_Lib_test_test_doctest_test_doctest.md` at
   gimple_codegen.py:24590) assumes the class body's attribute value is
   always a reference to a plain MODULE-level global (`self._global_var_
   types.get(gname, ...)`). Here the RHS is a generator-body LOCAL
   (`version`, `fake_pip`'s own parameter) — there is no existing
   mechanism to capture "the value of a local in the enclosing
   generator's frame at the moment its nested class statement executes"
   and thread it into a struct's per-instance field init; this needs a
   new, generator-body-scoped variant of that seeding logic (using
   `declared`/`_infer_simple_expr_ctype` the way `_cpp_stmt`'s other
   generator-local handling already does), not just a lookup-table
   extension.
3. **Construction requires an explicit `__init__`.** The generator-body
   struct-constructor branch added for the doctest.py fix
   (gimple_codegen.py, `_cpp_expr`'s CallExpr(IdentExpr) case) only fires
   when `fname in self._struct_has_init` — `class FakePip(): __version__
   = version` has no `__init__` at all (a bare class-attribute-only body),
   so even with (1) and (2) solved, `FakePip()` would still refuse via
   this gate. A real fix needs either a synthesized no-arg `__init__` for
   this shape or a separate zero-arg allocate-and-seed path parallel to
   the existing `__init__`-call one.

All three are genuine, separate extensions to already-complex shared
machinery (module-wide struct discovery, class-attribute seeding, and
struct construction), not a one-spot missing-case fix — consistent with
every prior session's classification. Not attempted this session either;
still a single instance in this cluster, not promoted to `bugs/hard/`.

## Status (updated 2026-08-09)

Re-verified again against current master (`42faf64`) with a real
`MOJO_DEBUG=1 python3 mojo.py build`: still reproduces byte-for-byte
identically (same `unsupported statement in generator body: StructDef`
refusal on `fake_pip`). No relevant `_cpp_stmt`/`StructDef` handling has
been added since the prior verification. Classification and disposition
unchanged from below — genuinely feature-sized, not a narrow fix, not
attempted.

## Status (updated 2026-08-07)

Re-verified against current master with a real rebuild — reproduces
byte-for-byte identically. Classification unchanged: nested `class
FakePip(): ...` inside `fake_pip`'s own generator body, genuinely
feature-sized (would need real design work for where a nested type's
layout/methods compile relative to the enclosing coroutine translation
unit). Not attempted, matching this task's guidance for #147-shaped
gaps. Still only one instance in this cluster — not promoted to a
`bugs/hard/*.md` doc.

## Status (updated 2026-08-06, superseded above — re-verified, unchanged)

**STILL FAILING**, confirmed reproducing against current master
(`2b0c4c5`) with a precisely identified, new gap.

```
$ MOJO_DEBUG=1 python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/test/test_ensurepip.py
[gimple_codegen] generator 'fake_pip' not eligible for C++ coroutine path, falling back to honest refusal: unsupported statement in generator body: StructDef
Error building: cannot compile module: function(s) fake_pip (generator function(s), ...) — falling back to interpreting this module from source instead
```

**Root cause (new gap — narrow, single instance, not yet a hard-bug
doc):**
```python
def fake_pip(version=ensurepip.version()):
    if version is None:
        pip = None
    else:
        class FakePip():          # <-- nested class def inside a generator body
            __version__ = version
        pip = FakePip()
    ...
    yield pip
```
`fake_pip` defines a NESTED CLASS (`class FakePip(): ...`) inside its
own generator body. The coroutine codegen's statement lowering
(`_cpp_stmt`) has no case for a `StructDef` node at all — nested class
definitions inside a generator are refused wholesale, distinct from
every other gap found in this cluster's pass (those are all about
parameter types, assignment targets, `raise` targets, or expression
shapes — this is about a whole nested TYPE DEFINITION).

Single instance so far in this cluster; not folded into a hard-bug doc.
If confirmed recurring elsewhere, write
`bugs/hard/CODEGEN_generator_nested_class_def_unsupported.md`.

Not fixed here — a nested class inside a generator is a genuinely
unusual shape and support would need real design work (where does the
class's own methods/layout get compiled relative to the enclosing
coroutine's translation unit?), well beyond a narrow fix.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/test/test_ensurepip.py
