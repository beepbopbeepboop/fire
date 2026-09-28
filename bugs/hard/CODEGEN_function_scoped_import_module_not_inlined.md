# HARD BUG: a function-scoped `from mod import Name` records the import's signatures but never pulls `mod` into the translation unit — the call lowers to the "unavailable in compiled mode" weak stub and silently returns 0

**State: PARTIAL — single-TU path FIXED 2026-09-27; link-mode still OPEN.**

Re-verified against the current tree: rows 0-2 of the table below (all
single-TU, `do_imports=True` — what `compile_stdlib.py`/`test_gimple.py`/the
gate exercise) now all match CPython. The `_compile_imported_module` call
this doc's root-cause section says never happens is, on the current tree,
already reached (verified: the struct typedef, `__init__` and the call site
all appear correctly in `--dump-full` output) — that diagnosis was accurate
in 2026-09-26 but had already been superseded before this session started.
The residue actually blocking rows 0-2 was a DIFFERENT, narrower bug: a
constructor call whose only field-type evidence is an unannotated
scalar/container literal argument (`Parameter('v', 7)`) left the field
`int64_t` in the DEFINING module's own compiled struct, because neither the
same-module ctor-literal pass nor its local/self.field companion
(`_ctxlit_*`, `mojo/backend_gimple/module_gen.py`) ever sees a call site in
a DIFFERENT module — this is true whether the import is function- or
module-scoped, so it is not really an import-scoping bug at all. Fixed with
a new cross-module hint mechanism, `_xmod_ctor_field_hints`
(`gimple_codegen.py`/`module_gen.py`/`emit_resolve.py`), mirroring the
existing `_xmod_gen_param_hints` pattern one struct field deeper: THIS
module's own ctor call sites are scanned (before any imported module is
inlined) for scalar/container LITERAL arguments to a constructor defined in
an imported module, and the resulting evidence is applied by the DEFINING
module's own temp_gen directly into its `struct_field_types`. Verified:
`test_gimple_runner.py`'s `gimple_cross_module_ctor_scalar_field_type`
(compiles AND runs, was a hard `gcc -fgimple` "non-trivial conversion"
failure before the fix — a scalar mismatch, unlike the container case's
silent SIGSEGV).

**Row 3/4 (link-mode) are UNCHANGED, confirmed still broken** —
`fire.py build`'s default pipeline (`driver.compile_program`, a genuinely
separate codegen path from the single-TU inline one) still prints
`can_colorize: unavailable in compiled mode0` for row 0's repro. Out of
scope for this fix; CLAUDE.md already tracks link-mode as needing its own
dedicated coverage (`linkmode` gate step) since a bug there is invisible to
every other check.

## History (found 2026-09-26, before the above fix)

Found 2026-09-26 by re-testing the claims in the now-removed
`CODEGEN_function_scoped_import_rettype_and_literal_cast_mismatches.md`. All
four of that doc's mechanisms are genuinely fixed — the GIMPLE type mismatches
they caused are gone, verified below. What its 2026-09-25 entry verified was
that a function-scoped-import repro **compiles with zero `error:` lines**, and
that is exactly where it stopped. It did not run the binary, and the binary is
wrong.

## Symptom

Two files. `insp.py`:

```python
class Parameter:
    POSITIONAL_ONLY = 1
    VAR_POSITIONAL = 2
    def __init__(self, name, kind=0):
        self.name = name
        self.kind = kind
    def __repr__(self):
        return self.name
```

Four one-method clients, differing only in **where the `from insp import
Parameter` sits** and **what is done with the name**. All four build with zero
`error:` lines.

| # | import site | use | CPython | compiled | exit |
|---|---|---|---|---|---|
| 0 | **function**-scoped, a plain **function** | `from _colorize2 import can_colorize`, `if can_colorize(): return 1` | `1` | **`can_colorize: unavailable in compiled mode0`** | **0** |
| 1 | **function**-scoped | `Parameter.VAR_POSITIONAL` | `2` | **`0`** | **0** |
| 2 | **function**-scoped | `Parameter('v', 7)` | `v` | **`Parameter: unavailable in compiled mode0`** | **0** |
| 3 | module-scope | `Parameter.VAR_POSITIONAL` | `2` | `Unhandled exception: AttributeError: VAR_POSITIONAL` | 1 |
| 4 | module-scope | `Parameter('v', 7)` | `v` | **`4320418240`** (a raw pointer decimal) | **0** ‡ |

(`/tmp/vd1/h1.py` for row 0, `/tmp/vd1b/f1.py` … `f4.py` for rows 1-4; row 4's
pointer value is ASLR-dependent.)

‡ **Row 4 is not this doc's bug.** It is
`CODEGEN_method_call_on_struct_param_mistyped.md`: the value comes back through
`repr(...)`, i.e. a method call on a struct that arrived as a free-function
parameter, which is mistyped independently of any import. Reproduced with no
imports at all (`/tmp/vd1b/k2.py`: `def show(p): return p.label()` → CPython
`v`, compiled `4354021824`, exit 0) and cross-module (`/tmp/vd1b/k3.py` → `0`,
exit 0). Row 4 is listed only so the table is not silently incomplete; it
belongs to that doc.

Row 0 is the removed doc's own canonical Mechanism-1 repro
(`from _colorize import can_colorize` inside a method), with `can_colorize`
returning `True` so the wrong answer is unambiguous. It is also the only row
whose *value* is wrong rather than only whose stdout is polluted.

Rows 0-2 are the silent ones. Each prints a **runtime diagnostic into the
program's own stdout** and then a wrong value, and exits 0 — so any harness
that only compares an exit code sees a pass.

Row 2 is the doc's exact original territory. It is `enum.py`'s
`EnumType.__signature__` shape (`from inspect import Parameter, Signature` inside
a method, then `Signature([Parameter('values', Parameter.VAR_POSITIONAL)])`),
which is also what the removed doc's own repro is. The full three-class version
(`/tmp/vd1/usr.py`) prints
`Parameter: unavailable in compiled modeSignature: unavailable in compiled mode0`
against CPython's `Signature(1)`.

Adding a module-scope import of the same module **does not help**:
`/tmp/vd1b/g1.py` and `g2.py` both have `from insp import Parameter` at module
scope *and* the function-scoped one, and both still print
`Parameter: unavailable in compiled mode0`.

## Root cause

`mojo/backend_gimple/emit_funcs.py`, the function-body `FromImport` path
(`_gen_stmt_FromImportStmt`'s nested-import branch, `:319-440`). For a
function-scoped `from mod import name` it:

1. resolves the module and reads its export table
   (`_mlmod_fi.load_module` / `gen._local_sibling_module_exports`, `:340-352`),
2. records the symbol's signature, return type, parameter ctypes, mangled home
   and default arguments (`:354-439`),
3. `continue`s (`:440`).

It **never calls `_compile_imported_module(gen, node.module)`** — the
single-TU inline path's "actually go read that module's source and generate its
code" step (`emit_resolve.py:362`). So nothing from `insp.py` is emitted into
this translation unit, and the call site has no real definition to bind to. The
comment at `:319-328` is explicit that this branch exists to stop the name being
registered with *no* signature (BUG-2026-021, which produced conflicting C
types) — the signature half was fixed; the definition half was not.

What the call site then binds to depends on the pipeline, and both paths are
wrong in different ways:

**Single-TU inline path** (`compile_to_gimple(src, do_imports=True)` — what
`compile_stdlib.py`, `test_gimple.py` and most of the gate exercise). The class
is absent, so `X.ATTR` falls to the PascalCase-import guard and emits the
"not yet inlined as a struct" 0-stub (`emit_exprs.py:1265`) — that is row 1's
`0`. A call instead binds to the extern-preamble's weak stub
(`mojo/backend_gimple/module_gen.py:7845-7860`, the `else:` arm taken when the
imported symbol has no `'signature'` entry — a class never does, and for a
plain function the signature the nested-import branch records did not win the
race), and the call site goes to it verbatim:

```c
__attribute__((weak)) int64_t Parameter (...) { mojo_print ((char *)"Parameter: unavailable in compiled mode"); return (int64_t)0; }  /* stub from insp */
...
_t2 = Parameter (_t1, 1);
```

Row 0's `can_colorize` is byte-identical on **both** paths
(`/tmp/vd1/h1_d.ci` and `/tmp/vd1/h1_l.ci`, line 1185 in each), which is why
the plain-function spelling is the cleanest single demonstration of this doc.

The same program with the import at **module** scope on this path is entirely
correct — `/tmp/vd1/usr2_d.ci` contains a real
`typedef struct Parameter {...} Parameter;`, a real
`void __GIMPLE insp_Parameter___init__ (Parameter *, int64_t, int64_t)`, and
both call sites bound to it. So the ordering-race diagnosis the removed doc
recorded for Mechanism 4 is no longer what is happening; the module is simply
never read.

**Link-mode path** (`fire.py build`'s default, the `linkmode` gate step). Here a
cross-module *class* import produces the weak stub in the client `.ci` whether
the import is module-scoped or function-scoped — verified in
`/tmp/vd1b/g1_l.ci` (module-scope import present, real
`insp_Parameter___init__` compiled into the closure, and the function-scoped
call still bound to `Parameter (...)` weak stub). Row 3's `AttributeError` is
this path's separate class-attribute bug: the client's `_mojo_classattr_init()`
is emitted **empty** and the attribute read is lowered to the *string literal*
`"VAR_POSITIONAL"` (`/tmp/vd1b/f3_l.ci:1206,1285`), so the runtime `getattr`
misses. Honest failure, wrong answer.

## Contradictions with the removed doc's own recorded claims

1. **"the generated C contains a real `typedef struct Parameter {...}
   Parameter;`, a real `inspect_Parameter___init__`, the `_MOJO_STUB_Parameter`
   guard already defined, and no colliding weak stub"** — for the
   function-scoped repro the doc describes. **Measured false.** The
   function-scoped `insp.py` client contains no `typedef struct Parameter`, no
   `insp_Parameter___init__`, and *does* contain a `weak` `Parameter (...)`
   stub (`/tmp/vd1/usr_d.ci`, single-TU inline path). All of those strings are
   present only in the **module-scoped** variant (`/tmp/vd1/usr2_d.ci`). The
   entry's own repro text says "a module doing a **function-scoped** `from
   inspect import Parameter, Signature`", so the claim and the repro disagree.
2. **"the constructor-call residual no longer reproduces"** (the banner) and
   "**NOT REPRODUCIBLE**" (the section heading). The *GCC diagnostic* the
   original doc was chasing — `expected expression before 'Parameter'`, the
   typedef-vs-identifier collision — is indeed gone, and the ordering race is
   indeed no longer the mechanism. But "the residual does not reproduce" was
   read as "this shape works". It compiles and prints
   `Parameter: unavailable in compiled mode0`. The residual moved from a compile
   error to a silent wrong value, which is strictly worse for a corpus whose
   gate is "does it build".
3. **"Not re-attempted … with no reproduction to fix there is nothing to verify
   a change against."** There was a reproduction to fix: it just needed running
   rather than compiling.
4. **The claim that the fix here means reordering class registration across the
   whole transitive closure.** That assessment, the doc says, is why it was left
   alone. It does not hold. The two files needed to reproduce this are the
   `inspect.py` and the client — both already in the closure, both already
   resolvable by `_module_candidate_paths` (`emit_resolve.py:102`), and the
   module-scope spelling of the identical import already inlines them correctly.
   The gap is one missing `_compile_imported_module` call in one branch, not a
   cross-closure registration-ordering change. The documented
   `CODEGEN_function_scoped_import_call_unresolved_at_link.md` corpus-wide
   regression (referenced throughout the removed doc, and one of the nine
   dangling cross-references in `bugs/hard/README.md`) is a real historical
   fact and is the reason to gate a change here on the full quality gate — it is
   not evidence that this shape is unreachable.

## Genuinely fixed, recorded so nobody re-opens them

All four mechanisms, re-verified 2026-09-26. Fix sites confirmed present in the
post-split tree.

| mechanism | fix site (current) | verification |
|---|---|---|
| 1 — function-scoped import's unknown-symbol return type defaulted to `'int'`, disagreeing with the weak stub's `int64_t` | `mojo/backend_gimple/emit_funcs.py:507` (`ret = sig[0] if sig else 'int64_t'`) — the comment above it still names this doc's `_colorize` repro and the argparse/enum/gettext error counts. `:371` is the same handler's resolved-signature path. | the `can_colorize` repro (`/tmp/vd1/m1.py`, `:319-328`'s shape) builds with **zero** `error:` lines. (It no longer binds to a real `_colorize` — that is the residue above — but the `int`/`int64_t` mismatch this mechanism caused is gone.) |
| 2 — `_new_val`'s digit-literal cast guard covered `int64_t` but not `_Bool` | `mojo/backend_gimple/emit_resolve.py:1361` (`ctype in ('int64_t', '_Bool')`) | `/tmp/vd1/m2.py`, `isinstance(x, type)` and `isinstance(x, (T, int, str))`: CPython `2` `3`, compiled `2` `3` ✓ |
| 3 — `super().method()` passed `self` typed as the derived struct pointer while `_emit_call`'s coercion pass saw no mismatch | `mojo/backend_gimple/emit_methods.py:1189-1213` (the `if self_type != fake_obj_type:` derived-to-base cast) | `/tmp/vd1/m3.py`, a 3-level `A`→`B`→`C` chain each calling `super().m()`: CPython `3`, compiled `3` ✓ |
| 4 — an imported class name used as a bare `X.ATTR` base mistaken for a zero-arg accessor, colliding with the class's `typedef` | the PascalCase-import guard, `mojo/backend_gimple/emit_exprs.py:1253-1265` | the `expected expression before 'Parameter'` diagnostic is gone in the four spellings I built (function/module scope × `X.ATTR`/`X(...)`); what the value is *now* is rows 1-4 above. I did not re-run the doc's original full `Lib/typing.py` / `Lib/enum.py` isolated compiles, so I am not claiming the original 14→7 count. |
| the `weakref.py` `#line` misattribution (a base class's inherited method body emitted under the subclass's `#line` filename) | `GimpleGen._module_source_paths` + `_inherited_method_src` | regression test `inherited_method_line_directive_names_its_own_module` **PASSES**, and it lives in `test_gimple.py`, which **is** registered (`gimple`, in both `check` and `gate`). `python3 test_gimple.py` → `Results: 316 passed, 0 failed`. This is what a correctly-homed regression test looks like — contrast `CODEGEN_ctor_arg_field_type_scalars_only.md`'s orphan. |

## Where

- `mojo/backend_gimple/emit_funcs.py:319-440` — the function-scoped `FromImport`
  branch: registers signatures, never inlines the module. `:440` is the
  `continue` that skips it.
- `mojo/backend_gimple/emit_resolve.py:362` — `_compile_imported_module`, the
  call that is missing there.
- `mojo/backend_gimple/emit_exprs.py:1253-1265` — the `X.ATTR` 0-stub that
  produces row 1's silent `0`.
- The `weak` "unavailable in compiled mode" stub emitter — the extern
  preamble's `else:` arm, `mojo/backend_gimple/module_gen.py:7845-7860`; the
  sibling arm at `:7806-7821` does the same for `_stub_only_modules`. The two
  places the message text is spelled out for readers are
  `mojo/backend_gimple/module_gen.py:83` and
  `mojo/backend_gimple/emit_infra.py:49`.
- `mojo/backend_gimple/module_gen.py` — the link-mode path's empty
  `_mojo_classattr_init()` and string-literal-valued class-attribute read (row 3).

## Suggested shape of a fix (not attempted)

Two separable pieces, cheapest first:

1. **Inline the module** for a function-scoped import whose names are actually
   used in the enclosing body — i.e. call `_compile_imported_module` the way
   the top-level Process-imports loop does, sharing the same dedup sets
   (`_compiled_modules` / `_emitted_structs` / `_compiling_file_paths`) so a
   module already inlined elsewhere in the closure is a no-op rather than a
   second copy. This is what rows 0-2 need, and row 0 is broken identically on
   both pipelines so the change has to work on both. It is the change the
   removed doc's assessment predicted was dangerous, so it owes the full gate
   plus a manual re-triage of the `COMPILE_FAIL_*.md` corpus — that risk is
   real and is why this is written down rather than landed.
2. **Stop the weak stub from being silently callable.** Independently of (1),
   an auto-stub that prints into the program's stdout and returns 0 should not
   be reachable from a call site the compiler knows is a real import. At
   minimum, route it to the honest-failure path the codebase already has, so a
   missed import is a refusal rather than a wrong number.

## Test coverage

The removed doc's own citation for its 2026-09-25 fix,
`inherited_method_line_directive_names_its_own_module`, is in `test_gimple.py`
and is registered. There is **no** regression test for the constructor-call or
`X.ATTR` spellings on either backend — the removed doc never wrote one, on the
reasoning that the shape did not reproduce. A fix here needs one that asserts
**stdout**, not just "it builds"; `test_gimple.py` has
`test_gimple_stdout`-style helpers, and note the sibling file
`test_gimple_runner.py` is currently orphaned from every gate (see
`CODEGEN_ctor_arg_field_type_scalars_only.md`), so it is the wrong home for a
new test.
