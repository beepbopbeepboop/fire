# STDLIB-BUGS.md — issues that look like stdlib / build-structure bugs

Tracks things encountered while making the stdlib **fully compile** (`-fgimple -c`
→ `.o` → `libmojostdlib.dylib`) that feel like stdlib-source or build-structure
issues, as distinct from compiler/codegen bugs (those live in BUGS-AST.md /
BUGS-STDLIB.md). Updated as found.

**Goal: 100% of the stdlib in the dylib.** The dylib is a speed hack — a client
uses a symbol from it if present, else falls back to source — so today the build
*skips* the 16 modules that don't yet compile and *excludes* 4 that collide on a
C name, and those fall back to source. **That fallback (and the collision
exclusion) is a stopgap**, not the design endpoint. Closing it needs the real
fixes: free-function overload mangling (SB-1) and the elaboration/feature work
for the 16 non-compiling modules (see BUGS-STDLIB.md). Until then the dylib links
and accelerates everything it does contain.

---

## SB-1 — Cross-module C-name collision for overloaded free functions

**FIXED (mostly).** Free-function C symbols are now overload-mangled by their
parameter types (`_func_csym` in gimple_codegen, mirrored in reflect.py), routed
through every emission site, so same-named overloads in different modules get
distinct symbols. This removed the `reduce` collision. The `input` alias was
fixed separately (weak runtime symbol).

**Residual** (handled by the build's collision-dedup stopgap — 3 modules
excluded; the dylib still links):

- `mojo_abs` — math `abs(SIMD)` and complex `abs(Complex)` both lower to the same
  C signature (`int64_t`), so the C-parameter-type hash is identical. Needs
  Mojo-source-type or module-qualified mangling to distinguish (the C types have
  collapsed by codegen time). SIMD/Complex scalarization limit.
- `_all_trivial_copyinit`, `_get_dylib_function` — these are **generic** functions
  (`def _all_trivial_copyinit[*Ts: AnyType]()`), defined in two modules each and
  emitted as type-erased zero-arg duplicates. Needs monomorphization
  (elaboration), not parameter-type mangling — a zero-arg erased generic has no
  parameters to hash.

**More instances found 2026-07-20 (BUG-2026-036 investigation) — broader than
previously known, and NOT all handled by the collision-dedup stopgap:**

- `std/gpu/host/_nvidia_cuda.mojo`'s `CUDA(DeviceContext)` /
  `CUDA(DeviceStream)` — a **same-module** (not cross-module) overload
  collision; `gen_module`'s own "overloaded top-level functions ... drop
  them here" pass never compiles a body for it at all (it relies on
  elaboration at a call site, which never happens when
  `build_stdlib_dylib.py` compiles each module standalone). Was crashing
  **every** `mojo.py` invocation at `dlopen` because `reflect.py`'s mirror
  of that drop condition had a separate bug (only matched `fn`, not `def`
  — fixed) and kept advertising it as an export anyway. `build_stdlib_dylib.py`'s
  `build()` now has a general safety net that drops any export whose
  mangled symbol has no compiled definition, so a *reflection-table*
  instance of this bug degrades to "that function falls back to source"
  instead of crashing dlopen — but it does not fix the underlying
  same-module-overload/no-elaboration gap.
- `std/builtin/coroutine.mojo`'s `_coro_destroy_fn` — **FIXED 2026-07-20.** A
  genuinely different flavor from `CUDA`: not overloaded (one `def`), not
  exported (leading underscore), but its mangled symbol differed depending
  on which file computed it (`coro_destroy_fn_0c85c9` when `coroutine.mojo`
  compiles it standalone vs. `coro_destroy_fn_fa7153` expected by
  `device_context.mojo`'s reference to it — passed as a bare function
  pointer to `external_call`, never invoked directly). This was a
  **call-site** reference baked into a compiled function body, not a
  reflection-table entry, so the safety net above couldn't catch or drop
  it — it crashed `dlopen` unconditionally.

  Root cause, traced to source: `AnyCoroutine` is a `comptime` MLIR-type
  alias that `_mojo_type` (gimple_codegen.py) does not special-case by
  name, so both files' codegen treats it as an unresolved annotation and
  falls to `_mojo_type`'s catch-all default, `'int64_t'` — *when the codegen
  itself resolves it*. But `_coro_destroy_fn`'s leading underscore means
  `device_context.mojo`'s import of it never had a dylib reflection entry
  to read a signature from (reflect.py never exports underscore-prefixed
  names — by design, matching real Mojo's visibility rules), so it fell
  back to `module_loader.py`'s `ModuleLoader.load_module` — a second,
  independent, source-regex-based signature extractor with its **own**,
  differently-defaulted `_mojo_type_to_c` (unknown-type default: plain
  `'int'`, a 32-bit C int, not `int64_t`). `hashlib.md5(','.join(['int64_t'])...)[:6]`
  = `0c85c9`; `hashlib.md5(','.join(['int'])...)[:6]` = `fa7153` — exactly
  the two observed symbols, confirming the divergence was entirely this one
  inconsistent default between two parallel type-mapping implementations,
  not a deeper structural cross-module-resolution problem.

  Fix (per CLAUDE.md's "consolidate duplicates, don't maintain parallel
  implementations"): `module_loader.py`'s `_mojo_type_to_c` now delegates to
  gimple_codegen's own canonical `_mojo_type` (the same function reflect.py's
  `_c_signature` already reuses for the dylib-reflection import path) instead
  of maintaining a second, drifted-out-of-sync copy. A handful of shapes
  `_mojo_type` doesn't see from this call site (an already-C-shaped `'...*'`
  string, the runtime's bare `MojoList`/`MojoDict`/`MojoSet` spelling, a
  bare un-bracketed `UnsafePointer`) are still special-cased locally before
  delegating. Verified: fresh from-scratch `libmojostdlib.dylib` build,
  `nm -u` on the dylib no longer references any `coro_destroy_fn_*` symbol,
  and `python3 mojo.py hello.mojo` runs end-to-end with no dyld error.
  Regression test: `test_module_cache.py`'s
  `test_cross_module_free_func_mangling_agrees` recreates the same shape
  (an underscore-prefixed function taking an unresolvable-type parameter,
  defined in one module and referenced by value from a sibling that must
  fall back to `module_loader.py`) and asserts the two files agree on one
  mangled symbol; reverting the `module_loader.py` fix makes it fail with
  the real linker error (undefined symbol), confirming it actually exercises
  this bug.

  **Not fixed by this change** (different root cause — see `mojo_abs` above):
  a case where the SAME file's own codegen genuinely produces the same C
  parameter-type hash for two truly different Mojo source types (e.g. SIMD
  vs Complex both boxing to `int64_t`) still collides; that needs
  Mojo-source-type-aware or module-qualified mangling, which is a much
  larger, more invasive rework (touching `_func_csym`/`overload_suffix_for`
  at every emission site in gimple_codegen.py and its reflect.py mirror) and
  was deliberately not attempted here — this fix only closed the *narrower*,
  concretely-diagnosed "two parallel type-mapping implementations disagree
  on their unknown-type default" gap that was actually blocking every
  interpreter invocation.
- Roughly **35 more exports** across many stdlib modules (`mojo_max`,
  `mojo_min`, `mojo_sum`, `MojoList_append`, `tuple`, `any`, several
  `Parser`/`Interpreter` methods, …) were found to have zero compiled
  definitions anywhere in a from-scratch dylib build — presumably more
  unresolved-cross-module-struct-collapses-to-`int64_t` collisions like
  `mojo_abs`, just never previously visible because `dlopen` aborts the
  whole process on the *first* unresolved symbol it binds, and `CUDA`
  happened to be first. Now silently dropped from the reflection table by
  the safety net (source-fallback instead of a crash) rather than
  individually root-caused.

**FIXED (real fix, not the collision-dedup stopgap) — 2026-07-28, commit
`bf96f55` + follow-up.** Free-function C symbols are now module-qualified
(`GimpleGen._func_qualifier` / `reflect._func_export_csym`'s `module_prefix`
param), the same mechanism struct methods already used
(`_struct_method_qualifier` / `_struct_method_csym_static`), extended to
free functions: a genuinely LOCAL definition is qualified with the
compiling module's own name; an IMPORTED reference resolves its true
defining module via `_imported_func_home` (and, for `do_imports=True`
inline builds, the per-instance `_own_imported_func_home` — see below),
populated at every import site (`_emit_stdlib_import_externs`,
`_register_link_imports`, and `gen_module`'s `do_imports` inline-compile
loop) so a caller and the definer always agree on the same qualified
symbol. `gimple_codegen.py` and `reflect.py` compute the qualifier
identically, keeping codegen and the reflection-table emitter in agreement
per this project's "single source of truth" convention.

Note: the originally-cited `math.abs(SIMD)` / `complex.abs(Complex)`
collision no longer reproduces in the current stdlib snapshot — `math.abs`
is now generic (`def abs[T: Absable](...)`), and generics are never
overload-mangled free-function exports (`collect_exports_src`'s existing
generic detection excludes them). Verified instead via a direct, faithful
minimal repro of the same collision shape (two sibling modules each
defining `def sb1_scale(x: Int64) -> Int64` — `Int64` always boxes to plain
`int64_t`, exactly like the historical case) —
`test_sb1_cross_module_same_c_param_overload_mangling` in
`test_module_cache.py`. A from-scratch dylib rebuild shows 0
excluded-for-collision both before and after this fix (unchanged from
baseline, since the concrete `mojo_abs` collision had already evaporated
independently).

**A real bug in the first version of this fix (`bf96f55`), found by
independent verification via `mojo.py build`'s actual CLI path (NOT
`build_stdlib_dylib.py`'s per-module-standalone-compile pipeline, which
never shares/nests `GimpleGen` instances the way `do_imports=True` builds
do) — fixed same day:**

1. `_imported_func_home` was a single dict SHARED across every nested
   `temp_gen` a `do_imports=True` build spins up
   (`_compile_imported_module`), keyed by bare function name via
   `setdefault`. Two sibling modules each defining the SAME bare
   free-function name (exactly the SB-1 shape) — e.g.
   `alpha_module.sb1_probe_x` / `beta_module.sb1_probe_x` — caused the
   SECOND module's own local definition to silently be emitted under the
   FIRST module's qualifier: a hard `redefinition of
   'alpha_module_sb1_probe_x_...'` compile error. Fixed by checking
   `_local_top_level_func_names` (this exact compile's own top-level
   `FunctionDef`s) FIRST in `_func_qualifier`, ahead of any imported/shared
   registry.
2. Even with (1) fixed, a SEPARATE, worse bug remained for CALL SITES: two
   sibling WRAPPER modules (`alpha_wrapper.mojo` doing `from alpha_module
   import f`, `beta_wrapper.mojo` doing `from beta_module import f`, both
   transitively imported into one program — an entirely ordinary way to
   organize sibling modules, not an exotic pattern) each correctly know
   their OWN function's true home from their OWN `FromImportStmt` — but the
   shared dict's first-registered-wins semantics meant the SECOND wrapper's
   call site silently CALLED the FIRST module's function instead of its
   own: a real, silent, WRONG-RESULT miscompile with no build error at all.
   Fixed by giving each `GimpleGen` instance its own private
   `_own_imported_func_home` dict (never shared across nested `temp_gen`s),
   checked ahead of the shared `_imported_func_home` fallback in
   `_func_qualifier`.
 3. A narrower RESIDUAL, found while fixing (2) and for a long time
    deliberately left NOT-fully-fixed (a proper fix needed per-lexical-scope
    import tracking this codegen didn't have): ONE file with two different
    NESTED (function-body-local) scopes each importing a same-named free
    function from two DIFFERENT sibling modules (`def call_alpha():
    from alpha_module import f; ...` / `def call_beta(): from beta_module
    import f; ...` in the SAME file) is genuinely ambiguous to
    `_own_imported_func_home`, which is per-`GimpleGen`-INSTANCE, not
    per-lexical-scope — both nested imports live in the same root instance.
    Before hardening, this silently picked whichever sibling module was
    processed first (confirmed: printed the SAME value from both call sites
    instead of two distinct ones) — a real silent miscompile. Hardened by
    detecting the same-instance conflict (`_note_own_func_home` marks the
    entry `_AMBIGUOUS_FUNC_HOME` instead of keeping the first value) and
    having `_func_qualifier` raise a clear, honest `RuntimeError` if that
    specific ambiguous name is ever actually looked up — never silently
    miscompile, even though the codegen couldn't correctly COMPILE this
    shape (workaround: rename one of the two functions, or use `import X` +
    `X.func(...)` qualified access instead of `from X import func`).

    **FIXED FOR REAL (2026-08-01):** `GimpleGen` now tracks imports per
    lexical scope — `_import_scope_stack` (a stack of `{bare_name ->
    module_qualifier}` dicts; frame 0 is the module's own top-level scope,
    every function/method body pushes its own frame) populated from this
    module's own `from X import ...` statements
    (`_emit_stdlib_import_externs` for top-level, `_gen_stmt_FromImportStmt`
    + `_collect_body_import_bindings` pre-scan for function/method bodies),
    with a later same-scope import shadowing an earlier one exactly like the
    interpreter's `Scope.define`. `_func_qualifier` walks the stack
    innermost-first, so a bare-name reference resolves to whichever module
    its LEXICALLY-CLOSEST enclosing import statement bound it to. This also
    fixes `std/memory/__init__.mojo`, whose two top-level imports of `alloc`
    (`from .alloc import alloc` + `from .unsafe_pointer import alloc` — two
    genuinely different sibling functions) used to trip the same
    `_AMBIGUOUS_FUNC_HOME` refusal on the standalone-compile path; the
    second top-level import now shadows the first, exactly as Mojo/Python
    scoping dictates. The `test_sb1_ambiguous_same_scope_import_refuses_
    not_miscompiles` test was updated accordingly:
    `test_sb1_per_scope_import_distinct_modules` now asserts the nested-scope
    shape COMPILES and the binary prints both distinct correct values
    (112/223), matching the interpreter. The identical class of gap, via the
    analogous `_imported_struct_home`, already existed and STILL exists for
    STRUCTS (confirmed unaffected by this session — still a hard
    `redefinition` compile error, not hardened to a clean refusal) — this is
    a general, pre-existing `do_imports=True` architectural limitation, not
    novel to free functions, and a full fix for structs is still future
    work.

    Also confirmed, separately and NOT fixed here (pre-existing on vanilla
    master before any SB-1 work, unrelated to overload-mangling): aliased
    free-function-VALUE imports (`from X import f as g`) never resolve
    their call site to the real mangled symbol via `mojo.py build`'s
    `do_imports=True` path at all (falls to a generic `(...)` vararg stub
    that never links) — even for a single, non-colliding aliased import.
    This is what stops the ORIGINAL coordinator-reported repro (two sibling
    modules, top-level ALIASED imports) from fully linking+running
    end-to-end even after the redefinition fix above: the redefinition is
    gone, but the alias-call-site bug still blocks the final link. Real,
    confirmed, but a different code path from anything SB-1 touches.

    Regression tests: `test_sb1_mojo_build_cli_wrapper_modules` (real
    `mojo.py build` CLI subprocess, wrapper-module shape, asserts distinct
    correct results 112/223) and
    `test_sb1_per_scope_import_distinct_modules` (asserts the nested-scope
    shape now compiles and prints both distinct, correct values 112/223,
    matching the interpreter), both in `test_module_cache.py`.

---

## SB-2 — Per-OS modules define the same symbols (FIXED at build level)

**Symptom:** dylib link failed with `duplicate symbol '__c_stat___init__'`,
`__stat`, `__lstat`, `__build_pw_struct`.
The stdlib ships per-OS variants that define identical symbols:
`os/_macos.mojo` vs `os/_linux_x86.mojo` vs `os/_linux_aarch64.mojo`;
`pwd/_macos.mojo` vs `pwd/_linux.mojo`. The dylib builder linked **all** of them.

**Nature:** build structure — only the host OS's variant should be in the dylib.
**Fixed** in `build_stdlib_dylib.py` (`_excluded_platform` filters non-host
`_linux`/`_macos`/`_windows` modules).

---

## SB-4 — `setvbuf` external_call arity vs the system `<stdio.h>` prototype

**Symptom:** `std/sys/_libc.mojo:105` — `too few arguments to function 'setvbuf';
expected 4, have 2`. The wrapper carries all four params but its `external_call`
forwards only two:

```mojo
def setvbuf(stream, buffer, mode: c_int, size: c_size_t) -> c_int:
    return external_call["setvbuf", c_int](stream, buffer)
```

**Not a naive "forgot the args" bug — `setvbuf` is a *special* FFI case.** Mojo's
buffered-IO model deliberately keeps the libc binding lean: the C status return is
dropped and re-surfaced as `raises` (check the code internally, panic on failure
instead of returning an ignorable int), and the buffer crosses the boundary as a
lifetime-tracked type (not a raw pointer), so the compiler enforces that the buffer
outlives the stream. The thin `external_call` is intentional within that design.

The blocker for our backend is purely the **C-level arity clash**: our prelude
includes `<stdio.h>`, whose `setvbuf(FILE*, char*, int, size_t)` prototype is in
scope, so a 2-arg call is rejected. The compiler-side resolution is to not let the
system prototype constrain this call — e.g. emit the `external_call` target with a
matching/variadic local prototype (as we already do for other reserved libc
wrappers) rather than deferring to `<stdio.h>` — so the intentional Mojo binding
compiles. (If `mode`/`size` are genuinely meant to reach libc, that part is a
source question for upstream; the design above is why they may not be.)

---

## SB-3 — `unlink`-style raising wrappers share a name with the libc symbol

**Observation (not a bug, documents an interaction):** Mojo's `os.unlink` is
`raises` and returns nothing; internally it calls
`external_call["unlink", Int32]` to read the C status and raises on failure.
The Mojo wrapper (`mojo_unlink`, void) and the libc `unlink` (Int32) share the
bare name `unlink` in the codegen's `func_return_types`, which let the void
wrapper's type shadow the external call's `Int32` and silently drop the status
into a `void` temp. Fixed in codegen (BUGS-STDLIB / commit: `_emit_call` never
coerces a used result through a `void` shadow). Recorded here because the
name-sharing is a property of the stdlib's libc-binding pattern.
