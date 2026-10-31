# CODEGEN_the_collections_abc_coro_close_idiom_refuses_only_in_a_full_closure

The first module rejection in the whole-closure stdlib builds of rows
6 (socket) / 22 (parsing) / 24 (zipfile) / 25 (mailbox) is
`generator .close() on a value with no known generator API ('_tNN')` from the
`## coroutine ##` block of `Lib/_collections_abc.py`. The same file, in the
same relaxed import context, compiles cleanly in isolation. The refusal is
CLOSURE-CONTEXTUAL. Owner-level follow-up to aed8bd53, which names this exact
idiom as its primary case.

## Status (2026-10-28, master 8c19a643f — measured 2026-10-25 on 5888fe4a, re-verified byte-identical on 1d2bdfe0; the four row reject profiles are pinned 56/48/62/66 with this as the first wall in each)

### The idiom (the real Lib/_collections_abc.py:95-98, 3.14.6)

```python
async def _coro(): pass
_coro = _coro()
coroutine = type(_coro)
_coro.close()  # Prevent ResourceWarning
```

### The split (measured)

- **File alone, relaxed import context** (1-line entry, the file as resolvable
  sibling, do_imports=True): **compiles** — 856,681 chars of C, 0 error lines,
  `__mgco__coro` machinery present x18, `__anext__` weak stubs x13.
  Re-verified byte-identical (md5 4056d4548fd682f1ef119f270c5fb431) across
  5888fe4a and 1d2bdfe0.
- **The four rows' full closures**: REFUSE the same `_coro.close()` statement
  (message above, only the temp number renames run-to-run). Reject census
  2026-10-25/26, whole-closure, cold store: socket 56, parsing 48, zipfile 62,
  mailbox 66 — byte-identical compositions across the aed8bd53 merge and the
  owner's ~100-commit bootstrap-verify integration (the owner's batch moved
  NOTHING in any row's reject profile).

### What is known about the mechanism

- Gating: every IMPORTED module compiles in the relaxed context (the entry
  compiles strict); in the relaxed path, unsupported async fns are skipped
  with weak stubs instead of refusing (`mojo/backend_gimple/emit_resolve.py`
  relaxed gating + `mojo/backend_gimple/module_gen.py` relaxed async skip —
  lines shifted by the owner's batch, grep `relaxed` / the weak-stub emission).
- The owner's aed8bd53 ("codegen: support generators and coroutines held in
  module globals") records the generator var api at global store time
  (`_note_global_generator_store`, `gimple_codegen.py`) and copies it onto the
  read-back temp in `_lower_IdentExpr`'s global-read arm; trust model: a name
  is trusted only while it has ONE binding (function-body store, toplevel
  rebind to a different generator, or any `_write_dest` write poisons it;
  poisoned names keep the old refusal). Its six-case suite
  (`test_gimple_generator_runner.py::run_module_global_generator_tests`,
  case 2 = the def-then-rebind shape) is GREEN — the idiom compiles
  deterministically in the small-closure shapes (shapes A-G all compile,
  measured; the full 5-line idiom compiles).
- The ONE gap: in the full row closures the same statement refuses. The
  live-table dump at the refusal point was never captured (the full-closure
  probe died mid-import under memory pressure before reaching the entry
  module; no second failure state exists). **Owed: a solo quiet-window
  full-closure run of one row (mailbox, `do_imports=True`, fresh store) with
  a live-table dump at the refusal point** (the `probe_full.py` pattern in
  `T/opencode/fsdec/probe_full.py`) to name the exact write that drops the
  api in the big closure.
- Candidate silent write (recorded from the one shape-E refusal observed,
  NOT pinned): the read arm in `mojo/backend_gimple/emit_stmts.py` — a typed
  read (`MojoGenerator *`) whose RHS temp is absent from `_generator_var_api`.

### The shape-E transient (context, do not chase)

The real line-92 gen line + idiom refused **1 in ~110,000 runs** (300 + 1500
+ 8000 unseeded runs, then a 100,000-value PYTHONHASHSEED sweep — all
compiled). Non-reproducible, not hash-seed-driven (the pipeline is
single-threaded with no `random`). If a second failure is ever caught:
capture the state dump first (the `probe_nondet` pattern), before anything
else.

### Guardrails

A fix must not trade the refusal for a silent wrong value: the trust model is
the owner's, poisoned names MUST keep the old refusal, and the four rows'
reject censuses (56/48/62/66) are the standing profile to diff against — a
fix is progress only if it is LOUDER or strictly fewer rejects with every
moved module's value behavior checked against CPython. Pointers: the row docs
(`COMPILE_FAIL_Lib_socket_...`, `COMPILE_FAIL_Tools_cases_generator_parsing.md`,
`COMPILE_FAIL_zipfile___init__.md`, `CODEGEN_tuple_unpack_of_a_boxed_dict_reads_slots_as_pointer_words.md`)
carry the per-row censuses.

### Round 2026-10-29 — planning round (light worker; no full-closure run)

**Measured, not chased to a fix.** Small-closure repro does NOT refuse, so
the mechanism is still unnamed. Each experiment below compiled with
`compile_to_gimple_with_cpp(src, do_imports=True)` under `memslot --gb 8`:

- `helper.py: def set_it(): global _coro; _coro = 5` imported by a file with
  the idiom → compiles (helper's C IS emitted; `_coro` read not refused).
- `helper2.py: def _coro(): yield 1; _coro = _coro()` imported → compiles.
- `helper3.py` with the same async idiom imported → compiles; the store trace
  shows two `_note_global_generator_store` calls for `_coro`, both `tracked`.
- `helper5.py: def _coro(): return 1` imported, then `async def _coro` +
  idiom in the entry → compiles.
- Entry `from _collections_abc import Sized` → compiles at 24 KB of C, so the
  stdlib import did not pull the module's body (the file alone is 856 KB).
  Not usable as a closure stand-in.

**Ruled out by reading (not by a run):** imports share ONE root gen
(`emit_resolve._compile_imported_module` passes `gen`), so the gen-wide
tables (`_global_generator_api`, `_global_generator_api_poisoned`,
`_async_api`) do span modules. `_async_fns`/`_generator_fns` are `id()`-keyed
but local to one `gen_module` call (module_gen.py:3363), so id reuse across
modules does not reach them.

**Code map (where the api can be lost — the candidates for the probe):**

1. Refusal: `mojo/backend_gimple/emit_methods.py:1419-1428` — raised when the
   receiver's actual type is `MojoGenerator *` and `_generator_var_api[av]`
   is absent. `av` is the READ temp.
2. Read arm that carries the api: `mojo/backend_gimple/emit_exprs.py:774-776`
   (end of the global-read arm). **Early returns BEFORE it skip the carry**:
   `_tagged_dyn_src` (:478), `_narrowed_exprs` (:500), `_boxed_mut_locals`
   (:505), `_captures` (:520), `_imported_global_accessors` (:538),
   `_BUILTIN_TYPE_NAMES`/`struct_field_types` (:560). A closure can make
   `_coro` hit one of these (e.g. a `from X import _coro` that registers an
   accessor, which `_emit_imported_global_accessors`, emit_infra.py:1518,
   does for any module that exports a `global_var` of that name). That
   would be the closure-only shape.
3. Store that records the api: `emit_stmts.py:969` →
   `_note_global_generator_store` (emit_stmts.py:972-1017). Recorded only
   when `_in_toplevel_gen` and `v` has an api in `_generator_var_api`.
   Poison sites: emit_stmts.py:1000-1015, and emit_infra.py:3689 (any
   `_write_dest` global write, unconditionally, for a name in
   `_global_var_types`).
4. Relaxed gating for imported modules: `module_gen.py:11103-11127` skips an
   unsupported `async def` with a weak stub and adds it to
   `_unsupported_generator_names` (module_gen.py:12590, :15470). A skipped
   `_coro` in the closure would make `_coro()` untracked.

**Decision the next round needs (one heavy probe, owed to the integrator):**
run ONE row (mailbox, `do_imports=True`, cold store) with a wrapper around
`emit_exprs._lower_IdentExpr` that, for `name == '_coro'` only, dumps:
`name in gen._global_generator_api`, `in gen._global_generator_api_poisoned`,
`in gen._imported_global_accessors`, `in gen._captures`,
`in gen._narrowed_exprs`, `in gen._boxed_mut_locals`, `gen._in_toplevel_gen`,
`gen._async_api.get('_coro')`, and `gen._unsupported_generator_names`,
plus `gen.module_name` at the time. The first read with a dump showing
`in _global_generator_api == False` and poisoned `False` selects which of
items 2-4 is the cause. Then:

- If item 2 (an early-return arm): the carry moves to just after the
  global-read branch is entered, so every arm that reads a generator-holding
  global keeps its api. Test: a sibling module with `from X import _coro`
  registering an accessor, then `_coro.close()`.
- If item 3 (poison): the poison source is the named writer; decide between
  scoping the table per module and keeping the poison. Test: the same
  two-module shape as above, with the second module's write.
- If item 4 (skip): the idiom is in a skipped `async def`; the fix is to
  keep the coroutine compiled in the relaxed context when it is eligible.

**Tests that will prove it:** `test_gimple_generator_runner.py`, in
`run_module_global_generator_tests`, a two-module fixture (write the sibling
with `_build_foreign_package_run`'s helper) and the `_coro.close()` idiom in
the entry; it must compile and run with output matching CPython. Then the
four row reject censuses (56/48/62/66) must drop or stay equal, and every
moved module's value behaviour is checked against CPython.

### Round 2026-10-29b — light-worker narrowing (no fix; no heavy run)

Measured with `compile_to_gimple_with_cpp(src, do_imports=True, filename=entry)`
under `tools/memslot.py --gb 8`, each entry in a fresh temp dir. **Every shape
compiled; none refuses `_coro.close()`:**

- Idiom in the entry with a sibling `a.py` holding the idiom, and a sibling
  `b.py` writing `_coro` three ways: top-level `_coro = 5`, a `global _coro`
  store in a function, and `_coro = _g()` from a generator. Both import orders
  (`import b; import a` and the reverse) — 6 cases, all OK. This RULES OUT
  the cross-module poison shape (item 3) for a plain second-module write to
  the same name.
- `from sib import _coro` where `sib.py` exports `_coro = 5`, with the idiom
  in the entry. OK. This does not exercise the item-2 early return on its own
  (the read is shadowed by the local rebind), so item 2 stays open.
- The REAL `Lib/_collections_abc.py` (Python 3.14 copy, 32 KB) copied beside
  the entry and `import _collections_abc` plus the idiom in the entry. OK
  (792 KB of C). The file itself does not reproduce; the refusal needs the
  other closure members.

Scratch scripts were in the worker's `.tmp/repro/` (git-ignored, not
committed). The mechanism is still unnamed. The owed step is unchanged: the
mailbox full-closure probe with the `_lower_IdentExpr` dump (see the
2026-10-29 round above). Nothing in this round changes behaviour, so no code
or test lands.

### Round 2026-10-30 — partial fix: accessor-read api carry (light worker; no full-closure run)

**Landed (commit 5161214e9):** `_lower_IdentExpr`'s `_imported_global_accessors`
early-return arm (`mojo/backend_gimple/emit_exprs.py:538-548`) now copies
`_global_generator_api[name]` onto the accessor read-back temp, unless the name
is poisoned. This is the same carry the global-read arm already does at
emit_exprs.py:797-799, so the two arms agree.

**Test:** `test_regress_coro_close_closure.py` drives the arm directly on a
`GimpleGen` with an accessor and a recorded api. Run under
`python3 tools/memslot.py --gb 8 --label unit -- python3 test_regress_coro_close_closure.py`:
- with the fix: `PASS` (both cases).
- with the pre-fix `emit_exprs.py` (`git show 5161214e9^:...`): fails with
  `accessor read _t1 lost the api: None`.
- poisoned name: no carry, as the trust model requires.

The earlier version of this test, a `from sib import _coro` + idiom
compile, passed on the pre-fix code too, so it was replaced.

**NOT established:** that this arm is the cause of the full-closure refusal.
Probes, all with `compile_to_gimple_with_cpp(do_imports=True)` in fresh temp
dirs under `memslot --gb 8`, COMPILE on both the fixed and the pre-fix code:
- idiom in a sibling, `from sib import _coro` in an importer (accessor
  registered, the read is not shadowed) — the accessor is registered but the
  read has no api to lose;
- sibling exporting `_coro = 5` plus a generator store in another module
  (accessor read, api recorded) — COMPILES; the accessor ctype is `int64_t`;
- sibling exporting `_coro = _g()` (a generator global) and an importer that
  does `next(_coro)` — refused for a different reason: "`next(...)` on
  next(IdentExpr) (receiver typed `int64_t`)".

The last one is the finding that matters. For a generator-held global exported
by a sibling, the accessor's C type is `int64_t`, not `MojoGenerator *`, so
the refusal in `emit_methods.py:1419-1428` (which needs a `MojoGenerator *`
receiver) cannot fire through this arm at all. The carry is therefore only
reachable when the export's `c_return_type` is `MojoGenerator *`, and no
small-closure probe produced that. The `c_return_type` default
(`emit_infra.py:1603`, `info.get('c_return_type', 'int64_t')`) and the local
sibling export typing (`_local_sibling_module_exports`) are the next things to
read. If a generator-held global is exported as `int64_t`, that export typing
is the real defect, and the carry above is a correct but unexercised change.

**Still owed (heavy, integrator):** the four rows' full-closure reject
censuses (socket 56 / parsing 48 / zipfile 62 / mailbox 66) have not been
re-run, so it is unknown whether this commit moves any of them. The mailbox
full-closure probe with the `_lower_IdentExpr` dump from the 2026-10-29 round
is still the step that decides it; add `gen._imported_global_accessors.get('_coro')`
and its C type to that dump, since that is the one value this round showed
matters.

### Round 2026-10-30b — partial fix: accessor read is typed as a generator (light worker)

**Landed:** the `_imported_global_accessors` arm of `_lower_IdentExpr`
(`mojo/backend_gimple/emit_exprs.py`, ~538-560) now, when the name has a
recorded, unpoisoned generator api, unboxes the accessor word through
`void *` into a `MojoGenerator *` read temp (the same unboxing the own-global
read arm does at emit_exprs.py ~921-928) and returns ctype `MojoGenerator *`.
Before, it returned the export's declared type (`void *`), so `.close()`/`next()`
refused with "receiver typed `void *`" even though the api had been carried.
Test: `test_regress_coro_close_closure.py::test_accessor_read_of_generator_is_typed_as_generator`
(FAILS on HEAD with `accessor read _t1 typed void *`, PASSES with the fix).
`test_gimple_generator_runner.py`: 297 pass / 8 fail, the SAME 8 on HEAD
(`generator_explicit_call_arguments_still_resolve`, ... see
`CODEGEN_genexp_over_annotated_param_refused.md`,
`CODEGEN_generator_function_Lib_os.md`), so none is caused by this change.

**Measured this round (not a fix):**
- The defining module's OWN accessor for a generator-held global is
  `int64_t root__mojo_global_get__coro(void)` (`var _coro = _g()` in a sibling,
  compiled alone, `do_imports=True`). The boxed-word convention holds there.
- The export scan (`module_loader.load_module_from_path`) types a
  `var NAME = <call>` line as `void *` (module_loader.py ~1262-1270), so an
  importer declares the accessor `void *`, not the real handle type. The scan
  reads ONLY `var` lines: a plain `NAME = _g()` in a `.py`/`.mojo` sibling is
  not exported at all (no accessor), and the importer reads it typed `int64_t`.
- **Cross-module api transport is absent in the small closure.** For both
  sibling shapes (`var _coro = _g()` and plain `_coro = _g()`), the importer's
  gen does NOT record `_global_generator_api['_coro']` (checked at each
  `_lower_IdentExpr('_coro')`: `api_in=False`). So the importer never learns the
  global is a generator, and the refusal stays `void *` / `int64_t`
  ("`next(...)` on next(IdentExpr) (receiver typed ...)"). The accessor arm
  fix therefore does not fire for these shapes; it fires only when the api is
  already in the importer's gen-wide table (a defining module compiled into
  the same gen, plus an accessor registered for the name).
- **Stdlib name poisoning is ruled out by grep.** In the Python 3.14.6 stdlib
  (`/Users/mrs/net/Python-3.14.6/Lib`), `_coro` is bound at module scope ONLY in
  `_collections_abc.py:94-95` (`async def _coro(): pass` / `_coro = _coro()`);
  every other hit is a local or an attribute. So no other stdlib module can
  poison the name through `_write_dest`/emit_infra.py:3689 in the rows'
  closures. (Grep of the closure's import graph, not a closure run.)

**Next step (unchanged in shape, now narrower):** the closure refusal is still
unnamed, and the owed heavy probe (mailbox, `do_imports=True`, cold store, the
`_lower_IdentExpr` dump of `_global_generator_api`, `_global_generator_api_poisoned`,
`_imported_global_accessors`, `_captures`, `_narrowed_exprs`, `_boxed_mut_locals`,
`_in_toplevel_gen`, `_async_api`, `_unsupported_generator_names`) is still the
decider. Before running it, the designable gap is the cross-module transport:
if the closure probe shows `_global_generator_api` lacks `_coro` in the reading
gen, the fix is to carry generator-ness through the export (module_loader's
`var` export, plus the defining accessor's C type kept consistent with the
export's declared type), not in the read arm. Full-gate verdict needed on the
four rows' reject censuses (56/48/62/66) before this lands as a closure fix.

### Round 2026-10-31 — planning round (light worker; no full-closure run; no code change)

**State of the landed partials.** `5161214e9`, `7c2224ee9` and `76672d9e0` are
on master. `test_regress_coro_close_closure.py` passes on HEAD
(`python3 tools/memslot.py --gb 8 --label coro-close -- python3 test_regress_coro_close_closure.py`
→ `PASS: accessor-read generator api carry`, peak 0.1 GB). Those commits fix
the accessor-read arm but are NOT established as the closure cause (see the
2026-10-30 rounds).

**What the api record is (read, not run).** `_note_global_generator_store`
(emit_stmts.py:1001) stores `gen._generator_var_api[v]`, whose `'base'` key is
the C symbol family of one compiled generator. The consumers build calls from
it: `cpp_core.py:1590-1605` / `:1752` / `:7986` (`{base}_start`, resume
dispatch), and `cpp_async.py:1209-1210` (`{base}_start` as a function address).
So an api is only meaningful in a translation unit that can see
`{base}_start` and its resume symbols. A cross-module carry is therefore not
just a type/table fix: the importer also needs those symbols declared, and the
defining module must emit them with external linkage.

**Decision the next round needs (still the owed heavy probe, integrator).**
Run ONE row (mailbox, `do_imports=True`, cold store) with the
`_lower_IdentExpr('_coro')` dump from the 2026-10-29 round. Add
`gen._generator_var_api` keys and the `base` of any hit, and record WHICH gen
(`gen.module_name`) performs each `_coro` read. Then:

- If the reading gen has no `_global_generator_api['_coro']` and the defining
  module's gen is a different object: the cross-module transport is the cause.
  Next round lands it as: (a) the defining module's `_note_global_generator_store`
  result is exported in its module_loader entry (`kind: 'global_var'` gains a
  `generator_base` / `value_ctype` field, filled from the compiled gen, not
  the text scan); (b) the importer's `_emit_imported_global_accessors` seeds
  `_global_generator_api` from that field and declares the `{base}_start` /
  resume symbols extern (the same `#ifndef` guard pattern as the
  `std`-import extern block in `emit_infra.py` ~1520-1535); (c) poisoning
  still applies to any second writer. Test: two-module fixture in
  `test_gimple_generator_runner.py::run_module_global_generator_tests`, the
  idiom in the entry, compile + run, output matched to CPython.
- If the reading gen HAS the api and the refusal still fires: the loss is
  inside the closure's read path, not the transport. The dump names which of
  `_captures` / `_narrowed_exprs` / `_boxed_mut_locals` / `_tagged_dyn_src`
  returned early; that arm then carries the api (the 2026-10-30 fix is the
  template).
- If `_unsupported_generator_names` holds `_coro`: the defining `async def` was
  skipped by relaxed gating (module_gen.py:11103-11127); the fix is to keep it
  compiled when eligible, not to carry anything.

**Gate verdict owed.** The four rows' reject censuses (socket 56 / parsing 48 /
zipfile 62 / mailbox 66) must be re-measured after whichever branch lands; a
fix is progress only if the census drops or the moved modules' values match
CPython.

### Round 2026-10-31b — the owed probe lands as a tool (light worker; no full-closure run)

**Landed:** `tools/probe_coro_close_refusal.py`. It wraps
`emit_exprs._lower_IdentExpr` for one name (default `_coro`) and prints one
`PROBE` line per read with every table the 2026-10-29 decision list names
(`_global_generator_api`, `_global_generator_api_poisoned`,
`_imported_global_accessors`, `_captures`, `_narrowed_exprs`,
`_boxed_mut_locals`, `_in_toplevel_gen`, `_async_api`,
`_unsupported_generator_names`), plus `gen.module_name`, the returned ctype/temp
and the carried api's base. The wrapper only observes; the compile is unchanged.
`test_regress_coro_close_closure.py::test_probe_observes_read_without_changing_it`
pins that the wrapped read returns the real arm's result.

**Verified:** `test_regress_coro_close_closure.py` PASS (direct run, peak 0.0 GB);
a two-module smoke (`import sib` + idiom in the entry) compiles OK under the
probe and prints the expected `PROBE` line (`api_table=True`, carried base
`__mgco__c2`).

**The owed run (integrator, heavy — one row only):**

    python3 tools/memslot.py --gb 8 --label probe-coro -- \
        python3 tools/probe_coro_close_refusal.py <row entry .py> --do-imports

Use the mailbox row's entry (cold store). The last `PROBE` line before
`COMPILE: REFUSED` is the read that lost the api; read its flags against the
2026-10-31 decision list. This round does not move the reject census and changes
no codegen behaviour.

### Round 2026-10-31c — planning round: the generator-global tables are not shared across modules (light worker; no full-closure run)

**Line refs re-measured on this tree** (the 2026-10-29/31 line numbers have
drifted): the relaxed-skip site is `module_gen.py:11785-11815`
(`_unsupported_generator_names` consumers at :13272 and :16176); the
accessor arm is `emit_exprs.py:538-560`; the own-global read carry is
`emit_exprs.py:819-821`; the store recorder is `emit_stmts.py:1015-1046`
(`_note_global_generator_store`); the imported-module temp gen is built in
`emit_resolve.py` (`temp_gen` setup, ~line 735-1140).

**Measured:**
- Small compile, `do_imports=False`, the idiom alone: `_generator_api` has
  `_coro`; `_supported_async`, `_async_api`, `_unsupported_generator_names`,
  `_cpp_refusal_reasons` are all empty; `_global_generator_api` has `_coro`.
  So `async def _coro(): pass` is compiled on the GENERATOR-shaped path
  (registered in `_generator_api`), not the `_async_api` path. Any reasoning
  about the C++ async eligibility gate (`_async_quick_eligible`,
  `module_gen.py:11520/11565`) does not describe this idiom.
- Same idiom as an IMPORTED sibling (`sib.py`), entry `import sib`,
  `do_imports=True`: the sibling's `_coro.close()` compiles with no refusal
  (the emitted C has `close` x2, no `no known generator` text), and the
  importer's gen has `_generator_api == ['_coro']` but
  `_global_generator_api == []`, `_global_generator_api_poisoned == []`.

**The verified root-cause candidate (code, confirmed by grep):**
`emit_resolve.py` builds each imported module's `temp_gen` and copies the
generator tables by reference: `_async_api`, `_generator_api`,
`_generator_method_api`, `_generator_home_api` (~lines 1014-1017). It does NOT
copy `_global_generator_api` or `_global_generator_api_poisoned`, and
`gimple_codegen.py:1132` gives every `GimpleGen` its own empty dict. So:
- a generator held in a global of module A (`_coro = _coro()`) is recorded
  only in A's temp gen, and is GONE once A's compile returns;
- module B (importer, or the same closure's later module) never learns the
  global is a generator, and a poison written in one module is invisible to
  the others.
This is the cross-module transport gap the 2026-10-30b round measured
("the importer's gen does NOT record `_global_generator_api['_coro']`").
It is now located in code, not inferred. It is a candidate for the closure
refusal, NOT yet shown to be it: the refused statement is `_collections_abc`'s
OWN `_coro.close()`, and a same-module store/read stays in one temp gen. The
closure-only ingredient is therefore still unnamed. What the sharing gap does
establish is that every read of a generator global through another module
(`from sib import _coro`) runs without its api, which is exactly what the
landed accessor-arm fix (`emit_exprs.py:538-560`) needs in order to fire.

**Decision the next round needs (one measurement, then one change):**
1. Cheap, no heavy run: `from sib import _coro; _coro.close()` and
   `next(_coro)` with `sib.py` holding `_coro = _g()` (a generator global).
   Expected today: refused (`receiver typed int64_t` / `void *`). That is the
   gap; it reproduces on a 2-module closure at 0.0 GB.
2. The fix is to carry the table, not to special-case the read. Two options,
   pick one and state the reason in the commit:
   - (a) share `_global_generator_api` and `_global_generator_api_poisoned`
     by reference into `temp_gen` (same pattern as `_generator_api` at
     `emit_resolve.py:1015`). Trust risk: keys are bare names, so module B's
     unrelated global `foo` could inherit module A's `foo` api. Mitigation to
     verify first: a non-generator store of `foo` in B must poison it (it
     does, via `_write_dest` / `_global_var_types` at emit_infra.py:3689 if
     `_global_var_types` is shared, which it is at emit_resolve.py:824).
   - (b) key the table by module-qualified name. More correct, larger change.
   Recommendation: (a) with the poison-sharing check, because the existing
   trust model already poisons on any second binding.
3. Tests: (i) the 2-module case in step 1 must compile and `.close()`/`next()`
   must match CPython output; (ii) the poisoned-name shape (B writes `foo = 5`
   after A stores a generator into `foo`) must still refuse. Put both in
   `test_gimple_generator_runner.py::run_module_global_generator_tests`.
4. Only after 1-3 pass: re-run the mailbox row's `probe_coro_close_refusal.py`
   (owed, integrator) and the four reject censuses (56/48/62/66).

**Still owed (heavy, integrator):** the mailbox full-closure probe from
2026-10-31b. Its result decides whether the closure refusal is THIS gap (the
reading gen then lacks `_global_generator_api['_coro']` while the defining
gen had it) or the unnamed own-read path.
