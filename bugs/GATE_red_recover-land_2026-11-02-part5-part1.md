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

Quick pinning test (cheap, for a light worker; run it beside the job):
`python3 test_imported_global_stub.py` — an imported module-level DICT/SET
global may not emit a function stub; the emitted C must build and print
CPython's answer. It is one stub class's pin, not the job's substitute.

## Status 2026-11-18 (five root causes fixed; the closure still carries dead weak stubs)

**This part is still open.** Its acceptance is a green job *plus* a closure
with no `unavailable in compiled mode` stub, and the second half is not met.
Five of the red's root causes have been found and fixed; the first is on
master, the second and third land with earlier commits on this branch, and
the fourth and fifth land with the commit that carries this Status. The
closure was not re-measured in this round (a whole-closure dump is the
integrator's job), so the stub count below is stale until
`python3 tools/suite.py bootstrap-stage1-transitive` runs.

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

| stub(s) | emitted because | probe / next step |
|---|---|---|
| `globals` (2 call sites) | **FIXED 2026-11-18** (cause 4 above): `getattr(globals(), '_FOREIGN_CALLABLES', {})` in `mojo/middle/types.py:2948`, i.e. `globals()` in FUNCTION scope; `is_module_globals_call` now lowers it and the snapshot covers the module's own globals in function scope | pin: `test_globals_in_function_scope.py`; re-measure the job's stub count |
| `locals` | `'obj_v' in locals()` in `emit_stmts.py:2843` | same shape; `_cur_func_body`/`var_types` already know the local set |
| `_EXPR_DISPATCH`, `_STMT_DISPATCH`, `_BIN_OPS`, `_CMP_OPS`, `_FLOAT`, `_SIGNED`, `_UNSIGNED` | **FIXED 2026-11-18** (cause 3 above): imported module-level DICT/SET globals from `generated_dispatch`; `_gmp_emit_imported_symbol_stubs` emitted a function stub for each `_imp_syms` entry with no signature, while their real lowering is the `_<mod>__mojo_global_get_<name>` accessor. The pass now skips an entry whose accessor is registered | pin: `test_imported_global_stub.py`; re-measure the job's stub count |
| `object` | same pass, but **not** a registered global — do not assume cause 3 removed it. `object` is an imported builtin/type name, never called | `grep '[^_a-z]object *(' fire.ci` finds no call — it is a type, not a function; find which import registers it (it is not in any `import object` statement) and then skip type-only imported names |
| `multi_kind_locals` (3 call sites) | **FIXED 2026-11-18** (cause 5 above): `ginf.multi_kind_locals(gen)` in `emit_stmts.py:1924,1979,3828`; `ginf` is `emit_infra`, which only STAR-imports it from `mojo.middle.infra_infer`. `_find_symbol_home_module` now follows `from X import *` re-export edges | pin: `test_star_reexport_resolution.py`; re-measure the job's stub count |
| `lower`, `mojo_register` | `gimple_codegen.gimple_gen_coro.lower(...)` / `.register(...)` in `emit_resolve.py:1297,1301` — a call through a MODULE ATTRIBUTE (`mod.submod.fn`), which the two-hop/module-qualified branches do not treat as a submodule function | the same two-line call in a fixture; resolve `gimple_gen_coro` as the module `mojo.middle.coro` |
| `_dc_fields` (10 call sites) | `from dataclasses import fields as _dc_fields` in `cpp_core.py`; CPython's `dataclasses` is not in the closure, so the imported alias gets the by-design unresolved-external stub — but this one IS called (`cpp_core.py:2874` etc.) | decide whether the compiled path reaches `_rewrite_node`'s `fields(type(node))`; if it does this is a silent wrong answer, and a static `__dataclass_fields__` walk is the lowering |
| `_yield_from` | registered for a generator/async function the lowering skipped; no call site exists in the `.ci` | find the skipped function with `MOJO_DEBUG`/the generator pre-pass note; either lower it or record the accepted gap |

The four `_mojo_gpu_*` weak definitions are the documented GPU no-op stubs and
were not counted above. The dispatch-table stubs (cause 3), the function-scope
`globals` stubs (cause 4), and the star-reexported `multi_kind_locals` stubs
(cause 5) are fixed in this lane; the remaining rows are separate causes, and
none is a one-symbol registration of the part-1/part-2 shape. The two fixed by
cause 2 were that shape, which is why they are here.

The last measurement of the full closure (before cause 3) was 15 stubs; causes
3–5 remove the seven dispatch-table stubs, the two `globals` call sites, and
the three `multi_kind_locals` call sites in that measurement, which would leave
`locals`, `object`, `lower`, `mojo_register`, `_dc_fields`, and `_yield_from`.
That is arithmetic from the table, not a reading — the number and the
membership are stale until `bootstrap-stage1-transitive` runs (a stub thought
dead may persist for a different reason, and a new one may have appeared on
master since the measurement).

The job's `reject=CLOSURE_INCOMPLETE` only reads the child's OUTPUT, and
`--dump-full` writes the stubs to `fire.ci` (it prints just
`✓ Generated fire.ci`), so the job can pass with them present. They are
stage2's and stage3's failure mode (their binaries CALL them), which is
`bugs/GATE_red_recover-land_2026-11-02-part5-part2.md`'s chain.

