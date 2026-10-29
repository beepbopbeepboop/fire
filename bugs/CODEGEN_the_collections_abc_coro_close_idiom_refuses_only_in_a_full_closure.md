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
