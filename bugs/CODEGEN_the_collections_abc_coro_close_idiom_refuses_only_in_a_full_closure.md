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
`COMPILE_FAIL_zipfile___init__.md`, `CODEGEN_generator_function_Lib_mailbox.md`)
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
