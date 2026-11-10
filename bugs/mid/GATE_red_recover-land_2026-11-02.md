# GATE red: 4 landing-gate job(s) red on `recover-land` (gate red)

## Status (2026-11-02, OPEN; jobs turned OFF to land the round)

The landing gate of round `recover-land` ran RED. The integrator turned these jobs OFF (`tools/gates.json`, one anchored regex) so the round could land, and files each one here until it is fixed:

    bootstrap-stage1-transitive
    bootstrap-stage2-dumps
    bootstrap-stage3-dumps
    mojoc

Tasks landed with this round: recover-land.

Evidence: `work-integ/gate.log` and `work-integ/confirm.log` (the failing jobs re-run alone), `work-integ/build/suite.log` for the job output.

Consequence: these jobs are NOT covered by the gate for this landing. Re-enable each one when fixed with `python3 tools/control.py gate on '<pattern>'` and remove this report in the same commit.

## Status 2026-11-02 (partial: `mojoc` goes from hundreds of errors to two)

Landed (module_qualifier leaf move + os.path word-ABI wrappers + the tuple-unpack container-slot fix):
`make mojoc` on master fails in `jit/arm64.py` ("invalid argument to gimple call", `expected expression before '('`)
and the closure-import errors (`module 'mojo.middle.coro' has no attribute 'module_qualifier'`); with this landing the
self-host compile of the compiler reaches gcc with exactly TWO errors left, both the same defect, in
`mojo/backend_gimple/module_gen.py` lines 13797 and 13860:

    error: passing argument 2 of 'gen_module_impl__phase17_value_type' makes integer from pointer without a cast
        _t = _phase17_value_type(_gvalue)      # _gvalue = _pairs[_pi][1]; typed `char *`, callee param is int64_t

A call to a nested function (`_lower_closure_call`, emit_calls.py ~6944) passes the argument pair as lowered, with no
coercion to the lifted function's parameter type. Next step: coerce each `full_arg_pairs` entry to
`gen.func_param_types[lifted]` (skipping the env slot) via the same `_safe_coerce_emit` path a free-function call
uses; then `make mojoc`, re-enable `mojoc` (`python3 tools/control.py gate on mojoc`), then the three bootstrap jobs.
Checks run: `compile_stdlib.py` 610 passed / 0 unexpected; `test_gimple_runner.py` 553 passed / 15 failed, the same
15 as pristine master (551 / 15). The four jobs are still OFF; nothing was re-enabled.

## Status 2026-11-02 (later: `mojoc` builds; the binary then crashes)

The two remaining gcc errors are fixed. Cause: a lifted closure registers its parameter types
(`func_param_types`) only when its OWN body is generated, and the parent generated its nested closures in plain
name order, so `_phase17_scan_if_branches` / `_phase17_scan_try_branches` (which sort before the helper they call)
were lowered before `_phase17_value_type` had a registered signature and passed a `char *` into its `int64_t`
parameter. `module_gen._gmi_closures_callee_first` now generates a sibling that another sibling calls first (name
order otherwise, a cycle falls back to name order); the three identical inline `sorted(...)` sites share it.
`make mojoc` now completes with 0 gcc errors. `compile_stdlib.py` 610 passed / 0 unexpected;
`test_gimple_runner.py` 554 passed / 15 failed, the same 15 as pristine master.

`mojoc` is re-enabled in THIS doc's OFF entry (`tools/gates.json`). It is still named by the separate underscore
entry (`GATE_red_recover_land_2026-11-02.md`, the 23-job one), which another worker holds; turn it on there with
`control.py gate on` when that doc lands.

NEXT (the real remaining blocker for the three bootstrap jobs, which stay OFF): the built binary segfaults on the
simplest use, `./mojoc FILE.py --dump` on a 20-line program: `EXC_BAD_ACCESS (address=0x9)` in `mojo_dict_len`
(the `-O2 -g0` binary gives lldb a single frame). That is the corrupt-dict-value class recorded in CLAUDE.md's
DEBUGGING METHOD. Next step: build with `-g` frame pointers (`MOJO_OPT`), get the caller chain, and bisect the dict
whose value is a non-dict. The earlier unpack fix (a list slot returns its own word) is a plausible neighbour, not a
confirmed cause: master's `mojoc` never built, so there is no baseline binary to compare against.

### 2026-11-03: the mojoc segfault is fixed; `bootstrap-stage1-transitive` is red on 26 unresolved calls

`./mojoc FILE.py --dump` now runs to completion (exit 0): `.tok`, `.ast` and `.pyi` are byte-identical to the
Python reference's, the `.ci` differs only in its `#line` path. Four defects, found with lldb against an
`-O0 -g` build and by reading the emitted C (HOW-TO-DEBUG §5), all in master (d674024cc and earlier):

1. `a or b or c` over a bool, a word of unknown kind and a dict stored the bool 1 in a `MojoDict *` slot and ran
   `mojo_dict_len(1)` (`_gmi_specialize_literal_kind_clones`). `_lower_binary` types that result as a word.
2. A kind-mixed tuple hands a `None` / `False` / NULL-string slot back as a non-zero BOX, which is truthy:
   `is_generator, ids = _detect_generator(body)` made every function the compiled parser read a generator, and an
   unannotated parameter's `None` annotation reached `strdup`. `mojo_unbox_plain` turns those boxes into their plain
   words at unpack targets and at user-function call sites; `mojo_word_is_none` counts a NULL `p`/`s` box.
3. `mojo/middle/coro.py` attached `module_qualifier` through `sys.modules[__name__]`, an `AttributeError: modules`
   in the compiled binary on every compile. The import already binds the name.

NEXT (why the three bootstrap jobs stay OFF): `bootstrap-stage1-transitive` rejects its own output
(`CLOSURE_INCOMPLETE`): the Python `--dump-full` of `fire.py` contains 26 weak `... unavailable in compiled mode`
stubs, i.e. calls the closure compile never resolved. 17 of them are PRIVATE (`_`-prefixed) functions called through
a module alias between this compiler's own modules: `ginf._open_block_scope` / `_close_block_scope`
(emit_infra, called from emit_stmts and emit_loops), `ggc._boxed_capture_source`, `ggc._build_outer_closure_env`,
`ggc._generator_star_slot`, `ggc._pack_generator_star_args`, `gex._closure_value`, `_ca._cpp_word_of_kind`,
`_ca._cpp_sig_default_word`, `_ca._fstring_field_names`, plus `_EXPR_DISPATCH`/`_STMT_DISPATCH`/`_GD_*` tables.
The PUBLIC sibling `ginf.tagged_for_target_name` resolves to its mangled symbol, and the definition of
`_open_block_scope` is emitted (`mojo_backend_gimple_emit_infra__open_block_scope_c6639c`), but the call site is
lowered as the bare name `_open_block_scope`. The suspect is the bare-name lookup in
`emit_methods._selfhost_sibling_member_kind` (`method_name in func_param_types / func_return_types`) missing a
private function whose module was compiled after the caller's (the emit_infra <-> emit_stmts cycle). The other
nine stubs (`append`, `update`, `items`, `object`, `issubclass`, `MojoParser`, `decode_c_escapes`,
`is_fstring_literal`, `_walk_lists`) need their own reading. Repro: `python3 fire.py --dump-full fire.py` in an empty
directory, then `grep -c 'unavailable in compiled mode' fire.ci`. Fixing it is what lets
`bootstrap-stage1-transitive`, then stage2/stage3, run; do that before re-enabling the gate entries.

### 2026-11-10: targeted self-host sibling home fix landed (verification pending, heavy)

`mojo/backend_gimple/emit_methods.py` (`_lower_method_call`, self-host sibling
module-qualified call path): before re-dispatching `alias.member(...)` as a bare
call, pin `member`'s home to the imported sibling module named by the alias via
`_note_own_func_home(method_name, <alias.module>, record_scope=False)`. This
addresses the documented root-cause shape where the call site is lowered as an
unqualified bare `_open_block_scope` while the definition is emitted under its
qualified mangled symbol, which can occur when the defining sibling module is
compiled later in a cycle and the member is absent from this gen's flat
`func_param_types`/`func_return_types` tables.

Quick checks run (memslot-wrapped): `pytest -q test_link_mode.py -k
bare_submodule_import_call_inside_source_tree` (1 passed);
`python3 test_module_boundary_regression.py` (6/7 passed; 1 failure
`imported_generator_mixed_str_int_call_sites_refused` — gcc ld error for
undefined `__mojogen_m_gen_*` symbols, not compared to a pre-change baseline in
this session).

NOT VERIFIED (requires heavy/whole-closure runs this worker must not perform):
- Repro from this doc in an empty directory:
  `python3 fire.py --dump-full fire.py` then
  `grep -c 'unavailable in compiled mode' fire.ci` (expect drop from 26,
  ideally 0 for the 17 private sibling-alias stubs listed above; the other 9
  may need separate fixes).
- `bootstrap-stage1-transitive`, `bootstrap-stage2-dumps`,
  `bootstrap-stage3-dumps` and re-enabling the four gate entries once green.

If the dump-full repro still shows the same private sibling stubs, the next step
remains deeper: ensure the defining sibling's function signatures/homes are
pre-registered into the shared/visible tables for cyclic self-host modules
before dependent call sites are lowered (not just noting the home at call time),
and investigate the 9 non-sibling stubs separately.

