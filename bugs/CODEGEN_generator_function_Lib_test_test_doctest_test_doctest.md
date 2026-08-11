# CODEGEN_generator_function: Lib/test/test_doctest/test_doctest.py

## Status (updated 2026-08-11) — this doc's own bug FIXED, file still doesn't build clean (unrelated bug)

Re-verified against current master with a real rebuild: the two documented
errors (`'TestHook' was not declared in this scope` /
`request for member 'remove' in 'hook', which is of non-class type
'int64_t'`) are **gone**. Root-caused and fixed for real, not just
narrowed:

`gimple_codegen.py`'s C++20-coroutine generator-body codegen
(`_gen_cpp_generator_unit`/`_cpp_expr`/`_cpp_stmt`) had NO support at all
for constructing a plain struct instance inside a generator body — only
struct-typed PARAMETERS and `self` (on a generator METHOD) were ever
threaded into a generator's separately-compiled `.cpp` translation unit
(see `_cpp_struct_ptr_local`/`_cpp_param_struct_names`, added for
`bugs/hard/CODEGEN_generator_struct_typed_param_refused.md`). `hook =
TestHook(pathdir)` — a plain local first-assigned from a call to an
ordinary (non-generator, module-level) class's constructor — fell all the
way through `_infer_simple_expr_ctype`'s unknown-call case to the
int64_t default, and `_cpp_expr`'s CallExpr(IdentExpr) case had no
struct-constructor branch at all (the call just fell through to the
"unrecognized bare-name call" fallback, emitting an undeclared `TestHook
(...)` C++ identifier).

**Fix** (`gimple_codegen.py`):
1. `_cpp_expr`'s CallExpr(IdentExpr) case gained a struct-constructor
   branch: `StructName(args)` for a struct with exactly one `__init__`
   (no kwargs — the narrow, no-overload-resolution shape this scalar
   body model already uses elsewhere) lowers to an immediately-invoked
   C++ lambda (`[&]() -> StructName * { ...; return t; }()`) that
   allocates (`calloc` + stamps `__mojo_type_id` + seeds any
   class-attribute instance fields — mirroring `_lower_struct_
   constructor`'s ordinary-path `_alloc_{struct}` helper's OWN logic,
   not calling that helper directly: it's emitted `static`/internal-
   linkage per module specifically so the monolithic stdlib dylib's
   independently-compiled modules don't collide at link time, which
   means this generator body's separately-compiled-and-linked `.cpp` TU
   can't call it either) and calls `__init__` via the same mangled
   `_struct_method_csym` symbol the ordinary compiled path already uses
   (struct methods, unlike `_alloc_`, are never `static`).
2. The `AssignStmt` first-assignment path now recognizes this same shape
   and types the local as `{Struct} *` (a new `_cpp_ctor_struct_names`
   set) instead of falling to the int64_t default — this is what let
   `hook.remove()` resolve through the ALREADY-EXISTING (and already
   working, for parameters) `_cpp_struct_ptr_local`/`_cpp_struct_method_
   refs` machinery with no further change needed there.
3. The `.cpp` preamble's struct-typedef-emission loop now also includes
   `_cpp_ctor_struct_names`, plus a new transitive-closure pass: a
   constructed struct can itself have a field typed as ANOTHER struct
   pointer (`TestHook.importer: TestImporter *`), which needs its own
   typedef visible too — walks `struct_field_types` to a fixed point,
   and forward-declares every struct tag in the closure before emitting
   any of their full definitions (sorted-alphabetical emission order
   doesn't necessarily match field dependency order).

Verified end-to-end with a standalone repro (not through `with ... as`,
see below): a generator constructing a struct, yielding it, and calling
a method on it in a `finally:` block, consumed via a plain `for h in
gen():` loop — compiles, links, and RUNS with correct output (the
`__init__`-set field value is visible at the yield site, and `.remove()`
in `finally:` fires with the right value on both normal completion and
early `break`).

**Remaining, separate blocker (not this doc's bug):** `test_doctest.py`
still doesn't build clean — it now reaches the LINK stage (a first, by
itself) and fails there with `undefined symbols: "_Wrapper_func"`. This
is `Wrapper.__call__`'s `self.func(*args, **kwargs)` (line ~2760) —
`self.func` is a plain field HOLDING a callable (assigned in `__init__`
from a constructor argument), not a struct method — a completely
different, unrelated codegen gap (calling a struct field that holds a
function reference/pointer is apparently resolved as if it were a
same-named STRUCT METHOD, `Wrapper_func`, which is never defined,
instead of loading the field and calling through it). Not a generator
issue at all (`Wrapper`/`wrapped` have no generator involved), not
investigated further here — out of scope for this cluster.

Also worth noting for anyone revisiting: `test_hook`'s ACTUAL use in this
file is only inside a docstring (`>>> with test_hook(dn):`), never real
executable code, so the separate, still entirely-unimplemented gap of
consuming an `@contextlib.contextmanager`-decorated generator via a real
`with ... as x:` statement (there is no `contextmanager` handling
anywhere in `gimple_codegen.py`'s `WithStmt` lowering at all — it only
recognizes structs with real `__enter__`/`__exit__` methods) never
actually blocks THIS file, and was not touched by this fix.

Full mandatory gate run after the fix: `test_gimple.py` 247/0,
`test_module_cache.py` 76/0, `make check-selfhost` clean, from-scratch
`libmojostdlib.dylib` rebuild 0 `skip <module>:` lines, `compile_stdlib.py`
664/664 passed 0 unexpected.

## Status (updated 2026-08-09)

Re-verified against current master (post `_MOJO_STUB_<NAME>` guard-macro
case-collision fix, commit `ee69066` — unrelated to this file, doesn't
change anything here) with a real rebuild: reproduces byte-for-byte
identically, same two errors, same lines (`test_hook`/`TestHook` at
source lines 3156-3161). Classification unchanged and confirmed still
accurate — this is the family-wide structural gap this session's parent
task lists as "Unannotated params/fields (including an untyped `with
... as cm:` binding) defaulting to `int64_t` inside generator bodies
specifically" (here: an untyped plain local, `hook = TestHook(pathdir)`)
combined with "Arbitrary outer-scope module/class name resolution inside
a generator's separately-generated translation unit" (here: the
`TestHook` class name itself). Both require broad/shared inference-
machinery changes (generator bodies compile into a separately-generated
C++ translation unit that doesn't get the same outer-scope name/type
threading the ordinary function path gets) — not narrow, not attempted.

## Status (updated 2026-08-07)

Re-verified against current master with a real rebuild — reproduces
byte-for-byte identically (same two errors, same lines). Classification
unchanged: both are the already-documented "outer-scope class name /
untyped local not threaded into generator C++ scope" gap family (see
`bugs/CODEGEN_generator_function_Lib_test_libregrtest_runtests.md` for
the closest sibling instance, and `bugs/COMPILE_FAIL_ctypes_macholib_
dyld.md`'s bullets 1/4 for the original two mechanisms). Not attempted
— broad/shared inference machinery, not a narrow single-instance fix.

## Status (updated 2026-08-06, superseded above — re-verified, unchanged)

**STILL FAILING**, confirmed reproducing against current master
(`2b0c4c5`) — same symptom family as 2026-07-30, still reaching the
real coroutine `.cpp` compile stage:

```
test_doctest_gen.cpp:106:12: error: 'TestHook' was not declared in this scope
test_doctest_gen.cpp:109:18: error: request for member 'remove' in 'hook', which is of non-class type 'int64_t' {aka 'long long int'}
```

**Root cause:**
```python
@contextlib.contextmanager
def test_hook(pathdir):
    hook = TestHook(pathdir)
    try:
        yield hook
    finally:
        hook.remove()
```
`hook = TestHook(pathdir)` — `TestHook` is a module-level class defined
elsewhere in the file. **Classification: two already-documented
dyld.py-cluster gaps hitting together:**
1. `TestHook` (the class NAME itself) isn't threaded into the generator
   body's C++ scope — the same "outer-scope name not in scope inside
   generator" gap already generalized in `bugs/CODEGEN_generator_
   function_Lib_test_libregrtest_runtests.md`'s re-diagnosis (there for
   a module name AND an enum class; here for an ordinary class name).
2. `hook`'s inferred type falls back to `int64_t` (the untyped-local
   variant of dyld.py's bullet 1 "untyped params default wrong" —
   `hook` is a plain local assigned from a constructor call, not a
   function parameter, but the same missing usage-based-inference root
   cause applies), so `hook.remove()` fails with "request for member
   'remove' in ... non-class type 'int64_t'".

Not fixed here — both are established, already-documented gaps in the
generator-codegen path.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/test/test_doctest/test_doctest.py
