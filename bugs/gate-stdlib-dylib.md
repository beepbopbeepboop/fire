# Gate: stdlib-dylib is red on master

**Job:** `stdlib-dylib`. Filed by the full gate at `203fd5ea3c`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

Reproduce on master (`python3 tools/suite.py stdlib-dylib`), then fix the cause.

## Gate ledger

- **Last known working:** `e8421fc41b` integrate fix-merge-fix-merge-fix-merge-bug-formal-formal-proof-covera
- **First known not working:** `131b61adee` diag: runtime assert prints 'Assert Error: <msg>'; except <name>: is a catch-all binding
- **Seen red in the full gate at:** `203fd5ea3c` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-203fd5ea.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-stdlib-dylib.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.

## Done when

The job is green on a tree with the `disabled=` argument removed from `tools/suite.py`, AND both quick tests below pass:

1. `python3 test_stdlib_dylib_ratchet.py` (the ratchet's own synthetic-dylib test).
2. The import-suffix agreement test named in the plan below (not yet written; it must fail on master first).

The job itself is the integrator's to run (`python3 tools/suite.py stdlib-dylib`); a worker does not run it.

## Status (2026-11-12): planning round — root cause narrowed, fix not landed

**What the job's red actually is.** The job fails with exit 1 and no `skip` lines: `build_stdlib_dylib.build_stdlib()` succeeds, and `tools/stdlib_dylib_ratchet.py` then fails its undefined-reference check, which names every `_std_` symbol the dylib references and does not define (clients abort at load). The build log at `build/stdlib_dylib.log` (Nov 12 12:16, verify tree) holds only `(150 modules excluded for symbol collisions)` and the export-table line, which is consistent with that.

**Measurement** — the dylib in the verify tree (`/Users/mrs/net/chatgpt/claude/work-verify/build/libmojostdlib.arm64.dylib`, Nov 12 14:37, built with the 150 exclusions) has **50 undefined `_std_` references**, classified by read-only `nm -u` / `nm -g -U` (a reference whose name minus its 6-hex suffix matches a defined name is a suffix mismatch; the rest have no definition):

- **21 are overload/instance-suffix mismatches.** The base name is defined, under a different 6-hex suffix. Example: `_std_collections_string__unicode_is_lowercase_55072c` is referenced, and `..._is_lowercase_fa3cf4` is defined. Same pattern for `is_uppercase`, `to_lowercase`, `to_uppercase`, `atof`, and the `Array`/`Deque` `__getitem__` instances.
- **29 have no definition under any suffix.** Examples: `_std_bit_mask_splat`, `_std_memory_alloc_dealloc_9f63a2`, `_std_collections_string_string__calc_initial_buffer_size`. These are the likely symptom of the 150 symbol-collision exclusions (`build_stdlib_dylib.py` ~L1099-1141) — but see the open question below.

**The suffix mismatch, reproduced in one light compile.** `compile_module_to_c` on two stdlib modules, each run under `tools/memslot.py --gb 8`:

- `std/collections/string/string_span.mojo` emits `std_collections_string__unicode_is_lowercase_55072c` (also `is_uppercase`, `to_lowercase`, `to_uppercase`, all `_55072c`) — the call names are correctly qualified; only the suffix is wrong.
- `std/collections/string/_unicode.mojo` defines `std_collections_string__unicode_is_lowercase_fa3cf4 (Span *s)`.
- `overload_suffix_for(['int64_t *'])` = `_55072c`; `overload_suffix_for(['Span *'])` = `_fa3cf4`. So the importer hashed `int64_t *` for `s: StringSlice[_]`, and the definer hashed `Span *`.

**Mechanism (from the code; the next round must confirm with a debugger print).**

- `mojo/middle/module_shared.py` ~L878-898 (the BUG-2026-024 import snapshot) computes the imported function's parameter ctypes with `self._signature_ctypes(_fs.params, _fs)` **in the importer's gen**. For a parametric `StringSlice[_]` parameter, the definer's gen infers `Span *` from the body; the importer's gen has no such inference and resolves `int64_t *`. The comment in `emit_funcs.py` (`_home_def_param_types`, ~L2470-2500) states exactly this disagreement.
- The definer's authoritative signature lives only in `gen._home_def_param_types`, a **per-process** store. The dylib build runs each module in its own worker (`pool.map`, `build_stdlib_dylib.py` ~L1074-1095), so importers in other processes never see it. The importer falls back to its own (wrong) snapshot.
- `emit_funcs._effective_param_types` tiers: 1 local def, 2 `_imported_def_pts` (this snapshot), 3 the shared `func_param_types[bare]` slot. Here tier 2 is the one that is wrong.

**Open question that blocks the 29 (must be answered before the plan is final).** The `dedup.log` from a 150-exclusion run (`/var/folders/bt/pjzl0n_w8xn64y008k907xch0000gs/T/mojostdlib__feynkon/dedup.log`) says `symbol already defined (_getdelim)` for every exclusion. That is the signature of the pre-`bb8554166` parser, which counted `(undefined) external _getdelim` as a definition; the current parser does not do that (it reports 0 `_getdelim` definers across that run's 249 pristine objects). So that log predates the fix, and the Nov 12 run's exclusions are **not explained by it**. Checked with the current parser:

- sequential dedup over the 249 pristine objects of that run: 5 real clashes (all `__SIterCodepoints_*`, generic-struct copies), all localizable;
- `_localize_symbols` succeeds on 238/238 objects with a synthetic clash (11 have no definitions);
- `std/collections/string/_unicode.mojo` compiles and clashes only on the `__SIterCodepoints_*` copies.

So the current exclusion trigger is not reproduced from these artifacts. Next step for the round that starts the fix: run the job once with the dedup log kept (`MOJO_DEDUP_LOG=<path>`), and list the exclusions' real clash symbols. Do not guess the 29 from the 21.

**Decision needed (the one that shapes the fix).** How does an importer learn the definer's committed parameter ctypes when the definer compiled in another process?

- **(a) Recommended:** the definer records its committed `_signature_ctypes` per function in its compile output (the module's export/manifest record, written by the definer's own compile, read by importers). Cross-process safe, and one resolver on both sides. Cost: the manifest format changes. The export table's `c_parameters` cannot be used as-is — its own comment says it carries `int64_t` placeholders for struct params — so the manifest needs the full ctype list.
- **(b)** The importer re-runs the definer's parameter inference over the definer's FunctionDef body (the definer's inference, in the importer's gen). Keeps the format, but duplicates inference — the "parallel implementation" CLAUDE.md forbids — and it is slower.

I recommend (a). Under (b) the duplication is the thing to avoid.

**Implementation plan (for option (a)).**

1. `mojo/backend_gimple/module_gen.py` (or wherever the definer's per-function ctypes are finalised; locate with `grep -n "_home_def_param_types\[" mojo/`): have the definer record `{function name -> committed _signature_ctypes}` in its compile result.
2. `build_stdlib_dylib.py` `_compile_module_job` (~L1063-1095): carry that record out with the module's `exports`, and cache it under the same CAS key as the `.o`.
3. `mojo/middle/module_shared.py` ~L893: replace the importer's `self._signature_ctypes(...)` with the definer's recorded list (fall back to the existing snapshot only when the record is absent, and count that fallback so it is visible).
4. Leave `_effective_param_types`' tier order alone; only tier 2's source changes.
5. For the 29: after the exclusion log is in hand, fix the clash/localize decision that produces them, or the export set they depend on.

**Tests that prove it.**

- **New (must fail on master first):** `test_stdlib_import_suffix.py` — compile `std/collections/string/string_span.mojo` and `_unicode.mojo` with `compile_module_to_c` (memslot 8 GB; about 1-2 s each); assert every `std_collections_string__unicode_*` call suffix in `string_span`'s C equals the suffix of the matching definition in `_unicode`'s C. Expected on master: fails with four mismatches.
- `python3 test_stdlib_dylib_ratchet.py` — the existing synthetic-dylib test, must stay green.
- Integrator only: `python3 tools/suite.py stdlib-dylib` with the `disabled=` argument removed, `stdlib-syntax` skip count not increased.

**Claims collision.** The claims list shows another worker holds `gate:stdlib-dylib` (`fix-gate-stdlib-dylib`), and `bug:CODEGEN_imported_global_export_type_residual_call_shapes` (`bug-codegen-imported-global-export-type`) touches the same export-scan / importer-signature area. Before starting the fix, the controller should confirm which lane owns `module_shared.py`'s import snapshot and the export record.
