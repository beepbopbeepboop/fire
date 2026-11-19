# Restore bootstrap-stage1-transitive closure completeness (replan part 1 of 5)

## Goal

Make `bootstrap-stage1-transitive` pass by ensuring the Python `--dump-full` closure of `fire.py` contains no `unavailable in compiled mode` stubs and no `# ERROR: compiling imported module`, so the job's `CLOSURE_INCOMPLETE` reject no longer fires.

This is a follow-up replan part of `bugs/hard/GATE_red_recover-land_2026-11-02-part5.md`. Parts 1–4 of the parent `GATE_red_recover-land_2026-11-02` chain are already landed on master; if the closure dump still names a weak stub that those parts do not explain, fix it here only if it is a one-symbol registration of the same shape those parts already handle. Otherwise file it as a new `bugs/` doc with a minimal probe and leave this part open rather than masking the stub.

## Acceptance

- `python3 tools/suite.py bootstrap-stage1-transitive` completes with a PASS verdict in `build/suite.log`.
- The run is not made green by an `expect=` marker, a skip, or a narrowed reject regex in `tools/suite.py`.
- The produced closure dump for `fire.py` has no `unavailable in compiled mode` and no `# ERROR: compiling imported module`.

## Done when

File: `tools/suite.py` (registry entry for `bootstrap-stage1-transitive`; the job is the test)
Command: `python3 tools/suite.py bootstrap-stage1-transitive`

Quick pinning tests (cheap, for a light worker; run them beside the job):
`python3 test_imported_global_stub.py` — an imported module-level DICT/SET
global may not emit a function stub; the emitted C must build and print
CPython's answer. It is one stub class's pin, not the job's substitute.
`python3 test_module_attr_module_call.py` is the same kind of pin for the
`lower`/`mojo_register` stub class (cause 7).
`python3 test_bare_object_ctor_no_stub.py`,
`python3 test_selfhost_no_dataclasses_fields_pin.py` and
`python3 test_selfhost_iter_structdefs_no_nested_gen.py` are the pins for the
`object`, `_dc_fields` and `_yield_from` stub classes (causes 8-10).
`python3 test_dump_full_reports_closure_stubs.py` is the pin for the job's
own verdict: `--dump-full` must report a stub the `.ci` it wrote carries, so
`reject=CLOSURE_INCOMPLETE` sees it instead of the job passing blind
(2026-11-19, below).

## Status 2026-11-19 (the job now observes its own artifact; the closure is still unmeasured)

**What landed in this round.** The acceptance's second half ("no
`unavailable in compiled mode` stub") was not observable in the job that is
supposed to prove it: `reject=CLOSURE_INCOMPLETE` is a regex over the CHILD'S
OUTPUT, and `--dump-full` wrote the stubs only into `fire.ci` and printed
`✓ Generated fire.ci`, exiting 0. `bootstrap-stage1-transitive` could
therefore pass with every stub present, and the only census was a manual grep
of a 120 MB artifact. `fire.py`'s `--dump-full` branch now scans the text it
just wrote (one `in`, not a per-line pass — cause 1 below is the cost of the
last whole-text scan) and, only when it finds one, prints
`closure: <name>.ci carries an unavailable in compiled mode stub` to stderr.
stderr is part of the child's output (`tools/procrun.py` merges it into the
run transcript), so the existing reject fails the job, with no regex change
and no new suite registration. Pinned by
`test_dump_full_reports_closure_stubs.py`, measured red before the change
(`--dump-full` on a `locals()` fixture printed only `✓ Generated prog.ci`
while `prog.ci` carried the stub) and green after, and it also asserts a
clean closure stays quiet so the report cannot become unconditional noise.

**Still open, and it is one measurement.** The ten root causes below are
fixed with their pins, but the closure itself has not been re-measured since
those fixes: that needs
`python3 tools/suite.py bootstrap-stage1-transitive`, which runs the
whole-closure dump and is the integrator's job, not a light worker's. With
the report above in place that single run IS the census — a stub makes the
job red and names the artifact, and stub-freeness is the job's own PASS — so
the next reading is a verdict rather than a grep. The risk named in the
2026-11-18 Status stands: a stub thought dead may persist for a different
reason, and master may have grown a new one.

## Status 2026-11-18 (ten root causes fixed; the closure is still unmeasured)

**This part is still open, pending one whole-closure measurement.** Its
acceptance is a green job *plus* a closure with no `unavailable in compiled
mode` stub, and the second half cannot be observed without the integrator's
whole-closure dump. Ten of the red's root causes have been found and fixed.
Causes 1-7 are described in the rest of this Status; causes 8-10 are the
three stub classes the previous measurement had left (`object`, `_dc_fields`,
`_yield_from`), fixed with this round's commit. Each has a cheap pin that was
measured red before its fix and is green after it, but the closure itself was
not re-measured (a whole-closure dump is the integrator's job), so the count
and membership below are still stale until
`python3 tools/suite.py bootstrap-stage1-transitive` runs. The remaining
risk named at the end of the previous Status stands: a stub thought dead may
persist for a different reason, and master may have grown a new one.

1. **The dump could not finish.** `_drop_unreferenced_extern_decls`
   (`module_gen.py`, added 2026-11-15 by the stdlib-dylib lane) ran a
   whole-text `re.findall` once per guarded extern symbol — O(symbols x
   text). The closure emits ~15k guarded externs into a 120 MB `.ci`, so a
   run at 43 minutes was still inside that loop (every `sample` frame in
   `_sre_SRE_Pattern_findall`). It is now one `\w+` tokenisation. Pinned by
   `test_codegen_drop_unreferenced_unimpl_stubs.py::
   test_extern_one_whole_text_scan` (measured red: 2000 whole-text scans).
   Landed as `ba340c188` ("perf: count guarded externs once, not once per
   symbol"). With it the named command passed in 4:10 on this lane's tree
   (3 jobs, 51 items, peak 4.5 GB):

       suite: 3 passed, 0 failed, 0 skipped  (3 tests, 51 jobs ...)
       bootstrap-stage1-transitive   3:11   exit 0

   That was measured on the lane's base (`0a932256b`) at 15:27. Master has
   since advanced 66 commits, and the integrator's gate round on 2026-11-17
   19:58 filed a fresh gate doc: the job was red again on master for a later,
   different cause (branch `work/bug-codegen-list-str-param-read-wrong-af`).
   That red was a false mixed-container refusal on the compiler's own
   `_to_returns` (`mojo/middle/out_result.py`) and `_choose_overload_symbol`
   (`mojo/backend_gimple/emit_calls.py`), fixed 2026-11-18: the job is green
   (3 passed, 0 failed, 394 s, peak 4.8 GB) and that doc was DELETED. It was
   not this part's two causes.

2. **Locals named like sibling modules were treated as modules.**
   `_is_selfhost_sibling_alias` (`mojo/middle/methods_shared.py`) tested
   `name.startswith(<module-prefix tuple>)`, and the tuple mixes package
   prefixes with module BASE names, so `cases`/`casted` matched `cas`,
   `comptime_bindings`/`comptime_members` matched `comptime`, and a local
   dict named `mlir` matched the `mlir` module. Their `.append`/`.items`/
   `.update` calls were re-dispatched as calls to module functions that do
   not exist — the `items`, `append` and `update` weak stubs the dump
   carried before this fix. The test is now boundary-correct and returns
   False for a locally bound name. Pinned by
   `test_selfhost_cycle_sibling_call.py`'s `locals_named_like_modules`
   (measured red on the old predicate: 2 stubs, 3 bare `append (` calls).

**The closure is still not stub-free.** Measured on this lane's tree at its
base, after both fixes (`fire.py --dump-full fire.py`, then
`grep -c '^__attribute__((weak)).*unavailable' fire.ci` → **15**), and the
class of each survivor, so the next round does not have to re-derive them.
The line numbers are as of that measurement; master has moved since, so
locate a survivor by the quoted call, not by the number.

3. **Imported module-level globals were stubbed as functions.**
   `_gmp_emit_imported_symbol_stubs` (`module_gen.py`) emits a weak
   `int64_t <name> (...)` "unavailable in compiled mode" stub for every
   `imported_symbols` entry with no `signature`. An imported DICT/SET global
   has no signature — `module_loader` records it as `'kind': 'global_var'`
   with a `c_return_type` — but every read of it is already lowered through
   the defining module's `<mod>__mojo_global_get_<name>` accessor, registered
   by `_emit_imported_global_accessors` earlier in the same
   `gen_module_impl`. So the stub is dead code that the closure still counts.
   The pass now skips a symbol present in `_imported_global_accessors`: that
   map's membership is proof the real lowering exists for every use site
   (the export's `kind` alone is not, since a global whose accessor could not
   resolve would not become callable behind a stub either). This removes the
   seven dispatch/rank-table stubs in the table below
   (`_EXPR_DISPATCH`, `_STMT_DISPATCH`, `_BIN_OPS`, `_CMP_OPS`, `_FLOAT`,
   `_SIGNED`, `_UNSIGNED`); the `object` row is not this class and stays
   open. Pinned by `test_imported_global_stub.py` (measured red before the
   fix: the minimal `generated_dispatch`/`types`/consumer fixture emits the
   `_EXPR_DISPATCH` and `_SIGNED` stubs; green after, and the emitted C
   builds and prints CPython's answer). The job was not re-run here — a
   whole-closure dump is the integrator's, not a light worker's — so the
   remaining count below must be re-measured by
   `python3 tools/suite.py bootstrap-stage1-transitive` before trusting it.

4. **`globals()` in function scope was refused.** `is_module_globals_call`
   (`mojo/backend_gimple/emit_infra.py`) only accepted module-scope reads
   (`_in_toplevel_gen`), so a bare `globals()` inside a real function body
   reached the generic unavailable-builtin path and the closure emitted a
   weak stub for it (the two call sites in the table below). The module's
   globals are its `_<mod>_globals` struct, readable from any function of the
   same module, so the gate no longer requires toplevel and
   `module_globals_bound_names` returns the module's full own-global set in
   function scope (it keeps the sequential "bound so far" view at toplevel).
   Pinned by `test_globals_in_function_scope.py`: a function reading module
   globals via `globals().get`/`in` emits no "unavailable in compiled mode"
   stub and the emitted C builds and prints CPython's answer.

5. **The re-export walk skipped `from X import *`.**
   `_find_symbol_home_module` (`mojo/middle/funcs_shared.py`) only followed
   explicit `from X import name` edges, so a symbol brought into a module's
   namespace by a wildcard import could not be traced to its defining module.
   The `multi_kind_locals` stubs came from this shape (`emit_infra`
   star-imports it from `mojo.middle.infra_infer`). Wildcard `FromImportStmt`
   edges are now followed (recursing with the looked-up name unchanged;
   depth/cycle guards unchanged). Pinned by
   `test_star_reexport_resolution.py`: `from p import helper` where
   `p/__init__.py` does `from .sub import *` resolves without an unavailable
   stub and the emitted C builds and prints CPython's answer. The closure was
   not re-measured, so confirm the `multi_kind_locals` row is gone by
   re-running the job.

6. **The compiler's own source called `locals()`.** A bare `locals()` call is
   a builtin the GIMPLE path cannot lower at all (unlike `globals()`, cause 4),
   so every call site in the closure emitted the `locals: unavailable in
   compiled mode` weak stub and every read of it in the self-hosted binary was
   the stub's `0`/absent answer. Five call sites in three modules, all of them
   a DEAD guard whose name is bound unconditionally on every path, so CPython
   and the constant answer agree and only the compiled binary took the other
   branch:
   - `mojo/backend_gimple/emit_stmts.py`, struct-subscript `__setitem__`
     fallback: `obj_v if 'obj_v' in locals() or True else addr` (`obj_v` is
     bound on both arms of the `_arr_tgt` test above; the `or True` already
     made the probe decorative).
   - `formal/build.py`, `compile_formal`'s `structs_by_name` build: neither
     `structs_by_name` nor (at that point) a probe for `structs` was ever
     absent — `structs` is bound unconditionally by the `_prepare_functions`
     unpack (None on the refusal path) — so the block is now the plain
     `globals().get('structs_by_name')` fallback plus the `structs is not
     None` comprehension, and `prog` takes `structs=structs`.
   - `formal/arm64_proof_gen.py`, `_ast_call_env2 = _cf2_text if '_cf2_text'
     in locals() else ...`: `_cf2_text` is assigned eight lines above with no
     branch, so the fallback was unreachable. Pinned by
     `test_selfhost_no_locals_pin.py`, which walks `fire.py`'s syntactic
     import closure (the set `bootstrap-stage1-transitive` compiles, and the
     same walk that reaches `formal/build.py` through
     `build_stdlib_dylib.py`'s function-local import) and fails on any call to
     the builtin. Measured red before this change: the five sites above.

7. **A module attribute that is itself a module was not resolved.** Python
   makes a module attribute a module object whenever the module did
   `import pkg.mod as name` (or `from pkg import mod`), so `a.name.f(...)`
   reaches `f` in that module. The self-host closure's own source has two
   such calls — `gimple_codegen.gimple_gen_coro.lower(...)` and
   `.register(...)` in `mojo/backend_gimple/emit_resolve.py` — because
   `gimple_codegen.py` does `import mojo.middle.coro as gimple_gen_coro`.
   No branch could resolve them: the submodule branch wants a file
   `gimple_codegen/gimple_gen_coro.py` (there is none — the attribute is a
   module the base module imported), and the single-hop module branch wants
   a local module alias of the file being compiled (the receiver is
   `gimple_codegen.gimple_gen_coro`, not an alias). Both calls fell through
   to the generic scalar-receiver dispatch, which matched `lower` against
   `str.lower` (`_t4 = string_lower (_t3)`) and `register` against the
   scalar-method stub (`_t8 = _t6; /* int64_t.register() stubbed */`) —
   exit-0 silent wrong answers, plus the weak `lower`/`mojo_register` stubs
   in the `.ci`. `_module_attr_module` (`mojo/middle/funcs_shared.py`) now
   answers "which module does this module's namespace bind this attribute
   to" from the base module's own import statements (parsed once through
   `_parsed_import`), and `_lmc_resolve_module_attr` /
   `_lmc_two_hop_module_call` / `_lmc_dotted_receiver` register that target
   as a module namespace and re-dispatch the call on it, so the existing
   module-qualified machinery pins `lower`'s home to `mojo.middle.coro` and
   emits the real call. Pinned by `test_module_attr_module_call.py`:
   measured red before the fix on the ordinary package shape
   (`import pkg.hub as hub; hub.alias.lower` emitted `string_lower`), green
   after for that shape, the `from pkg import leaf` spelling and the
   compiler's own hub shape (`gimple_codegen.gimple_gen_coro.lower` under a
   checkout path), with the emitted C building and printing CPython's
   answer. The test also checks the exact closure source shape
   (`gimple_gen_coro` -> `mojo.middle.coro`) through `_module_attr_module`,
   and that a from-imported CLASS (`Parser`) does not resolve as a module.

8. **A bare `object()` emitted a stub its placeholder lowering never used.**
   `_lower_named_call` (`mojo/backend_gimple/emit_calls.py`) already had a
   real lowering for the bare base-object constructor (a quiet null
   placeholder), but the `_is_unknown` test ran first. `object` is unknown
   by construction — no definition, no import entry — so `_lnc_unknown`
   emitted a weak `int64_t object (...)` stub, and only then did the
   placeholder arm return. The call site used the placeholder, making the
   stub dead, but it was still a stub in the dumped `.ci`. The arm now runs
   BEFORE `_is_unknown`. The closure carried it from the compiler's own
   source: `mojo/middle/funcs_shared.py`'s `_PARSE_FAILED = object()`.
   Pinned by `test_bare_object_ctor_no_stub.py` (measured red before the fix:
   that exact stub line in the emitted C; green after, and the emitted C
   builds and prints CPython's answer).

9. **`from dataclasses import fields as _dc_fields` is not lowerable, and
   the walks that used it saw an empty field list.** `cpp_core.py`'s AST
   copy/rewrite walks called the alias in ten comprehensions/expressions.
   The MODULE-QUALIFIED `dataclasses.fields(x)` is modelled (the reflection
   dispatch `_mojo_dispatch_fields`), but a from-imported bare name is an
   unresolved import alias: `_lnc_unknown` emitted the weak `_dc_fields`
   stub returning 0. In the self-hosted compiler every one of those walks
   therefore copied nothing. The ten sites now read `__dataclass_fields__`
   through one `_cpp_field_names` helper — the same ordered mapping
   `dataclasses.fields` reads, and the guards at those sites already used
   it. For fire_compiler's AST dataclasses the two agree exactly: none
   declares a `ClassVar`/`InitVar` pseudo-field, the only entries
   `fields()` filters out. Pinned by
   `test_selfhost_no_dataclasses_fields_pin.py`, which walks `fire.py`'s
   closure and rejects the from-import spelling (measured red before: the
   nine `cpp_core.py` import sites; green after).

10. **The structdef walk was a nested generator that captures.** The helper
    used to be `def _yield_from(coll)`, a generator defined INSIDE
    `emit_stmts._iter_structdefs` (itself a generator) and reading the
    enclosing `seen` set. The coroutine path has no capture model for a
    nested generator, so the imported-module compile (`relaxed_imports`)
    skipped it and emitted the weak `_yield_from` stub; every call under it
    read 0 in the compiled compiler. The walk needs no generator at all:
    `_collect_structdefs` is a module-level collector that appends to a list
    as it descends, and `_iter_structdefs` yields that list in the same
    order with the same per-`id` de-duplication. Pinned by
    `test_selfhost_iter_structdefs_no_nested_gen.py`: an AST pin on the real
    function, a behaviour check on order/de-duplication, and a compile of
    the REAL current source as an imported sibling module (measured red
    before: the `_yield_from` stub; green after).

| stub(s) | emitted because | probe / next step |
|---|---|---|
| `globals` (2 call sites) | **FIXED 2026-11-18** (cause 4 above): `getattr(globals(), '_FOREIGN_CALLABLES', {})` in `mojo/middle/types.py:2948`, i.e. `globals()` in FUNCTION scope; `is_module_globals_call` now lowers it and the snapshot covers the module's own globals in function scope | pin: `test_globals_in_function_scope.py`; re-measure the job's stub count |
| `locals` (5 call sites) | **FIXED 2026-11-18** (cause 6 above): `emit_stmts.py`'s `'obj_v' in locals()` and four dead `locals()` probes in `formal/build.py` / `formal/arm64_proof_gen.py`. Cause 4's `globals()` lowering does NOT cover it — `locals()` has no module struct to read | pin: `test_selfhost_no_locals_pin.py`; re-measure the job's stub count. **One stub LINE for the whole dump is expected even before the fix** (`#ifndef _MOJO_STUB_locals`): three modules can emit it and only the first survives, which is why the previous round attributed this row to `emit_stmts.py` alone |
| `_EXPR_DISPATCH`, `_STMT_DISPATCH`, `_BIN_OPS`, `_CMP_OPS`, `_FLOAT`, `_SIGNED`, `_UNSIGNED` | **FIXED 2026-11-18** (cause 3 above): imported module-level DICT/SET globals from `generated_dispatch`; `_gmp_emit_imported_symbol_stubs` emitted a function stub for each `_imp_syms` entry with no signature, while their real lowering is the `_<mod>__mojo_global_get_<name>` accessor. The pass now skips an entry whose accessor is registered | pin: `test_imported_global_stub.py`; re-measure the job's stub count |
| `object` | **FIXED 2026-11-18** (cause 8 above): NOT the imported-symbol pass — a bare `object()` call reached `_lnc_unknown` first, which emitted the weak stub before the placeholder arm returned. `mojo/middle/funcs_shared.py`'s `_PARSE_FAILED = object()` is the closure's source | pin: `test_bare_object_ctor_no_stub.py`; re-measure the job's stub count. The old note here ("find which import registers it") was a false lead: no import ever did — the writer is the call site, and the fix is the ordering |
| `multi_kind_locals` (3 call sites) | **FIXED 2026-11-18** (cause 5 above): `ginf.multi_kind_locals(gen)` in `emit_stmts.py:1924,1979,3828`; `ginf` is `emit_infra`, which only STAR-imports it from `mojo.middle.infra_infer`. `_find_symbol_home_module` now follows `from X import *` re-export edges | pin: `test_star_reexport_resolution.py`; re-measure the job's stub count |
| `lower`, `mojo_register` | **FIXED 2026-11-18** (cause 7 above): `gimple_codegen.gimple_gen_coro.lower(...)` / `.register(...)` in `emit_resolve.py:1297,1301` — a call through a MODULE ATTRIBUTE (`mod.submod.fn`) where the attribute is a module the base module imported. The old code stripped the hub qualifier and then looked for a module FILE named `gimple_gen_coro`; the call fell to the generic scalar-receiver dispatch (`string_lower` / `int64_t.register() stubbed`). `_module_attr_module` now resolves the attribute through the base module's own imports and the call is re-dispatched on `mojo.middle.coro` | pin: `test_module_attr_module_call.py`; re-measure the job's stub count |
| `_dc_fields` (10 call sites) | **FIXED 2026-11-18** (cause 9 above): `from dataclasses import fields as _dc_fields` in `cpp_core.py`; the module-qualified spelling is modelled, the from-import alias is not, so it became a weak stub returning 0 and every AST rewrite walk saw an empty field list. The call sites now use `__dataclass_fields__` through `_cpp_field_names` | pin: `test_selfhost_no_dataclasses_fields_pin.py`; re-measure the job's stub count |
| `_yield_from` | **FIXED 2026-11-18** (cause 10 above): the nested generator `def _yield_from(coll)` in `emit_stmts._iter_structdefs` captured the enclosing `seen`; the coroutine path cannot compile a capturing nested generator, so the imported-module compile skipped it and stubbed it. Replaced by the module-level `_collect_structdefs` collector; `_iter_structdefs` is a plain generator over the collected list | pin: `test_selfhost_iter_structdefs_no_nested_gen.py`; re-measure the job's stub count |

The four `_mojo_gpu_*` weak definitions are the documented GPU no-op stubs and
were not counted above. The dispatch-table stubs (cause 3), the function-scope
`globals` stubs (cause 4), the star-reexported `multi_kind_locals` stubs
(cause 5), the `locals` stubs (cause 6) and the module-attribute module calls
(cause 7) are fixed in this lane, as are the `object` (cause 8), `_dc_fields`
(cause 9) and `_yield_from` (cause 10) rows. Every row this table carried is
fixed; none was a one-symbol registration of the part-1/part-2 shape, and the
two fixed by cause 2 were that shape, which is why they are here.

The last measurement of the full closure (before cause 3) was 15 stubs; causes
3–10 remove every row in that measurement — the seven dispatch-table stubs,
the two `globals` call sites, the three `multi_kind_locals` call sites, the
`locals` stub, the `lower`/`mojo_register` pair, and the `object`,
`_dc_fields` and `_yield_from` rows. That is arithmetic from the table, not a
reading. The count must be re-measured by
`python3 tools/suite.py bootstrap-stage1-transitive` before the acceptance is
claimed: a stub thought dead may persist for a different reason, and a new one
may have appeared on master since the measurement.

Until 2026-11-19 this last paragraph said the job's `reject=` only reads the
child's OUTPUT while `--dump-full` wrote the stubs to `fire.ci` and printed
just `✓ Generated fire.ci`, so the job could pass with them present. That
hole is closed: the dump reports a stub it wrote (see the 2026-11-19 Status),
so the reject now sees stage1's artifact too, the same way it already saw
stage2/stage3's (their binaries CALL the stubs), which is
`bugs/hard/GATE_red_recover-land_2026-11-02-part5-part2.md`'s chain.

