# Bug-fix roadmap: next 28 items

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

Rows are removed as they land, not left struck through: a completed item
whose document has been deleted is indistinguishable from an open one to
whoever reads this next. Two were removed 2026-09-29 —
`COMPILE_FAIL_Tools_wasm_wasi___main__.md` and
`hard/CODEGEN_ctor_arg_field_type_scalars_only.md`, both landed
2026-09-27 with their docs deleted at the time. The numbering below is the
ORIGINAL queue number, kept stable so a row can still be referred to by
the number it was assigned when it was filed.

| # | Bug document | Priority | Why it is here | Next bounded action / done condition |
|---:|---|---|---|---|
| 0 | `CODEGEN_arm64_cmp_flags_and_loop_signedness.md` | **SHARED** | **CODEGEN half DONE 2026-09-26; the only remaining work is PROOFS, and was deliberately left alone 2026-09-27** (that session was redirected away from `formal/`). Unannotated `int` is SIGNED, `common_type` is signed-wins, the loop contracts are parameterised over the loop test, the 8 loop-contract `sorry`s are closed, `test_formal_run.py` is 91/91. "Still open 3" is entirely inside `formal/`: the `dec`-while and `range` MODELS assume a non-negative counter, plus 2 named `sum_range` holes. | Nothing in the compiler. Next session with `formal/` budget: the models — `pred_iff` and `countdown_go` need the `m < 2^63` split a signed `int` forces, `prog_correct`'s step case needs a branch for "the loop does not run", and `sum_range_loop_cond_flag` is restated with a signed order, with a reusable `Nat`-to-two's-complement signed-order lemma in ProofLib as the shared piece. NOT VERIFIED this session: `test_formal.py` was deliberately not run. |
| 1 | `CODEGEN_bootstrap_resource_blowup.md` | **BLOCKER** | **2026-09-27 round 2: the masking segfault is STILL the first thing that happens, so the `mojo_boxed_is_str` guard fix was deliberately NOT applied this round and the triage behind it is still unmeasured.** Reason, unchanged: `CLAUDE.md`'s `expect=` anti-rot rule turns three marked-for-failure steps into gate FAILURES the moment the binary stops crashing, and nothing behind the first AST walk has been measured, so the honest sequence is to land the guard and triage the new SELFHOST-CRASHED wave as its own piece of work with the gate's time budget for it. Everything else landed this round (two registered compile-and-run suites, `@classmethod` in the oracle, staticmethod generators on both backends, `asyncio.run(<name>)`, the parser's decorator arguments) moves the compiled path but is untestable end-to-end until the binary runs. | Apply the 31-bit-tag-range guard in `mojo_boxed_is_str` (the full chain is in `CODEGEN_noshim_dumpfull_preexisting_divergence.md`'s 2026-09-27 entry), then run `make gate` and triage the SELFHOST-CRASHED set as the real work. **ADVANCED 2026-09-27 (localised, NOT fixed).** The `vmmap` probe this row's own step 3 asked for is done and answers it: on the real self-host input (`./mojoc --dump-full fire_compiler.py`) the malloc zone holds **11.4 GB across 130,462,322 live blocks at t=12 s** (mean 87 B, only 953 mappings, 1% frag) growing linearly to **58.6 GB / 1.24 T instructions / SIGTRAP(133)** — so it is a never-frees ACCUMULATOR of ~670M small objects, not a leak-of-record, not a miscomputed fixed arena, and not one hot loop (a 5 s `sample` is flat). The tokenizer is ruled out as the volume source (14.8 MB of source across the three seed passes vs 670M blocks). **Supersedes BLOW.md §4's "do not go looking for the per-module leak first"**, which was derived from the now-fixed 15.84 GB false-positive. Untested next lever: per-module AST lifetime. See the doc's 2026-09-27 section for the full rule-out list. |
| 3 | `COMPILE_FAIL_importlib_resources_readers.md` | HIGH | **Both generator gaps this doc was opened for are now FIXED with compile-and-RUN coverage, and the file's first blocker has moved twice.** The `@classmethod` `yield from cls.<sibling generator>` gap (round 1) and the `@staticmethod`-generator gap (this round) are both closed on BOTH coroutine backends, by one shared rule: `fire_compiler.method_receiver_kind` — decorator first, first parameter's name second — which replaced three consumers that each read the name alone and therefore each classified a `@staticmethod` as receiver-less. Four fixes: `module_gen.py`'s free-function generator loops now skip by MEMBERSHIP (`_struct_method_ids`) instead of by first-parameter name, so a method's coroutine unit can no longer be emitted under the free-function symbol `_mojogen_<name>`; `coro.py`'s A3 `_eligible`/`_lower_one` read the shared rule, so a `@staticmethod` no longer declares a `self` the caller never passes nor drops its first real parameter; `cpp_async.py`'s `_gen_cpp_generator_unit` accepts a receiver-less method; and `emit_methods.py`'s call site reads the api entry's `receiver` key instead of unconditionally prepending one. Three new cases in `test_gimple_generator_runner.py`, **now registered as `gimplegenerators`** — they were unregistered, so round 1's own regression never ran in the gate. | The file itself is NOT green and this is now measured, not guessed: it gets all the way to gcc and has two errors of its own — a cross-module symbol-name mismatch (`__itertools_only_<hash>` emitted where `_itertools_only_<hash>` is defined) and `re_finditer` (the `re` module falls back to source interpretation, so a call on it inside a coroutine body has no compiled symbol). Fifteen sibling modules of the closure also fail (`pathlib` 19, `_bootstrap_external` 15, `_os` 10, `tokenize` 8, `glob` 7, `statistics` 6, `_common` 6, `random` 4, `numbers` 4, `_functional` 4, `tempfile` 2, `_adapters` 2, `_bootstrap` 1, `fractions` 1) plus an upstream `shutil` `'open' is ambiguous` refusal. **LANDED 2026-09-27 (the symbol-name blocker):** the mismatch was `_register_sym` in `mojo/middle/module_shared.py` — the only one of five module-string→C-prefix manglers that omitted `lstrip('.')`, so `from ._itertools import only` gave the call site `__itertools_only_<hash>` against a `_itertools_only_<hash>` definition. One token (`s.module.lstrip('.')`). Verified on the real file (the `readers.ci:322744` call site now matches the definition; that one line is the only diff) plus a fails-before regression, `test_module_cache.py`'s `test_underscore_prefixed_sibling_import_symbol`, which asserts the call site and definition use ONE identifier spelling — necessary because in the minimal shape a sibling TU accidentally satisfies the bad name and a link/exit-code assertion passes on the broken tree. STILL OPEN: the `re` one (`_sre` objects have no compiled representation — feature-sized) and the fifteen sibling modules. Doc stays. |
| 4 | `COMPILE_FAIL_Android_android.md` | HIGH | **The `asyncio.run(<non-literal>)` bridge is built — BOTH halves, not one.** Static: `_scan_handle_vars` accepts a name this function binds from `create_task(...)` or from a call to an `async def` this module actually compiled (new `_ASYNC_FN_NAMES` registry, filled from the same eligibility verdicts that create the `__mgco_<name>_start`). Runtime: `__mojo_async_run_gen` now checks the handle against a live-handle registry — added at the single allocation site, removed at the single free site — and raises `ValueError: a coroutine was expected`, Python's own answer, with the tag spelled as `663468903` so a compiled `except ValueError:` catches it. Also fixed a one-token latent bug in the neighbouring `_scan_task_vars` (it tested `isinstance(s.target, ...)` against the STATEMENT, so a bare `task = create_task(f())` never registered). Regressions on both sides: `test_runtime_diff.py`'s `asyncio_run_of_a_name`, and `runtime/test_fire_coro_gen.c`'s `test_run_gen_rejects_non_handle` (driven at the C level, because every shape the compiler can get wrong is already refused statically). Also closed earlier in round 1: `await` nested in a call's argument list. | The async subset is still refused for all 9 remaining functions (`async_process`, `async_check_output`, `list_devices`, `find_device`, `find_pid`, `logcat_task`, `read_logcat`, `gradle_task`, `run_testbed`) — their `await` targets are `create_subprocess_exec` / `communicate()` / `wait()` / `readexactly()` / a local `wait_for` helper. That is the async-subprocess/stream composition layer, feature-sized, and the same project `COMPILE_FAIL_asyncio_queues.md` describes. The bridge does NOT move it: `android.py`'s own `result` comes from `dispatch[context.subcommand](context)`, a dynamically-obtained coroutine with no statically-named callee, so half 1 still refuses it — correctly. A general dynamic-callee handle would be a separate piece. |
| 5 | `COMPILE_FAIL_Lib_contextlib_request_for_member_module_in_something_not_a_structure_or_union.md` | HIGH | Core `contextlib` module failure affects many stdlib consumers. | Isolate the first non-scalar `__aenter__`/variadic `__aexit__` shape and implement the smallest typed-boxing/packing fix. |
| 6 | `COMPILE_FAIL_Lib_socket_request_for_member_module_in_something_not_a_structure_or_union.md` | HIGH | Socket stdlib failure shares the async/module-typing class with contextlib. | Reuse the contextlib fix where possible; otherwise fix the socket-specific receiver/type boundary and add a focused repro. |
| 7 | `COMPILE_FAIL_Apple___main__.md` | HIGH | Compile stage is fixed but runtime still fails through a stubbed argparse subsystem. | Finish the smallest runtime-backed argparse path needed by the real file; keep unsupported APIs honest rather than silently stubbing them. |
| 8 | `COMPILE_FAIL_Mac_BuildScript_build-installer.md` | HIGH | A real packaging script still has one stale global-type error, and the inline path can silently miscompile the same pattern. | Fix the global type join across `global` reassignment; done when both link-mode and inline generated C agree and the file builds. **ATTEMPTED AND REJECTED 2026-09-27** (see the doc's new top section): a first version DID make `fire.py build` succeed with zero errors, but `--dump-full` still declared `char * FW_VERSION_PREFIX` and cast a `MojoList *` into it — a silent miscompile that links — and making the paths agree regressed link mode from 1 error to 10. Diagnosis is now much narrower than "high-risk shared machinery": **three** sites re-derive this global's type (Phase 1.7, `_gscan_declare_global`, and an as-yet-unidentified `_<mod>_toplev` field emitter — `global_decls` is NOT emitted, `module_gen.py:7281`), and `_phase17_value_type` has no `BinaryOp` row at all, so it reports no container evidence for `FW_PREFIX[:] + [...]`. An implementation is preserved in `stash@{0}`. The bar stands: build AND link/inline agreement. |
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
| 29 | ~~`hard/CODEGEN_function_scoped_import_module_not_inlined.md`~~ | ~~SHARED~~ | **LANDED 2026-09-29 — doc DELETED.** Both pipelines now agree with CPython on every one of its rows (11/11 shapes measured, incl. a no-import control). The link-mode half was three independent defects, not the one the doc predicted: (1) `mojo/middle/funcs_shared.py::_parsed_import` could not resolve a bare, non-dotted, local `.py` sibling at all (`imports.resolve_source` is MOJO_PATH-relative, `_resolve_test_relative_module` is `.mojo`-only), so `_register_link_imports` got `source=None` and registered nothing — now falls back to `_submodule_source_path`, the resolver `_compile_imported_module` already used for the same name, so the two can no longer disagree; (2) the source-text classifier that routes a name with no concrete export was written out TWICE inside `_register_link_imports` and neither copy knew `class X:` (a hard keyword to `fire_compiler._parse_struct`), so a class import was never inlined at all — now ONE `_classify_unresolved_export`; (3) `gen_module_impl` had a second, hand-rolled copy of the inline-compile loop for link mode that skipped the cross-module hint pre-passes, so a struct in a link-inlined sibling compiled with int64_t field defaults and the client's constructor became a hard GIMPLE `non-trivial conversion` — now one loop, two sources for the module set. A fourth defect surfaced doing the work and is in the same family: the mangled symbol's qualifier half is computed in two places and they disagreed on a DOTTED module name (`sub_tri_...` vs the real `p_sub_tri_...`). The doc's own suggested item 2 (stop the weak stub being silently callable from a call site the compiler knows is a real import) needs no separate work: such call sites no longer reach it. | Regression coverage is in `test_link_mode.py` (5 new cases, each comparing against CPython run on the same text in the same directory, through the real `driver.compile_program`) and `test_gimple.py` (`user_defined_dunder_repr_is_called`, `user_defined_dunder_repr_value` — the latter runs BOTH pipelines). Residue found while re-triaging, filed separately and NOT part of this bug: `CODEGEN_link_mode_bare_submodule_marker_call_silent_wrong_value.md` (a `linkmode` gate step already red on master), `CODEGEN_reexported_function_import_qualifier_names_the_wrong_module.md`, `CODEGEN_import_dotted_name_two_hop_attribute_call_exits_1.md`, `CODEGEN_return_type_not_inferred_from_a_method_call_result.md`, `CODEGEN_user_defined_dunder_repr_not_consulted_by_str_and_container_spellings.md`. |
| 30 | ~~`hard/CODEGEN_ctor_arg_field_type_scalars_only.md`~~ | ~~SHARED~~ | **LANDED 2026-09-27 — doc DELETED** by `0e87ed4` ("redo the discarded ctor-arg fix, plus 9 more real codegen bugs"). All three shapes now type the field correctly: a container literal, a field value round-tripped through a local (`t = self.f; return t`), and the residue — a container reached through one extra hop (a local bound to a container literal, or a `self.<field>` read of a field the caller's own struct sets to a container literal). The residue's fix is a third purely-syntactic evidence pass beside the existing literal-argument one, feeding the SAME unanimity-gate dicts — not the context observer (`_arg_scalar_type`) a prior attempt tried and reverted after it broke `test_selfhost.py` (that observer runs after the field-write pass that needs its answer, and on the wrong `GimpleGen` instance for an imported module). **Do not resurrect this doc:** an earlier "DONE" marker on this row referred only to the *prerequisite* that `test_gimple_runner.py`/`test_gimple_generator_runner.py` were registered in `check` — real and worth keeping, but not this bug. | `test_gimple.py` 326/326 (two new regression tests), `test_selfhost.py` green, `test_gimple_runner.py`/`test_gimple_generator_runner.py` unaffected (both pre-existing failures on `master` confirmed unrelated via `git stash`). |

## Recently completed or intentionally excluded

- `CODEGEN_all_any_dict_set_miscompile.md` — fixed.
- `CODEGEN_arm64_cmp_flags_and_loop_signedness.md` — item 0, partially landed 2026-09-26 (signedness + the loop-contract parameterisation); the doc keeps ownership of the loop-model gap.
- `CODEGEN_boxed_method_name_list_set_ambiguity.md` — fixed.
- `CODEGEN_container_free_registry_dangling_entries.md` — resolved.
- `CODEGEN_container_no_deallocation_unbounded_growth.md` — resolved.
- `CODEGEN_large_dict_accumulation_exit_crash.md` — no longer reproduces.
- the `struct` module and the `bytes` value type — both landed, and their
  hard-bug reports have since been removed per the fully-fixed-is-deleted
  rule. `hard/CODEGEN_struct_kwargs_and_inline_unpack.md` had both its items
  **closed 2026-09-27** (keyword arguments bound per CPython 3.14's measured
  signature table; mixed int/float formats correct through every
  statically-indexed read), and keeps only the residue it names: a read with
  no compile-time slot index has no single right C type in a `MojoList`, and a
  `Struct` reached through a class attribute has no recoverable format. The
  `f"{list}"`/`str(list)` gap found on the way is its own doc,
  `CODEGEN_fstring_and_str_of_a_list_are_garbage.md`.
  `hard/CODEGEN_bytes_silent_wrong_values.md` had **items 1-5 and 6b closed
  2026-09-27** (plus three more wrong values found on the way:
  `partition`'s swapped no-match arms, its empty-separator case, and four
  `str` predicates that did not exist and answered `0`), and keeps only
  **item 6a**: `partition`/`rpartition`'s container TYPE, which cannot be
  fixed without introducing a tuple type — this runtime has none, and a
  tuple literal is a marked `MojoList`. Two test expectations that asserted
  the CPython-wrong answers were corrected, not worked around.
- `hard/CODEGEN_coro_nested_async_closure_capture.md` — landed, report removed 2026-09-26; live residue went to `hard/CODEGEN_coro_captured_param_capture_crashes.md`, which is itself **closed and removed 2026-09-29**: item 1 (capturing an enclosing function's *parameter* crashed the compiler) 2026-09-27; item 2 (the regression file orphaned at 0/9, one case asserting the pre-Increment-E answer) 2026-09-27, now 10/10 and registered as `coro-nested-capture`; item 3 (a capture-independent `async for`-over-a-generator gap printing `0` where CPython prints `11`) 2026-09-29 — plus three residues that re-testing the doc's own "Verified genuinely fixed" list turned up: a wait-descriptor bound as the `async for` loop variable (a heap address, exit 0), two nested `async def`s sharing one captured local (a generated-code argument-count error), and Increment D's honest refusal not existing on the `MOJO_CORO=cpp` backend.
- `COMPILE_FAIL_Tools_build_umarshal.md` and `COMPILE_FAIL_Tools_build_deepfreeze.md` — compile blockers resolved; remaining items are runtime/adjacent and need a new doc if pursued.
- `hard/PERF_nested_module_compile_walk_ast_quadratic_rescan.md` — excluded from this queue because the documented candidate optimizations are unsafe without a new design.
- `hard/CODEGEN_same_bare_name_struct_collision_across_modules.md` — **closed and removed 2026-09-29**: the deferred high-risk shared machinery landed (module-qualified C identity for colliding same-named structs), and the doc is gone rather than kept as a monument; the mechanism and what shipped are summarised in `bugs/hard/README.md`.
- `CODEGEN_compiled_path_gaps_round2.md` — **NEW 2026-09-27 round 2.** Four
  compiled-path gaps found by synthetic probe while landing this round's
  fixes, none of which any tracked doc covered: an inherited `@classmethod`
  / generator method is neither resolved nor rebound through a subclass; `x ==
  None` is False for a NULL `char *` (so every `d.get(k) == None` guard
  takes the wrong branch — pre-existing, found by accident); a heterogeneous
  `dict | dict` has no static value type; and a cross-module symbol-name
  mismatch (`__itertools_only_<hash>` emitted where `_itertools_only_<hash>`
  is defined) that blocks a whole module. Each is ordered there by how likely
  it is to bite real code.
- `CODEGEN_noshim_dumpfull_preexisting_divergence.md` — already-active investigation, not a new queue item.
- `hard/CODEGEN_generator_lambda_expr_unsupported.md` — deliberately guarded miscompile; only revisit with a new supported-shape design.

## Working rules

1. One queue item at a time; do not bundle unrelated fixes.
2. Reproduce before editing and add a regression that fails before the fix.
3. Run the smallest relevant test immediately, then the full gate once targeted work is clean.
4. If a fix changes a previously tracked `.ci` baseline, record the baseline change and prove it is intentional before accepting it.
5. Do not call a doc closed because the first error disappeared; verify the original end-to-end file or explicitly record the remaining independent blocker.
6. Update this roadmap when an item is fixed, split, or proven stale so future sessions do not repeat triage.
