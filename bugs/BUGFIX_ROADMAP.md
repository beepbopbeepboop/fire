# Bug-fix roadmap: next 30 items

**Snapshot:** 2026-09-25. This is the working queue for the bug-fix campaign. It is
ordered by user impact and tractability, not by document age. Each item names
the bug document that owns the detailed evidence. Start at the top, land a real
fix plus regression coverage, run targeted checks, fix everything the change
uncovers, and only then run the full gate.

Items marked **BLOCKER** must be resolved before spending time on lower-tier
compile failures. Items marked **SHARED** change machinery used by many
consumers and need extra care, not avoidance.

## Generator/iterator feature work (2026-09-25, landed — read this before
## starting the next generator item)

The user redirected the campaign away from the memory/native-infrastructure
class ("too soul sucking") toward Python feature work, generators first. What
landed, all with regression coverage in `test_generators.py` (interpreter),
`test_gimple_generator_runner.py` (compiled) and `test_gimple_runner.py`:

1. **Generator EXPRESSIONS are real lazy generators on both paths.**
   `fire_compiler.genexp_body` is the single definition of what
   `(x for x in xs)` means as statements; `fire_compiler.desugar_genexps`
   (called from `gimple_codegen`'s one compile choke point, before the
   coroutine lowering) rewrites each expression into a call to a synthesized
   module-level generator FUNCTION, and `myinterpreter._generator_expression`
   hands the same body to `MojoGeneratorObject`. Laziness is observable and
   tested (early `break` over an unbounded source).
   - Left on the old eager path ON PURPOSE, because a faithful lowering is
     not expressible yet: a captured name that is rebound anywhere in the
     enclosing function (real Python closes over a mutable cell), a `self`
     reference, and an outermost iterable that is neither a literal, a
     never-rebound module-level name, nor a call to `range`/`enumerate`/
     `zip`/`reversed`/`sorted` (inlining an arbitrary call would re-evaluate
     it on first resume).
2. **`g.send(v)`** resumes a compiled generator with a value for the yield
   it is suspended on, including the double bit-cast (new runtime helper
   `__mojo_gen_send_d`, and the matching unbox for `x = yield <double>` in
   the body, which previously bound the raw slot bits).
3. **Standard consumers of a generator**: `sum`/`any`/`all`/`max`/`min`/
   `list`/`set`/`tuple`/`join`/`in`, plus `sorted` and `zip`, all work over
   one. `zip(...)` as a value now returns a real `MojoList *` of pair-lists.
4. **Two silent-wrongness fixes found on the way**: consuming a generator no
   longer DESTROYS it (a second pass was a use-after-free), and
   `String`/`Int`/`Float`/`Bool` (Mojo's capitalized constructors) lower
   like their lowercase builtins instead of as a bare C cast of the
   argument.
5. **Two honest refusals** rather than subtly wrong code: `g.throw()` and
   `g.close()` inject an exception INTO a suspended body, which the A3
   stack-switch coroutine lowering cannot express (a propagating `.throw()`
   escapes the caller's `except`; `.close()` skips the body's `finally`).

### The next generator items, in order

6. **`.throw()` / `.close()`** — needs exception injection into a suspended
   A3 coroutine body: the body's exception-frame slice is currently
   restored over the caller's live frame, and a `finally` does not run on an
   injected throw. `runtime/fire_coro_gen.c` already has `__mojo_gen_throw`
   and `__mojo_coro_destroy` already does the mode-2 close injection.
7. **Generator expressions over a local/parameter iterable**
   (`sum(x for x in items)` inside a function) — the most common remaining
   fallback. Needs container-typed generator parameters (today the A3
   param-kind inference is scalars only, `coro.py`'s
   `_scan_callsite_param_kinds`).
8. **Generators that yield containers** — a compiled generator's value slot
   carries scalars only, so `yield list(...)` prints a raw pointer. Affects
   any generator expression whose element is a container.
9. **`enumerate(x)` / `sorted(x, key=...)` in VALUE position** — both are
   pre-existing, non-generator gaps: `mojo_enumerate` is an identity
   passthrough (so `list(enumerate(gen()))` is silently empty) and `sorted`
   ignores a key function for every input type. The `for i, v in
   enumerate(x)` form is correct.
10. **`module_may_have_supported_generator`** does not textually detect a
    generator expression, so a genexp-only module is routed through the
    cached compile path. Harmless today (the A3 lowering and the runtime
    link both key off the generated C, not the source text) but worth
    making explicit.

## Ordered queue

| # | Bug document | Priority | Why it is here | Next bounded action / done condition |
|---:|---|---|---|---|
| 0 | `CODEGEN_arm64_cmp_flags_and_loop_signedness.md` | **SHARED** | arm64 conditional/loop selection is landed and green, but comparisons involving a negative value and a *variable* are still wrong: unannotated `int` is modelled `UInt64` and `common_type` resolves mixed to unsigned. Also holds the 13 remaining formal sorries, whose single root cause is that `while_dec_exit_contract` is register-shaped. | Signedness: build the minimal failing matrix (negative literal vs unannotated local, `0 - 3` vs literal) before changing `function_var_types` — the default is shared with the truncators, CSET width and the x86-64 shift/compare mnemonics, so a one-line flip needs the full gate. Proofs: parameterise that contract's test (a WIP pass proved the countdown shape) and add the per-condition-code closing-lemma table beside `_COND_LEMMA`. |
| 1 | `CODEGEN_bootstrap_resource_blowup.md` | **BLOCKER** | Full native Stage 2 still intermittently `SIGTRAP`s on the large transitive dump; bootstrap/gate cannot be trusted. | Capture a deterministic native failure and fix the memory/invariant root cause. Done when repeated `make stage3` and the full gate complete without a native trap. |
| 2 | `COMPILE_FAIL_Tools_wasm_wasi___main__.md` | **BLOCKER** | `nonlocal` is silently miscompiled: the compiled program exits 0 with the wrong closure value; it also affects compiler self-host source. | Add `NonlocalStmt` parsing, interpreter no-op support, closure capture, and plain-`=` write-back. Done with a compiled program whose outer variable changes exactly as CPython does, plus the wasm repro. |
| 3 | `COMPILE_FAIL_importlib_resources_readers.md` | HIGH | `yield from cls.<generator>` is refused; the same machinery affects `Lib/enum.py`, a core stdlib module. | Fix the `cls` receiver/delegation path in the C++ generator emitter. Done with synthetic classmethod-generator coverage; do not claim `readers.py` green until its independent `re.Match`/`reversed(list(...))` blockers are also fixed. |
| 4 | `COMPILE_FAIL_Android_android.md` | HIGH | Broad stdlib surface remains blocked by async/Awaitable eligibility gaps. | Inventory the smallest async subset, extend the eligibility table with regression cases, then iterate file-by-file. |
| 5 | `COMPILE_FAIL_Lib_contextlib_request_for_member_module_in_something_not_a_structure_or_union.md` | HIGH | Core `contextlib` module failure affects many stdlib consumers. | Isolate the first non-scalar `__aenter__`/variadic `__aexit__` shape and implement the smallest typed-boxing/packing fix. |
| 6 | `COMPILE_FAIL_Lib_socket_request_for_member_module_in_something_not_a_structure_or_union.md` | HIGH | Socket stdlib failure shares the async/module-typing class with contextlib. | Reuse the contextlib fix where possible; otherwise fix the socket-specific receiver/type boundary and add a focused repro. |
| 7 | `COMPILE_FAIL_Apple___main__.md` | HIGH | Compile stage is fixed but runtime still fails through a stubbed argparse subsystem. | Finish the smallest runtime-backed argparse path needed by the real file; keep unsupported APIs honest rather than silently stubbing them. |
| 8 | `COMPILE_FAIL_Mac_BuildScript_build-installer.md` | HIGH | A real packaging script still has one stale global-type error, and the inline path can silently miscompile the same pattern. | Fix the global type join across `global` reassignment; done when both link-mode and inline generated C agree and the file builds. |
| 9 | `COMPILE_FAIL_ctypes_macholib_dyld.md` | HIGH | Platform stdlib module failure has historically caused wrong C symbol/ABI behavior. | Reproduce the smallest dyld/find-library expression and fix its type/receiver lowering without weakening diagnostics. |
| 10 | `COMPILE_FAIL_ctypes_util.md` | HIGH | Core ctypes utility failure blocks other platform modules. | Reduce to the first failing helper, fix its argument/return typing, and run the focused ctypes suite. |
| 11 | `COMPILE_FAIL_Modules__decimal_tests_randdec.md` | MEDIUM | Numeric correctness test module remains a useful precision/typing canary. | Fix the first numeric literal or conversion mismatch and add a boundary regression before chasing the rest. |
| 12 | `COMPILE_FAIL_Tools_c-analyzer_c_common_scriptutil.md` | MEDIUM | Shared c-analyzer utility failure affects several analyzer entry points. | Fix the shared consumption-ordering/parameter-value path once, then verify all analyzer consumers instead of patching each caller. |
| 13 | `COMPILE_FAIL_Tools_c-analyzer_c_analyzer___main__.md` | MEDIUM | Only a small number of generator refusals remain after earlier fixes. | Finish the remaining generator shape(s) with focused compile-and-run tests. |
| 14 | `COMPILE_FAIL_Tools_c-analyzer_c_analyzer_info.md` | MEDIUM | Analyzer info module has a bounded remaining failure after one prior fix. | Reproduce current first error, fix its narrow type/consumer boundary, and keep unrelated analyzer failures separate. |
| 15 | `COMPILE_FAIL_Tools_c-analyzer_c_parser_datafiles.md` | MEDIUM | Data-file parser has a dynamic-callee/tuple-unpack gap. | Add a minimal dynamic-callee test and implement the missing value provenance, not a broad dynamic fallback. |
| 16 | `COMPILE_FAIL_Tools_c-analyzer_c_parser_parser___init__.md` | MEDIUM | Parser package is shared by the analyzer tools and exposes a specific value-flow gap. | Fix the smallest parser-only repro, then run the c-analyzer parser tests. |
| 17 | `COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md` | MEDIUM | Table utilities remain blocked by the same callable-parameter/tuple-unpack family. | Reuse the datafiles/parser value-provenance fix and add a table-specific regression. |
| 18 | `COMPILE_FAIL_Tools_jit__targets.md` | MEDIUM | JIT tooling is blocked by async eligibility and `TemporaryDirectory()` support. | First fix the async shape that blocks the smallest target, then handle the context-manager path separately. |
| 19 | `COMPILE_FAIL_Tools_gdb_libpython.md` | MEDIUM | Large but well-decomposed gdb/libpython build failure. | Reduce to the first remaining `.cpp` coroutine error family and land one shared fix at a time; avoid re-chasing already-fixed earlier errors. |
| 20 | `COMPILE_FAIL_Tools_importbench_importbench.md` | MEDIUM | Benchmark tooling has documented unreachable blockers; only fix it if a live repro shows a reachable root cause. | Re-verify current failure shape; if still unreachable, mark the stale doc closed rather than spending implementation time. |
| 21 | `COMPILE_FAIL_Tools_scripts_summarize_stats.md` | MEDIUM | Closure-returning nested `def` blocks a real script. | Add the smallest closure-return/value-passing capability needed by the script, with a runtime check. |
| 22 | `COMPILE_FAIL_Tools_cases_generator_parsing.md` | MEDIUM | Polymorphic `yield from self.<field>.tokens()` exposes a real generator-receiver gap. | Add a minimal polymorphic-receiver generator test and implement receiver lowering without erasing the call shape. |
| 23 | `COMPILE_FAIL_importlib_metadata___init__.md` | MEDIUM | Loop-variable/field typing leaks into nested helper parameters. | Fix the loop-variable field provenance at its source, then verify the importlib metadata path end-to-end. |
| 24 | `COMPILE_FAIL_zipfile___init__.py` | MEDIUM | Archive tooling has multiple independent blockers and a prior attempted fix regressed self-host. | Split the doc into independent sub-bugs; do not retry the reverted broad fix. Land the smallest memoryview/generator or link-mode slice independently. |
| 25 | `CODEGEN_generator_function_Lib_mailbox.md` | MEDIUM | Mailbox is blocked by a non-generator module refusal, not the old tuple-yield issue. | Fix the current foreign-base-class/struct refusal first; only then revisit mailbox-specific behavior. |
| 26 | `CODEGEN_generator_function_Lib_enum.md` | MEDIUM | Enum’s dynamic metaclass attributes are the real blocker, not just generator syntax. | Model the minimum `EnumMeta.__new__` classdict-to-class-attribute flow with a real test; refuse only what is genuinely unsupported. |
| 27 | `CODEGEN_generator_function_Lib_test_test_string_test_string.md` | MEDIUM | Nested class-in-function support is larger than the old tuple-shape diagnosis. | Implement the three pieces named by the doc: hoist nested struct, seed class attributes from generator bodies, and allocate/seed instances correctly. |
| 28 | `CODEGEN_generator_function_Lib_test_test_frame.md` | MEDIUM | Real stdlib generator consumer remains refused. | Isolate its first unsupported generator shape and land a shared fix if it overlaps items 3/22; otherwise add a focused emitter change. |
| 29 | `hard/CODEGEN_function_scoped_import_module_not_inlined.md` | **SHARED** | A function-scoped `from mod import Name` records the import's signatures but never inlines `mod`, so the call lowers to the "unavailable in compiled mode" weak stub and silently returns 0. (Landed 2026-09-26 out of the removed `..._rettype_and_literal_cast_mismatches.md`, whose four GIMPLE-type mechanisms were all verified fixed.) | Call `_compile_imported_module` from the function-scoped `FromImport` branch, sharing the closure's dedup sets; separately, stop the weak stub from being silently callable. Owes the full gate plus manual re-triage of the `COMPILE_FAIL_*.md` corpus — a comparable cross-module resolution fix has regressed that corpus before. |
| 30 | `hard/CODEGEN_ctor_arg_field_type_scalars_only.md` | **SHARED** | The ctor-call-site field-typing pass understands only scalars, so a list argument still yields an `int64_t` field that segfaults on iteration; and a field value round-tripped through a local loses its type. (Landed 2026-09-26 out of the removed `CODEGEN_unannotated_init_param_field_type_defaults_int64.md`, whose scalar/IdentExpr/MemberExpr cases were all verified fixed.) | Either widen the field representation or refuse honestly when the observed argument type cannot be stored; add the `t = self.f; return t` local-provenance rule. Register `test_gimple_runner.py` in `tools/suite.py` first — it is in no bucket, so neither existing regression test runs. |

## Recently completed or intentionally excluded

- `CODEGEN_all_any_dict_set_miscompile.md` — fixed.
- `CODEGEN_arm64_cmp_flags_and_loop_signedness.md` — added as item 0; the landed half (B.cond selection, loop exits, spill sign) is documented in `BUG.md`, and the doc owns what is still open.
- `CODEGEN_boxed_method_name_list_set_ambiguity.md` — fixed.
- `CODEGEN_container_free_registry_dangling_entries.md` — resolved.
- `CODEGEN_container_no_deallocation_unbounded_growth.md` — resolved.
- `CODEGEN_large_dict_accumulation_exit_crash.md` — no longer reproduces.
- the `struct` module and the `bytes` value type — both landed, and their
  hard-bug reports have since been removed per the fully-fixed-is-deleted
  rule. Live residue found while verifying them lives in
  `hard/CODEGEN_struct_kwargs_and_inline_unpack.md` and
  `hard/CODEGEN_bytes_silent_wrong_values.md`.
- `hard/CODEGEN_coro_nested_async_closure_capture.md` — landed, report removed 2026-09-26; live residue is in `hard/CODEGEN_coro_captured_param_capture_crashes.md` (capturing an enclosing function's *parameter* crashes the compiler, and this doc's own regression file is orphaned at 0/9).
- `COMPILE_FAIL_Tools_build_umarshal.md` and `COMPILE_FAIL_Tools_build_deepfreeze.md` — compile blockers resolved; remaining items are runtime/adjacent and need a new doc if pursued.
- `hard/PERF_nested_module_compile_walk_ast_quadratic_rescan.md` — excluded from this queue because the documented candidate optimizations are unsafe without a new design.
- `hard/CODEGEN_same_bare_name_struct_collision_across_modules.md` — deferred as high-risk shared machinery until a reachable default-path repro is identified.
- `CODEGEN_noshim_dumpfull_preexisting_divergence.md` — already-active investigation, not a new queue item.
- `hard/CODEGEN_generator_lambda_expr_unsupported.md` — deliberately guarded miscompile; only revisit with a new supported-shape design.

## Working rules

1. One queue item at a time; do not bundle unrelated fixes.
2. Reproduce before editing and add a regression that fails before the fix.
3. Run the smallest relevant test immediately, then the full gate once targeted work is clean.
4. If a fix changes a previously tracked `.ci` baseline, record the baseline change and prove it is intentional before accepting it.
5. Do not call a doc closed because the first error disappeared; verify the original end-to-end file or explicitly record the remaining independent blocker.
6. Update this roadmap when an item is fixed, split, or proven stale so future sessions do not repeat triage.
