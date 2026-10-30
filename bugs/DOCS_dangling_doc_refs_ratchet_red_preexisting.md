# DOCS: the `doc-refs` ratchet is red on master, and it grows with every integrate

## Status

OPEN. Pre-existing on master; not introduced by any single merge. Three
measurements, 2026-10-29, same machine, every run wrapped in
`tools/memslot.py`:

| tree | commit | `--ratchet` result |
|---|---|---|
| master at merge time (the merge parent) | `03720c18b` | exit 1, 17 files over baseline |
| merged tree, `work/fix-merge-bug-hard-codegen-param-used-only-as-meth` | `62093a363` | exit 1, 17 files — the identical file set to the merge parent |
| master tip (a few hours later) | `7949c7eee` | exit 1, 28 files |

The merged tree's 17 are the same file set as its merge parent: this merge
introduced zero new regressions. Its only tree deltas versus the merge parent
are two fixed-bug docs, deleted (their sole surviving citations retargeted to
the fix commits), and one open doc retargeted the same way.

## Reproduce

    python3 tools/memslot.py --gb 8 --label doc-refs -- \
        python3 tools/dangling_doc_refs.py --ratchet

The registered gate job is `doc-refs` in `check` (see CLAUDE.md). Exit 1
means at least one file cites more deleted docs than its per-file ceiling in
tools/dangling_refs_baseline.py.

## The 17 files at `03720c18b` and `62093a363`

The doc names below were deleted from the tree; each citing file is listed
with its over-ceiling count as measured. A line that says a doc was deleted
is not a citation, so these quotations stay out of the walk's own count.

- bugs/CODEGEN_ab_native_fails.md: 4 (baseline 1) — deleted docs cited: CODEGEN_noshim_dumpfull_preexisting_divergence.md, CODEGEN_the_gimple_match_lowering_drops_the_capture_and_reads_every_pattern.md
- CRASH.md: 2 (baseline 0) — deleted docs cited: CODEGEN_noshim_dumpfull_preexisting_divergence.md
- doc/OWNERSHIP_MODEL.md: 2 (baseline 0) — deleted docs cited: CODEGEN_noshim_dumpfull_preexisting_divergence.md
- mojo/backend_gimple/emit_methods.py: 2 (baseline 1) — deleted docs cited: CODEGEN_noshim_dumpfull_preexisting_divergence.md, RUNTIME_argparse_is_stubbed_so_parse_args_consumers_crash.md
- mojo/backend_gimple/module_gen.py: 2 (baseline 0) — deleted docs cited: CODEGEN_noshim_dumpfull_preexisting_divergence.md
- mojo/middle/types.py: 2 (baseline 1) — deleted docs cited: CODEGEN_noshim_dumpfull_preexisting_divergence.md, RUNTIME_argparse_is_stubbed_so_parse_args_consumers_crash.md
- CLAUDE.md: 1 (baseline 0) — deleted docs cited: CODEGEN_noshim_dumpfull_preexisting_divergence.md
- bugs/CODEGEN_str_slice_tuple_return_segfaults_at_run_time.md: 1 (baseline 0) — deleted docs cited: CODEGEN_imported_generic_never_elaborated_calls_nothing_defines.md
- bugs/COMPILE_FAIL_Tools_c-analyzer_c_analyzer___init__.md: 1 (baseline 0) — deleted docs cited: COMPILE_FAIL_Tools_c-analyzer_c_analyzer_info.md
- bugs/FORMAL_a_module_that_exports_nothing_cannot_be_a_dylib.md: 1 (baseline 0) — deleted docs cited: FORMAL_no_public_api_reason_lost_the_backend_rule_clause.md
- bugs/RUNTIME_gate_sqliteruntime_red.md: 1 (baseline 0) — deleted docs cited: the nested-module-walk PERF doc from the hard/ subdirectory (gone)
- mojo/backend_gimple/emit_calls.py: 1 (baseline 0) — deleted docs cited: CODEGEN_noshim_dumpfull_preexisting_divergence.md
- mojo/middle/lambdareduce.py: 1 (baseline 0) — deleted docs cited: CODEGEN_noshim_dumpfull_preexisting_divergence.md
- test_pin_dispatch_globals_list_fixed.py: 1 (baseline 0) — deleted docs cited: the dispatch-globals doc from the hard/ subdirectory (gone)
- bugs/OPEN_WORK.md: 7 (BARE baseline 3) — deleted docs cited include CODEGEN_noshim_dumpfull_preexisting_divergence.md, FORMAL_int_of_an_out_of_range_double_saturates_the_other_way_on_each_backend.md, FORMAL_macho_dylib_stub_and_segment_fields_violate_the_spec.md
- bugs/CODEGEN_bootstrap_resource_blowup.md: 5 (BARE baseline 0) — deleted docs cited: CODEGEN_noshim_dumpfull_preexisting_divergence.md
- mojo/middle/stmts_shared.py: 2 (BARE baseline 1) — deleted docs cited: CODEGEN_dynamic_attribute_on_generic_object.md, CODEGEN_noshim_dumpfull_preexisting_divergence.md

The dominant target is CODEGEN_noshim_dumpfull_preexisting_divergence.md
(deleted on master), cited from twelve of these lines.

## What master did in the same day

At tip `7949c7eee` the ratchet reports 28 files: the same drift plus eleven
more, minus one. The sqliteruntime gate doc (RUNTIME_gate_sqliteruntime_red.md)
went green on the tip because that file was itself deleted on master after the
merge above — its citation's target had already gone, and deleting the citing
file is one of the two valid resolutions. No commit in the range
03720c18b..7949c7eee touched the ledger, so the whole drift is citation-side.

## Stale ledger entries (a ceiling may be dropped)

The walk also reports two ledger entries the corpus has outgrown — the
citations were fixed, or the citing file was deleted; either the entries can
be removed or the ledger regenerated: CODEGEN_loop_target_rebind_outside_the_zip_enumerate_families.md
and tools/control.py.

## Next step

For each file over its ceiling, pick one:

1. Retarget the citation: name the BUG or the fix commit rather than the
   deleted doc (the convention test_arm64_encoders.py uses for its shift
   sweep). A line that says a doc was deleted is not a citation, so a
   sentence about one stays out of the count.
2. If the citation is deliberate, say so in a comment on the same line, or
   raise the ceiling on purpose with `--write-baseline` after reading the diff.

Deliberately not done here: no edits to those files (they belong to other
areas) and no ceiling rewrite, which would silence a pre-existing red rather
than resolve it.
