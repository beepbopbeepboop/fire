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

## Status 2026-11-17 (two root causes fixed; the closure still carries 15 dead weak stubs)

**This part is still open.** Its acceptance is a green job *plus* a closure
with no `unavailable in compiled mode` stub, and the second half is not met
(15 stubs, table below). Two of the red's root causes were found and fixed
in this lane; the first is already on master, the second lands with the land
commit that carries this Status.

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

| stub(s) | emitted because | probe / next step |
|---|---|---|
| `globals` (2 call sites) | `getattr(globals(), '_FOREIGN_CALLABLES', {})` in `mojo/middle/types.py:2948`, i.e. `globals()` in FUNCTION scope; `ginf.is_module_globals_call` only lowers the module-scope read | a function with `getattr(globals(), 'X', 0)`; extend `lower_module_globals_read` to function scope (the module globals struct is readable from any function of the same module) |
| `locals` | `'obj_v' in locals()` in `emit_stmts.py:2843` | same shape; `_cur_func_body`/`var_types` already know the local set |
| `_EXPR_DISPATCH`, `_STMT_DISPATCH`, `_BIN_OPS`, `_CMP_OPS`, `_FLOAT`, `_SIGNED`, `_UNSIGNED` | imported module-level DICT/SET globals from `generated_dispatch`; `_gmp_emit_imported_symbol_stubs` emits a function stub for each `_imp_syms` entry that has a return type but no signature. Their real lowering is the `_<mod>__mojo_global_get_<name>` accessor, so these are dead | any module that imports one dict global; skip imported symbols whose home records them as globals (the getter path is already taken at each use) |
| `object` | same pass; `object` is an imported builtin/type name, never called | `grep '[^_a-z]object *(' fire.ci` finds no call — it is a type, not a function |
| `multi_kind_locals` (3 call sites) | `ginf.multi_kind_locals(gen)` in `emit_stmts.py:1924,1979,3828`; `ginf` is `emit_infra`, which only STAR-imports it from `mojo.middle.infra_infer`. `_find_symbol_home_module` follows `from X import name` but not `from X import *` | a `p/__init__.py` doing `from .sub import *` and a caller of a `sub` function; teach the re-export walk about star imports (keep its cycle cap) |
| `lower`, `mojo_register` | `gimple_codegen.gimple_gen_coro.lower(...)` / `.register(...)` in `emit_resolve.py:1297,1301` — a call through a MODULE ATTRIBUTE (`mod.submod.fn`), which the two-hop/module-qualified branches do not treat as a submodule function | the same two-line call in a fixture; resolve `gimple_gen_coro` as the module `mojo.middle.coro` |
| `_dc_fields` (10 call sites) | `from dataclasses import fields as _dc_fields` in `cpp_core.py`; CPython's `dataclasses` is not in the closure, so the imported alias gets the by-design unresolved-external stub — but this one IS called (`cpp_core.py:2874` etc.) | decide whether the compiled path reaches `_rewrite_node`'s `fields(type(node))`; if it does this is a silent wrong answer, and a static `__dataclass_fields__` walk is the lowering |
| `_yield_from` | registered for a generator/async function the lowering skipped; no call site exists in the `.ci` | find the skipped function with `MOJO_DEBUG`/the generator pre-pass note; either lower it or record the accepted gap |

The four `_mojo_gpu_*` weak definitions are the documented GPU no-op stubs and
were not counted above. None of these is a one-symbol registration of the
part-1/part-2 shape; the two fixed here were, which is why they are here.

The job's `reject=CLOSURE_INCOMPLETE` only reads the child's OUTPUT, and
`--dump-full` writes the stubs to `fire.ci` (it prints just
`✓ Generated fire.ci`), so the job can pass with them present. They are
stage2's and stage3's failure mode (their binaries CALL them), which is
`bugs/GATE_red_recover-land_2026-11-02-part5-part2.md`'s chain.

