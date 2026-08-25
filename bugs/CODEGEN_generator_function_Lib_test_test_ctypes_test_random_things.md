# CODEGEN_generator_function: Lib/test/test_ctypes/test_random_things.py

## Status (updated 2026-08-25, worktree fix/opencode-arity — RESOLVED: the inherited-method arity blocker is FIXED and the full build now exits 0 with verified runtime behavior)

The doc's own proposed fix (mirror `_cpp_module_variadic_func_refs`'s
variadic-extern convention for unresolved free functions, paired with a
matching weak stub definition) was implemented for the struct-method case
and verified END-TO-END. Commit `b46fd5d` on `fix/opencode-arity`.

**The uncertainty that stopped the 2026-08-24 pass is now resolved
definitively.** Tracing the codegen found that the ordinary
(non-generator) path ALREADY had half the mechanism:
`_lower_struct_method_call`'s auto-stub branch
(gimple_gen_methods.py, the `struct_name in gen._structs_with_
unresolved_base` case) emits a WEAK variadic stub definition —
`__attribute__((weak)) int64_t Sym (Struct *_self, ...) { mojo_print
("...unavailable in compiled mode (inherited from an unmodeled base
class)"); return 0; }` — into the .ci whenever an inherited method of
an unresolved-base struct is called from an ordinary function body.
But generator-body call sites only recorded `(struct, method)` pairs
in `_cpp_struct_method_refs`; nothing emitted any definition for them,
and the extern-declaration loop's `[f"{_sm_struct} *"]` fallback made
the declaration itself non-variadic. So a generator-only call site got
neither correct arity NOR a backing definition.

The fix (gimple_module_gen.py's final `.cpp` assembly, `_cpp_struct_
method_refs` loop): when neither lookup key has recorded param types,
emit BOTH halves in the companion `.cpp` TU — (1) the weak variadic
stub DEFINITION (`extern "C" __attribute__((weak)) T Sym (Struct
*_self, ...) { ... honest diagnostic ... }`, same guard namespace
`_MOJO_STUB_*` via `_stub_guard_name`, same message wording as the
ordinary path's auto-stub) and (2) implicitly its own prototype — so
declaration and definition always agree regardless of which other TUs
participate. The definition is `extern "C"` so it lands on the same
UNMANGLED C symbol a real definition elsewhere would use; verified via
`nm` (weak external `_CallbackTracbackTestCase_assertEqual`, no C++
mangling) AND via an explicit strong-definition link test: linking a
third object defining the same symbol strongly succeeds with no
duplicate-symbol error and the strong def wins, while linking WITHOUT
one succeeds against the weak stub — both sides of the link agree in
every scenario. A bare-vararg-only recorded signature (`['...']`) is
routed through the same variadic treatment rather than joined as a
receiver-less `(...)`.

Verification (all real, this session):
1. Isolated repro (`compile_to_gimple_with_cpp(do_imports=False)` +
   `gcc-mp-15 -fgimple -fsyntax-only` / `g++-mp-15 -std=c++20
   -fsyntax-only`): the 4 documented "too many arguments" errors at
   lines 128/130/132/133 are GONE — 0 errors on BOTH sides.
2. Full link: both objects + `build/libmojostdlib.dylib` link clean
   into a working executable (C++ driver for the final link, as the
   pipeline's needs_cxx logic prescribes).
3. FULL BUILD: `python3 mojo.py build .../test_random_things.py`
   EXITS 0 (8s warm-CAS run) producing a working `test_random_things`
   executable; module-level execution correctly does nothing (source
   guards `unittest.main()` under `__name__ == '__main__'`) and exits
   0.
4. RUNTIME behavior of the previously-broken generator verified with a
   small C driver driving the exported coroutine API
   (`_mojogen_CallbackTracbackTestCase_expect_unraisable_start/resume/
   value/destroy`): generator starts, yields the bare yield (value=0),
   then on resume runs each formerly-failing site — each prints the
   honest per-site diagnostic ("CallbackTracbackTestCase.assertEqual:
   unavailable in compiled mode (inherited from an unmodeled base
   class)") and returns 0, exactly the established weak-stub
   convention — then completes cleanly, exit 0. With a REAL backing
   implementation linked strongly, those calls would dispatch to it
   instead (verified at link level as above).
5. Full mandatory gate for the gimple_module_gen.py change:
   `test_gimple.py` 252/252, `test_module_cache.py` 76/76,
   `make check-selfhost` clean ("self-host compiles + links clean"),
   from-scratch stdlib dylib rebuild EXIT=0 with **0** `skip <module>:`
   lines — matching the baseline of exactly 0 skips.

Operational note for future sessions: with NO stdlib dylib present and
a cold CAS cache, `mojo.py build` of this file walks its transitive
import closure INLINE, spending minutes PER MODULE on big modules that
then fall back to interpretation anyway (collections → inspect →
shutil → ...), with RSS climbing ~6.7GB before our watcher killed one
run — the same runaway family the faulthandler doc warns about, here
driven by import-closure compile cost rather than one bad file. With
`build/libmojostdlib.dylib` built (gate 4 builds it), imports resolve
via link mode and the whole build takes seconds. Build the dylib
first.

Same mechanism re-verified fixed for `_test_eintr.py`'s
assertEqual/assertIsInstance/addCleanup sites — see that doc's
2026-08-25 entry.

## Status (updated 2026-08-24, worktree fix/rest-remainder — arity-mismatch fix considered and DELIBERATELY NOT attempted; see reasoning)

Investigated the `(self)`-only extern-declaration arity mismatch (the
residual blocker shared with `_test_eintr.py`'s `assertEqual`/
`assertIsInstance` sites — same underlying mechanism,
`gimple_module_gen.py`'s `_cpp_struct_method_refs` extern-declaration
loop: `self.func_param_types.get(_smsym, self.func_param_types.get(
_smkey, [f"{_sm_struct} *"]))` falls back to a bare `(self *)`-only
signature whenever an inherited method — one never defined on the local
subclass itself, only on an uncompiled base class like
`unittest.TestCase` — has no recorded real signature).

The obvious-looking narrow fix (declare it C-variadic, `extern "C" T sym
(...);`, mirroring this same file's existing `_cpp_module_variadic_
func_refs` convention for an unresolved free function) was NOT attempted:
that convention's free-function counterpart pairs its variadic EXTERN
DECLARATION with a real, matching, weakly-defined VARIADIC STUB BODY
(`__attribute__((weak)) {ret_type} {safe} (...) {body}`, `gimple_module_
gen.py` ~line 4931) generated elsewhere for exactly the same symbol — so
the two sides of the link always agree. The struct-method case has no
such confirmed backing definition: `unittest.TestCase` is real CPython
source (not a project-local stub module — confirmed no `unittest.mojo`/
similar exists anywhere in this repo), so whether `OSEINTRTest_
assertEqual`-style symbols get ANY real or weak-stub definition anywhere
in a full whole-program build was not established. Changing only the
extern declaration's arity, without confirming (or adding) a matching
definition, risks silently trading a diagnosable compile-time "too many
arguments" error for a much harder-to-diagnose link-time "undefined
symbol" error — worse, not better, and contrary to this codegen's
existing "refuse honestly, don't guess" convention. A real fix needs
either (a) confirming/adding a weak variadic stub definition alongside
the variadic extern declaration (mirroring the free-function mechanism
exactly), or (b) real inherited-method signature resolution. Left
open, not attempted, for whoever picks this up next with the time to
verify the link-level assumption first.


## Status (updated 2026-08-23 — PARTIAL)

The documented `cm.unraisable.*` int64_t-member errors are GONE:
attribute reads/calls rooted at opaque-scalar locals now stub to 0
(diagnosed) instead of emitting invalid C++, so `with ...
catch_unraisable_exception() as cm:` bodies compile through. The build
now fails one level deeper, on a NEWLY-diagnosed residual: inherited
unittest.TestCase method calls from generator bodies
(`self.assertIsInstance(...)`) get extern declarations whose parameter
list defaults to `(self)`-only when no param info exists in this module,
so the 3-arg call site fails 'too many arguments'. Same residual blocks
_test_eintr's assertEqual sites. Not attempted here (needs arity-aware
_cpp_struct_method_refs or inherited-method resolution). The #147-shaped
classification below otherwise stands. Gate verification (2026-08-23): `test_gimple.py` 250 passed / 0 failed;
`test_module_cache.py` 76 / 0; `make check-selfhost` clean; from-scratch
stdlib dylib rebuild EXIT=0 with **0** `skip <module>:` lines — matching
the pre-change baseline of exactly 0 skips.

## Status (re-verified 2026-08-11, unchanged — deeper investigation confirms genuinely structural, not attempted)

Re-ran a fresh isolated build; reproduces identically to the 2026-08-09
note below (same 4 `cm.unraisable.*`/`int64_t` errors). Went one level
deeper than the prior notes to confirm this is really #147-shaped and
not narrowly fixable, by reading the real source
(`Lib/test/support/__init__.py`'s `catch_unraisable_exception`):

```python
class catch_unraisable_exception:
    def __init__(self): self.unraisable = None; self._old_hook = None
    def _hook(self, unraisable): self.unraisable = unraisable
    def __enter__(self):
        self._old_hook = sys.unraisablehook
        sys.unraisablehook = self._hook
        return self
```

Even a maximally narrow, single-shape fix (special-casing exactly
`with support.catch_unraisable_exception() as cm:` to type `cm` as
`catch_unraisable_exception *` from its `__enter__`'s `return self`)
would only get one level deeper before hitting the SAME wall twice
more: (1) `cm.unraisable` is itself a field set from `sys.
unraisablehook`'s callback argument — a real CPython `UnraisableHookArgs`
object this compiled runtime has no representation for at all (`sys.
unraisablehook` itself isn't implemented here), so the field's type is
unknowable even in principle, not just untracked; and (2) `cm.
unraisable.exc_value` is a THREE-level `self`-rooted chain (`_cpp_expr`'s
`MemberExpr` case only supports a `self.field` one-level read and a
`self.field1.field2` two-level chain, both rooted at `self` — never a
chain rooted at an arbitrary non-`self` local/with-binding at any
depth). Confirms the existing classification: a `with X() as y:`
binding's real type has no representation anywhere in this narrow
scalar-body codegen model (the same "no class-attribute/field-access
story for non-`self` objects inside a generator body" gap #147 already
tracks architecturally), and here it's compounded by a genuinely
un-typeable field (sourced from an unimplemented CPython runtime hook)
one level down. Not attempted, per this task's own guidance to leave
#147-shaped gaps alone and per this session's direct confirmation that
a narrow fix wouldn't reach past the first level anyway.

## Status (re-verified 2026-08-09, unchanged)

Re-ran `python3 mojo.py build .../Lib/test/test_ctypes/test_random_things.py`
against current master (140 commits past the 2026-08-07 note below). Fails
identically:

```
test_random_things_gen.cpp:124:56: error: request for member 'unraisable'
in 'cm', which is of non-class type 'int64_t' {aka 'long long int'}
```

(4 occurrences, same `cm.unraisable.*` member accesses.) Same root cause as
before: `with support.catch_unraisable_exception() as cm:` inside a
generator body — an untyped `with ... as` binding defaults to `int64_t`
instead of its real context-manager struct type. Confirmed still the same
`with`-binding variant of the broad, deliberately-untouched #147
struct-typed-param-in-generator-body gap. No fix attempted, per this
cluster's guidance to leave #147-shaped gaps alone.

## Status (updated 2026-08-07)

Re-verified against current master with a real rebuild — reproduces
identically (line numbers shifted by a few lines but the same shape,
same `cm.unraisable`/`int64_t` errors). Classification below unchanged
and still accurate. This is the same "no real class-attribute/field-
access story for non-`self` objects inside a generator body" limitation
already tracked as architecturally broad in `bugs/hard/CODEGEN_
generator_struct_typed_param_refused.md` (task #147) — a `with X() as
local:` binding is a second entry point into the identical gap
(alongside a plain parameter's own declared type). Not attempted here,
consistent with this task's guidance to leave #147-shaped gaps alone.

## Status (updated 2026-08-06, superseded above — re-verified, unchanged)

**STILL FAILING**, confirmed reproducing against current master
(`2b0c4c5`) — same symptom as 2026-07-30, now precisely classified.

```
test_random_things_gen.cpp:117:31: error: request for member 'unraisable' in 'cm', which is of non-class type 'int64_t' {aka 'long long int'}
test_random_things_gen.cpp:117:27: error: expression cannot be used as a function
```

**Root cause:**
```python
def expect_unraisable(self, exc_type, exc_msg=None):
    with support.catch_unraisable_exception() as cm:
        yield
        self.assertIsInstance(cm.unraisable.exc_value, exc_type)   # line 117
        ...
```
`cm` is bound via `with support.catch_unraisable_exception() as cm:` —
an UNTYPED `with ... as` binding inside a generator body. **Classification:
a `with`-binding variant of `bugs/COMPILE_FAIL_ctypes_macholib_dyld.md`'s
bullet 1** ("untyped params inside a generator default to `int64_t`
instead of their real inferred type") — the same root mechanism (no
usage-based type inference for the coroutine codegen path, unlike the
ordinary closure path's `_gen_lifted_closure`/`ci.inferred_params`), just
triggered by a `with`-statement's bound name rather than a function
parameter. Every subsequent `cm.unraisable`/`cm.foo` member access then
fails since `cm`'s emitted C++ type is a raw `int64_t`, not the real
context-manager struct type.

Not fixed here — already-known gap family, no new fix attempted.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/test/test_ctypes/test_random_things.py
