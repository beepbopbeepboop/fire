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

The job is green on a tree with the `disabled=` argument removed from `tools/suite.py`, AND the quick tests below pass:

1. `python3 test_stdlib_dylib_ratchet.py` (the ratchet's own synthetic-dylib test).
2. `python3 test_stdlib_import_suffix.py` (written 2026-11-15; red before that round's fix, green after). It compiles `string_span.mojo` and `_unicode.mojo` with `compile_module_to_c` and requires every `_unicode` call in `string_span` to name the symbol `_unicode` emits, and pins the export record's parameter ctypes (`Span *` for `StringSlice[_]`, `char *` for bare `StringSlice`).
3. `python3 test_stdlib_import_extern_variadic.py` (written 2026-11-19). It pins the unexpected-skip class's root cause: the export record publishes the overloaded `std.time.sleep` as variadic (`...`, empty `c_parameters`), and the generated C of a synthetic importer and of `std/testing/assert_aborts.mojo` must declare that symbol variadic, never `(void)` — with a non-variadic control (`_unicode.is_lowercase`) so the test cannot pass by calling everything variadic.

The job itself is the integrator's to run (`python3 tools/suite.py stdlib-dylib`); a worker does not run it.

## Status (2026-11-19, this round): the residual skip fix is SUPERSEDED on master, so nothing from it is needed here; a pinning test now covers the class; the doc stays because this base cannot carry the job's switch

**All three quick tests pass on this tree**, each run under
`tools/memslot.py --gb 8 --label t`:

    python3 test_stdlib_import_suffix.py          -> PASS (0.1 GB)
    python3 test_stdlib_dylib_ratchet.py          -> PASS (0.0 GB)
    python3 test_stdlib_import_extern_variadic.py -> PASS (0.0 GB; new)

RED-before for the new test is measured, not asserted: running it with
`_emit_stdlib_import_externs` wrapped to replace the imported `sleep` extern
with `(void)` — exactly what the regression below emitted — fails four checks
(`synthetic importer: every extern is variadic`, `synthetic importer: no (void)
prototype`, and both for `std/testing/assert_aborts.mojo`). The tree's own
emitter keeps the export record's text, so the test is green here.

**The earlier 2026-11-19 Status's next step (`56470f49b`) is obsolete, twice
over.** That commit patched `_emit_stdlib_import_externs` where the importer
rebuilt every extern signature from `c_parameters`; an overloaded export has
`c_parameters: []` and only the text `ret name (...)`, so the rebuild produced
`(void)` and `sleep(x)` in `std/testing/assert_aborts.mojo` became a NEW dylib
skip. But:

- `5a0dcec4a` (master, 2026-11-15 12:32 — twelve minutes after `56470f49b`)
  removed that rebuild entirely: the importer now emits
  `gimple_ctypes.c_client_sanitize_signature_text(sig)`, so the export record's
  `(...)` is kept. This branch's base predates the rebuild (`ae41bf838`) and
  needs no patch: `std/testing/assert_aborts.mojo` compiles here and emits
  `extern int64_t std_time___init___sleep (...)`.
- `942bc269c` (master, 2026-11-12 14:53 — ten minutes after this branch's merge
  base `88ccccf1d`) replaced the ratchet's `nm -u`-vs-`nm -gU` contract with
  the `dlopen(..., RTLD_LAZY)` load contract, re-enabled the job, and deleted
  this doc. The 29 "no definition under any suffix" references it left are
  reported as lazy notes, not a failure; parts 8/9 then landed (`2b992be66`,
  `30c4597ef`).
- The three modules `56470f49b` wanted in `EXPECTED_FAILURES`
  (`std/compile/compile.mojo`, `std/ffi/__init__.mojo`, `std/simd.mojo`) all
  compile on this base with `compile_module_to_c` (measured: 35020, 123139 and
  535409 bytes of C, no exception), so no entry is warranted, and this base's
  `EXPECTED_FAILURES` is empty.

**Why the doc still is not deleted here.** Deleting it requires removing
`disabled='bugs/gate-stdlib-dylib.md'` from `tools/suite.py` in the same commit
(the marker is the doc's existence switch), and on this base the job cannot
pass: the ratchet predates `942bc269c` and still fails on the lazy references
parts 8/9 exist to fix, neither of which is in this branch. Removing
`disabled=` would declare green a job this base cannot pass; deleting the doc
with the marker still present makes `tools/suite.py` refuse to load its
registry. The delete belongs to the tree that carries `942bc269c` — which is
where it already happened. Master has since re-filed the same path for a
different red (`83b4bccad`: eight files failing elaboration on
`work/bug-codegen-scalar-integer-dtype-represe-4`), so a delete from this stale
base must not overwrite that filing either.

**Next step: none on this branch.** The branch's remaining value is the new
pinning test (independent of the job). On master the job is already enabled on
the load contract, and its open red is the re-filed eight-file elaboration bug
owned by that other branch's lane — not this one.

## Status (2026-11-19): part 6 is already on master; the residual skip fix is a dead lane's unlanded commit; doc stays

**Measured, not re-asserted.** Both Done-when quick tests pass on this tree,
each run under `tools/memslot.py --gb 8`:

    python3 test_stdlib_import_suffix.py   -> PASS (0.1 GB; call symbols + export-record ctypes)
    python3 test_stdlib_dylib_ratchet.py   -> PASS (0.1 GB; synthetic dylib, names the missing symbol)

**Part 6 is already on master, twice over.** `2a76b8e55` ("land: ADAPT
bug-gate-stdlib-dylib-3 suffix rule onto master") landed this branch's
`5b1f033a5` rule — `mojo.middle.types.param_annotation_ctype` plus the three
readers (`funcs_shared._param_ctype`, `module_loader`'s scan, `reflect._param_mt`)
and the 209-line `test_stdlib_import_suffix.py`; `ed92614db` landed the
bracketed `Span *` half. So the 2026-11-17 Status's "next step" (land
`5b1f033a5`) is done on master, not pending. The parts 8/9 blockers named
there also landed (`2b992be66` gives same-name free-function overloads their
own definitions; `30c4597ef` emits cross-module generic free-function
instances), and `942bc269c` replaced the `nm -u` contract with the
`dlopen(RTLD_LAZY)` load contract and removed `disabled=` from the job on
master.

**The one residual this branch cannot finish.** The unexpected-skips fix is
`56470f49b` on `work/fix-proof-fix-gate-stdlib-dylib` (emit variadic `(...)`
externs for an overloaded imported function whose export signature has no
concrete parameters, plus three `EXPECTED_FAILURES` entries). It is NOT on
master: `git show master:mojo/backend_gimple/emit_infra.py` has no
`info.get('variadic')` branch, and master's `compile_stdlib.EXPECTED_FAILURES`
does not name those modules. Its lane is dead: `control.py status` shows it
`exited-err` after 0 s, and its `work.log` is the provider's "Free usage limit
reached" error, while its `gate:stdlib-dylib` claim is still registered. Its
files (`mojo/backend_gimple/emit_infra.py`, `compile_stdlib.py`) are that
lane's claim, so this round did not edit them.

**Why the doc is not deleted here.** On this base `tools/suite.py:2506` still
carries `disabled='bugs/gate-stdlib-dylib.md'`; deleting the doc while the
skips fix is absent makes `tools/suite.py` refuse to load its registry, and
removing `disabled=` would declare green a job this base cannot pass. On
master the job is enabled and its current red is a DIFFERENT filing:
`83b4bccad` re-filed `bugs/gate-stdlib-dylib.md` for the eight stdlib files
that fail elaboration on `work/bug-codegen-scalar-integer-dtype-represe-4`
(the placeholder copy filed under `bugs/mid/` is that re-filing). That red
belongs to that branch's lane, not here.

**Next step.** Land/adapt `56470f49b` on master — keep the variadic-extern
half, but drop its `std/simd.mojo` `EXPECTED_FAILURES` entry, since master's
own comment at `compile_stdlib.py:110` records that module as clean since
2026-11-14 — then run `python3 tools/suite.py stdlib-dylib`; when it is green,
delete this doc and the `bugs/mid/` placeholder in the same commit and run
`python3 tools/dangling_doc_refs.py --ratchet`. Both Done-when quick tests
already pass here.

## Status (2026-11-17): part 6 is measured complete; the red this doc was re-filed for is the UNEXPECTED-SKIPS class, owned by another lane

**This branch's root cause is fixed and now pinned for all of part 6.** The
shared parameter rule landed in `5b1f033a5`
(`mojo/middle/types.param_annotation_ctype`, used by
`funcs_shared._param_ctype`, `module_loader._mojo_type_to_c(..., param=True)`
and `reflect._param_mt`). This round extended the Done-when test to the rest
of part 6's acceptance, all three pairs measured on this tree:

| importer call | definition | caller suffix before -> after |
|---|---|---|
| `_unicode.is_lowercase(StringSlice[_])` | `_fa3cf4` | `_55072c` -> `_fa3cf4` |
| `_utf8._count_utf8_continuation_bytes(Span[UInt8, _])` | `_fa3cf4` | `_55072c` -> `_fa3cf4` |
| `_amdgpu.printf_append_string_n(..., Span[UInt8, _], ...)` | `_bdbef0` | `_f5e74a` -> `_bdbef0` |
| `parsing_floats._atof(StringSlice)` (bare) | `_d719e0` | `_55072c` -> `_d719e0` |

RED-before is proved, not asserted: running `test_stdlib_import_suffix.py`
with `mojo.middle.types.param_annotation_ctype` monkeypatched back to the old
`Span`/`StringSlice` -> `int64_t *` box (which is the branch base's
`module_loader` rule; `funcs_shared` binds the rule at import, so the
importer is reverted) fails every call/export check it contains (17 FAIL
lines in that run, the reflection pin included because `reflect` imports the
patched name) — the four `_unicode` mismatch pairs,
`_count_utf8_continuation_bytes`, `printf_append_string_n`, and the four
export-record ctype checks. With `reflect._param_mt` reset to the old `_mt`
(the field/return resolver) the new reflection pin fails too
(`probe_bare(StringSlice)`: codegen `_d719e0` vs reflect `_9f63a2`). With the
tree's rule both are green. The export record now also pins `Span * span` for
`_count_utf8_continuation_bytes` and `Span * data` for
`printf_append_string_n`, and the reflection pin covers both spellings, i.e.
the third reader of the rule.

**Correction to the 2026-11-15 Status below: it measured the job against the
SUPERSEDED ratchet contract.** Master's `tools/stdlib_dylib_ratchet.py` no
longer fails on a `_std_` reference with no definition — `942bc269c`
(2026-11-12, "gate the dylib on LOADING, not on a complete export set") made
the contract `dlopen(..., RTLD_LAZY)`; the residual lazy references are
printed as a note. This branch's base predates that commit, so the "29 make
the job red" reading is true only of the old `nm -u`-vs-`nm -g -U` check, not
of the job as it now gates.

**What the job's red at the re-filing actually is.** The gate round that
re-filed this doc (`fa105c747`, 2026-11-15) names no cause; the lane holding
`gate:stdlib-dylib` found and fixed it in `56470f49b` ("gate: fix
stdlib-dylib unexpected skips"): emit variadic `(...)` externs for an
overloaded imported stdlib function whose export signature has no concrete
parameters (so `time.sleep(...)` in `std.testing.assert_aborts` compiles),
and add the three modules that fail elaboration (`std/compile/compile.mojo`,
`std/ffi/__init__.mojo`, `std/simd.mojo`) to `EXPECTED_FAILURES`. That commit
deletes this doc, which is the right landing for it. Its files
(`mojo/backend_gimple/emit_infra.py`, `compile_stdlib.py`) are another lane's
claim, so this branch does not touch them, and it does not delete the doc
either: deleting it here would declare green a job whose red this branch does
not fix, on a base that cannot observe master's load contract.

**Next step.** Land `work/fix-proof-fix-gate-stdlib-dylib` (56470f49b) together
with this branch's `5b1f033a5`; on that merged tree the job's Done-when holds
and this doc goes with 56470f49b. Until then both Done-when quick tests pass
on this tree: `python3 test_stdlib_dylib_ratchet.py` (PASS) and
`python3 test_stdlib_import_suffix.py` (PASS, now 3 pairs / 4 export records).

## Status (2026-11-15): the 21 suffix mismatches' root cause fixed (scan-side type drift); the job is still red on the 29

**What landed.** The 21 "overload/instance-suffix mismatches" were not a cross-process
inference problem at all: the importer's suffix never came from the definer's
signature. `module_loader._mojo_type_to_c` — the export text scan the importer
reads (`_emit_stdlib_import_externs` sets `func_param_types[sym]` from its
`c_parameters`) — boxed every `Span`/`StringSlice` parameter to `int64_t *`, to
avoid naming a `Span` typedef an importing TU "might not have". Every generated
TU has carried `typedef struct Span Span;` in its prelude since that workaround
became stale, and the box is a DIFFERENT C type from the one the defining
module emits (`_param_ctype`):

    string_span.mojo calls   ..._is_lowercase_55072c (int64_t * s)
    _unicode.mojo defines    ..._is_lowercase_fa3cf4 (Span * s)

The bare spelling was the same bug in its other shape: `_atof(x: StringSlice)`
is emitted with `char *` (`_d719e0`) and was called with `int64_t *`
(`_55072c`), i.e. `atof` from this doc's list. One symbol, two independent
type resolvers — the CLAUDE.md "no duplicated implementations" failure.

**Two corrections to the mechanism note below.** A fresh gen's
`_signature_ctypes([('s', 'StringSlice[_]')], fn)` resolves `Span *`, not
`int64_t *` (measured), and `module_shared.py`'s snapshot block is inside the
`if _sib_qualifier and sym_info:` arm, so a STDLIB import never reaches it. The
importer's `int64_t *` comes from `func_param_types[sym]`, which
`_emit_stdlib_import_externs` fills from the export scan — i.e. the second
resolver in `module_loader.py`, not cross-process inference and not
`_signature_ctypes`.

The fix states the parameter-annotation rule ONCE, in
`mojo/middle/types.param_annotation_ctype` (bare string wrappers → `char *`;
everything else → `_mojo_type`, whose bracket branch already gives `Span *` for
`StringSlice[_]`/`Span[...]`), and makes the three existing readers use it:

- `mojo/middle/funcs_shared._param_ctype` — the definer's own parameter
  resolver (its `char *` branch is now the shared predicate);
- `module_loader.ModuleLoader._mojo_type_to_c(..., param=True)` — the importer's
  export text scan (the Span/StringSlice box is deleted; `param=True` is now
  passed at both parameter sites, return types keep `_mojo_type`'s rule);
- `reflect.py::_param_mt` — the AST signature emitter whose `export_csym`
  advertises the dylib's reflection entries (its advertised symbol for a bare
  `StringSlice` parameter was also hashed from `int64_t`).

Measured on this tree (each compile under `tools/memslot.py --gb 8`):

- `string_span.mojo`: the four `_unicode` references are now
  `is_lowercase/is_uppercase/to_lowercase/to_uppercase_fa3cf4`, matching
  `_unicode.mojo`'s definitions (were `_55072c`).
- `string.mojo`'s `_atof` call is now `..._atof_d719e0 (char * x)`, matching
  `parsing_floats.mojo`'s definition (was `_55072c (int64_t * x)`).
- 151 parameter entries across the stdlib change to the type their defining
  module emits; no other annotation does (the shared rule differs from
  `_mojo_type` only for those four bare names).
- New regression test `test_stdlib_import_suffix.py`: RED before the fix with
  exactly the ten failures the pre-fix resolver produces (four call-vs-definition
  mismatches, their four general-rule twins, and the two export-record checks),
  GREEN after. Also `test_stdlib_dylib_ratchet.py` and `test_module_cache.py`'s
  cross-module / reflect cases (24 checks) pass.

**This supersedes the (a)/(b) decision for the 21, not for everything.** Option
(a) (the definer publishing committed signatures) is still the answer for a
signature whose ctypes come from BODY inference (an unannotated parameter
refined at emit time) — the scan cannot re-derive those, and this round did not
touch that class. But the measured 21 were all annotated parameters whose types
the two resolvers disagreed about; no manifest was needed for them.

**Master's `4ac31ae95` fixed only the bare half, and its p6 probe proves the
other half is still red.** That commit (2026-11-14, `_parsing_numbers` part 2)
replaced the `int64_t *` box with `char *` for BOTH spellings. `char *` is what
a BARE `StringSlice` parameter emits (`_atof` -> `_d719e0`, so
`p2_imported_suffix_matches_the_defining_unit` is green), but a bracketed
`StringSlice[_]` parameter emits `Span *` (`fa3cf4`), so the same commit still
leaves `is_lowercase`/`is_uppercase`/`to_lowercase`/`to_uppercase` hashing
`_d719e0` against `_fa3cf4`. Measured this round with master's own probe file
run against a scan forced back to `4ac31ae95`'s rule:

    p6 under master 4ac31ae95 scan: FAIL -> string_span references
      ..._is_lowercase_d719e0 but _unicode defines ..._is_lowercase_fa3cf4

With this round's rule both probes pass (`p2_imported` and `p6_bracketed` in
`test_stdlib_dylib_lazy_undefined_refs_probes.py`, master's file, run against
this tree). So when landing, resolve the `module_loader._mojo_type_to_c` hunk in
favour of this change (it deletes the box and splits parameter from return
type), NOT by keeping `4ac31ae95`'s `char *` for both. That commit's part-6 doc
in the CODEGEN_stdlib_dylib_lazy_undefined_refs family is then resolved too:
p6 is its Done-when probe, so delete that doc (and run
`dangling_doc_refs.py --ratchet`) in the landing commit — the doc is not on this
branch's base, which is why it could not be deleted here.

p7 of that family (a parameter/return type that is a struct PRIVATE to the
defining module is seen by the scan as `int64_t`) is a different class: its
type is not an annotation the shared rule can resolve without the definer's
struct table, so it stays open. It is claimed by another lane
(`claude-lazy-refs-part7`).

**What is still red, so this doc stays and `disabled=` stays.** The 29 "no
definition under any suffix" symbols — the other half of the original 50 — are a
different mechanism, filed as parts 8 and 9 of the
CODEGEN_stdlib_dylib_lazy_undefined_refs family (part 8: same-name free-function
overloads neither emitted nor callable; part 9: a generic free function
instantiated only by another module is never emitted; both open on master).
The Array/Deque `__getitem__` instance-suffix mismatches are in the same
generic-instance family. None of them were reproduced or changed here. So the
job is NOT green: the integrator must not remove `disabled=` or delete this doc
until parts 8/9 (and the method-instance half) land. The open question about
the 150 symbol-collision exclusions below is also unchanged (it needs a full
build with `MOJO_DEDUP_LOG`, which a light worker does not run).

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
