SPLIT: CODEGEN_stdlib_dylib_lazy_undefined_refs-part5 (part 6 fixed 2026-11-17, doc deleted)

# CODEGEN: the stdlib dylib references 50 `_std_` symbols it never defines

**Job:** none. This is the latent half of `stdlib-dylib`, which now passes because the JOB's contract is
that the dylib LOADS (a data/class-table reference to an undefined symbol is fatal there; see
`tools/stdlib_dylib_ratchet.py`). These 50 are lazy CALL references: they do not stop the load, but a
client that reaches one through the dylib aborts at that call unless another image happens to define it.

## Replan (2026-11-15): the live parts are 5-6 (part 9 landed)

Parts 1-3, 4, 7, 8 and 9 landed and their docs were deleted when they landed:

- part 1: a re-exported free function's reference carries the DEFINING module's
  qualifier (`_reexported_defining_qualifier`).
- part 2: an imported free function's overload suffix is the DEFINING unit's
  (the text-scan `Span`/`StringSlice` -> `char *` mapping).
- part 3: a same-arity struct dunder names one concrete overload (subscript
  dispatch and the comparison lowering); the suffix-less forward declaration
  for an overloaded dunder is gone. The total was 50 -> 43 -> 32 by
  2026-11-14, with 0 modules falling back to source.
- part 4: a `comptime if` chain over `CompilationTarget` predicates emitted
  every target's bodies. `eval_const` / `eval_const_int` / `_const_foldable`
  now fold `CompilationTarget.<pred>()` to the host constant, so the lowering
  keeps only the host branch, and `_drop_unreferenced_extern_decls` strips the
  extern declaration blocks left for the folded-away targets. The four
  `std_os__linux_{aarch64,x86}__{lstat,stat}` references from
  `std/os/path/path.mojo` are gone; none new.
- part 7: a parameter typed with a struct private to the DEFINING module
  (`benchmark._run_impl(opts: _RunOptions)`) is `Name *` there but `int64_t`
  in the importer's text scan, so the two hashed different overload suffixes.
  The importer now hashes the definer's list (`_home_signature_ctypes`, ranked
  ahead of the shared slot by `_imported_private_struct_pts`) while still
  DECLARING and CALLING the extern with the opaque `int64_t` word: naming
  `Name` there makes the importer lower `.field` as a typed `->` against a
  struct it never defines. 32 -> 31 undefined `_std_` names, the one that went
  being `_std_benchmark_benchmark__run_impl_9f63a2`; none new.
  Follow-up 2026-11-17: the same rule missed a home struct spelled BARE
  (`_GraphemeBreakState *` in `_grapheme_break.mojo`, not the tag form
  `struct N *`). The private-struct test now accepts both spellings, skipping
  generic home structs (`SIMD`, whose call sites are elaborated per instance
  and must keep the scanned hash). The definer list is recorded once, in the
  early import pass (`emit_infra`, `_home_private_pts_by_name`), because call
  sites are generated before the import block is written. Grapheme pair
  `..._is_grapheme_break_c427b8` and `..._reset_grapheme_state_to_other_9f63a2`
  now resolve to the definer's `5d88b0` / `de8baa`. 10 -> 8 undefined.
  Still open: `_std_random__rng__get_global_random_state_55072c`. The definer
  is `void f(_RandomState *)` (an `out` parameter) and the importer declares
  `int64_t f(int64_t *)`; hashing the definer's list alone creates a
  conflicting-types error at the call site, so the out-parameter calling
  convention must be fixed together with the hash, not one or the other.

  **Planning guide (2026-11-17), the `out` parameter convention.** Measured
  this round, not inferred:
  - A local `out` parameter is not implemented at all. For
    `def make(out r: Box): r = Box(7)` the definition is
    `void m (Box * r)` with body `r = _t1` (it assigns the pointer, it does not
    write through it), and the caller emits `m (0);` then `b = 0`. So a local
    call loses the result too; this is not specific to the cross-module case.
  - `mut` parameters already work end to end: `setv(mut r: Box)` is
    `void setv (Box * r)` and the caller passes `b`, and the body writes through
    `r.v`. That is the convention `out` should reuse.
  - Scope: 110 stdlib files use `out`. Most are `out self` (constructors, a
    different path) and `out result: ...` returns. The random failure is
    `std.random._rng.get_global_random_state(out result: Pointer[_RandomState,
    ...])`, one of the few free functions with an `out` result.
  Plan, in order:
  1. Definition side: in the function emitter, a parameter with `out`
     convention is bound like a `mut` parameter (pointer, reads and writes
     through `*r`), and the function returns `void`. Files: the param binding
     in `emit_funcs.py` (where `mut` is recognised), `module_gen.py`.
  2. Call side: `make()` with an `out` parameter is elaborated to a fresh local
     of the out type whose address is the argument; the call expression's value
     is that local. Files: `elaborate.py` (call elaboration, where the argument
     list is built) so both local and imported calls get the same rewrite.
  3. Import side: the import scan records the out parameter's pointee type and
     the `void` return, so the extern declares `void f (T *)` and the hash uses
     the definer's list (the part-7 path, already in place).
  Status 2026-11-17 (landed): steps 1 and 2 for LOCAL free functions. A
  caller that omits an `out` struct argument allocates the object
  (`emit_calls._lower_out_param_call`, at the top of `_lower_call`) and the
  call's value is that object; an assignment to the `out` name in the body
  copies into it (`emit_stmts._lower_out_param_store`: `*r = *value`). Scope is
  deliberately narrow: `out self` is excluded, methods are excluded, and a
  generic annotation (`out task: Task[...]`) is excluded because its C slot is
  a word. A first version without those limits broke 15 stdlib files and 47
  build errors; the restriction is what the gates measured. Test:
  `test_out_param_local.py` (compiles the module and runs it, expects 7).
  Status 2026-11-17 (step 3 landed): the cross-module case. The import scan
  declares an `out` function `void` when its annotation is plain (no `[`), and
  the caller rewrite finds the callee in its home module's parsed statements
  (`emit_calls._root_function_def`). `test_out_param_local.py` now also runs a
  two-module round trip (expects 7). Still open: the random name is NOT this
  convention. Its `out result: Pointer[_RandomState, ...]` is a pointer RESULT,
  not an object the caller fills; the right fix is to return the pointer
  (`_RandomState * f(void)`), a separate change to the definer's signature and
  the caller's use of the value.
  Status 2026-11-17 (overload selection for an imported name): the import scan
  records a name defined more than once as a variadic `name(...)` stub, which
  names no overload, so `bitset.mojo`'s `unsafe_memset_zero(ptr, count)` bound
  to the bare stub. `emit_calls._imported_overload_call_symbol` now picks the
  overload from the HOME module's own statements (following a package
  re-export to the defining module), and declares it. It decides ONLY when
  exactly one plain (non-generic) overload fits the call's arity and the call
  supplies every parameter; anything else keeps the stub. Both call paths use
  it (`_lower_named_call` and the statement path in `emit_stmts`).
  `test_import_overload_choice.py` fails on the committed code and passes here.
  Undefined `_std_` names: 8 -> 7 (`unsafe_memset_zero` resolved).
  Not done, found while doing it: (a) a defaulted or ambiguous overload set
  (`assert_equal`, `b64encode`, `time.sleep`) still falls back: the imported
  call path does not fill defaults, and the chooser does not see argument types;
  (b) `std.time.time` emits NO `sleep` symbol at all, so `_std_time_time_sleep`
  stays undefined whatever the caller names; (c) the scan takes an overload
  set's return type from its LAST overload, so the declaration can differ from
  the definer's (`unsafe_memset_zero` is `void` there, `int64_t` in the import).
  Gates: stdlib-syntax 610/610, dylib 1203/1203 with 0 errors, test_gimple
  465/0, lint and ratchet clean.
  Status 2026-11-17 (time.sleep, landed): two causes, both fixed. (1)
  `module_gen`'s overload guard dropped EVERY overload of a name whose plain
  overloads include an `external_call[...]` body. The stdlib builds clean with
  those overloads emitted, so that branch is removed; the generic-struct branch
  stays. `time.sleep`'s two overloads were both missing. (2) The import choice
  now also uses the lowered argument C types (`emit_stmts` moves the hook after
  the arguments are lowered): when exactly one plain overload fits the arity it
  is taken as before; when several fit, the one whose parameter types equal the
  arguments' is taken (an integer literal's `int` matches Mojo's 64-bit `Int`).
  `time.sleep(1)` and `time.sleep(1.5)` now name `_9f63a2` and `_f77bd1`.
  `test_import_overload_choice.py` gained two cases: argument-type selection
  (fails on the committed code) and external_call overload emission.
  Undefined `_std_` names: 7 -> 6. Still open: `random` (its `Pointer`-result
  change is parked in stash@{0}) and the `_std__gpu_intrinsics` / `bit_mask` /
  `getpw` generic instances.
  Status 2026-11-17 (random, landed): `out result: Pointer[T]` is a pointer
  RETURN, not a value the caller fills. `mojo/middle/out_result.py` lowers it
  (the definer and the import parse both apply it), and the import scan mirrors
  the rule, including the same "body reads the name" bail. `_struct_name_of`
  strips the `struct ` tag so a struct private to another unit names its method
  `<home>_<Struct>_<method>`. `test_out_param_local.py` gained a cross-module
  pointer-result case (expects 9). Undefined `_std_` names: 6 -> 5 (random gone).
  Still open: the gpu `mulhi`/`mulwide` instances. Found: `fast_div`'s
  `mulhi(self._mprime.cast[.uint32](), ...)` inside a generic struct reaches the
  Int64 overload, because `.cast[.uint32]()` lowers to a 64-bit word and loses
  its type. That is a wrong-result bug, not only a link gap. The elaborator
  route to the definer's symbol was tried and reverted: choosing on erased
  argument types picked the wrong overload.
  Previously open (now done): step 3, the cross-module import. Gates:
  stdlib-syntax 610/610, dylib 1203/1203 with 0 errors, test_gimple 465/0.
  Hook points found 2026-11-17 (no code landed; the slice is not safe alone):
  - Callee chosen: `mojo/backend_gimple/emit_calls.py` ~11650-11676, where
    `_def` (the FunctionDef) and `_sym` are resolved. `_def.param_convs` gives
    the `out` names. The argument list is built after this point from
    `node.args`, so the synthetic temp must be threaded in there.
  - Temp: a struct result is allocated with `_alloc_<Struct>()` (seen in
    emitted C); `gen._emit_call(ret, tmp, fname, arg_pairs)` emits a call from
    pre-lowered `(ctype, value)` pairs (`emit_resolve.py:2445` `_call_expr`).
  - Callee writes: an assignment to an `out` name must copy into the caller's
    object (`*r = *value`), not rebind the pointer. Struct locals are heap
    pointers and today's `b = Box(9)` only rebinds (`emit_stmts`, the Assign
    lowering).
  - Local-only first: `_closure_call_stmts` (emit_calls.py ~70) gives the
    module's root FunctionDefs; the cross-module case needs the import entry.
  Decision needed: do steps 1-2 for ALL `out` free functions (the general fix,
  large: the 110-file population) or only `out result` free functions
  (sufficient for the 1 remaining dylib name, but leaves `out` broken elsewhere).
  Tests: a local `out` round-trip (`var b = make(); b.v == 7`), the same across
  two modules (cross-module import of `out`), and the stdlib-syntax and
  dylib counts. Do not land the import hash alone: it creates a conflicting
  type at the call site (shown above).
- part 8: two same-name free functions in one module each get a definition
  under their own mangled symbol, and a call names one of them — by
  arity/argument types inside the module, by the defining unit's first
  non-generic declaration across modules. Two overloads that erase to the
  same C signature get `_<n>` disambiguation rather than one being dropped.
  The generic half of a mixed plain+generic name is instantiated in-TU
  (`splat[.int]`), and overloads whose bodies cannot be emitted correctly
  because of an unrelated platform/external-call typing bug keep the
  historical "not emitted" disposition instead of failing the module.
- part 9 (landed 2026-11-16, doc deleted): a generic free function
  instantiated only by ANOTHER module is now emitted by its defining module.
  `build_stdlib_dylib._generic_instance_requests` reads each caller object's
  references (`nm -u`), matches an erased signature to a top-level
  `def <name>[` in the module that owns the symbol's qualifier, and recompiles
  that module once with the monomorphized instance appended, emitted under the
  caller's exact symbol (the caller's own `_func_csym` spelling) in the
  defining module's own translation unit. Pinned by
  `test_dylib_generic_instances.py` and the `p9_generic` probe.

The title's "50" is the 2026-11-12 measurement and is stale; the live
residual is the table below. Measured 2026-11-15 in this worktree by compiling
each caller and definer module with `compile_module_to_c` and comparing the
undefined `_std_` names against the definers' exported names (no whole-stdlib
build, no link), then confirming the end-to-end shape with two-module
`build_stdlib_dylib.build` dylibs. The probes are
`test_stdlib_dylib_lazy_undefined_refs_probes.py`.

| part | doc | class | example symbols |
|---|---|---|---|
| 5 | `...-part5.md` | a body the backend cannot lower vanishes, so the caller's qualified name has no definition (its own calls get a BARE weak stub) | `std_sys_info_is_{apple,nvidia,amd}_gpu`, `std_python__cpython_CPython_as_imm` |
| 6 | fixed 2026-11-17, doc deleted (its probe `p6_bracketed` passes) | a BRACKETED `Span`/`StringSlice` param is `char *` in the text scan and `Span *` in the defining unit | 4 x `std_collections_string__unicode_*`, `_count_utf8_continuation_bytes`, `std_sys__amdgpu_printf_append_string_n` |

Not a part:

- The five `_std_ffi___init___OwnedDLHandle_*` references from
  `std/python/_cpython.mojo` are not a name mismatch. Their defining module,
  `std/ffi/__init__.mojo`, does not compile in this tree at all:
  `std/ffi/__init__.mojo:360:0: error: invalid bindings in signature: lacking
  evidence` (the same error `std/simd.mojo` gives at 2247). A module that
  falls back to source is the dylib's documented, accepted state; making ffi
  compile is a diagnostics/elaboration bug (see the `lacking evidence` note in
  `bugs/hard/DIAGNOSTICS_missing_validation_modular.md` and
  `test_binding_deferral_diagnostic.py`), not this doc's name-resolution work.
- The Array/Deque/List `__getitem__` entries in the old bare-dunder list are
  gone after part 3; the in-flight
  `CODEGEN_simd_and_array_values_erase_to_int64` lane is not touched by these
  parts.
- The `unresolved_stdlib_refs` count is not made a gate condition here: the
  ratchet's contract is still "the dylib LOADS", and the parts shrink the lazy
  gap one class at a time.

**Working the parts:** each part's `## Done when` names one probe in
`test_stdlib_dylib_lazy_undefined_refs_probes.py`; run it red first, fix, run
it green. The probe file is deliberately not a registered gate job. Part 4's
probe (`p4_target`) now passes.


**This section is the 2026-11-12 snapshot**, kept for the measurements'
provenance. Several of its group diagnoses are superseded by the
`## Replan (2026-11-15)` table above (notably: `mask_splat` is
`std/bit/mask.mojo`'s `splat`, an overloaded free function, and
`_run_impl` is a suffix mismatch, not a missing function).

**Measured on master `793118227`, 2026-11-12**, with the ratchet's own build and the `nm` pair the bug
doc for the matcher used:

    python3 tools/stdlib_dylib_ratchet.py        # builds build/libmojostdlib.<arch>.dylib
    nm -u  build/libmojostdlib.arm64.dylib       # 50 _std_ names below
    nm -gU build/libmojostdlib.arm64.dylib       # none of them is defined
    dyld_info -fixups build/libmojostdlib.arm64.dylib   # all 50 are lazy-bind __la_symbol_ptr

The names, grouped by what the DEFINITION is actually called (the group is the cause):

- **Overload suffix disagrees with the definition's** (same symbol, different hash):
  `_std_collections_string__parsing_numbers_parsing_floats__atof_55072c` vs defined
  `..._atof_d719e0`; `_std_collections_string__unicode_is_lowercase_55072c` vs `..._fa3cf4` (same for
  `is_uppercase`, `to_lowercase`, `to_uppercase`,
  `_std_collections_string__utf8__count_utf8_continuation_bytes_55072c`). The call site's
  `_effective_param_types` is not the defining unit's signature. **The suffix half is fixed**
  (`module_loader`'s text-scan maps `Span`/`StringSlice` parameters to `char *`, the defining unit's
  lowering) — re-measure the remaining names.
- **Qualifier is the re-exporting package, not the defining module**: callers emit
  `_std_memory___init___unsafe_memset_zero`, `..._unsafe_destroy_n_2dbb98`, `..._forget_deinit_9f63a2`,
  `..._alloc_dealloc_9f63a2`, `_std_time___init___sleep`, `_std_os___init___listdir_9f63a2`,
  `_std_pwd___init___getpwnam_d719e0`/`getpwuid_9f63a2`, `_std_random___init___seed`; the definitions
  live in `std/memory/memory.mojo`, `std/time/time.mojo`, `std/os/os.mojo`, `std/pwd/_macos.mojo`, …, so
  their symbols are `std_<module>_...`. **The qualifier half is fixed** (`_reexported_defining_qualifier`):
  references now spell `std_time_time_sleep`, `std_pwd_pwd_getpwnam_d719e0`, etc. This does NOT define a
  symbol that has no emitted definition: `unsafe_memset_zero` is generic/uninstantiated in
  `std/memory/memory.mojo`'s standalone compile, so its reference now names
  `std_memory_memory_unsafe_memset_zero` and stays undefined — that is this doc's
  "Function not emitted at all" class, not the qualifier group.
- **Bare dunder where the definition is overloaded**: `_std_collections_array_Array___getitem__`,
  `_std_collections_deque_Deque___getitem__`, `_std_collections_list_List___getitem__`,
  `_std_collections_string_string_span_StringSpan___{eq,gt,le,lt}__`,
  `_std_ffi_cstring_CStringSpan___eq__`, `_std_memory_pointer_Pointer___{eq,getitem}__`,
  `_std_python__cpython_CPython_as_imm`. `_lower_struct_subscript_dunder` picks an overload only when
  the arity match is UNIQUE; two same-arity overloads leave `overload_id == ''`.
- **Function not emitted at all**: `_std_memory_memory__free` (and `std/collections/string_string.mojo's
  `_calc_initial_buffer_size` reference to `..._int32_9f63a2`/`..._int64_88e58d`), `_std_bit_mask_splat`
  (no source defines `mask_splat`), `_std_benchmark_benchmark__run_impl_9f63a2`,
  `..._compiler_keep_9f63a2`, `_std_bit___init___log2_ceil_9f63a2`, and the `std_sys_info_is_*_gpu`
  family.
- **Target-mismatched**: `_std_os__linux_aarch64__{lstat,stat}_d719e0`,
  `_std_os__linux_x86__{lstat,stat}_d719e0`, `_std_sys__amdgpu_printf_append_string_n_f5e74a` — a macOS
  build's `std/os/path/path.mojo` still references the other targets' bodies.

**Callers per symbol** (module object that carries the undefined reference) were measured the same way:
`std_memory_pointer` → `..._free`; `std_python_python` → `CPython_as_imm`;
`std_collections_string_string_span.local.o` → the `StringSpan` comparisons and the unicode helpers;
`std_benchmark_bencher` → `benchmark__run_impl_9f63a2`; `std_testing_assert_aborts` →
`time___init___sleep`/`perf_counter`; `std_os_path_path` → the linux `lstat`/`stat` and pwd symbols.

**What to expect:** each reference should name the symbol its defining unit really emits (qualifier,
overload suffix, or a body that exists). The gate for this class is a check that says so, not the load
test: run `nm -u` against `nm -gU` and require the `_std_` difference to *shrink*. Do not make
`stdlib-dylib` fail on it until the count is zero: all 50 exist before the fix and the job's documented
contract is that the dylib need not be complete.

**Exact next step:** work parts 5-6, in the order of the table above. Each
part's `## Done when` names the probe that is red today and green when the
part lands. The old advice to take "the arity-only overload choice" is part 3,
which landed; the remaining classes are the replan table's, not this
section's.

## Re-measured 2026-11-15: the JOB is green; 32 references remain

The job this doc was filed against now PASSES:

    python3 tools/stdlib_dylib_ratchet.py
    -> stdlib-dylib: 0 module(s) fell back to source (0 expected)
    -> exit 0

and `tools/control.py gate list` no longer turns `stdlib-dylib` off. The count
is **32**, down from the 50 the Symptom above records (43 after part 1, 32
after part 3). Of the 32, **12 carry no overload suffix** — `_std_sys_info_
is_apple_gpu`, `_std_sys_info_is_nvidia_gpu`, `_std_random_random_seed`,
`_std_time_time_sleep`, `_std_memory_memory__free`, `_std_bit_mask_splat`,
`_std_collections_string_string__calc_initial_buffer_size`,
`_std_python__cpython_CPython_as_imm`, `_std_sys_info_is_amd_gpu`,
`_std_sys_info_has_nvidia_gpu_accelerator`, `_std_time_time_time_function`,
`_std_memory_memory_unsafe_memset_zero` — and the other 20 carry a suffix that
is not the defining unit's.

All 12 unsuffixed ones were calls to an OVERLOADED free function from a module
that did not define it (`std/sys/info.mojo`'s `is_apple_gpu()` has both a
`()` and a `[subarch: StaticString]()` overload). **Fixed 2026-11-15
(`ddc086d41`)**: a MIXED overload set (one plain head + one bracketed head) was
caught by the generic-import registration and returned early, so it never
reached the overload registration, and the opener set `'('` could not even see
a bracketed head; `_elaborate_overload_call` also mangled from the BARE name,
dropping the defining module's qualifier. The references are now correct --
`_std_sys_info_is_apple_gpu__void`, `_std_pwd__macos__getpw_macos__1_0_6_
String` / `__1_0_6_UInt32`.

**The count went 32 -> 38, and that is an honest regression in the metric,
not a fix.** The names are right now, and being right exposes references the
dylib never defined: both `getpw_macos` overloads are referenced where before
only the one the ABI scan happened to pick was, and two `_gpu_intrinsics_`
entries appeared. The job still PASSES (0 modules fall back to source, ratchet
exit 0) because these are lazy call references a client falls back from, but
the definers are still absent from the dylib -- that, not the naming, is now
the visible remaining work.

## 2026-11-15 (later): the next layer -- `external_call` bodies are dropped

The 38 references are not one class. Naming is now right; what remains is that
some DEFINERS contribute no body at all. Measured on
`std/pwd/_macos.mojo` through `build_stdlib_dylib.compile_module_to_c`:

* the module's generated C contains `extern int64_t external_call (...);
  /* from std.ffi */` -- `std.ffi.external_call` was never compiled, only
  declared;
* `_getpw_macos` (both overloads) and `_stat_macos` appear ONLY as guarded
  forward declarations (`#ifndef _MOJO_STUB__getpw_macos` /
  `int64_t _getpw_macos (...);`), with zero occurrences of `getpwuid` /
  `getpwnam` in the whole file -- their bodies are gone;
* `_build_pw_struct` from the SAME module IS defined
  (`_std_pwd__macos__build_pw_struct_9f63a2`), and it is the one that does not
  call `external_call`.

So the correlation is exact: a function whose body calls `external_call` loses
that body. `external_call` is an ordinary generic function in
`std/ffi/__init__.mojo` -- `def external_call[callee: StaticString,
return_type: RegisterPassable, *types: AnyType,
num_fixed_args: Optional[Int] = None](*args: *types) -> return_type` -- so the
gap is the VARIADIC generic call (`*args: *types` captured and forwarded), not
the FFI lowering itself. This is a different and deeper defect than the naming
one above; filing it here rather than half-fixing it.

## 2026-11-15 (wakeups 24/27): a definer emits NOTHING for an overload family
## -- and it is DOCUMENTED POLICY, not a silent defect

**Correction (wakeup 27).** An earlier revision of this section called the
absence "silent". It is not: `module_gen.py`'s duplicate-def pre-pass
(`BUG-2026-021`, around line 5551) classifies a same-name multi-def group and
deliberately drops it --

* REDEFINITIONS (identical signature key): keep the LAST copy, interpreter
  semantics;
* GENUINE OVERLOADS (differing signature key): drop EVERY copy, on the premise
  that "the elaborator selects and instantiates the right overload per call
  site (slice 4), so no single C definition exists to emit".

Isolated with a cold single-module compile, so the branch is not in doubt:

| module | contents | `splat` in emitted C |
|---|---|---|
| a | two same-name defs, different params | **0** |
| b | one def | 3 |
| c | two DIFFERENT names, one calls the other | 3 |
| d | generic + plain same-name pair | **0** |
| e | two same-name defs, different arity | **0** |

So the trigger is purely the name collision, and `splat` / `unsafe_memset_zero`
/ `is_apple_gpu` are absent for this reason. Reverting all three of the
iteration-19 commits still gives 0, so none of them is implicated.

**What is actually open** is the premise, not the drop: the policy is sound for
a SAME-module caller (slice 4 resolves and inlines), but a library module built
into the dylib has cross-module callers that emit an extern reference to a
symbol the defining module deliberately never emits. That is the whole
remaining population of this table. Measured on `std/memory/memory.mojo`:

* the dylib references `_std_memory_memory_unsafe_memset_zero` (undefined) and
  defines `std_memory_memory_unsafe_memset_37bd8e`;
* compiling that module through `compile_module_to_c` yields a C file in which
  the literal string `unsafe_memset_zero` occurs **zero** times -- both
  declarations (the plain `def unsafe_memset_zero(ptr, count)` at line 381 and
  the generic `def unsafe_memset_zero[dtype: DType, //, *, count: Int]` at 397)
  contribute nothing, and `compile_module_to_c` prints no diagnostic at all.

Ruled out, by temporarily reverting the iteration-19 opener-set change in
`module_gen.py`: the count is still 0, so this is NOT a regression from that
commit (and the file was restored byte-identical -- tree clean afterwards).

The distinguishing feature of the dropped pair: the generic declaration's body
contains a **recursive same-name call with a different arity** --
`comptime if count > 128: return unsafe_memset_zero(ptr, count)` -- where the
compiler has to pick the 2-arg plain declaration over the enclosing generic one.
That is the next concrete thing to instrument: whether overload resolution
inside the body binds to the enclosing generic (self-recursion) and the failure
is swallowed rather than diagnosed. Not fixed here; recorded with the
measurements rather than guessed at.

**Probe caveat, stated rather than glossed.** `compile_module_to_c` on that
module with the correct `module_name_for_path` name yields only 6 distinct
`std_memory_memory_*` symbols, while the built dylib carries 10 (it additionally
defines `std_memory_memory__free`, `..._forget_deinit_9f63a2`,
`..._unsafe_destroy_n_2dbb98`). So the dylib's contents are not exactly
reproducible from a cold single-module compile -- the CAS is serving C the cold
path does not produce. The `unsafe_memset_zero` finding is unaffected (0 in
both), but anyone re-measuring the whole table should recompile rather than
trust either number blind.

## 2026-11-16 (wakeup 28): the unsuffixed half has a precise root cause

The remaining unsuffixed references are not a naming policy, they are a
SWALLOWED EXCEPTION. Instrumented on `std/collections/span.mojo` (which calls
`splat(<Bool>)` from `std.bit.mask`):

1. `splat` IS registered for the importer -- probed at
   `module_gen.py`'s registration site: `sym='splat'` with
   `path=.../std/bit/mask.mojo`, so the overload set is visible.
2. `_elaborate_overload_call` then calls
   `elaborate.Elaborator().elaborate_overload_call(module_src, 'splat', ...)`
   to compile the defining module, and that compile RAISES:
   `RuntimeError: cannot compile module: a bracketed call splat[...]() needs
   link-mode specialisation, which this build does not do`
   (emit_calls.py's `SubscriptExpr` arm, ~line 3014).
3. The `except Exception` around it sets `info = None` and only
   `_debug_note`s, so the call site falls back to the unsuffixed extern
   `std_bit_mask_splat`.

The refusal is deliberate and correct for a single-TU program (its own comment
pins `test_comptime_bracket_params.py::test_paramless_function_bracket_refused_
in_single_tu`), but it is ownership-scoped by `func_return_types` /
`imported_symbols` only -- it does not know it is compiling a module on the
IMPORTER's behalf, where the refusal's premise (no specialisation) does not
apply: the importer only wants the family's signatures.

**Proof that the refusal is the blocker:** with the `raise` temporarily
replaced by `pass`, the same compile emits BOTH `std_bit_mask_splat` and the
correctly suffixed `std_bit_mask_splat__1_0_4_Bool`; restored, only the
unsuffixed one. So one call site gains a real suffix.

**First fix attempt failed, and the measurement is the finding.** Exempting
overload-family names (publishing the dup pre-pass's `_dup_defs` as
`gen._overloaded_fn_names` and testing it in the refusal condition) changed
nothing: probed at the refusal site, `_overloaded_fn_names` is EMPTY there
(`in_frt=True ovl=[] imp=False`). The generator instance that compiles the
imported module is not the one the `module_gen.py` pre-pass populates, so the
exemption never fires. Both edits were reverted (tree clean, the iteration-19
changes verified still present); recorded rather than shipped as a no-op.

**FIXED 2026-11-16 (`a00f40d02`).** The symbol and the signature come from
`mangle_signature`, not from the object, and `_emit_generic_instantiation`
already tolerates `object=None` (a recursive-cycle instantiation returns it).
So `elaborate_overload_call` now keeps them and drops only the link object when
the standalone snippet cannot compile. Measured: `std/collections/span.mojo`
emits only `std_bit_mask_splat__1_0_4_Bool` (was the unsuffixed
`std_bit_mask_splat`); the dylib's undefined `_std_` population falls
**37 -> 31**, and `_std_pwd__linux__getpw_linux__*` now resolves outright.

Of the 31, 16 do not end in a 6-hex overload hash (the other 15 are
already correctly suffixed). Those 16 are now the OTHER half only:
correctly-named references to symbols the definer never emits, because
BUG-2026-021 drops a genuine overload family whole. That policy is the single
remaining cause of this table.

## 2026-11-16 (wakeup 38): the part-1 probe is RED, and it is a real dropped call

`test_stdlib_dylib_lazy_undefined_refs_probes.py` fails:

    AssertionError: std/itertools/itertools.mojo emits no forget_deinit
    reference; probe is stale

Measured, and narrowed:

* `std/itertools/itertools.mojo:30` imports `forget_deinit` from `std.memory`
  and `:259` calls `forget_deinit(arg^)`, inside the generic `_flatten`
  (`:222`).
* compiling that module yields **zero** occurrences of both `forget_deinit` and
  `_flatten`.
* `_flatten` has exactly one definition, so this is NOT the BUG-2026-021
  overload-family drop.
* its two call sites (`:321`, `:452`) are inside `__next__` methods of iterator
  structs, and those `__next__` symbols ARE emitted -- so the enclosing methods
  exist while the `_flatten(...)` call inside them resolves to nothing.

Ruled out as the cause: the iteration-19/31 commits (re-running with them
reverted still gives 0) and Mike Stump's part 7 (`emit_funcs.py` at
`f766bb314~1` also gives 0). So a generic call inside an emitted struct method
is being dropped, which is a different defect from every item above. The
probe's message says "stale"; the measurement says the call is gone, so the
probe is right and the tree is wrong.

## 2026-11-16 (wakeup 40): why the call is dropped -- a silent 0, and the guard
## that should have caught it is on a different code path

The emitted body is the answer:

```c
__GIMPLE int64_t std_itertools_itertools__Product3___next__ (_Product3 * self)
{
  int64_t _t1;
bb_2:
#line 321 ".../std/itertools/itertools.mojo"
  _t1 = (int64_t)0;  /* indirect call via SubscriptExpr */
#line 321 ".../std/itertools/itertools.mojo"
  return _t1;
}
```

`itertools.mojo:321` is `return rebind_var[Self.Element](_flatten(next(self._inner)))`.
The callee is a **bracketed call whose base is `rebind_var`** -- a builtin, not
imported (the module's only import is `forget_deinit`), and not a function this
TU defines. So it misses every arm of `emit_calls._lower_call`'s
`SubscriptExpr` branch: not the ownership-scoped refusal (that needs
`name in func_return_types and name not in imported_symbols`), not a struct
constructor dispatch, not an imported-symbol stub. It falls to the
`indirect call via SubscriptExpr` fallback, which returns integer `0` -- and the
inner `_flatten(...)` call is discarded with it. That is a SILENT WRONG ANSWER:
`__next__` returns 0 rather than the flattened tuple.

There IS a guard for exactly this shape: `elab_intu._FLAT_NEXT_RE` /
`_rewrite_product_next` (with a comment naming this very line). It never runs.
Probed: instrumenting `_rewrite_product_next` to print every call while
compiling this module produced **no output at all** -- `monomorphize_source` is
not on the `compile_module_to_c` path that builds the stdlib dylib, so the
rewrite is dead code here and the `rebind_var[...]` shape has no guard on the
path that matters. (Probe removed; tree clean.)

So the probe's red is two facts: a wrong-answer fallback that is unguarded on
this path, and a guard that exists but is wired to a different entry point.
