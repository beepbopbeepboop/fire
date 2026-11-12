# Round 2026-11-11: `make check` reds fixed on master

**Status:** 6 jobs fixed and committed on `master`; master pulled to `d210765a2`.
Stopping here so the code can be moved around.

## Fixed (each with its own commit)

| job | commit | what was wrong |
|---|---|---|
| `no-new-casts` | `bfe9096f2` | `_lower_subscript` spelled the same bytes-slot coercion twice (the `_struct_slot_kinds` arm and the `_tuple_slot_types` arm `dd73f8bcd` added); the guard counts spellings. One `_list_slot_bytes` helper serves both. |
| `formal-bracketed-method-field-set` | `d05a3c8c7` | Six existing cases declared `out self` WITH a return type, which modular rejects (`mojo/test/mojo-parser/decls/decls_errors.mojo:108`) and `551bbbccf` started rejecting here. Rewritten to `mut self` — the same `MUTATING_RECEIVER_CONVENTIONS` entry the model already used. Three cases were in `test_formal_bracketed_method_field_set.py` (the first crashed the job out of `_parse_funcdef`), three in `test_formal_frame_slot_subscript_census.py` (the census tool swallows the parse failure and returned `[]`). |
| `doc-refs-stale-verdicts` | `99eb78995` | `bugs/hard/README.md` named 8 deleted docs and had no row for 17 docs on disk. Now indexes exactly the 25 docs on disk. |
| `gimple` | `1851f24bf` | `d[i]` on a `Dict[Int, Int]` stringified the key (`mojo_cstr_or_int_str` + a release per access). `mojo_dict_slot_boxed` is now in `emit_infra._KW_DICT_FNS` and has a `_kw` twin, `mojo_dict_slot_boxed_kw`, which answers through `_dict_slot_boxed` so a bool/None slot keeps its kind. |
| `runtimediff` | `1851f24bf` | `dict_items_reads_each_slot_kind`: a container stored under dict kind 0 rendered as its own ADDRESS in `print(d)`, `d.items()` and `d.values()`. `_dict_val_repr_int` now declines a registered-container word, and the emitted `_mojo_repr_dict` hands a container kind-0 slot to `_mojo_generic_elem_repr`. The probe is the container registry, not a range test, so an integer stored under kind 0 (2^40) still renders as itself. |
| `suite-self-test` (1 row) | `07131682d` | `emit_stmts` imported `_box_escaping_dict_slot_read` from `emit_calls` at module level; `emit_calls -> gimple_codegen -> emit_stmts` made `import mojo.backend_gimple.emit_calls` fail outright. Now reached through the `ggc` alias every other helper in that file uses. |

## Master pulled

`origin/master` was 20 commits ahead, then 2 more; both merged (`e8e703447`,
`d97ad68c7`). One conflict, `bugs/hard/README.md`: master's own index is stale
(its `doc-refs-stale-verdicts` job is red there — 2 names it lists do not exist,
17 docs on disk have no row; it had dropped `.md` from deleted docs' names to
make the check ignore them). Resolved with our version; both directions of
`test_dangling_doc_refs.py` pass. The `doc-refs` ratchet is green.

## Verified

- `test_gimple.py` 437 passed / 0 failed (was 435/2)
- `test_runtime_diff.py` 69/0 (was 68/1)
- `test_ptr_registry.py` 28/28
- `test_runtime_header_scan.py` 53/53 (the new declaration is banked: 806 -> 807)
- `test_dangling_doc_refs.py` 7/7
- `tools/dangling_doc_refs.py --ratchet` green
- `test_suite.py` 358/19 (was 357/20)

## The two master merges

`origin/master` moved twice while this round ran; both are merged.

1. `e8e703447` / `d97ad68c7` — 22 commits (PEP 810 lazy imports, the narrowed
   `out self` check, import ambiguity by lexical scope, `isinstance` reporting
   `_Bool`, cpp-path f-string refusals, comptime assert in a called generic,
   `formal/elf` `.rela.dyn`, orchestration tooling). One conflict,
   `bugs/hard/README.md`: master's own index was stale (its
   `doc-refs-stale-verdicts` job was red there — 2 names it lists do not exist,
   17 docs on disk have no row; it had dropped `.md` from deleted docs' names to
   make the check ignore them). Resolved with our version.
2. `7f75c96cb` / `73e8057ae` (by the integrator) — 83 commits: the SPLIT
   decompositions, the `out self` check, more diagnostics. Three reds followed,
   all fixed here:
   - `bugs/hard/README.md` again — the five SPLIT part docs had no row
     (`ae3f0228a`).
   - the `doc-refs` ratchet — two new dangling citations, one real
     (the deleted elaboration-recursion diagnostics doc, which master's side of
     the next merge rewrites as "the elaboration-recursion diagnostics bug doc")
     and one fixture (`tools/test_swarm_replan.py` writes a synthetic hard-class
     doc named `X.md` into a temp dir; sanctioned in the ledger at 1, documented
     in its header) (`3070c1081`).
   - `test_formal_bracketed_method_field_set.py` — master's new
     `_check_out_self_declaration` refused the last `out self` fixture
     (`7c06a4ffe`).

3. `ea14049db` / `2e3c98267` — 27 more commits (the container-variable
   f-string fix, the c-analyzer replans, the linked-list hash probe). One
   conflict, `bugs/mid/DIAGNOSTICS_missing_validation_modular-part1.md`, where
   master had independently fixed the same dangling citation by naming the bug
   instead of the deleted doc's path; master's wording is taken. Two more reds:
   the merge re-exposed the ratchet on this round's own status doc (it had
   quoted the fixture's synthetic doc path), and `test_no_new_container_casts.py`
   went to 27 — the new `_cpp_fstring_list_piece` spelled five ad-hoc
   `(MojoList *)` casts, now routed through `_cpp_as` (`e638c9447`).

## Still open

From the report, the jobs not addressed here: `gimplegenerators`, `gimplerunner`,
`silentnoop`, `modcache`, `formal-host-import-shapes`, `suite-self-test` (19
rows), `doc-refs` (marker), `async-void-return`, `bootstrap-stage1-dumps`,
`formal-link-accounting`. Several names in the report (`selfhost`, `linkmode`,
`runtimere`, `globcompiled`, `rthdrscan`, `ptrreg`, `sqliteruntime`,
`formal-sweep-truth`, `formal-per-struct-asks`, `formal-doc-truth`, `formal-sys`,
`formal-read-before-store`) are green on current master.

`async-void-return`'s two failures are a codegen gap, not a bug in a lowering:
an async closure calling an unresolved callee (`Ctx.enqueue_cpu_function`'s
wrapper) is refused. `modcache`, `gimplerunner` and `silentnoop` were not
reproduced here.

## Pre-existing, not from the merge

`bugs/TEST_out_self_with_return_type_fixtures_are_invalid_mojo.md` (OPEN, HARD)
is the same `out self` question in the fixtures themselves: 32 of them across
five files declare `out self` on an ordinary method, which modular refuses
(`out` is the RESULT convention). They are red independent of this round —
`test_formal_method_param_field.py` 11, `test_formal_debug_assert.py` 2, and
`test_formal_run.py`'s share — because `551bbbccf` made our front end refuse
the combination. The fix is mechanical (`out self` -> `mut self`, as done here
for the four in `test_formal_bracketed_method_field_set.py` and the three in
`test_formal_frame_slot_subscript_census.py`) but it is a separate campaign the
bug doc tracks.
