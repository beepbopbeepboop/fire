# recover/save.md

Re-derived from content, not subject lines. This replaces the first draft, which called 1095 merges integration merges
without checking them, and counted 94 non-merge commits already on master as unique.

## Summary
PARKED rows (110) are NOT on master. Their docs are on branch work/recover-apply-haiku (23 commits). Each row's tag keeps its commit reachable. Decision on them is pending.

- Dangling commits: 1310. Each is a chain of length 1: no dangling commit names another as a parent.
- MERGE-LANDED: 1010. The merge's second parent (the branch tip it merged in) is on master.
- MERGE-CONTENT-ON-MASTER: 68. The branch tip's changes are on master by patch-id. Tag kept (merge's own resolution).
- NONMERGE-ON-MASTER: 111. Same patch-id as a master commit, or master already contains the change.
- NONMERGE-EMPTY: 7. No diff.
- NONMERGE-UNIQUE: 97. No master patch-id match, and the reverse-apply check fails.
- MERGE-UNIQUE: 17. The branch tip has changes not on master.
- Tags: recover-<sha9> exist only for the NEEDS rows (unique plus merge-content-on-master). Others were deleted as landed or identical.

## Needs integration (oldest first)

Dispositions, branch `work/recover-apply-haiku` (2026-11-02). Evidence, all run this session:
- Patch-id against master (`git log master -p --no-merges | git patch-id --stable`, matched to `git show <sha> --no-merges | git patch-id --stable`, or the merge's first-parent diff): **0 of 114** match. Table in `.tmp/checks.tsv`.
- Reverse-apply (`GIT_INDEX_FILE=.tmp/idx git read-tree master`, then `git apply --cached -R --check` of the commit's diff): **0 of 114** pass. Sanity-checked on a master commit, which passes.
- Forward-apply (same temp index, `git apply --cached --check` of the diff): 12 of 114 apply cleanly to master's tree; 102 do not. Table in `.tmp/fwd.json`.
- No row qualifies for ALREADY-ON-MASTER or OBSOLETE.
- **APPLIED: 4** (cherry-picked onto this branch, narrow test run). **BUG-DOC: 110** (one doc each under `bugs/mid/RECOVER_*.md`).
- Branch base is `7877347f7`, 25 commits behind master. Most BUG-DOCs are conflicts with master's later edits, not defects in the commits. Rebasing the branch onto master (controller's call) would apply the 12 forward-clean rows directly, and the rest still need manual resolution.
- Marker commits `4970a5506` and `5d20c342c` (`.wip-base`, `.wip-chk2`) were applied and reverted (`90295450b`, `964ffb2dc`). They are BUG-DOCs.
- Narrow test for `581cd068b` (from `93cdc68cf`): `test_gimple.py` under memslot, 428 passed, 2 failed (`a_character_is_an_immortal_table_entry_not_a_slice`, `for_over_str`). Neither is in the diff of the applied commit (which changes `emit_infra.py` and adds the dedup check). Not verified against the base.


| # | Tag | Date | Kind | Files | Subject | Disposition |
|---|---|---|---|---|---|---|
| 1 | recover-1b22f11c6 | 2026-07-16 | commit | 1 | Add enum keyword support as a mojo.py extension (mojolib BUG-2026-024) | PARKED: `bugs/mid/RECOVER_Add_enum_keyword_support_as_a_mojo_py_extension_1b22f11c6.md` (fwd-check on master index: fwd-fail) |
| 2 | recover-a40ce6a55 | 2026-09-06 | commit | 1 | bugs: update zipfile Status -- os.path.splitdrive/splitroot + reversed() landed | PARKED: `bugs/mid/RECOVER_bugs_update_zipfile_Status_os_path_splitdrive_sp_a40ce6a55.md` (fwd-check on master index: fwd-fail) |
| 3 | recover-f04048b87 | 2026-09-15 | commit | 157 | Rename mojo.py to fire.py and mojo_compiler.py to fire_compiler.py across entire repository | PARKED: `bugs/mid/RECOVER_Rename_mojo_py_to_fire_py_and_mojo_compiler_py_t_f04048b87.md` (157 files; fwd=fwd-fail) |
| 4 | recover-abf5638ba | 2026-09-25 | commit | 14 | formal: struct types, methods, and a one-word layout that actually works | PARKED: `bugs/mid/RECOVER_formal_struct_types_methods_and_a_one_word_layou_abf5638ba.md` (14 files; fwd=fwd-fail) |
| 5 | recover-e552ae5d0 | 2026-09-25 | commit | 6 | formal: widen the sweep, and stop the dylib path failing for the wrong reason | PARKED: `bugs/mid/RECOVER_formal_widen_the_sweep_and_stop_the_dylib_path_f_e552ae5d0.md` (fwd-check on master index: fwd-fail) |
| 6 | recover-8bb98d4fe | 2026-09-30 | merge | 0 | integrate fix-merge-compiled-silent-2 | PARKED: `bugs/mid/RECOVER_integrate_fix_merge_compiled_silent_2_8bb98d4fe.md` (20 files; fwd=fwd-fail) |
| 7 | recover-61d3c07e2 | 2026-09-30 | merge | 0 | integrate fix-merge-fix-merge-fix-merge-fix-merge-fix-merge-fix-round8 | PARKED: `bugs/mid/RECOVER_integrate_fix_merge_fix_merge_fix_merge_fix_merg_61d3c07e2.md` (157 files; fwd=fwd-fail) |
| 8 | recover-0d71c2e43 | 2026-09-30 | commit | 1 | Move _static_arg_elems out from under the METHOD-half comment it was never about | PARKED: `bugs/mid/RECOVER_Move_static_arg_elems_out_from_under_the_METHOD_0d71c2e43.md` (fwd-check on master index: fwd-fail) |
| 9 | recover-2f60724c8 | 2026-09-30 | merge | 0 | integrate fix-merge-fix-merge-fix-merge-fix-round8-selfhost | PARKED: `bugs/mid/RECOVER_integrate_fix_merge_fix_merge_fix_merge_fix_roun_2f60724c8.md` (116 files; fwd=fwd-fail) |
| 10 | recover-f563ac810 | 2026-10-01 | commit | 6 | tests: gate the fourteen registered tests nothing ran, and make an `expect=` marker's stated count checkable | PARKED: `bugs/mid/RECOVER_tests_gate_the_fourteen_registered_tests_nothing_f563ac810.md` (fwd-check on master index: fwd-fail) |
| 11 | recover-42f2531a3 | 2026-10-01 | commit | 18 | parser+codegen: a 1-tuple for-target and a parenthesised single name are two targets | PARKED: `bugs/mid/RECOVER_parser_codegen_a_1_tuple_for_target_and_a_parent_42f2531a3.md` (18 files; fwd=fwd-fail) |
| 12 | recover-737b5b00e | 2026-10-01 | commit | 3 | the 15 registered tests that no bucket ever ran, now run — and a check | PARKED: `bugs/mid/RECOVER_the_15_registered_tests_that_no_bucket_ever_ran_737b5b00e.md` (fwd-check on master index: fwd-fail) |
| 13 | recover-144a2b145 | 2026-10-02 | commit | 4 | formal: a dict from a CALL has a shape, and a string index against an unstated base is refused | PARKED: `bugs/mid/RECOVER_formal_a_dict_from_a_CALL_has_a_shape_and_a_stri_144a2b145.md` (fwd-check on master index: fwd-fail) |
| 14 | recover-ba212ef21 | 2026-10-02 | commit | 4 | A local rebound to two container kinds is the box in a closure too, and the box survives a hop | PARKED: `bugs/mid/RECOVER_A_local_rebound_to_two_container_kinds_is_the_bo_ba212ef21.md` (fwd-check on master index: fwd-fail) |
| 15 | recover-791e53d7e | 2026-10-02 | commit | 6 | A module global rebound inside a function has no single kind: box the field, keep the semantic | PARKED: `bugs/mid/RECOVER_A_module_global_rebound_inside_a_function_has_no_791e53d7e.md` (fwd-check on master index: fwd-fail) |
| 16 | recover-6126ab815 | 2026-10-02 | commit | 3 | formal: the field-access refusal no longer claims a binding it cannot see | PARKED: `bugs/mid/RECOVER_formal_the_field_access_refusal_no_longer_claims_6126ab815.md` (fwd-check on master index: fwd-fail) |
| 17 | recover-511e44b01 | 2026-10-03 | commit | 3 | formal: a subscript through an UNANNOTATED parameter takes the convention its call sites use, and a base declared an integer is refused | PARKED: `bugs/mid/RECOVER_formal_a_subscript_through_an_UNANNOTATED_parame_511e44b01.md` (fwd-check on master index: fwd-fail) |
| 18 | recover-7dfa6575f | 2026-10-03 | commit | 6 | formal: a store into a module-owned blob is REFUSED, and so is an untyped one | PARKED: `bugs/mid/RECOVER_formal_a_store_into_a_module_owned_blob_is_REFUS_7dfa6575f.md` (fwd-check on master index: fwd-fail) |
| 19 | recover-b20a4544b | 2026-10-03 | commit | 2 | formal/imports: `html` has a tier now, so it leaves the UNCLASSIFIED row | PARKED: `bugs/mid/RECOVER_formal_imports_html_has_a_tier_now_so_it_leaves_b20a4544b.md` (fwd-check on master index: fwd-fail) |
| 20 | recover-da444a039 | 2026-10-03 | commit | 9 | formal: a dylib runs its module body at load time (`__init_offsets`/`.init_array`) | PARKED: `bugs/mid/RECOVER_formal_a_dylib_runs_its_module_body_at_load_time_da444a039.md` (fwd-check on master index: fwd-fail) |
| 21 | recover-8957d1231 | 2026-10-03 | commit | 3 | formal: a target query in a CLASS-LEVEL initializer is a query, not storage | PARKED: `bugs/mid/RECOVER_formal_a_target_query_in_a_CLASS_LEVEL_initializ_8957d1231.md` (fwd-check on master index: fwd-fail) |
| 22 | recover-8b97ba5a2 | 2026-10-03 | commit | 6 | formal: a one-field mutator may not rebind its receiver to a name of its own type | PARKED: `bugs/mid/RECOVER_formal_a_one_field_mutator_may_not_rebind_its_re_8b97ba5a2.md` (fwd-check on master index: fwd-fail) |
| 23 | recover-2a6572795 | 2026-10-03 | commit | 5 | formal: `recv.f()[k](x)` is the same call as `recv.f()(x)`, and is refused like one | PARKED: `bugs/mid/RECOVER_formal_recv_f_k_x_is_the_same_call_as_recv_f_x_a_2a6572795.md` (fwd-check on master index: fwd-fail) |
| 24 | recover-30acf7ed5 | 2026-10-04 | commit | 4 | bugs: the b11 formal sweep, both architectures, 722 files, no file unclassified | PARKED: `bugs/mid/RECOVER_bugs_the_b11_formal_sweep_both_architectures_722_30acf7ed5.md` (fwd-check on master index: fwd-fail) |
| 25 | recover-84eccd26a | 2026-10-04 | commit | 4 | bugs: the b11 formal sweep, both architectures, 722 files, no file unclassified | PARKED: `bugs/mid/RECOVER_bugs_the_b11_formal_sweep_both_architectures_722_84eccd26a.md` (fwd-check on master index: fwd-fail) |
| 26 | recover-88c2a1d21 | 2026-10-04 | commit | 4 | formal_sweep: name string composition, the corpus's largest unowned row | PARKED: `bugs/mid/RECOVER_formal_sweep_name_string_composition_the_corpus_88c2a1d21.md` (fwd-check on master index: fwd-fail) |
| 27 | recover-d7f5d7fbf | 2026-10-04 | commit | 4 | bugs: the b11 formal sweep, both architectures, 722 files, no file unclassified | PARKED: `bugs/mid/RECOVER_bugs_the_b11_formal_sweep_both_architectures_722_d7f5d7fbf.md` (fwd-check on master index: fwd-fail) |
| 28 | recover-38f84dbfc | 2026-10-04 | commit | 1 | tests: the stack-floor guard is pinned as what gates the x86-64 value theorem | PARKED: `bugs/mid/RECOVER_tests_the_stack_floor_guard_is_pinned_as_what_ga_38f84dbfc.md` (fwd-check on master index: fwd-fail) |
| 29 | recover-38c7c07f7 | 2026-10-04 | commit | 2 | tests: the twelve red examples are eleven generations and one owned refusal | PARKED: `bugs/mid/RECOVER_tests_the_twelve_red_examples_are_eleven_generat_38c7c07f7.md` (fwd-check on master index: fwd-fail) |
| 30 | recover-202d50f5b | 2026-10-04 | commit | 1 | tests: the twelve red examples are eleven generations and one owned refusal | PARKED: `bugs/mid/RECOVER_tests_the_twelve_red_examples_are_eleven_generat_202d50f5b.md` (fwd-check on master index: fwd-fail) |
| 31 | recover-e2391d64e | 2026-10-05 | commit | 6 | formal: a container ELEMENT the build can fold was refused as 'computed by a call' | PARKED: `bugs/mid/RECOVER_formal_a_container_ELEMENT_the_build_can_fold_wa_e2391d64e.md` (fwd-check on master index: fwd-fail) |
| 32 | recover-c61e17b65 | 2026-10-05 | commit | 2 | formal: the export gate's bare-call refusal names the method, on 133 of 145 | PARKED: `bugs/mid/RECOVER_formal_the_export_gate_s_bare_call_refusal_names_c61e17b65.md` (fwd-check on master index: fwd-fail) |
| 33 | recover-89b504983 | 2026-10-05 | commit | 9 | formal: a printf conversion that disagrees with its operand's kind is refused | PARKED: `bugs/mid/RECOVER_formal_a_printf_conversion_that_disagrees_with_i_89b504983.md` (fwd-check on master index: fwd-fail) |
| 34 | recover-7e961fb7e | 2026-10-08 | commit | 1 | bugs: `stat_dev` is a 32-bit field read two ways, and test_formal_os_backing's oracle compares them with %d | APPLIED: `0e9b8fd75` (`git cherry-pick -x 7e961fb7e4f407ac978318306e56b3112f398266`) |
| 35 | recover-7ef0fea50 | 2026-10-08 | commit | 5 | formal: a bare-literal comptime value parameter instantiates | PARKED: `bugs/mid/RECOVER_formal_a_bare_literal_comptime_value_parameter_i_7ef0fea50.md` (fwd-check on master index: fwd-fail) |
| 36 | recover-0937b30ee | 2026-10-08 | commit | 7 | formal: a starred for/comprehension target is refused by BOTH backends | PARKED: `bugs/mid/RECOVER_formal_a_starred_for_comprehension_target_is_ref_0937b30ee.md` (fwd-check on master index: fwd-fail) |
| 37 | recover-d54ca9e23 | 2026-10-08 | commit | 4 | formal: an f-string that interpolates nothing is folded, not refused | PARKED: `bugs/mid/RECOVER_formal_an_f_string_that_interpolates_nothing_is_d54ca9e23.md` (fwd-check on master index: fwd-fail) |
| 38 | recover-47bde1508 | 2026-10-08 | commit | 2 | formal: record that the div0 class's fixture now refuses to generate | PARKED: `bugs/mid/RECOVER_formal_record_that_the_div0_class_s_fixture_now_47bde1508.md` (fwd-check on master index: fwd-fail) |
| 39 | recover-8a81db37e | 2026-10-08 | commit | 7 | formal: x86-64 nested for/comprehension target unpack, via one shared target tree | PARKED: `bugs/mid/RECOVER_formal_x86_64_nested_for_comprehension_target_un_8a81db37e.md` (fwd-check on master index: fwd-fail) |
| 40 | recover-5f0525a37 | 2026-10-12 | commit | 1 | bugs: regenerate the formal doc index, which the new doc references moved | PARKED: `bugs/mid/RECOVER_bugs_regenerate_the_formal_doc_index_which_the_n_5f0525a37.md` (fwd-check on master index: fwd-fail) |
| 41 | recover-5a505a741 | 2026-10-12 | commit | 5 | formal/arm64 proof gen: the SP trackers dropped the frame's `sh` bit, so four dec1 examples failed | PARKED: `bugs/mid/RECOVER_formal_arm64_proof_gen_the_SP_trackers_dropped_t_5a505a741.md` (fwd-check on master index: fwd-fail) |
| 42 | recover-f19a3c4fe | 2026-10-12 | commit | 4 | formal/arm64: a length-changing slice store resizes the blob | PARKED: `bugs/mid/RECOVER_formal_arm64_a_length_changing_slice_store_resiz_f19a3c4fe.md` (fwd-check on master index: fwd-fail) |
| 43 | recover-14065e4e2 | 2026-10-12 | commit | 2 | bugs: module_state §(3)'s `len()` remainder is closed, and the paragraph was false | PARKED: `bugs/mid/RECOVER_bugs_module_state_3_s_len_remainder_is_closed_an_14065e4e2.md` (fwd-check on master index: fwd-fail) |
| 44 | recover-48f0f9131 | 2026-10-12 | commit | 1 | docs: subprocess_run — option 1's real blocker is the return-type binding, measured | PARKED: `bugs/mid/RECOVER_docs_subprocess_run_option_1_s_real_blocker_is_t_48f0f9131.md` (fwd-check on master index: fwd-fail) |
| 45 | recover-bb2f36a71 | 2026-10-12 | commit | 3 | docs: fold the unreached-div0-residual doc into the division doc | PARKED: `bugs/mid/RECOVER_docs_fold_the_unreached_div0_residual_doc_into_t_bb2f36a71.md` (fwd-check on master index: fwd-fail) |
| 46 | recover-e0f2d2ce8 | 2026-10-12 | commit | 2 | census: re-bank `fact`'s row after its source changed | PARKED: `bugs/mid/RECOVER_census_re_bank_fact_s_row_after_its_source_chang_e0f2d2ce8.md` (fwd-check on master index: fwd-fail) |
| 47 | recover-9ef31ad0d | 2026-10-12 | commit | 8 | formal/macho: three latent spec details match ld's dylib, and three fixed docs go | PARKED: `bugs/mid/RECOVER_formal_macho_three_latent_spec_details_match_ld_9ef31ad0d.md` (fwd-check on master index: fwd-fail) |
| 48 | recover-277ad54bd | 2026-10-12 | commit | 8 | formal/macho: three latent spec details match ld's dylib, and three fixed docs go | PARKED: `bugs/mid/RECOVER_formal_macho_three_latent_spec_details_match_ld_277ad54bd.md` (fwd-check on master index: fwd-fail) |
| 49 | recover-ebaedb8ce | 2026-10-12 | commit | 8 | formal/macho: three latent spec details match ld's dylib, and three fixed docs go | PARKED: `bugs/mid/RECOVER_formal_macho_three_latent_spec_details_match_ld_ebaedb8ce.md` (fwd-check on master index: fwd-fail) |
| 50 | recover-d406d8ad2 | 2026-10-12 | commit | 3 | FORMAL.md: the runtime ABI triple reads 273/217/177, and the check parses it | PARKED: `bugs/mid/RECOVER_FORMAL_md_the_runtime_ABI_triple_reads_273_217_1_d406d8ad2.md` (fwd-check on master index: fwd-fail) |
| 51 | recover-dfea763b1 | 2026-10-12 | commit | 3 | formal: declare the three undeclared dec1 reds (fact, sum, sqsum) | PARKED: `bugs/mid/RECOVER_formal_declare_the_three_undeclared_dec1_reds_fa_dfea763b1.md` (fwd-check on master index: fwd-fail) |
| 52 | recover-a100e3290 | 2026-10-13 | commit | 1 | formal build: a module-qualified callee is not claimed when a struct declares the member | PARKED: `bugs/mid/RECOVER_formal_build_a_module_qualified_callee_is_not_cl_a100e3290.md` (fwd-check on master index: fwd-fail) |
| 53 | recover-9eaae456c | 2026-10-13 | commit | 5 | formal: a module-level literal sequence decides a loop's emptiness | PARKED: `bugs/mid/RECOVER_formal_a_module_level_literal_sequence_decides_a_9eaae456c.md` (fwd-check on master index: fwd-fail) |
| 54 | recover-abee33ece | 2026-10-13 | commit | 5 | formal: a module-level literal sequence decides a loop's emptiness | PARKED: `bugs/mid/RECOVER_formal_a_module_level_literal_sequence_decides_a_abee33ece.md` (fwd-check on master index: fwd-fail) |
| 55 | recover-d055134c9 | 2026-10-13 | commit | 4 | build_stdlib_dylib: build()'s mojostdlib_* work directory is removed on every exit | PARKED: `bugs/mid/RECOVER_build_stdlib_dylib_build_s_mojostdlib_work_direc_d055134c9.md` (fwd-check on master index: fwd-fail) |
| 56 | recover-fa549cfc4 | 2026-10-13 | commit | 1 | bugs: file the generator's ADD/SUB-immediate shift drop (a second cause of the call_proofgen reds) | APPLIED: `4dd88c3f6` (`git cherry-pick -x fa549cfc40a9dbcf630b483d8e369234f138a95a`) |
| 57 | recover-162cbfe6e | 2026-10-13 | commit | 1 | bugs: file the generator's ADD/SUB-immediate shift drop (a second cause of the call_proofgen reds) | PARKED: `bugs/mid/RECOVER_bugs_file_the_generator_s_ADD_SUB_immediate_shif_162cbfe6e.md` (conflict: the ADD/SUB sh-bit generator fix, landed in 2e585ba4c) |
| 58 | recover-219808ef7 | 2026-10-13 | commit | 1 | bugs/FORMAL_set_value_model (doc deleted): the model table says what the lowering does | PARKED: `bugs/mid/RECOVER_bugs_FORMAL_set_value_model_md_the_model_table_s_219808ef7.md` (fwd-check on master index: fwd-fail) |
| 59 | recover-f94e00e5a | 2026-10-13 | commit | 1 | bugs/TEST_formal_os_backing_is_red_with_no_marker: CLOSED, the job is green 70/70 | PARKED: `bugs/mid/RECOVER_bugs_TEST_formal_os_backing_is_red_with_no_marke_f94e00e5a.md` (fwd-check on master index: fwd-fail) |
| 60 | recover-c92e2a277 | 2026-10-13 | commit | 2 | formal: the ext-imm12 shift fix is verified; drop its doc | PARKED: `bugs/mid/RECOVER_formal_the_ext_imm12_shift_fix_is_verified_drop_c92e2a277.md` (fwd-check on master index: fwd-fail) |
| 61 | recover-911133564 | 2026-10-13 | commit | 1 | bugs: the known-proof-gaps census's stack-floor reason is stale | PARKED: `bugs/mid/RECOVER_bugs_the_known_proof_gaps_census_s_stack_floor_r_911133564.md` (fwd-check on master index: fwd-fail) |
| 62 | recover-c216f2acd | 2026-10-13 | commit | 4 | formal: refuse a `with` whose construction makes __exit__ provably truthy | PARKED: `bugs/mid/RECOVER_formal_refuse_a_with_whose_construction_makes_ex_c216f2acd.md` (fwd-check on master index: fwd-fail) |
| 63 | recover-fadd1e3c1 | 2026-10-13 | commit | 7 | formal: `return g(…)` for a return-less `g` is refused, on both backends | PARKED: `bugs/mid/RECOVER_formal_return_g_for_a_return_less_g_is_refused_o_fadd1e3c1.md` (fwd-check on master index: fwd-fail) |
| 64 | recover-5fe80477a | 2026-10-13 | commit | 5 | formal: lower ==/!= between two word-element blobs, both backends | PARKED: `bugs/mid/RECOVER_formal_lower_between_two_word_element_blobs_both_5fe80477a.md` (fwd-check on master index: fwd-fail) |
| 65 | recover-71ab994a5 | 2026-10-13 | commit | 5 | formal: a nested comprehension element is per-iteration on both backends | PARKED: `bugs/mid/RECOVER_formal_a_nested_comprehension_element_is_per_ite_71ab994a5.md` (fwd-check on master index: fwd-fail) |
| 66 | recover-b1ad993bf | 2026-10-13 | commit | 6 | formal/x86_64: the ISA census has no BACKLOG row left, and its test exits 0 | PARKED: `bugs/mid/RECOVER_formal_x86_64_the_ISA_census_has_no_BACKLOG_row_b1ad993bf.md` (fwd-check on master index: fwd-fail) |
| 67 | recover-6cd2a0bee | 2026-10-13 | commit | 8 | formal: the three registered x86-64 drivers never imported on Python 3.14 | PARKED: `bugs/mid/RECOVER_formal_the_three_registered_x86_64_drivers_never_6cd2a0bee.md` (fwd-check on master index: fwd-fail) |
| 68 | recover-a9dfc7472 | 2026-10-13 | commit | 4 | formal monomorph: a scalar value literal is a demand at a declared value parameter | PARKED: `bugs/mid/RECOVER_formal_monomorph_a_scalar_value_literal_is_a_dem_a9dfc7472.md` (fwd-check on master index: fwd-fail) |
| 69 | recover-2ca08188a | 2026-10-13 | commit | 7 | formal: stat_dev sign-extends the signed 32-bit dev_t | PARKED: `bugs/mid/RECOVER_formal_stat_dev_sign_extends_the_signed_32_bit_d_2ca08188a.md` (fwd-check on master index: fwd-fail) |
| 70 | recover-af309c28f | 2026-10-14 | commit | 7 | formal: a kernel string through a `String` parameter answered `len` in bytes | PARKED: `bugs/mid/RECOVER_formal_a_kernel_string_through_a_String_paramete_af309c28f.md` (fwd-check on master index: fwd-fail) |
| 71 | recover-d300bbfe1 | 2026-10-16 | commit | 1 | dangling-refs ledger: re-bank after the 98-branch merge | PARKED: `bugs/mid/RECOVER_dangling_refs_ledger_re_bank_after_the_98_branch_d300bbfe1.md` (fwd-check on master index: fwd-fail) |
| 72 | recover-2a5d54a5a | 2026-10-18 | commit | 2 | proofgen: the B.cond arm stops interpolating a Python `w`, and three stale pins move | PARKED: `bugs/mid/RECOVER_proofgen_the_B_cond_arm_stops_interpolating_a_Py_2a5d54a5a.md` (fwd-check on master index: fwd-fail) |
| 73 | recover-c529e7f4d | 2026-10-19 | commit | 12 | formal: three wrong answers at a call boundary, fixed at their roots | PARKED: `bugs/mid/RECOVER_formal_three_wrong_answers_at_a_call_boundary_fi_c529e7f4d.md` (12 files; fwd=fwd-fail) |
| 74 | recover-86bafecae | 2026-10-19 | commit | 12 | formal: three wrong answers at a call boundary, fixed at their roots | PARKED: `bugs/mid/RECOVER_formal_three_wrong_answers_at_a_call_boundary_fi_86bafecae.md` (12 files; fwd=fwd-fail) |
| 75 | recover-f2ef4a61f | 2026-10-19 | commit | 12 | formal: three wrong answers at a call boundary, fixed at their roots | PARKED: `bugs/mid/RECOVER_formal_three_wrong_answers_at_a_call_boundary_fi_f2ef4a61f.md` (12 files; fwd=fwd-fail) |
| 76 | recover-0e93df24b | 2026-10-24 | commit | 3 | orchestration: 'Model unavailable' is a dead model, not a worker to replace | PARKED: `bugs/mid/RECOVER_orchestration_Model_unavailable_is_a_dead_model_0e93df24b.md` (fwd-check on master index: fwd-fail) |
| 77 | recover-b23a0083d | 2026-10-26 | commit | 4 | Fix: reject heterogeneous float+ptr tuple inference to prevent Span* mis-type | PARKED: `bugs/mid/RECOVER_Fix_reject_heterogeneous_float_ptr_tuple_inferen_b23a0083d.md` (fwd-check on master index: fwd-fail) |
| 78 | recover-af1671395 | 2026-10-26 | commit | 3 | CODEGEN: fix comptime function-type alias erasure (part 3) | PARKED: `bugs/mid/RECOVER_CODEGEN_fix_comptime_function_type_alias_erasure_af1671395.md` (fwd-check on master index: fwd-fail) |
| 79 | recover-6eead0a37 | 2026-10-27 | commit | 4 | fix RUNTIME_int64_key_above_2gb: char*-declared local uses provenance; discard on MultiAssign | PARKED: `bugs/mid/RECOVER_fix_RUNTIME_int64_key_above_2gb_char_declared_lo_6eead0a37.md` (fwd-check on master index: fwd-fail) |
| 80 | recover-1bea28d8e | 2026-10-27 | commit | 2 | Fix PARTIAL_WORK_HANDOFF (doc deleted): remove stale advice, clean deleted-doc citations, add pinning test | PARKED: `bugs/mid/RECOVER_Fix_PARTIAL_WORK_HANDOFF_md_remove_stale_advice_1bea28d8e.md` (fwd-check on master index: fwd-fail) |
| 81 | recover-a03699ec0 | 2026-10-27 | commit | 2 | procrun: add per-process unique-memory instrument (max RSS, not summed) | PARKED: `bugs/mid/RECOVER_procrun_add_per_process_unique_memory_instrument_a03699ec0.md` (fwd-check on master index: fwd-fail) |
| 82 | recover-a4c53051d | 2026-10-27 | commit | 2 | Fix PARTIAL_WORK_HANDOFF (doc deleted): remove stale advice, clean deleted-doc citations, add pinning test | PARKED: `bugs/mid/RECOVER_Fix_PARTIAL_WORK_HANDOFF_md_remove_stale_advice_a4c53051d.md` (fwd-check on master index: fwd-fail) |
| 83 | recover-4ef1d610c | 2026-10-28 | commit | 3 | Fix CODEGEN_polymorphic_struct_param_degrades_to_a_pointer: refuse loud at struct-evidence loop for non-unanimous all-struct-pointer receiver slots | PARKED: `bugs/mid/RECOVER_Fix_CODEGEN_polymorphic_struct_param_degrades_to_4ef1d610c.md` (fwd-check on master index: fwd-fail) |
| 84 | recover-ddb3d8f17 | 2026-10-28 | commit | 3 | fix(CODEGEN): dict loop target rebind outside zip/enumerate (force char* when previous type differs) | PARKED: `bugs/mid/RECOVER_fix_CODEGEN_dict_loop_target_rebind_outside_zip_ddb3d8f17.md` (fwd-check on master index: fwd-fail) |
| 85 | recover-af4ed1bd7 | 2026-10-29 | commit | 1 | bugs: file DOCS_dangling_doc_refs_ratchet_red_preexisting | APPLIED: `ebddf3a4c` (`git cherry-pick -x af4ed1bd7de3eddca3e148e216b9e77db0283597`) |
| 86 | recover-2d84bdd89 | 2026-10-29 | commit | 4 | File the coroutine element and kwargs gaps; record the contextlib status | PARKED: `bugs/mid/RECOVER_File_the_coroutine_element_and_kwargs_gaps_recor_2d84bdd89.md` (fwd-check on master index: fwd-fail) |
| 87 | recover-88bba386c | 2026-10-29 | commit | 2 | fix: pad compile_to_gimple auto_gpu default | PARKED: `bugs/mid/RECOVER_fix_pad_compile_to_gimple_auto_gpu_default_88bba386c.md` (fwd-check on master index: fwd-fail) |
| 88 | recover-93cdc68cf | 2026-10-30 | merge | 0 | integrate fix-red-fix-red-fix-red-fix-red-fix-merge-fix-leftover-fix-s | APPLIED: `581cd068b` (`git cherry-pick -x -m 1 93cdc68cf9518441273b4fb5cab1a4e9a424eb22`) |
| 89 | recover-46a832e21 | 2026-10-30 | merge | 0 | integrate fix-red-fix-red-fix-red-fix-merge-fix-leftover-fix-screen-pe | PARKED: `bugs/mid/RECOVER_integrate_fix_red_fix_red_fix_red_fix_merge_fix_46a832e21.md` (conflict with applied 581cd068b (same two files, later version of the same change)) |
| 90 | recover-9d6245867 | 2026-10-30 | merge | 0 | integrate fix-red-fix-red-fix-merge-fix-leftover-fix-screen-perf-modul | PARKED: `bugs/mid/RECOVER_integrate_fix_red_fix_red_fix_merge_fix_leftover_9d6245867.md` (conflict with applied 581cd068b (same two files, later version of the same change)) |
| 91 | recover-11870fed2 | 2026-10-30 | merge | 0 | integrate fix-red-fix-merge-fix-leftover-fix-screen-perf-module-walk | PARKED: `bugs/mid/RECOVER_integrate_fix_red_fix_merge_fix_leftover_fix_scr_11870fed2.md` (conflict with applied 581cd068b (same two files, later version of the same change)) |
| 92 | recover-1945a1a1c | 2026-10-30 | merge | 0 | integrate fix-red-fix-merge-fix-leftover-fix-screen-perf-module-walk | PARKED: `bugs/mid/RECOVER_integrate_fix_red_fix_merge_fix_leftover_fix_scr_1945a1a1c.md` (conflict with applied 581cd068b (same two files, later version of the same change)) |
| 93 | recover-61650970f | 2026-10-30 | merge | 0 | integrate fix-merge-fix-leftover-fix-screen-perf-module-walk | PARKED: `bugs/mid/RECOVER_integrate_fix_merge_fix_leftover_fix_screen_perf_61650970f.md` (conflict with applied 581cd068b (same two files, later version of the same change)) |
| 94 | recover-2cd1fc4b5 | 2026-10-30 | commit | 4 | Partial fix class-pattern positional capture (bug COMPILE_FAIL_Tools_cases_generator_analyzer): model kind + emit guard; regression test; doc updated | PARKED: `bugs/mid/RECOVER_Partial_fix_class_pattern_positional_capture_bug_2cd1fc4b5.md` (fwd-check on master index: fwd-fail) |
| 95 | recover-f3d5f43ba | 2026-10-31 | commit | 1 | bugs/mid: f-string self-host segfault - planning guide: candidate fault sites outside the except, decision and plan | PARKED: `bugs/mid/RECOVER_bugs_mid_f_string_self_host_segfault_planning_gu_f3d5f43ba.md` (fwd-check on master index: fwd-fail) |
| 96 | recover-e1ffdde85 | 2026-10-31 | commit | 14 | gate: fix the doc-refs, rthdrscan and formal-doc-truth reds | PARKED: `bugs/mid/RECOVER_gate_fix_the_doc_refs_rthdrscan_and_formal_doc_t_e1ffdde85.md` (14 files; fwd=fwd-fail) |
| 97 | recover-488d1be86 | 2026-10-31 | commit | 3 | bug-hard-readme: remove completed CODEGEN_gate_linked_list doc from index | PARKED: `bugs/mid/RECOVER_bug_hard_readme_remove_completed_CODEGEN_gate_li_488d1be86.md` (fwd-check on master index: fwd-fail) |
| 98 | recover-11e677c9e | 2026-10-31 | commit | 3 | Cherry-pick fix commits 8cda11b64 and a98f133ed (mixed-list kind copy) | PARKED: `bugs/mid/RECOVER_Cherry_pick_fix_commits_8cda11b64_and_a98f133ed_11e677c9e.md` (fwd-check on master index: fwd-fail) |
| 99 | recover-f6eb3c9aa | 2026-11-01 | commit | 4 | Fix GIMPLE invalid-operand: use MojoExc* direct assignment, no (void*) cast on mojo_exc_new call Root cause: emit_stmts emitted (void*)mojo_exc_new(...) which GCC GIMPLE rejects as 'invalid operand in unary operation' (see gimple_codegen.py line 2618). Declare result as MojoExc* and emit plain assignment; register mojo_exc_new in _RUNTIME_FUNCS. Fixes compiled-path build for exception object args. | PARKED: `bugs/mid/RECOVER_Fix_GIMPLE_invalid_operand_use_MojoExc_direct_as_f6eb3c9aa.md` (fwd-check on master index: fwd-fail) |
| 100 | recover-4970a5506 | 2026-11-01 | commit | 1 | base marker (do not clean) | PARKED: `bugs/mid/RECOVER_marker_4970a5506.md` (marker file .wip-base; applied as cc03d2cef then reverted 90295450b) |
| 101 | recover-f4e5261e8 | 2026-11-01 | merge | 0 | integrate bug-codegen-dict-slot-read-loses-its-val-8899 | PARKED: `bugs/mid/RECOVER_integrate_bug_codegen_dict_slot_read_loses_its_v_f4e5261e8.md` (22 files; fwd=fwd-fail) |
| 102 | recover-b2d75f501 | 2026-11-01 | merge | 0 | integrate bug-codegen-dict-slot-read-loses-its-val-8246 | PARKED: `bugs/mid/RECOVER_integrate_bug_codegen_dict_slot_read_loses_its_v_b2d75f501.md` (22 files; fwd=fwd-fail) |
| 103 | recover-5d20c342c | 2026-11-01 | commit | 1 | chk marker (do not clean) | PARKED: `bugs/mid/RECOVER_marker_5d20c342c.md` (marker file .wip-chk2; applied as f655318ba then reverted 964ffb2dc) |
| 104 | recover-f899f9d06 | 2026-11-01 | merge | 0 | integrate fix-merge-bug-codegen-dict-slot-read-loses-its-val-6152 | PARKED: `bugs/mid/RECOVER_integrate_fix_merge_bug_codegen_dict_slot_read_l_f899f9d06.md` (20 files; fwd=fwd-fail) |
| 105 | recover-d901fb1bf | 2026-11-01 | merge | 0 | integrate fix-red-bug-codegen-linked-list-reflection-and-s-4681 | PARKED: `bugs/mid/RECOVER_integrate_fix_red_bug_codegen_linked_list_reflec_d901fb1bf.md` (fwd-check on master index: fwd-fail) |
| 106 | recover-5df6dbcf0 | 2026-11-01 | merge | 0 | integrate bug-codegen-linked-list-reflection-and-s-4681 | PARKED: `bugs/mid/RECOVER_integrate_bug_codegen_linked_list_reflection_and_5df6dbcf0.md` (fwd-check on master index: fwd-fail) |
| 107 | recover-40b980b91 | 2026-11-01 | commit | 4 | codegen: fix the three gate reds the dispatched-loop change exposed | PARKED: `bugs/mid/RECOVER_codegen_fix_the_three_gate_reds_the_dispatched_l_40b980b91.md` (fwd-check on master index: fwd-fail) |
| 108 | recover-ef17e3c53 | 2026-11-01 | merge | 0 | integrate bug-codegen-dispatched-for-loop-shares-o-2362 | PARKED: `bugs/mid/RECOVER_integrate_bug_codegen_dispatched_for_loop_shares_ef17e3c53.md` (fwd-check on master index: fwd-fail) |
| 109 | recover-7ab77803d | 2026-11-01 | commit | 4 | bugs: file three gaps found while fixing the received-None arithmetic bug | PARKED: `bugs/mid/RECOVER_bugs_file_three_gaps_found_while_fixing_the_rece_7ab77803d.md` (fwd-check on master index: fwd-fail) |
| 110 | recover-69bb45659 | 2026-11-01 | commit | 4 | codegen: a capturing nested function used as a VALUE inside another nested function gets its env (sibling env from the current closure's env; value references join the shared-env call group) | PARKED: `bugs/mid/RECOVER_codegen_a_capturing_nested_function_used_as_a_VA_69bb45659.md` (fwd-check on master index: fwd-fail) |
| 111 | recover-3fe727f14 | 2026-11-01 | commit | 4 | cpp: refuse a bare yield in the emitter instead of writing a 0 literal | PARKED: `bugs/mid/RECOVER_cpp_refuse_a_bare_yield_in_the_emitter_instead_o_3fe727f14.md` (fwd-check on master index: fwd-fail) |
| 112 | recover-4501f6b56 | 2026-11-02 | commit | 3 | codegen: os.path.split in a C++-emitted generator lowers to the real pair | PARKED: `bugs/mid/RECOVER_codegen_os_path_split_in_a_C_emitted_generator_l_4501f6b56.md` (fwd-check on master index: fwd-fail) |
| 113 | recover-ba2b61aee | 2026-11-02 | merge | 0 | integrate fix-merge-bug-codegen-dict-slot-read-loses-its-val-9672 | PARKED: `bugs/mid/RECOVER_integrate_fix_merge_bug_codegen_dict_slot_read_l_ba2b61aee.md` (22 files; fwd=fwd-fail) |
| 114 | recover-762ecad4a | 2026-11-02 | merge | 0 | WIP on work/ann: 4595162d6 wip marker (do not clean) | PARKED: `bugs/mid/RECOVER_WIP_on_work_ann_4595162d6_wip_marker_do_not_clea_762ecad4a.md` (19 files; fwd=fwd-fail) |

## Complex (more than 10 files, or a merge)

- recover-f04048b87 (commit, 157 files): Rename mojo.py to fire.py and mojo_compiler.py to fire_compiler.py across entire repository
- recover-abf5638ba (commit, 14 files): formal: struct types, methods, and a one-word layout that actually works
- recover-8bb98d4fe (merge, 0 files): integrate fix-merge-compiled-silent-2
- recover-61d3c07e2 (merge, 0 files): integrate fix-merge-fix-merge-fix-merge-fix-merge-fix-merge-fix-round8
- recover-2f60724c8 (merge, 0 files): integrate fix-merge-fix-merge-fix-merge-fix-round8-selfhost
- recover-42f2531a3 (commit, 18 files): parser+codegen: a 1-tuple for-target and a parenthesised single name are two targets
- recover-c529e7f4d (commit, 12 files): formal: three wrong answers at a call boundary, fixed at their roots
- recover-86bafecae (commit, 12 files): formal: three wrong answers at a call boundary, fixed at their roots
- recover-f2ef4a61f (commit, 12 files): formal: three wrong answers at a call boundary, fixed at their roots
- recover-93cdc68cf (merge, 0 files): integrate fix-red-fix-red-fix-red-fix-red-fix-merge-fix-leftover-fix-s
- recover-46a832e21 (merge, 0 files): integrate fix-red-fix-red-fix-red-fix-merge-fix-leftover-fix-screen-pe
- recover-9d6245867 (merge, 0 files): integrate fix-red-fix-red-fix-merge-fix-leftover-fix-screen-perf-modul
- recover-11870fed2 (merge, 0 files): integrate fix-red-fix-merge-fix-leftover-fix-screen-perf-module-walk
- recover-1945a1a1c (merge, 0 files): integrate fix-red-fix-merge-fix-leftover-fix-screen-perf-module-walk
- recover-61650970f (merge, 0 files): integrate fix-merge-fix-leftover-fix-screen-perf-module-walk
- recover-e1ffdde85 (commit, 14 files): gate: fix the doc-refs, rthdrscan and formal-doc-truth reds
- recover-f4e5261e8 (merge, 0 files): integrate bug-codegen-dict-slot-read-loses-its-val-8899
- recover-b2d75f501 (merge, 0 files): integrate bug-codegen-dict-slot-read-loses-its-val-8246
- recover-f899f9d06 (merge, 0 files): integrate fix-merge-bug-codegen-dict-slot-read-loses-its-val-6152
- recover-d901fb1bf (merge, 0 files): integrate fix-red-bug-codegen-linked-list-reflection-and-s-4681
- recover-5df6dbcf0 (merge, 0 files): integrate bug-codegen-linked-list-reflection-and-s-4681
- recover-ef17e3c53 (merge, 0 files): integrate bug-codegen-dispatched-for-loop-shares-o-2362
- recover-ba2b61aee (merge, 0 files): integrate fix-merge-bug-codegen-dict-slot-read-loses-its-val-9672
- recover-762ecad4a (merge, 0 files): WIP on work/ann: 4595162d6 wip marker (do not clean)

## Every tip

| Tag | SHA | Date | Kind | Files | Disposition | Subject |
|---|---|---|---|---|---|---|
| recover-97c997453 | 97c9974534488fa086e0d2ad7a8e59182c20720c | 2026-08-10 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on worktree-agent-aa386f03756d20a48: 7633d90 Merge worktree-agent-ad9ab59f880b934aa: fix write-side global reassignment misrouting to wrong module, delete resolved module_globals_cross_contamination + multi_assign_local_var_type docs, deepen selfhost_getattr_dispatch doc |
| recover-eb1fb5d0a | eb1fb5d0ad76a1cfea78dda19595abfe5d58768e | 2026-08-20 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on worktree-agent-a617ce770b9354cd5: 024abd4 Fix ModuleNotFoundError silently swallowed in interpreter imports |
| recover-bbb3a8961 | bbb3a896146dccf67adcdce826c1d138690d40d3 | 2026-08-22 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on master: 0ef3383 wip(wave2): extract leaf modules ctypes/solvers/exprtypes (selfhost dup issue being fixed) |
| recover-4c324d10f | 4c324d10f4840ad510fe0fd7ae6f924751007837 | 2026-08-25 | merge | 0 | MERGE-CONTENT-ON-MASTER | On fix/opencode-genorder-solo: WIP: earlier genorder-solo attempt at generator-consumption-ordering, superseded by 9ea2749 on master, preserved for reference |
| recover-274448bb0 | 274448bb0534eb05e883c0f5c7af84c4a40376a6 | 2026-08-25 | merge | 0 | MERGE-CONTENT-ON-MASTER | On fix/opencode-genorder3: wip-genorder-fixes |
| recover-314b0715b | 314b0715ba388a106ae60b77da76541207189bb8 | 2026-08-29 | merge | 0 | MERGE-CONTENT-ON-MASTER | On worktree-agent-a9c973abfd1b2a899: wip: bug-2026-027/028/029/030 fixes against stale pre-refactor snapshot |
| recover-71c85f81f | 71c85f81fb738128e3da7239f6514741c6f4faf9 | 2026-09-18 | merge | 0 | MERGE-CONTENT-ON-MASTER | On master: diagnostic prints r2 (revert) |
| recover-8c84eec6d | 8c84eec6d3bf02ea183a987231dcccc55dd54c53 | 2026-09-18 | merge | 0 | MERGE-CONTENT-ON-MASTER | On master: diagnostic prints (broken indentation, revert) |
| recover-da1bf4ec6 | da1bf4ec60f644aef79f7466ed6a421f9f8e4330 | 2026-09-25 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on master: 070a010 cluster B groundwork (tagged nested-tuple generator slots) — ABI only |
| recover-5d70c6311 | 5d70c6311d042b9c08f2f6de275a55c41028a1c8 | 2026-09-30 | merge | 0 | MERGE-CONTENT-ON-MASTER | integrate fix-merge-leakhunt |
| recover-f0df5e954 | f0df5e954fca15b441e15f627448d3bdcc99da2c | 2026-09-30 | merge | 0 | MERGE-CONTENT-ON-MASTER | integrate fix-merge-leakhunt |
| recover-259257ba7 | 259257ba783c6799f8615b67e1d1fd610c97dde7 | 2026-10-01 | merge | 0 | MERGE-CONTENT-ON-MASTER | On metal: MOJO_TRACE_TOPLEVEL scaffolding, diagnostic only |
| recover-3416af2f8 | 3416af2f8b4af1d2ce30f61602153b27c5ba411c | 2026-10-11 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on metal: 8598b033 remove two scratch generator probes (gen1.py, gen2.py) that fe70d2b4 committed by accident |
| recover-f8a042a18 | f8a042a188d60bfb7b8ca41a057b657ba04798ba | 2026-10-16 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on work/merge-qwen5-r2-r2: ebf8cd00 Merge work/formal293-docs |
| recover-deec3b8ff | deec3b8ff4d543dd855809a72d972c032ca08b12 | 2026-10-19 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on work/qwen-cgen3: 75ba42d1 codegen: a statically-typed bytes value materializes as its byte ints, not its struct slots |
| recover-1c50f241e | 1c50f241ee859984d599fe9f524a04706dbaa4aa | 2026-10-20 | merge | 0 | MERGE-CONTENT-ON-MASTER | On master: tmp4 |
| recover-d108b1543 | d108b1543bd5c9b769ea0cf2ef8f61b30598ed5f | 2026-10-20 | merge | 0 | MERGE-CONTENT-ON-MASTER | On master: phase2-session-changes |
| recover-6c74c8e73 | 6c74c8e736f9866e7345f002a2bcd47a305c0f01 | 2026-10-24 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on master: 109753df codegen: a bare read of a name locally bound by a nested `def` let a same-named module global win the read — the os.py shadow shape's NULL-fnptr segfault, module-side half |
| recover-c3160cd18 | c3160cd1807e2a7df7221d721cf0a1959b118fff | 2026-10-24 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on master: d20e7984 Merge branch 'master' of /Users/mrs/net/chatgpt/claude/mojo-reference |
| recover-01565f34a | 01565f34a131ba9e0f80ade903660db40f1bc38f | 2026-10-24 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on master: d20e7984 Merge branch 'master' of /Users/mrs/net/chatgpt/claude/mojo-reference |
| recover-6e88f62fd | 6e88f62fdc7b54fce2d6e58f68ef5de2ebf83293 | 2026-10-25 | merge | 0 | MERGE-CONTENT-ON-MASTER | On master: r22fix-abstract |
| recover-5167c7879 | 5167c7879e536b11d000f0c8777186cdd8ff0820 | 2026-10-26 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on master: 978386fb refill: a fix-landed task starts regardless of the slot target (a red master is repaired at once) |
| recover-4a6f49c99 | 4a6f49c99e9bba81789bb39fb2764d1acf01ae45 | 2026-10-26 | merge | 0 | MERGE-CONTENT-ON-MASTER | On master: item3-fix-temp-for-failsbefore |
| recover-12ee0485a | 12ee0485ad8972b4ffddf653f2d3ef6a46d88ab2 | 2026-10-26 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on master: 13c296e6 Merge branch 'master' of /Users/mrs/net/chatgpt/claude/mojo-reference |
| recover-b7b9433f5 | b7b9433f541b0e91e58cfc1311825d9ba7761e92 | 2026-10-26 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on master: 1208af1b integrate bug-codegen-list-copy-of-a-runtime-pair-list |
| recover-0fd8db11a | 0fd8db11a0ac0ae13ad04db90a87c9ea27450325 | 2026-10-30 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on work/gen-lib-os: d712caeb4 Merge branch 'master' into work/gen-lib-os |
| recover-11e05cdc9 | 11e05cdc9ce8ff02230a24e4e620f1e0650f1adf | 2026-10-30 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on master: f1d6240f2 bugs: file the residue found while closing fsutil (module-attribute generator kwargs, list(mod.gen()), bool result off an unsolved word, try/except after an empty generator loop, double-parameter signatures) |
| recover-0acebd2e6 | 0acebd2e6aa645aac8a784019448bf88d1356226 | 2026-10-30 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on master: 548e763d2 Merge remote-tracking branch 'fire/master' |
| recover-58402feaf | 58402feaf28c0787b15dcee3251c986d5af7979f | 2026-10-30 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on master: 11bb43005 control: a queued task can be pinned to its slot (--only) |
| recover-1f329baee | 1f329baee329a1d06492e48092bdc88f35e78049 | 2026-10-30 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on master: a3905dd3d Runtime os.walk / glob.glob / glob.iglob (eager lists) as direct calls and as callable values; a for over a call through a callable parameter iterates the runtime's view of the result (mojo_iter_word); Python's value-returning 'or' for strings in generator bodies; _walk_tree and glob_tree now compile (tests: cpp_for_over_callable_param_walks_and_globs; generator runner 295, same 8 pre-existing failures) |
| recover-44ee7481e | 44ee7481e4ec6d6c48fb49c58a99a582662f320f | 2026-10-30 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on master: d12302ab7 Kind-mixed list parameters: int call sites count as disagreeing evidence (order-independent), mixed means unknown contract, generator construction tags a str/float list argument, unsolved generator list params read boxed; the old 'conflicted param is refused' test now compares against CPython |
| recover-265cc7332 | 265cc73322bd084d1be5afa11d63bbad56ac0a51 | 2026-10-30 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on master: d12302ab7 Kind-mixed list parameters: int call sites count as disagreeing evidence (order-independent), mixed means unknown contract, generator construction tags a str/float list argument, unsolved generator list params read boxed; the old 'conflicted param is refused' test now compares against CPython |
| recover-758ed2d26 | 758ed2d26dd584dd024518ff015f27af65951314 | 2026-10-30 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on master: d12302ab7 Kind-mixed list parameters: int call sites count as disagreeing evidence (order-independent), mixed means unknown contract, generator construction tags a str/float list argument, unsolved generator list params read boxed; the old 'conflicted param is refused' test now compares against CPython |
| recover-7a630481a | 7a630481af19c9f556ffb5331e37fa242085b1b7 | 2026-10-30 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on master: 758d5a750 bugs/FORMAL_arm64_the_proof_generators_sp_trackers_drop_the_imm12_shift: already fixed upstream, removed (verified: the doc's fixed half -- the five byte-form sp trackers _step_rhs, _frame_ldp_addrs, _frame_read_addrs, _hcond_mem_rws, _sp_stores -- read through the one helper, and its remaining *8 half -- _frame_stack_depths, _frame_slot_accesses, _frame_store_depths, _frame_store_writes -- landed with the byte-unit decision 98c0ca91 made from the doc's own STP/LDP imm7*8 evidence, now all _imm12_scaled(w) with no *8; the doc's step-3 verification: test_formal_dylib.py 27/29 with the 2 failures the value-model reds the suite registry records predating the fix, test_formal_cross_module.py 38/0 incl. the per-parameter frame-contract publishing rows, and TestMethodFrameDepthTrackers 4/4; the only remaining ((w>>10)&0xfff) reads in the file are the helper itself and the LDR/STR/LDP step-RHS arms whose *8/*4/*scale is the per-instruction address-size scale; OPEN_WORK.md regenerated, 108 documents, --check PASS) |
| recover-ddccc00e5 | ddccc00e52161db3b7efa99c7fcb3c7e314eb3bf | 2026-10-31 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on master: 1b76ab816 integrate bug-codegen-a-bare-or-explicit-yield-of |
| recover-5c7a921a4 | 5c7a921a48b3a7fbe4a283bc30c124be5b0abd56 | 2026-10-31 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on work/midhard3: a8ebd0bdf perf: memoise realpath in the selfhost-source predicates (realpath 6.7% -> 1.1% of the fire.py compile); test_selfhost 3/3 |
| recover-5701a742f | 5701a742f0d0957d43ea671409ee364bc2c9e16a | 2026-10-31 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on work/midhard: 7e70c6978 test_silent_noop_iter: findall with re.MULTILINE is pinned by its answer, not by a refusal that the runtime re path made obsolete |
| recover-9f8038a4e | 9f8038a4e9c3a8ec73db1405e1fd02034451728f | 2026-10-31 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on work/midhard: 7e70c6978 test_silent_noop_iter: findall with re.MULTILINE is pinned by its answer, not by a refusal that the runtime re path made obsolete |
| recover-48e06d474 | 48e06d474808f22e02376f2afee49f3437b650a0 | 2026-10-31 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on work/midhard: 3061cc96b bugs: file the 9 red make check jobs from the 2026-10-31 run (generator and selfhost to mid, the rest to easy) |
| recover-711bb16ad | 711bb16ad1a18e626972431650f8f5eec62ee081 | 2026-10-31 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on work/midhard: 3061cc96b bugs: file the 9 red make check jobs from the 2026-10-31 run (generator and selfhost to mid, the rest to easy) |
| recover-a2ca40616 | a2ca4061691bcf9c8b408695f086ccd803058cfb | 2026-10-31 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on work/midhard: 3061cc96b bugs: file the 9 red make check jobs from the 2026-10-31 run (generator and selfhost to mid, the rest to easy) |
| recover-ccb1e471d | ccb1e471df178a0a064ec3541a286f5d294c3c72 | 2026-10-31 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on master: c0ce3031c Merge branch 'master' of /Users/mrs/net/chatgpt/claude/mojo-reference |
| recover-5a0c293e6 | 5a0c293e62c6a33fb45a5785eff29417833abed1 | 2026-10-31 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on master: 651bf86b5 free functions: a sliced parameter every call site passes a string for is a string (keyword-only functions included); pattern.split on a word of unknown kind dispatches at run time |
| recover-2c9f727c4 | 2c9f727c4d837faaad628dba177ad7ba64809e47 | 2026-10-31 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on master: 1dcb85895 run-time re: a backtracking engine for patterns built at run time (+ compile/match/search/fullmatch/findall/sub/split/finditer, match objects, flags), fnmatch/glob wildcard globbing, generator handles as words, test_runtime_re registered |
| recover-1ea5d5407 | 1ea5d5407513a76baa4390aa1bf3c75d8e3ed46a | 2026-10-31 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on master: 093e74529 generators: glob.py compiles end to end - moved capturing siblings with transitive captures, per-subclass copies, abstract methods return a word, staticmethod receivers, pointer-to-word casts, sliced path params |
| recover-61b41f41a | 61b41f41a5326f188d3ec7a8a6b5fc501935b1b8 | 2026-10-31 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on master: c89501142 generators: dynamic-word '+' and subscript, method return types read refined params, glob selector chain with method-built path |
| recover-e9e00b5fd | e9e00b5fd5601a9bafe1fdd6603c6c9f6ff93497 | 2026-10-31 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on work/gen-glob5: fc8c7c23f WIP glob5 |
| recover-17163d277 | 17163d277a85656a7db1bd9825c6cd9b0c7635c7 | 2026-10-31 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on master: 18cafca43 generators: escaping closure generators are variadic closures (keyword/default binding via the registered signature), dynamic-word params, vkind 5 drains, dyn-call argument typing for method calls and literals |
| recover-83665f2e0 | 83665f2e0763e6ed117aced41fd42e15fdce0cba | 2026-10-31 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on master: 67312b912 generators: escaping closure generators in METHODS (self captured as the moved generator's struct receiver), signatures accept struct-pointer params; Lib_glob status |
| recover-e91f27ed9 | e91f27ed96a1ccb7c0c998d4fa71bd115339c09b | 2026-10-31 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on master: 072e1bd06 Merge branch 'master' into work/gen-glob2 |
| recover-bd60b2509 | bd60b250902ecd3969853dc0cdc7755581fe8757 | 2026-10-31 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on master: 001cbe9aa integrate fix-red-fix-red-bug-codegen-dylib-generic-inline-copies-370 |
| recover-7daf00de9 | 7daf00de9d707a7008ea53bcf37cbde7d7aafa9c | 2026-10-31 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on work/gen-glob2: f1037d078 WIP glob |
| recover-e4cb34d64 | e4cb34d64fa6fbf0186b6cd9aec110c51319a42a | 2026-10-31 | merge | 0 | MERGE-CONTENT-ON-MASTER | On master: foreign edit |
| recover-7dbb58d87 | 7dbb58d872ea272cdbf9fb012424741e245a406f | 2026-10-31 | merge | 0 | MERGE-CONTENT-ON-MASTER | On master: foreign edit |
| recover-1b05ec79b | 1b05ec79bdd25604c7f6761dd88fb5caa8212266 | 2026-10-31 | merge | 0 | MERGE-CONTENT-ON-MASTER | On master: foreign edit |
| recover-b6f3f4157 | b6f3f4157ce8291d107844d46ee86d05ba5770d6 | 2026-10-31 | merge | 0 | MERGE-CONTENT-ON-MASTER | On master: foreign edit |
| recover-e5d5c79f9 | e5d5c79f99e7b036b4ec339dfd02f0037bb54fcc | 2026-10-31 | merge | 0 | MERGE-CONTENT-ON-MASTER | On master: foreign edit |
| recover-7614fa2eb | 7614fa2ebcef9cd83fc958d1a6673f670103facd | 2026-10-31 | merge | 0 | MERGE-CONTENT-ON-MASTER | On master: foreign uncommitted edit, stashed to land gen-kinded |
| recover-706d19123 | 706d19123a351ece10a7b8e345e6680e376dd2ca | 2026-10-31 | merge | 0 | MERGE-CONTENT-ON-MASTER | On master: foreign uncommitted coro.py edit (module qualifier), stashed to land gen-kinded |
| recover-12fa60f84 | 12fa60f8483a7571182fca17344a85c7ef9c606a | 2026-11-01 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on work/co: c2dfe3c0b StopIteration.value: a generator's/coroutine's return value and raise StopIteration(x) reach ex.value (was always None) |
| recover-eae7a81cb | eae7a81cbfe4b72900b708eba3187b45816c8be9 | 2026-11-01 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on work/tf: 99d01e769 wip marker (do not clean) |
| recover-e8aa08b04 | e8aa08b04078cbcb701d919bdd784ba476d20609 | 2026-11-01 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on work/gsh: 3deda6853 wip marker (do not clean) |
| recover-b6b2d20e0 | b6b2d20e0a4e51fb28d844aebcd4e5f21a756e47 | 2026-11-01 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on work/wraps: 48eec19d9 wip marker (do not clean) |
| recover-c7aa87d05 | c7aa87d05e9a05405510f87fdf18e79a7a445ad2 | 2026-11-01 | merge | 0 | MERGE-CONTENT-ON-MASTER | On master: orphan runtime WIP found in main checkout 2026-11-01: None as dict key (mojo_dict_set_none_key/contains_none), no compiler side; not from this session |
| recover-ca7c44b0b | ca7c44b0b1a3b5f297e162b1425fa892f46f1890 | 2026-11-01 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on master: 96b064c40 bugs/hard: check_all - measured repro, the partial that was reverted and why |
| recover-9e12a55e5 | 9e12a55e57652955f4e0f02ccacad14958c26b38 | 2026-11-01 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on master: 31b8472af Merge branch 'master' of /Users/mrs/net/chatgpt/claude/mojo-reference |
| recover-223f8579a | 223f8579ab440bf375299b3c52a3204319c4d1e3 | 2026-11-01 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on work/frames3: 31b8472af Merge branch 'master' of /Users/mrs/net/chatgpt/claude/mojo-reference |
| recover-6e199ec98 | 6e199ec9813b63e859f2f3d10ab56a06493aa86b | 2026-11-01 | merge | 0 | MERGE-CONTENT-ON-MASTER | WIP on work/frames: 28c535961 bugs/mid: PERF doc - 98.5% of _infer_local_var_types calls repeat a seen result; what a safe cache needs |
| - | 839d636083709a410a4594058d3dc6ad815e8097 | 2026-09-29 | merge | 0 | MERGE-LANDED | integrate hard-struct-kwargs |
| - | c5b4ab363c2990f70953cdced10cbe5ef71ff8fa | 2026-09-29 | merge | 0 | MERGE-LANDED | integrate formal-toplevel-stmts |
| - | 686287c0dea7f63291801d485fdedecf472afe2b | 2026-09-29 | merge | 0 | MERGE-LANDED | integrate formal-toplevel-stmts |
| - | 0f7422b9c97e6f6585273fb8fb76daf8465a76dd | 2026-09-29 | merge | 0 | MERGE-LANDED | integrate coro-nowd-blowup-2 |
| - | 9826c4a421a1a89f8391f790c4e4f2e60e4b413a | 2026-09-29 | merge | 0 | MERGE-LANDED | integrate formal-slice3 |
| - | 23f693f06f2da53e615bc418e68a9c1f82873003 | 2026-09-29 | merge | 0 | MERGE-LANDED | integrate mod-os |
| - | 1450ddf2e184b4e64d93a0e8093760b28f6a1b86 | 2026-09-29 | merge | 0 | MERGE-LANDED | integrate help-rename |
| - | a9c362f6abcc65448b5a215bb4c9805440b0cd2f | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate fix-merge-disabled-until-fixed-23917 |
| - | 74e502d60f75dda0c72c04fac0291cce58395e22 | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate compile-fail-stdlib-misc |
| - | 734d83bd4cf62ea62f0aeb70d30812df0c987a41 | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate formal-method-param-field |
| - | 0a72562640366d9b279d1d49af975bbbec9c1dd5 | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate formal-method-param-field |
| - | 67f0aa4bd03cb456b2a64d490f32515d5a95dacd | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate formal-method-param-field |
| - | 471921c850f851082b70e4a9ff9f3ad6f584e63e | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate hard-method-call-struct-param |
| - | d90ca0c30b7f1c2250cac731ccb986c4a1f1c16d | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate formal-sweep-next |
| - | b0f10465a03c4b558a88d03b39e1120f396a8a24 | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate merge3-stragglers |
| - | f2c073548299d242902fac95e0f3bf0b1786483c | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate container-eq |
| - | fcb86eddc25cbe0bdc89b458517db167affa7b8d | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate register-unregistered-tests |
| - | 858654a6bce7a98dd5752d588671f6d2e36ea887 | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate disabled-until-fixed |
| - | c3dd83fdc59d33751b1d48c3f0175c1406db663d | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate perf-module-walk |
| - | 51e48b4993c6e073d0a29d5d35788ef8ac37852f | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate linkmode-flake |
| - | 4564deb43068bce7f0966b63003095d374745809 | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate fix-merge-formal-x86-dylib |
| - | f4faca5d3d685ed424b227b8486d74b5a4d24070 | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate fix-merge-formal-x86-dylib |
| - | 173daf69db07e662d647a9c52e6f528395d2b1a7 | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate hostmods-2 |
| - | a571ecb6d9101ae2362122b98e68a0b50939e68b | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate hostmods-2 |
| - | 4b33116c7e67d7b693959c2ea389837f87c818d0 | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate formal-os-backing |
| - | 390d530cf9aa50bbeacdddff67a50609c8412a80 | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate formal-module-attr |
| - | 6faadbe56ec84a2eee11e76ac9ec68a7b959de3f | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate register-unregistered-tests |
| - | bda9a148710db7b0c4e802cabcfb4b5c7a84ecd8 | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate disabled-until-fixed |
| - | c66cb24217ca62993e5d7985e0234697d9eb66a0 | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate register-unregistered-tests |
| - | fe3684e6749af15d2418d37113d8f150a2b82798 | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate disabled-until-fixed |
| - | 50a605af87caf28b059d5ae22405a38773c131e7 | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate formal-module-attr |
| - | d7e574bfe16f4c9b651e8cbc14aeae17f0c70ca0 | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate compiled-imports-decorators |
| - | 19c2be991fc5c9315ff5be13800265a707953bf8 | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate compiled-imports-decorators |
| - | 66da39d519b0eb1525ba448b3407a54f7988762f | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate leakhunt |
| - | 79a8d3959dae792b9988661c9080aa13131bd31e | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate memslot-backfill |
| - | c3b874928bc1234bddee1839730560f4bf657fee | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate compiled-imports-decorators |
| - | 00185a84073aa8ff4db582c4bd51d9074ece9f5c | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate compiled-silent-2 |
| - | dcbe36b5476598cd86e2f9018299e3d289f5d640 | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate leakhunt |
| - | 7e1062f8d82b36f05dd68aa45abee624ef1cd1f9 | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate formal-module-attr |
| - | 0e06e80415ab3810dbc53faaab0659cb890e8755 | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate fix-merge-fix-merge-fix-merge-formal-cross-module |
| - | 340646eef66b04c55dfee65918707bab24e1db52 | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate fix-merge-formal-x86-dylib |
| - | bd5e90bd7a238f7c2b2cd2821e424ae972954da3 | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate fix-merge-formal-x86-dylib |
| - | 985c450812a916afd8e49fe9066584fd837a8327 | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate fix-merge-formal-x86-dylib |
| - | dcb86e60bf754b71c1ab6c01f498b2796490d072 | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate fix-merge-formal-x86-dylib |
| - | 5179cc30e9396dd4c66013cef96df9cbaa245f40 | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate fix-merge-formal-x86-dylib |
| - | 547c0dbfe8ca1f03cf458c948add05b1418e00be | 2026-09-30 | merge | 0 | MERGE-LANDED | integrate fix-merge-formal-x86-dylib |
| - | 85a9eb4de17bb46e9d6e24f0ff3c2389844b4f8c | 2026-09-30 | merge | 0 | MERGE-LANDED | merge work/mod-ast: the ast host module, with HOST_MODELLED accounting for all three |
| - | cb8255ea9c5dea6dfd181212924e2978f61fbaaf | 2026-10-01 | merge | 0 | MERGE-LANDED | integrate batchfix-851763-a1 |
| - | 5d6b5f41d6e89220a6ad5376a1752feea7f20709 | 2026-10-01 | merge | 0 | MERGE-LANDED | integrate batchfix-851763-a1 |
| - | 3ff3a9c124e2d430d33793808823d03c9f01dd65 | 2026-10-01 | merge | 0 | MERGE-LANDED | Merge work/batch1-sync into work/stage2merge: batch 1's repairs and master's new-modular work, over batch 2's merged branches |
| - | 4c812adf297877072c82468308779b3675a651f4 | 2026-10-01 | merge | 0 | MERGE-LANDED | Merge branch 'work/fix-merge-fix-merge-disabled-until-fixed-23917' into work/stage2merge |
| - | fe9ab7fee9bb188458eb834213d6fd4243b76419 | 2026-10-01 | merge | 0 | MERGE-LANDED | Merge branch 'work/formal-callee-no-def' into work/stage2merge |
| - | cb50c91c2b3f4b4f4ef4ff8d7ee6e22356fb55ac | 2026-10-01 | merge | 0 | MERGE-LANDED | Merge branch 'work/formal-dylib-export' into work/stage2merge |
| - | e81692d7a6905ac31ceefff998023664552883ef | 2026-10-01 | merge | 0 | MERGE-LANDED | Merge branch 'work/codegen-old-divergences' into work/stage2merge |
| - | 8f08f80361d26d0a015ea97c97815fdfd0f7bf6d | 2026-10-01 | merge | 0 | MERGE-LANDED | Merge branch 'work/compile-fail-stdlib-misc' into work/stage2merge |
| - | fc0ec39ab323001db957bc2c69c5b5bb9026a856 | 2026-10-01 | merge | 0 | MERGE-LANDED | Merge branch 'work/memory-ownership' into work/stage2merge |
| - | 03b3f0c8df77b5849ab92592713632c3c3122fe4 | 2026-10-01 | merge | 0 | MERGE-LANDED | Merge branch 'work/compiled-silent' into work/stage2merge |
| - | 4c1bf09a1b9cc956c0b7093d43ed69c25bcbd51a | 2026-10-01 | merge | 0 | MERGE-LANDED | Merge branch 'worktree-agent-a4427eb542b05159d' into work/stage2merge |
| - | 6680bac61a4469975ae17f43e3e2fef1e7e35149 | 2026-10-01 | merge | 0 | MERGE-LANDED | Merge branch 'work/perf-module-walk' into work/stage2merge |
| - | 60087441057353187b4a92ca4404c4a29842c989 | 2026-10-01 | merge | 0 | MERGE-LANDED | Merge branch 'work/hard-fsutil' into work/stage2merge |
| - | 14745b1a3233cbacad3239e29c27ef52161061e9 | 2026-10-01 | merge | 0 | MERGE-LANDED | Merge branch 'work/hard-gen-lambda' into work/stage2merge |
| - | d975f85c2560cc800b61a0822e7cea79cc25dedf | 2026-10-01 | merge | 0 | MERGE-LANDED | Merge branch 'work/compiled-silent-2' into work/stage2merge |
| - | 08ce6a9a3e5f24de567fba52f436a94ffbd29ff7 | 2026-10-01 | merge | 0 | MERGE-LANDED | Merge branch 'work/hard-bytes' into work/stage2merge |
| - | 76fc3f27b84938d804800ab07d89710a62767e41 | 2026-10-01 | merge | 0 | MERGE-LANDED | Merge branch 'work/frontend-silent-r2' into work/stage2merge |
| - | 5e9fd9e23f498cb6eac5dae50d7b9b3b34d4dd35 | 2026-10-01 | merge | 0 | MERGE-LANDED | Merge branch 'work/frontend-silent-r2' into work/stage2merge |
| - | b53131a4734133446be2ec7fce4388c450c21196 | 2026-10-01 | merge | 0 | MERGE-LANDED | Merge branch 'work/frontend-silent' into work/stage2merge |
| - | 6323a464cf8fa58bc9fe37e38f709adcf41c3299 | 2026-10-01 | merge | 0 | MERGE-LANDED | Merge branch 'work/hard-same-name-struct' into work/stage2merge |
| - | a442f81dda35c85c54c29474780d539221c328bb | 2026-10-01 | merge | 0 | MERGE-LANDED | Merge branch 'work/coro-nowd-blowup-2' into work/stage2merge |
| - | 8c2c595854c123dd037f375372a29cb580c09d5f | 2026-10-01 | merge | 0 | MERGE-LANDED | Merge branch 'work/formal-comptime-asm-r2-r2' into work/stage2merge |
| - | 8ac38c0fe6fc4399c1dd4d08cc07506253343142 | 2026-10-03 | merge | 0 | MERGE-LANDED | merge formal14-fuzz-x86: ONE differential fuzzer for both architectures, and two harness defects it turned up |
| - | 8489ca9ec7bc5749d5aa41615cb0c00ff328a8fe | 2026-10-03 | merge | 0 | MERGE-LANDED | merge formal14-fuzz-x86: ONE differential fuzzer for both architectures, and two harness defects it turned up |
| - | a727481170e008fa6fe01afbfd24ac3a97a103bc | 2026-10-03 | merge | 0 | MERGE-LANDED | Merge branch 'work/formal14-std-os-io' into work/merge-formal14 |
| - | 54f348eff47f0bb6aed0274cf751cdb55b3ef42e | 2026-10-03 | merge | 0 | MERGE-LANDED | Merge branch 'work/formal14-std-builtin-math' into work/merge-formal14 |
| - | fd8afc7318321275a54c2385dc43329d1502dd14 | 2026-10-03 | merge | 0 | MERGE-LANDED | Merge branch 'work/formal14-std-collections' into work/merge-formal14 |
| - | f7bd8344a9c9588574c1089f0cbafc8f059dea88 | 2026-10-03 | merge | 0 | MERGE-LANDED | Merge branch 'work/formal14-proofs-breadth' into work/merge-formal14 |
| - | c80a986467ed7a4e65614f07cd0f6af57c24b956 | 2026-10-03 | merge | 0 | MERGE-LANDED | Merge branch 'work/formal12-hostmods-subprocess' into work/merge-formal14 |
| - | 7bdf63a264cb49a2cf8999f3dbd0fd44114036a9 | 2026-10-03 | merge | 0 | MERGE-LANDED | Merge branch 'work/formal13-8' into work/merge-formal14 |
| - | 90928ece2304d5eee637000de372aaec2c142fea | 2026-10-03 | merge | 0 | MERGE-LANDED | Merge branch 'work/formal13-5' into work/merge-formal14 |
| - | 965da8281293fd10a417cf2f889ec9b5fdd41fc7 | 2026-10-03 | merge | 0 | MERGE-LANDED | Merge branch 'work/formal13-4' into work/merge-formal14 |
| - | a74952bce0662333fcd99abe0c3ace0d2dc6361f | 2026-10-03 | merge | 0 | MERGE-LANDED | Merge branch 'work/formal13-3' into work/merge-formal14 |
| - | 969603a42f9d0ee5b9b33d2fd62e266caad1ec41 | 2026-10-03 | merge | 0 | MERGE-LANDED | Merge branch 'work/formal13-1' into work/merge-formal14 |
| - | a32d0426e0b6b49af01ec03298db36b03ef39456 | 2026-10-08 | merge | 0 | MERGE-LANDED | Merge branch 'work/formal115-docs' into work/merge-formal8-oct7 |
| - | 96b3883f71c51bc5a3a7a9065017ad5984518496 | 2026-10-12 | merge | 0 | MERGE-LANDED | Merge branch 'work/formal167-docs' into work/merge-qwen1 |
| - | bf07881cab4c1c14fba3e0492c0147e17a1c5652 | 2026-10-12 | merge | 0 | MERGE-LANDED | Merge branch 'work/formal173-docs' into work/merge-qwen1 |
| - | a667a0104d8e74fbf79c4d8e55d0da2f2ad773cc | 2026-10-12 | merge | 0 | MERGE-LANDED | Merge branch 'work/formal156-docs' into work/merge-qwen1 |
| - | f0f83fb3ced0b6f4e3d4fc759c006d759c7a3b51 | 2026-10-12 | merge | 0 | MERGE-LANDED | Merge branch 'work/formal137-docs' into work/merge-qwen1 |
| - | f574f7e3f6d10a7d7e379e206b87d574f6f211b8 | 2026-10-13 | merge | 0 | MERGE-LANDED | Merge branch 'work/formal287-docs' into work/merge-qwen5 |
| - | 31625543c7bb08f47402f6e019554ed9962f7791 | 2026-10-17 | merge | 0 | MERGE-LANDED | Merge work/formal404-docs |
| - | 99d8387f8a0aa617ee2eb632b6867283aaf341fb | 2026-10-17 | merge | 0 | MERGE-LANDED | Merge work/formal403-docs: encode_call_r64 is a harness limit, so the x86-64 instruction backlog is EMPTY |
| - | ea42d1d44a499931aa43d3b614f1ff28b18f0371 | 2026-10-17 | merge | 0 | MERGE-LANDED | Merge work/formal403-docs |
| - | 5fb8808ac08e9375587b31a3b27f9038cecbdf48 | 2026-10-17 | merge | 0 | MERGE-LANDED | Merge work/formal402-docs |
| - | 9a272080f6512089d5248fd0ee5488fd2a6afb59 | 2026-10-17 | merge | 0 | MERGE-LANDED | Merge work/formal401-docs |
| - | 3a9929a9dccb917cb9949e614d60f03e028966cf | 2026-10-17 | merge | 0 | MERGE-LANDED | Merge work/formal400-docs |
| - | 4a4934bf2db5cc7729ccfc898a8d491b53415635 | 2026-10-17 | merge | 0 | MERGE-LANDED | Merge work/formal399-docs |
| - | 14b4afd6c8fd120a11e58b96ab8dab2a0d4614b0 | 2026-10-17 | merge | 0 | MERGE-LANDED | Merge work/formal398-docs |
| - | 67fdc1c421bb676b1a1efcff9996a2dbc6de2431 | 2026-10-17 | merge | 0 | MERGE-LANDED | Merge work/formal394-docs |
| - | d782ed4b1d094e905e97bff68a50fb9c15cd8559 | 2026-10-18 | merge | 0 | MERGE-LANDED | Merge work/formal410-docs |
| - | 1a89054102301634100adeb388e2e2a2109fb23b | 2026-10-18 | merge | 0 | MERGE-LANDED | Merge work/formal409-docs: arm64's ADD/SUB reads its `imm6` shift, and the pointer store's two kinds-check merge into one |
| - | 71f5cacf6051c0bc8c961fb7125e46bca9c936e2 | 2026-10-18 | merge | 0 | MERGE-LANDED | Merge work/formal406-docs |
| - | 4921f1eb1060c668fe4da94ae1a2b7b4dda73037 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 8106701c84d63e753d6e03560fb697041ed11220 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | f76033f5d8dfea86de515a06973b871972f15f21 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | b3264c572dfe0439c5690ba922c1d94c67325c30 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 7d3cfe42eb9a956d4b4105bb699c571b98e638a2 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 7defe79f11eb990e82d6051013767a4c82d74b11 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 257d1972ae74bf09880eb7bba4065916ee8b3d28 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 524025cb6ea8dd21884eae9e537f6c6e10f26306 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 2fba3ac91b7a52a04f2cb3229e8e7c66dad083f8 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | c9bccfc20da6f5a51e9c4ce8772b3acc3f4b6e57 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | adaf96fdaf685a1ee9d955a9e657bbd49c0551b0 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | e7e0150cbd5ac83a2f9aae00c296178cd0f6d504 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 9c3c769c989f80a381e6e0a1f22410e7630775d3 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 6902ff286c6b7ea5e063dae0aae11d80be50107a | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 08a2c5aeeb6d4e40788cc4d9d7b2408cea8e4949 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | f00c3f92c6c7d2a817ea20c99b91c5f6b8a6d7d8 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 17c4fdf010ec8e8db4695d65b164d8cb9cc283fa | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 7319711a31c47592803c838d9dd9c12545fc35ca | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | ff04e42423506a27e652ba1dda3c4da7350f46de | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 1b4af7d703862ff935dac2fee48ee05807adc75b | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 31c06763e375346a9801d7569be233d4a2b56ae0 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 7e82bb6bf9f53199d630217e1e511a8e2966191c | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 82ee8cfc5dd9c56efdd2214bc6996586c701da9c | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | bfbbd722e1d530a7acab7b090817cc37fd386719 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | f5ff0c56478217255913dfd2355553e68c5841fe | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | edd2186481d65b013b2b588f7d6cc17b8801226c | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 30bc711502d2f4e054cc5b674f0e6a8aa8c33344 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 3d5f35fc92a66460238058248eb74611de648389 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | d0cae946274a13c1eede4b482e40a37da0844f4c | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | a3ecdccae736efbdd861d7d82c63cc144b83b8d0 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 43dc32e475fde5fb2cf2ef6e1c2d9a4c9a626262 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 79f6f23946d59c71f552f2ac386082aee883cbf7 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 4cae8e7e3814773ff80401803d69934f3b169932 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | edc408b7df7d6769e05ff5f67313e4f78df1a499 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 416449020c07d90887a7487db2e1495443943291 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | ab18f8dbfc279950de0068a43997078b34c0d4ff | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 1915f08ddd284132fc7ab426126e508349bebc09 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 53b948cdfc7086f5d203a1566da6b97d1c2986b7 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | a78fa84de2ff063da4257463bdc141c0d4fe07f3 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 16770512ddb739cdbee5971536506e116c31c062 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 126304b084563a1ae5c8be4034ddde9b3a190b7c | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 01d260c4b2d43b3b4ecd67c7ba9576df4219df54 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | e1ff35da739a4ba86323d7fbbf63aef1569cfbda | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | fd0157324d7e72b76789bb21dea0b70d2d2b983a | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 7132044454b1dcf498cfc50c36f9a2a682b7a575 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 186c97aa4ef0ecfaa4a4a29bc77514c89d12944a | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 6900ecf6136adc997348e5b0901e891e8322c7c2 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 22d20da015f037d99b108e8590bfedb68a0057ab | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | d503945b221e46dee249fb230c3f7c5628bf0740 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 20fb3f6d2705162528ea23fda79d1f8b5c6c6e66 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 1fadad012a345e9b42dd78fa53af553531b28aef | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | f2c39ea7e2e8c2d8e1e93437aa8877684adca296 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | b6baf5687b6a657a539be147975222e49ed61503 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 51ff1de43b46e9df87136c8bea9d993754eba1bf | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 9f9250ac9fa790855acdfa3cde52e60e620227f6 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 3f89f23d83b18892daf7da87ba941cca71590f62 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 68d67ee11ab975752c9fe57345b48455a7d93ca7 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 97a4522168be8109ba103811d885637bae65196a | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 56d5796b73ae53f13e9502deabe5a6e622cfcdb3 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 13b588aef6e2a582db3e15d4fa32474bf7a26c93 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 1e5846c7e55572e60597bd49fce3f8815dba1a1a | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | bd0ed7c5b8e14dbbee7e55c653391890738c6f27 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | fbb198ca65fc6a2feb17f33570fde85bb7856c56 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 98e38d66bfdfc99dac99f70603196f5416b22e6b | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 41ff9d6ad30a8bfdd251285f44a29bef1da07650 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 604dd2235f8a0d7fd157366d89868671ef406a28 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 41f073f38f951ace260bb96a4140e63292c96836 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 1513360ad0284f985ae6fddf186408e127e136d4 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | ac1454723533604b582c7c79ac9f64e787e05cbb | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 53da94296530d37986810f06f0a652ee991d2c17 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 7f3a6ea96a13409b46b003e17b5515304a1d9c36 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 84d940d9b67ae27ca4fb82bf15d838403767a6cb | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | d665c87e947cd6fba11654e9de7aa3a23d35b1a6 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 4548160149ae80a98510e1c35ddfb7c6e7c0ad7f | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 3c4d96dd35867eaffdca48f08cf1619d0068415a | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 5d877af1bb5bd9bb24bcb983a21e49794e6b66a7 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 9ef7a72a7d88537a647baffa78ffc1e4cd72afac | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 27f80c3a6532a1ef3e8f1a383e0c2f143018a648 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 30352db23dc5cadd2d108e25688884cc6a3900c2 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 1507c7eb7adbd8037ae0d6998522c63dc77dbc59 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | f50077357352613f04c75560a6f39c4958b851c8 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 67c675205e526051fc06020270b55ca449d67348 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 3df783ca6ca404425aec9aed29cd73719b52110d | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 38d93f34aac47bce466edfbe1cd573cbc0194243 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | e8173dd34e0b5d9275b09b35c6f693fe96d8416b | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 66697817dd2ff34d31cc9b73a0aa0563d9e32d05 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | bb22f9110c20c6960f4c6893f138ad1c507b609a | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 96f9464669697b79b93a78cbf98ca2be4ce3057c | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 08bc34240e080407c15254871be77481fd614945 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | a28a2922144ec0add68b97e75b1ba8cd8658dfae | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 566316ff621b62e85a88f55154604a06ad33c49f | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 6913fd8bf08f3c8d8f7d6cb6b865e70818f0d778 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | ff49707353b655d5a64fb2b335825bfa19fb1ca7 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | a02f6c8c31e32096c7d6bc0209cd5e9b0061db32 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | b51467045375c62484ba977cfbab22d077e1d1ac | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 24d272c0d86aa9e5f5dee0c126ad5d2121f107ec | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 484484589e167132c59bc9311d74f591cc5184ed | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | aeb9e9c1ba33c924f5c8195206af2bbeea396d1c | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 72780e893f1954a2e6209cdf105a4500d0f93711 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | c6decf54271790e8995a487d90c6d4cfeda3a41a | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | fd5e20d9d9104c0da25444498d664a0435e847cd | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 939d74f655c4deb3bbfdb1f7e1c180fc00b8f6ca | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 03122a72b5fe2c59ee5e3af5b970803d160012e2 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 6275fc58442a4e5ef94af4645979ec839590bbb7 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | c8103c3db8f2c3a8d25934dbbc507ad358da4627 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | e072b4619f7c5cf51bd906f2d0624caeaeca03a5 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 652b92541d90412c7e43de455eb615656cfe2b1f | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 481053294960fc0ab2736122487ae7770997179d | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 953ff6f31c01b9a52704b200ba269a9a05bea114 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | b008addafc182d01eaf71d5db23de979ea3ef61f | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | c87bf8aac1dd113bbd262d48d8bbe6f23d32592e | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 9fd726a7d8c91d2b50f679473cd92d9b7f8b1f93 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 94ba84b9fecc644a2802efc0715a7f86ee599fd2 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | d84517c21d0d336d9977d117ec67e33d368816b1 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | ad3576b14a13579eef141b9fb0934f33fa25a235 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 996479b2fef8693edfc39da6e90d9d536c04e7c5 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 3df3845b7cc40fd131037749022e441286add81a | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 927ebbdd7d33aaadbc2e28a21325e3e28e976c70 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 218ead8069ea1f92895f2d0f14316d2204c150c9 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | ec3f0bfce64be836e6280f32b79dc377aa235a14 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 6c2a5d472b277cad5c9685835e4a82b7df604950 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 8452705b9440e4fbf34f232e1d23912eb551c754 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 549cb599047950fdb72cef58ffd33c11bb16804f | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 8624613d5d036b37aff6a9db8bf0ffdd6c48624d | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 721c4a6da03cd60606739b5ed43dc963cc9b98d3 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 8dfd479f41a76510e086a125d59a092955fe7307 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | c70f20c7850a0bf48afb0246c66598b4d59f8f74 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 554bfd577a2c62c3464688e379e84705d20b2b81 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 491b43c8df0c5832ddaa96d9b48332ffde572258 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 122c2f62668d51e3e152366afaa8ebd44e4bfaa0 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | acc129a95c82d4d464295616cb5353dc71602ebb | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | df2b1d46418670570410da02de7d7aa703a4585a | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 7e7d4049fa5d3df4f390b5ac4a5542e7ef95cb18 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 7d33e3458a6c4e969536d327a9fc6493a31da4b7 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | d70a768d06cf609f1b304b1c16df405b0a0e3e51 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 405c8839e33dd385ac907f56b74f06076f4d7324 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 3e22b9402f9b5c9cd1107241f9ee439882442d7d | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | f3314a3f1afb2758b74e28ee4c4219a597d30507 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | a211a24571ebc27fe318ca40f3f7a9c7244b3571 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 53303b3558589065d2a932ae53791d244b1cda79 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 99d41ad95f36a591d71ca4c95a1a0fcece8df404 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | c71993b83178361e55c0871f99a53615ab5fc78a | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | c99827a847e27338fae041c2bfc38ac2973dbbbb | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 9a28841ea7cfeec994c210dcf66972915c54f795 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | af93d5298f7357c35a4137d3c0087375b3826eee | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 62f510e12c6cfba7668fe2296f067d861f0991a2 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 56a486fd24c43184559dad83557b1370db59026c | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | b255e0575e6dbf37441a2c408e7a7fb4c73b4ab2 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 14cf623539328714769e4c129d78cf142ad22e2e | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | f63151a3647a51d15cf435e53eb37cfcccb42108 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 6b14775ea7a83c52842abc1f92df7a12f7a1c980 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | c5426c082fe66630ea9bd9a68843cd95fb330b19 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 901b91b1e6352dca76c170f729c6fc41720e054a | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 9b5b620b61292124073a7b96e890f11594307378 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 804a32557f7811858f9b9623ece625ec086772c5 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 00673c6d4b0cdb8c3bf76d09dfbb60bddddbdbea | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | d064414ceefa746a4ffcc6fb8f6a01d0f1e2ef96 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | d368155335413051ba0b46b5be3e6718f79fd954 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 1e4e633f2523e12399d746ca88425e2f553fb42e | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 207698db544afa694f43ce2f56cd74e72ca442a5 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 1bfb43d8067884d3df3fb4e1cdc55e6bafcb7585 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 0a991556d10cfc38731e7d04d45cf691aee2ca09 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 1bdffcf62fdbcede956732153b7b35a87208b35b | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | c5b0b6c3c33f08e4ce49635941caf556d13b280f | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 91639b7411316c0ae6f139ad9351a43138b72a10 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 53c6024e6f117cc85fb2b80f6fdd8f5f94309f20 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | e4c4d6a8fe7d79bd6f857e37fef45307ae0b2304 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | ffd0bb2ba62ed7b60c18082bc1446af211076fea | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | b4f24449d165e7de0397eae51afa1a1879907d7b | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | e36a1ad4c5027052405cff948519ae8c0959b1a2 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | f86acdbd6984323b23f0b09d37d808f131db8c6c | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 83ca7cce60e38f62d50e2b64419c7317d7bce5f9 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 5e47a48280ac037fa5ea36e41ae61fd5dd90716b | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 078d09375edfa992b249e41ff7c150851061c1cb | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 722a0cbbfc5c5a3931b80e0f01f838cdda02a851 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | a53c767d13634ba436899ae3701d022109f94a08 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 6911f59860f4286e075f6573e8ed2cebb5090649 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | f85afadeed29874904ab898ebe507c138195e723 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 3eb7f080d1370fb45786a7f9096cd0bbba3c4d3f | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | de4a911c086a32b40cb868fcccf2e17d88990b42 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | f303f8bee02f3aa90b9f0036b6b2054d33fe3293 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 48721f553fc02e1bc486a69dc7ccb43dabc2244f | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 09e91338f5d72b1a39483094c946cbadd666987d | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | b2c83bdc974303fa27716b39a9e5e0f3f2bf8932 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | e02549bb42b26575dd281daffd2ee746cfe2c6ee | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 3303963d753632ca7926b289246eeb10b95d623a | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 5883888b7d27202edec0795a2648c697d7098c05 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 8213e579a87dc3995b381ac5138bcb98403d7fc4 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | d390ae1562551aaac3a2fe182fe0f2e3515106e0 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | d09fff24b9450b19d1b52192f556cf30d640cd1e | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | e16afe9fbcbdf9e8c57ced71ee749661c2ecc1a2 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | beddf0e7396b7f0d1b78ceb010dc141f69ba3ece | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 0e804b0d7b66c69b8eac8638efffafecd5f615b1 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 8a8666ae85613b0ae76d390bc5191ea5ddccaae1 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 0424b502fee4d4c63cb272691241bfd02615d314 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 8c69e5bf0173f09b19e913ce19a707620282df7d | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 5ab40643fa0da67eb044372a24b70707edb0c15a | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 06d6b44edecae85cc5ceead6fafb54320c534a29 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 1c3a060b519c8b6423077f8f054a23e997374070 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 1c73b2ed10fb0a7037c6003cbb32a5eb3479e6bf | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | b51877c3409cc660c195f6a2af8d38d05fea03ec | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 836d76d508e0f329a1b3d86cef67b5a6a067db55 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 2faef212ba5d4366120967dd242fc5d40f5de640 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | d8e3cc8062e64ced4030bddfdbf097218289dce8 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | de1b86cc37d768f5ddaf565e91a690017026f578 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 6e549daa6b57b93cd4830b4773bd0802d6eb828d | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 3337c1eca71f428a35f5a90058842315120f8dd8 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 5edcc837c5d69a167e9865ded3795aaafa68b365 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | bb46136eccf4070a505a5d93a8832830a27922da | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 8150635fe7414c162bf913efb7292dc95c56d6c1 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | c7e4ead3eb23f3a1f822dc5df5cfaee08c9c2cd7 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 9b9d10f847c5244716d04991acef551140e5a9b1 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 2d447c1287c642c4aa42571803fd6273bb2aaaed | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | b961daa08f07189fd89ced3aa4bb8fd99f849e8a | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | fc1c3fd0ddddae59e61550694ef28baf8ea1aa59 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 4a12c8287b881cfc05a2c14f05b0583a3e657c9f | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | aa9fd02cb73b5639056ec2bf00c1659a4c810572 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 00428770a08ceb23fa2ceee56cafec7f31df2fbf | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 78ebf8eb5752ec00fe524ea6a025b2be1b05d72d | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | c3e33b645ee7170bdd8cefbe566c9a5eb49284f7 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 25d9948f2fab83169606bd6fc96a8608a82a7036 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 0cfc993e8ac4d7b66e37ac51669ec56ad78eccdf | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 40873c88a550f1acf6f763badf9c52664dd58bc4 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 47ccf3993951a996a42bb726a370d46ab6641c2a | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 4f913f5ce5b8ad169c69cb372189ab0c67912ee5 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 5bda465a5152bc9bf60b3e47c9a405c43304fc72 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | cdeab60fa2795d2991f22959324ea32906bc4577 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 28e512598f830727276ee04d1cac9345d815635f | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | aaed6d3af72b4243028b2bb3a4ac54e5f5f6e93a | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | c23a978a1bfdb0ca994047fabd3414822781323a | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | c61b1ba57308ac52f88ff8af172ec585e685b44d | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 1f7859c1162d3667ceca1130e95d11ab5954acb2 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | a8fcdb96182312ce2c27fc4c653354607bc78ccd | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | edd779d7c162531e896c44c595f1825d3b8f555d | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | edbafd1b3fa3d88f4d0015363c108b5bbbff17ab | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | ac68b5d02ec519ddfbb99f10a214329a5a987c76 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | d97c3b18ef7e0c4eb822853a7de57fcf95e1ed34 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 34483fa808057ac476b000bca77089bfad7c2e94 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 8fa3ed221b1471fe904a14fc717b2bb0bd22f7e3 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 0e10d85f8c8ac129ec3e0b18dbbf7e8487eb21b1 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 32979ef2c0c00dce23d573c47e612b600240dc9d | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 12fa149e05bdfc098aece1de34c670513d8382af | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 6523f39769da199cb39bb9cfd6259b2b67558797 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 13977ad425124b9162e9597ef12fd4fe0099070a | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 51a2c4543a6df68f8f086ef6b62c55ef1ce14e31 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 6d419be041f7c165ed083d136f075b34ee0dbeb5 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 45f062961c883cc036b20c02d73f6bb71f9ff93f | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 75d22530df000eb143929365fb81a1dac6d9dd58 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 5cb4771b62a922e16a154bd836b587b559c82494 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 04f227e78cc009c92ee0ab135355adcac6defd6b | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 9790225e1cce4521c2c33273f43483aa16f2ee8f | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | f07edc3df784554f16edeb57f3207733551b7c45 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | ad6c03dd7fe2633493eb16e749759b48632d9f56 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 064e1cf602aa0d44de0d1d1c4386f41bf214a752 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 6f79b8eb66aec435701be9ae88ff2d7036319ab4 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | d6dc8ee333e8521f0a1d63fa3b71b4c21581c765 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | efb3d87db9949df2c97f714ebe5837a65965180c | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 49ad27416c330ea4215df1247c2a8482bf5f2adb | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 8760dda7fda024deee29e4a4db0728c7ffa4520c | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 113a46345866eec65811dfd4a548f4c6791fb37f | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | d41ba3d6e7ccc32e0c41fe985c8e225170f470d8 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 37c29141af1c4956a40695df52d1f0cf8bb0b62b | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 178eaea5becdd3b643377d0e47456c4722e2b5ad | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | fe8ae5e97c2fef281e0aee7198b256d949461633 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | e03f738a000e7a48222d07dcd4bf35d3ca0d7f10 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 80f203e319d3aa2c5f82b2a93548fab3bc51a55b | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | b60bea52d437660a374bd87093f8fa13c9fff17b | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 29bfcf4090ccb0dbb06c35b6da55b3dc021638e3 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 76055f90bce9a0593b15e4328e10ef78d24baa34 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 0152c11d9388dd538e81b1b8dcf929a6456103d0 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | ab771c574fcfdb0879c4f196f678b5365e64e3ad | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | d4c84df94edefc58a6744c4105ccef9522dcdc19 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | a3b9e7c5ebec56979ac5006fa33489ea51157209 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 98decefc3ede9c1aaa8e4fa07dcebe5efcbabe07 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 6ffd9935957af8c93d9a16a6df7d2952d8c7f4fe | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | cdb5120236eaa6d77e0fbe540173376e103887da | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 509b59bb3253643a5d6f2ba7f5b3a08de58fc0a1 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 8c121479805b92346a3a0647cdb0ac51961f90fb | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 3270b889f978b9bb689dcc76fe3d6696c77bb38f | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | ad7cc4eaf9ac92e534c657c8f6880aee7d6731e1 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 939be0f9891a4561f5ff34edf9aad3013a6be994 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 81f4173a10afc734cdee05e7d1761ccb572b0056 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 9b25fc3bb63031e75b7459bb9a6c5408f3068bd0 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 57209ac6d1b57eb469d2c3665a8a4d33b1b1883f | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | f1d8d8a3419d34d89ba98a729fb5c624f8aef60d | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 0346992ff739779890e3b9a6bcbe0cc3be978342 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 1b8b79bc3456c16d8675257005b5fb94f66dec63 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 64d842254ae030cddb1551e22fb325ab8c0da00a | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 283ec62022e0135ddc742440219bb85c30e68ac7 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 9e1db203742967debc028531229ebaffed0da280 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | c0a88065f96c8bb9a39e6506ff0d9d2df8a12d4a | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 5f1c370f8ff385a511306344e528063a7e876368 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 02844d8f85a2910c4f618d487b56b28cb0a6efc0 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | d3b07bfde9dfd929ce898a774557f6b3ad3f56da | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 2407f5b83e4b4dd3f803b8eb6339b346ae6a53e4 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 28fbe4493a4bc956bc22465abb627816ff960668 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 0f2889423fc3bca2a6be8bcdb5a6629ad8c3be1c | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | ea5f722e4e60a1b143c7d1953aab8889d92126c4 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 6e03fc8c4827f11cd3b81fc6f69448755bc2eef6 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 4a4402af0cb3d73e17f01a6990b5edaae5e13507 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 7e36b9251a4fdafb07d37455ef1c47cf368fccc2 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 4d9627fb17d86419757d21cd55fa6feaae0ff9e8 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 12df01050f9b315839f4132e62bc6b101d894f24 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 49e03aeb855876c72867000fe5d769309c0bdc16 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | c60bab9c6c4b06669adf29c846fe43e3b10e2f4b | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 321c4d5d82472765d5c9cda5522faf25f09b4794 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 1e21b604a7cc1bdd840d1d1422cc95752ccc3c89 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 0430aad785bcb7bb5ca577e342ae3725d24f3309 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 57ca352eec745902157a18a305eca82deb91a0d6 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | f5c35d6dd080377696acb9797105ae57a496e97d | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 07687e2775623db04c0803fafc09bbcfd81b442e | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 5fa18c804d10af060818748131add1378fe6d21d | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | c29b1e68d7c43ee0fb9ec606f7db958c96b87941 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | ab04691299a3b2d86930e6eef3489e17f7a8a721 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 6cf71c4801d3fe229006d18562d28c31283ce6ad | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 2b955a0932897cb6a0a5af97f535603d22b25a16 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | b2603dd7928e3b31196f6db294536b82a1469832 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | d837eecba1632f89377151203e0b6c0992c0768d | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 8d9c76675d1d3e3654e0249e3276bbfe49e5ec1f | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 1b75931c57c1214efbb36829542d5f167113aa3a | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 55dba551338af8f7e7ef550cc5750e88366c4919 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 760d47ab9900978fa442e3d588db432282eb45b6 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 0acaabe09c7bc94ad5fe48a417bbacf2d6c14e40 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | e760fe54d783a5168fe506a84b233f815ec072fb | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 5102073d5ebe8e7d8373035b323232caab3e73d4 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 2f1b68718a9323ea4dc8711e3b60b6c5f4d82766 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | ecc3174e63d76588f961c4cb0ded08c2182c180a | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 9821b7a1b69ba02d4a0daecb48ace22e02dfb61a | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | a3a701c65a8b0acbf78bdcc2a12a8889c7af79af | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 3743a91defc0a9a4705ebb2663e7f42125721a63 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | a4e568174bdfee089a85f6d12a490299cdeba077 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | f8d250cefa09abd16ab8dcce0ecfe922030ce418 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | ee2a36fdf8df87952b94241a63017f669c0a3d66 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | b0037c19ca4d3a84b2cce378fed3be17d9783b7d | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 9c03f41d4715b6a5630bf83bbad9cd532d18049a | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 345399cd59bac916d1c7ebfa3e45b15aaf24504e | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 064f01164fc58a43b83bbb5d0857aec3a6dace30 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | aa3502a7cc262ac65613e9783124adc3572c20be | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 93faa24253d50b92b82384f79d5168515dae2f82 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 4be199d07084f6533e25f5c3518ec5aeaa61b650 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | c3a3e73ab61604cfd4353a40711b6ab93c1008b2 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 9565405c1ccab3b093c05178f307e9eda6f9c54c | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 0ee90b243a683fd2df91ab487617131ecdf46139 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 00f1c794805b9d25648c718c00909d22bb91865f | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 232b926879d3b1942bd5aac44330d4516bdc5e1a | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 691a39ecf90050c4ac43a0ccdc58c56c5b526c94 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 0c2a7a06c72c67cb03550c22c7e7ead05a8b7829 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 82d09f04cc89a1eba95c560a2f52acc4b7c201f5 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 4788dc162f2b018e63ac1039b591691f433bc1f7 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 3efd13451598060ed901258141596281fbc108ab | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | f0005cc9adb6fb06eb6455307cc318b09140ce25 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | b9119269547f81471d707b6709138a09bfd16b3f | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 502e919b20e9d0c4e63855f5f820ebac7c8197db | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 628c42ce058311d15b485d0bfe23563003d2d469 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 985ce3eb40b18dd7719186f602efb504b2e184b7 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | f97c9bbff76af1760979214cc903cffef7d967ef | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 6256560355282b881745f0560581c7e23f1d8f0c | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 8c246c9fa1ab6131be11f618aa842d6453d6aaf9 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 6f2e37a4bac5ab9814c5c211de55c451f1d8d4cb | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | dfd4ca976c78a504ea2457e49897b44acc10f1bb | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | c20c10c9b62788c000fb8c77ef4b9185a57e095e | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 7b5dd5b2bbced680a0691cfb53014d13b3242378 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | fb0997a03834d2de26bbbc91f63ef0cc03858ee5 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 9e419065d007342b5275c96d117d6af20662b4a4 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-enum-8986 |
| - | c87e241d5c9e90a4ef2b15e379b9e634a0e88a7f | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-ctor-temp-field-read-loses-e-8778 |
| - | 23846579f09275c684427209636e6e0d8c211fb3 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-ctor-temp-field-read-loses-e-8778 |
| - | 9a6ce6bfa239cf19cb611bcc0195313a5a5ba8de | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-a-method-call-on-an-uncompil |
| - | 653bba97498ac583133c3afee2b0eb97c2df17f1 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-a-typed-container-local-with-no |
| - | 7b2c364bb51cbd41d0a7609cee153e808d4807a4 | 2026-10-26 | merge | 0 | MERGE-LANDED | integrate bug-codegen-a-typed-container-local-with-no |
| - | 44b3b8fa33f9c85ac95e4c3b20427b7949726279 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-mailb-240 |
| - | b99c75f23ed6350a2d78028074394e5f4325915e | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 49965b7a1782fd503aa01e071159b266e666963b | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | bf1da9741dd364a12fd43edee84c8dbe9a115418 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 227e5bdb8dc513a07f30f8c34f3d0537adc986c8 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 5a31fa53443bbf8717f9878aa776357f873ca2af | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 3a650fc6d15f789c60e56f62cb377c901db1e7fc | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 244817060a8a0811511ac26938adaf1b223fbbaa | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 4224146dddeab33b451eac49aee4067d3e6af1a8 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 3ba6fb33fd19a3cde330f1f5e6d51a2441cf1d09 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | bbd3fceb163c5a8b59c9ef624b53b74cd832a81c | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | be4ddbcc2fb0768e31f6cb308ab63be10ad4f981 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | c22c3265a801e8a3fe1168869674ea79b2ad6789 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | fdb8d90156e72fe95d9698964cb6f36c8fbb9d8d | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 6fa67d886c5a7102d8b70045e73ee9cb20572398 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 05480494d3d88b7acab3e46de174319748c8cff7 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | da97bd4cade26402c41766034638e5fb68800341 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 2fb84dbe3d34e545f15439c6793f76c04f071963 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 421d4a1ce5dd61480498f263685f80460d9ea3f4 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | dbbb8b722ac17718e1222f3ff84c8698b7ef1d11 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | f7ce61ea38739c9a6c8dc01a624eebd5795164c8 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 2935f92c0f175d5f060f23fc7af231aad102dac6 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | a3e4bd39843036004b52ffe1928dce6714182920 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | c9950ede548942170a77789bba6966b38047089d | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 6d1e9722c21a016295c6760b5728e7db2f4517f7 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | b3e27fc0a1ed443e8fd67e82b27c16ca2fdba45f | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 25d63a357a26fd331aef880e550bc936b4812be5 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 3c6f6873b754aaf0ba7e1c9ebd26d4b828cbf237 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 0ce2d940171e55332fe134e3c084f980ab35c559 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 78670f18aec7aa954ae0d9f9f92ac66627d3478d | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | b7bbd6fe28633f85cc0ebe7b161be046c437e82f | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 72c531ee12e79cf06c63e4c72cf1ed04ff7e7f87 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | d70bd16121f6c26174cb96d8c46712f84882de8b | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 82d2ca9916287c0932230037560c9c0e19b9ab1d | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 53de225a73b19a873581c30d4073841928e8b89b | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | cf491f8127ec846e54bbbbae4970d0e6c5988320 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | c9d75daab145a2f8eaf14aa302557f8612880cae | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | a591462f971e27ec449526f0285270aaea3d5a8e | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 70a075dc742a0bc35db044e9a15dc35319d50a5d | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 4e9dd5ac8b86c632a8ff2eab994cb505cb2f0826 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | e51a4409218541a89fd7b46df5ff983d27d71097 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 18efd5eae27c87e573132256765a4818e02c83d4 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 9f5f19cc44ba5adef5e5cee56405e8f7ea225bb2 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | ecda9a9ac160b8f3cb6dec7ff62d9c616393516a | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 1cfeef28187da1e163b02d8a2340d3d7e4a9b0b8 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | de89c905a22744475a104a837ed78d1a8eb8eebe | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 7ac5a5d0bd9d12cbd591813fd4571f933e37e455 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | c2fe047886c8026d4cb18fc26f1f711dc800d7d1 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 0ef67a0c024d2678906096ca99ac7ef30c6ad348 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 6a0161fdf71ce01fd04748293929ac2d938b4dcc | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 571121e5b4a9eba6b44a7bf868c68e8c065d78ed | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | a1c921b27ad398fe859f8a9110205d8809439554 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 97defa496c6b861e0e35c1a48d11885a5135b044 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 8154a566e1fef1759caaa8f567b4ad24f4258def | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 740726fb32f5700a2e790a1c8a85cf137548773c | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 9ad47176266299aa32f3b03626781354c4a2aa78 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 90c2cb4a6195300e0ec06da45effe1e1e6482019 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | f976abd4b5be282297bd183944a271358038a9ce | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 5e4247db374717d3a30b1054791a4f6edfbb44c0 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 2a648660574db3eaf5989a4dfd6e2ecc2aea9228 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 1a49976c00d335e8135dc52e0bcc7be2ebc2d493 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 8ed8329e284289c924c860d251c309f57f6897e4 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 764490a21aab40b0aaffbd5de35de2cdb9e2e25e | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 763e20fa5a5c45e461845e7312d5fe23bae2f35e | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | a9c6c0b5611e48ccb57baf0ad7a8be873e91e395 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 2c1f9a63d53e3a62b246ccc15446fb71c7519239 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | abc7ac5e404feb29440e9b9ed1ea60e758f6da84 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | a6cc9a87565ed651fd58a2e11f3ee04470eeb390 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 51fef74b1b69bff0740a5f192edca0bf7e036ff7 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | c45279eeeb5d68d1f207c1c5b0cde487b6d70553 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 1dc20e2ea7e2e5cf21bc7ca6fb769bdd871e816d | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 08b01b43d85a7eaded116107bbc487670e0a3f2d | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 63426c736ab9e7498b0310276045e7975bfdf21e | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 366e7ec29c5056e70b48673476c98cb75e6036bc | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | e94c930ac8dbe16e483cd890675060ff90535148 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 6520c9fe52ef4bb283c6929f7f77eeed6513e77b | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 0fd33dc3a38f49e118e9f037e8e28d3e8d537825 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | c0b12f737c4cb7b2a9aeeb72ff834173d9a02ec3 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 392bd7e5f5dedd3e8d37feec14d9488c258fbb22 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 2c1918af5f8b5792782b2f497cb7d9aaed818ec9 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 8390b3edec5b636eadc7d0b54a42444d4a8fe5f8 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 80fee97775d85eab32c192b49919d76e3e46276b | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 5495f5f220681ccb375e919538c8c4184d6322b6 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 65c91159911400764a945579c1d5e2f34be665b6 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | ed7a288e9b1755dd1f8fa8eb6e0ee03cdf142744 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 829e93af0ad8d4cc838c4f2a0b82740e9f2d17ba | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 0613ed9db42b1b202738e7435d572a0e259f42a1 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | ae76d3cf10eceda80c22ea861844b3d985a3c360 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 9f90bc17a788ca398d381e2935415823ad811ea5 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 36a5004c1b061aee00c72e54f50401f6ac4bd68f | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 068c500af0f86e1ef40c0ec8044207d0abf17d19 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 28e884a07c8c10b1cbb587fcbcf5d026a12b65cc | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 99ffbbcdfabf7dd57facdcf30eca72ce7870cb5b | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 5d85af5ee4396fa2de5139f1929f302ac169e4c1 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 9d44e750674684ff6e84097398505e0407f4ce8a | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 665d7ddf29714ffe4f6f92a2301fa886df63617a | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 4ddc9584d37ab717527fa9651fb05d70c4059541 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | b43105b9dddc41a4f68f5e0f8df4f331eb0887d7 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 6cfd3b32b4572e661885464b49d8eac03b12a139 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 70d8790651a25f04af169d6b62a2fdb0766b8684 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 0f1ec901c2c332e8b03db5080877710a31330f66 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | f1e4a4b6a0c4689373ae789235dc5adbd567c7f5 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | c5a548260fcca56e14a23c3698faf5f73a3e3a24 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 5d2bcef4eef41e4df7ed67a58c934543eb797cd1 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 592ae03578d80c91e071194188d50ae7becfae32 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 749726514c66b24090702f80027512d1c5235abf | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | b56f402395137871095bc63173973582002a468b | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 38deb073198e193803391eab65ee7927beee4494 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | b54189f46e8fd72b682c3573b460c12e2079a36b | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 2a09718b42bad5f61684c7152ec512030b2c90b2 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 80dea3b378f4c572818b6f94d318ae0c0cbfba89 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | ec1cf308de2997096ff8f4cb2e5cc4cd8bd56c9e | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 4d473caf5e0a20ca1cb36cb721f27689fa54f72b | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 01bd96082b4483cdf442570ce82ee7b368ca03f7 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | d9481d8f70b45317430b8cfd2ba346982e3fd0e1 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | c1c41f48eb062dc0646f442878cf2cf27f5a5e6b | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 838a4d0a3efd896b6671dc5efa4df2f43679a78e | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 2d4e51448c79bf4fac22169e841add3adb85be83 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 177510add1446c908445c10ff7bf6c89a1ee5140 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 1a37f3351a0f4d3247a4d9923883a67d9cef6959 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | ad3c2d5cd8306a91c59c9b1e46409fe2b52367b9 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 56f4ae1053a3473736f01cd72330d80eaf7eb042 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 5eaa683b7a2dbbb598055047a22f6e78da7c0a8f | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | d8d9a495d2ac7a5605384b5deae697b896f45b5c | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 2d3f99c364e27d2d93e237b6f4fa92168cc022eb | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 4b85417b73418ae5406fe3fbc3edb72da372dd4e | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 0794ccd11d77e5d8a7f5b44e6e833c16732d1f35 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 3631d268caceac3d38cfc1932a02672cb37997b7 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | c9997b5b9a4799e1e507019e7b86aac63285251a | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 0a11f4070a49881d96beec76341afbf3226cc0db | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 33a1508844c851655f850c5a4d287f16e35a1a72 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 0f98cff334188e08938bc1013e9b356b0359c346 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 22e80cdd84e9442e4d592a3817e4882decaa0765 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 65bc4e30debc71c30c67e448e8adf554dd9b49d4 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | ffbb5ad4759cb482f951e0a98d40e3a062a048d5 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | b3d0142877329c809d4e6058a09810b1c9f9b295 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | cd12438d0718094df2ec4c62ad786a741c134fb1 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 426ddb5851ef0131fe110718caf4f9783192f197 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 0682defeffd1114f5198664f15a023bb08e04e3e | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 4561afee210293497b4dad1fcd605c0203256e9f | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 88d4a094d4b3e9ebf1c3cfa7ce79410f7dd6958d | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 3b82c72aedb446e210ce1ba2b7bd8427c08b24fa | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 33b93bcfea9c7f1f7a9bb8e51d92ab015e0ba38a | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 384831c9d23bbccabcfd1629544de72ba9b86d33 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 671bc8cdff8ecbf07505ead29d6d88f85c123b52 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-untested |
| - | 58ddb28c53ffca481b9b6cdd89b6db7ce7198825 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-test-the-axiom-closure-table-is-stal |
| - | 02f1e1761256f7db0e4e70b7ee3c7b9d7869bad7 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-bootstrap-resource-blowup-3294 |
| - | ea136fdd42ec0de0b21659891f1f4fa89b7312ce | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-proof-lib-prooflib-work-step-smulh-c |
| - | de170145979b939fc380a63431fc2ac5a26792ab | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generic-struct-elaboration-f-2915 |
| - | 95ff5999b7f80fbb6ef945134aa780b0b5a27a9e | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | c3b144077aa0174310ca0424b7c7cae377d3237f | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 8a63a14fece80a0630fc7765768c67124d72c32b | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 8e1d33819b83a3007106f6245b074aff584c2a10 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 6f0d2e72f58441b2cf1baab9105bb79f31ee67b6 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 47aca347ecf458abadf33809c60fdf44cc2cc2d5 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | c39b8a65148c5c87d1c28fb0e16f7a7da1fa12dc | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 87f326285bdf712d233af27c49dd9f73ae240203 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | a22f56052ba871dc58959621b9ae4c2677e2df55 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | b7421eb2ad55933bcb54c39db268e0a0ffd06e1c | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 019f30b472db847ff6bd9e51f6dddc0dd02beb1c | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 5d6ace44489e94340a4d04f45b0263b661fd193e | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | c0629edcf7d9effeb250257cca00ce313802a8c2 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 4ec8a384f7693d6ac9c0c0a0028898c5741e2af5 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 20334213e4432bdbc30adbd2bda5de93f3e19884 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 01762be7b4c846607446d2f1282b5ebb8cf8ffd9 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | bf6e3ede55c2f2056d83b8c65ec1b4504e6a88d8 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 5292286d03b87c86c9e3a236a04f5b407415c0c8 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | d6972bffd0fd0ef64652dff957f6ce4b2815cab6 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 199ec97e4012e5482fe4f7d7f591f64419bb08bb | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 5f3fdcd1f80edd19668c51d285e9116ccd277246 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 32409739ed0fa49c56f8614caea835960c64f532 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 85f8ed62f04365b913366d40328371445c278be8 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | fa2fdca4fde6092bdc4b9b112b4c01139d72ccdf | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | f5abe3bcb3a0b75a4f2f6daba946c40b8b33d6b8 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | c9043e69d5a69f96330dc47c1548e425dc24f525 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 4aa01a528f0f87e5270e8bacb1fef89768c8eef0 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | b6885cca42a0f1e4dccd32faa8431b009913d6cd | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | dd8fd409248168710b90f86a52ea7896a326db7a | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 6e43725c22185b6e2ad6dda042bca36c28a6273a | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 5eb12fad62339865917122843b864071028e02bf | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | d80c1d82d1d69512cf255020888aae3b83829747 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 9f474952b38d34bdd23115bfad9cefb8d1716ed5 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | a46db2046b9491f9d172cbe6b82bd5f9ddd8a709 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | e2c6701afbc2d2781a30d6deed4c24bed099bd0a | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 12669eb545d2234bf0e5e76266337c7c8e674d0f | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | d2b3f0e4535cf904ea534ea80dcbb2540fa20a9c | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | bac1614c36b3f460e1dd85e2c188c4467f6c31dd | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | e479d5990a20f32e41b434a4cbfe01ad086c9d8f | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | a573420037004211d92a7f0c4af9ee473482c853 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 4165751483ad39913edeb98046e8b6611c69a27d | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 0380e6a96663ffc0a57844bfc0a28446041412d7 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | a9e97fc0546eba1cbc8f157c56df59493c0c3e54 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 5d98a7fbc6c07a791c3bed095a4c1fdc5a2cc916 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 551959f7ed2933e583b7d1a350c093b8b8b4a1a4 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 9558eb4174579d9e5b547b21160ead4bdf24fc71 | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 35fa627de98237137156263309d9270f9298e50b | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | cea0cd63755ff5e010d477e8028047b78352061d | 2026-10-27 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-ipadd-8986 |
| - | 157a9afe69e313e5d30679c8c5463196a18ba731 | 2026-10-28 | merge | 0 | MERGE-LANDED | integrate bug-codegen-star-kwargs-call-through-a-p-7519 |
| - | 3d03472125cd7aa7f061add4ed91fb62e7fb51d2 | 2026-10-28 | merge | 0 | MERGE-LANDED | integrate bug-codegen-selfhost-tokenize-region-eq-7110 |
| - | e641b8be4bc828ee0e6f1fe2a51f8116a98d78f1 | 2026-10-28 | merge | 0 | MERGE-LANDED | integrate bug-codegen-selfhost-dumpfull-ends-in-at-6701 |
| - | 0e55188a101e214f41938195a7d79079e24e8782 | 2026-10-28 | merge | 0 | MERGE-LANDED | integrate bug-codegen-selfhost-closure-compiles-an-6042 |
| - | 4e6cd28b08e5fdeb53088b4a6922a7b17e9f336d | 2026-10-28 | merge | 0 | MERGE-LANDED | integrate bug-codegen-selfhost-binary-links-then-s-5874 |
| - | cc1d4213130bba18afac6eda02947d5a1b4328fc | 2026-10-28 | merge | 0 | MERGE-LANDED | integrate bug-codegen-selfhost-actual-types-identi-5582 |
| - | 5c2bbe1efef71c3a087eb4d406b8bb4f498c9cc2 | 2026-10-28 | merge | 0 | MERGE-LANDED | integrate bug-codegen-return-element-type-is-unifi-5167 |
| - | 13b29646576703f197b8627d0c1a8fa7e47fc562 | 2026-10-28 | merge | 0 | MERGE-LANDED | integrate bug-codegen-polymorphic-struct-param-deg-4876 |
| - | 149443d3c0309c58da5c5f42e21d590189b19ca9 | 2026-10-28 | merge | 0 | MERGE-LANDED | integrate bug-codegen-polymorphic-param-non-str-ki-3971 |
| - | 4f2f15b5f6a012f5362745b42a9443df33339211 | 2026-10-28 | merge | 0 | MERGE-LANDED | integrate bug-codegen-noshim-dumpfull-preexisting-3559 |
| - | bf692eb22be72c8bd80fe5534ddfd614710dd936 | 2026-10-28 | merge | 0 | MERGE-LANDED | integrate bug-codegen-next-on-a-user-defined-itera-3268 |
| - | e1430282f564f54055ed368a74c49d99e11cf5dd | 2026-10-28 | merge | 0 | MERGE-LANDED | integrate bug-codegen-nested-list-param-two-elemen-2975 |
| - | 1ede51a8c7173ed6a7d4b68fd75786c478df9374 | 2026-10-28 | merge | 0 | MERGE-LANDED | integrate bug-codegen-nested-class-method-cannot-r-2810 |
| - | 8f05676f6a91500c27ba9abaf974949ad6d63225 | 2026-10-28 | merge | 0 | MERGE-LANDED | integrate bug-codegen-multi-kind-global-read-befor-2385 |
| - | 01ff19443ba2e9b72294495ad6d417afbc72eb28 | 2026-10-28 | merge | 0 | MERGE-LANDED | integrate bug-codegen-loop-target-rebind-outside-t-1163 |
| - | 0c32253ca4af13014a3500549c34f36699e82a76 | 2026-10-28 | merge | 0 | MERGE-LANDED | integrate bug-codegen-module-toplevel-undefined-in-9940 |
| - | 729750c7720e8f485a038841a19e49ca791202c9 | 2026-10-28 | merge | 0 | MERGE-LANDED | integrate bug-codegen-module-boundary-carries-no-v-9328 |
| - | cb8840b870bc1116a551114cdfcf7875b789e6b7 | 2026-10-28 | merge | 0 | MERGE-LANDED | integrate bug-codegen-method-with-overloads-is-unr-8794 |
| - | 78493c6f5abbdd10ffa7eac418c5b5ad550ced42 | 2026-10-28 | merge | 0 | MERGE-LANDED | integrate bug-codegen-imported-generic-never-elabo-8135 |
| - | d5dfecbac9f6ae489f160aefe8422da202d61477 | 2026-10-28 | merge | 0 | MERGE-LANDED | integrate bug-codegen-materialized-container-has-n-7281 |
| - | 4b7ad46f870fca555cbc48fec088bad4ec416592 | 2026-10-28 | merge | 0 | MERGE-LANDED | integrate bug-codegen-len-of-a-non-ascii-string-co-4037 |
| - | 742e88d78408fff319f68c0fdb4388f768ab490c | 2026-10-28 | merge | 0 | MERGE-LANDED | integrate bug-codegen-lambda-call-boundary-loses-t-3422 |
| - | eed79883a4b63b1cd114f56fd5200ed6f6a74475 | 2026-10-28 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-test-362 |
| - | aebc3a2e47cb43c3f7de11b85678a06fd2d8b71f | 2026-10-28 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-pickl-240 |
| - | 7be000738e2959ae549f748654058c2674936447 | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate bug-codegen-int-true-division-truncates |
| - | 3ba562947fc8dfd2f723022c2a59aa5a8086265e | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate fix-merge-fix-merge-bug-hard-readme |
| - | 10977041ab85545db90a517ea0864a79b9dc18bf | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate fix-merge-bug-merge-master-still-misses-definition |
| - | 1267f9773ce35fe1fce20a75b0140c436120c808 | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate fix-merge-bug-merge-formal58-three-doc-conflicts-a |
| - | 8114d73d921dd15be92ae9ca485ad93fb3853128 | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate fix-gate-native-dumpfull |
| - | 3177ff96f8cf7f5d5a7cb0553537a22c3f51a168 | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate fix-merge-fix-merge-bug-codegen-gate-stdlib-syntax-enum-case |
| - | cffd77409bb57fe5875ebfd44f6dc835a6094345 | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate fix-gate-mojoc |
| - | 52a4633d8a3de9b17ce6605bbe7958154456be18 | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate fix-gate-async-void-return |
| - | d6f273cbdcb972dbf6d1a462c5fc311f6b2fc80c | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate fix-gate-runtimedylib |
| - | fbb165aba8297b6f53dd45d29564aee4c1963e9f | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate fix-gate-runtimedylib |
| - | ec6ec5aea505e165eec70af953461b21eeb3a1b6 | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate bug-codegen-int-true-division-truncates |
| - | d38b3f75d806c692efa05c172473e20feec969d7 | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate bug-compile-fail-ctypes-util |
| - | 2f5270609fe4d818c2d35a26fcf87f428ac813f9 | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate bug-codegen-int-true-division-truncates |
| - | 1d9c917c0f0ab93c2e7b7bec2d93608c109de76c | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate bug-codegen-int-true-division-truncates |
| - | ff848ad0291317880fe38091e8e04b1c48fd2992 | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate bug-compile-fail-ctypes-util |
| - | 8bec95b0adb9c0421eedf7e65d08a86e68c00cf5 | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate bug-codegen-int-true-division-truncates |
| - | 92238e172bdd6a21e942ff87c8a63001e5992901 | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate bug-codegen-int-true-division-truncates |
| - | b7adcc74ee3b9089d778834e7a3df66c8ed464c0 | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate bug-codegen-int-true-division-truncates |
| - | 61fb2a33700dc52ec32e8c68b2d6933efb1a06de | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate bug-codegen-selfhost-tokenize-region-eq-2974 |
| - | f962f7d09114cc2502430728ae8df71323b28d8b | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-test |
| - | cafc6d2855b7a931c745fbf7f025b58b5afa9511 | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate bug-codegen-async-result-slot-is-int64-o |
| - | e56792edbf1fccabc52c8ebee369a73febfc63fd | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate bug-codegen-nested-class-attr-reads-encl |
| - | 48cd94abe686e1e95ffa002d6abd74d195aab271 | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate bug-codegen-nested-class-attr-reads-encl |
| - | 52dec174a3ea2af3cb7a39d8bd868a1ada9a62d5 | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate bug-codegen-module-boundary-carries-no-v |
| - | e3481588b81d54d4b17d98b3b54171d5bf0e093b | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-test-1975 |
| - | 85849413b134e14f8b2432d3d9f8aa6ac898766f | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate bug-compile-fail-ctypes-util |
| - | ec230538179017421d838bf6835c92647b25d1fc | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate bug-codegen-gate-selfhost-red-3596 |
| - | aebdd09818c13d02dcb0baf207cb936589f5e28c | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate bug-hard-readme |
| - | 223f4175a5da5ff98f4af8177476df7b6fa69aae | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate bug-hard-codegen-generator-lambda-expr-u-2294 |
| - | 5ea0095d03d1e56ec0eadc4fdb2bec09a2e54338 | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate bug-hard-readme |
| - | 13d2c3666a7e9620508f174d6e30e51c2977601c | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate bug-hard-perf-nested-module-compile-walk |
| - | c4ee8f950e9b06725e24182673932bb034b200bc | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate bug-perf-dump-full-closure-is-single-thr |
| - | 39e2853064206cfa9f8f4621daec016ffb1822a3 | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate bug-hard-codegen-param-used-only-as-meth |
| - | e40c7ba20547c69229c0b1a61d70aec96cba706b | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate bug-codegen-gate-stdlib-syntax-enum-case |
| - | 29bedf42088fa44af4ecc8a6199655894e855c7e | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate bug-perf-dump-full-closure-is-single-thr |
| - | 322328da55b11dde896bd37c354692d37392ffe1 | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate bug-hard-codegen-param-used-only-as-meth |
| - | 860c442609308f08bb6a4cc4c3d8ef28e0b03689 | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate bug-hard-codegen-dispatch-globals-list-f-2168 |
| - | f2d7e1421a7a6aeaa3f6f32d24973b3a234617c9 | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate bug-runtime-gate-sqliteruntime-red |
| - | d3487605305ccc0362d38dc1b73813a6f57a4667 | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate bug-runtime-gate-coro-future-await-red |
| - | f3607d4be8d9367dadd9b175b8232b996833e3c7 | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate bug-runtime-gate-coro-detached-async-red |
| - | 682fb04a0b5d430c4fc0cd59dd3db12a7410d0b9 | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate bug-codegen-the-collections-abc-coro-clo |
| - | 9f2105b92f77b453e8bac759501c14f3c050b576 | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-str-method-call-yi |
| - | b2ea6cb56d4cfb396c7a3105ff906989ba78dc6d | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-test-1175 |
| - | a73c0554c546612d570a6f89ca2dee7bca1916cf | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate bug-codegen-gate-native-dumpfull-red |
| - | 3be0d016a35046adb71062f99dbc4b86a79c99c1 | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate bug-runtime-gate-sqliteruntime-red |
| - | 75c74bcd2ed519c9ab0882a99ba672f5d7c24510 | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate bug-runtime-gate-coro-future-await-red |
| - | eab229359a65941893d9ee8e7e3382cf7d2b9701 | 2026-10-29 | merge | 0 | MERGE-LANDED | integrate bug-codegen-gate-gimple-async-runner-red |
| - | fa15b0cb610232b237b4d33a82745b8859223b92 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-bug-codegen-dylib-generic-inline-copies-4599 |
| - | d9f19379f626fb1c84e3a3e395f9b4c5d2c2a57d | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate bug-codegen-closure-str-return-is-lost |
| - | 06677b5bb52e68d012e955de449ee8ed3186eee4 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-red-bug-codegen-dylib-generic-inline-copies-4599 |
| - | fade809996d52eed9b6c3e35f08a6091f90a5a5e | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate bug-codegen-closure-env-and-boxed-local |
| - | ba168a47fee084ccf5bd5f046fb9cd32e768b158 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate bug-codegen-capturing-closure-float-retu |
| - | 6bd8daa8b3f307c9e94420b805a91db3f1fb724e | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-test-6516 |
| - | b519b1703b690c71f55e4756216218b63c86b66a | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-enum |
| - | 36e392edb2b95f28116fe1db3e09dcd5627f45f2 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate bug-codegen-dict-literal-container-key-v |
| - | aa612d665a1805ef4470323bb8fdc0b0e0b25bef | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-glob |
| - | 8dea124654c31734c4a6ddad80d2fc487cdf7886 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate bug-codegen-closure-env-and-boxed-local |
| - | 90223bc3aa4ebdeba2a9d039994b7fc749377f59 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate bug-codegen-closure-env-and-boxed-local |
| - | 29cfc334ff9fa44b1ce339895e7365b8abfa7d8a | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate bug-codegen-closure-env-and-boxed-local |
| - | d941c33a07064650d7bbf61fe973a48880a5756e | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-merge-fix-decided-bug-compile-fail-tools-scripts-summari |
| - | 4b901f12e87f4112d4aa7a6cc435981cd1e986e5 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate bug-codegen-dylib-generic-inline-copies-4599 |
| - | 10fcf18ade62626753c0832310a80d4f50d67b96 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate bug-codegen-dict-literal-container-key-v |
| - | ec0cf60e160252cbe593ea19173f2864b88620fd | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate bug-codegen-comptime-alias-read-through |
| - | 2fc1e5040fc98314deba0a51855e39ec6d515fb2 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate bug-codegen-closure-env-and-boxed-local |
| - | 5193ed8d853c30b6a39af280ed75f87768b27a7b | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-decided-bug-perf-dump-full-closure-is-single-thr |
| - | 03966b5c7ed006e61c1428663dd51fc90d841bc8 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-decided-bug-compile-fail-tools-jit-targets |
| - | 229056995937546b265c2de9dd628a3a84f24e3f | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-decided-bug-compile-fail-tools-gdb-libpython |
| - | e4cc8acf33040b13bfb3169d2ac4f9043d13b158 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-runner-pre-existin |
| - | 936709d6eada8c9ad42a04f320b9187ed39e18d1 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fi-429531 |
| - | 46ad7a131a800a39ecb6507220a2d4cfa3f1eaf6 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fi-429531 |
| - | be6001ce75b7b61f0acae1119f8f85fff4c3177b | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate bug-codegen-dynamic-call-layer-residue-a |
| - | 0d805f4caeeeee8d2bfc20f3711493084e30c6cd | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-merge-fix-merge-bug-run-builtins-over-a-user-iterator-st |
| - | 54e5f5792b051280945ab39b4c43adb901bc2276 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate bug-codegen-the-collections-abc-coro-clo-1068 |
| - | e8ed74c57644330b2f9a19e758c404de6fc082f4 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate bug-codegen-the-collections-abc-coro-clo-138 |
| - | 601e5cfa341aeb09eda008a4a96e3fd8a8e0d640 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate bug-codegen-the-collections-abc-coro-clo-138 |
| - | 8012a91300418c2134cd887fba14779779343177 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate bug-codegen-the-collections-abc-coro-clo-138 |
| - | c27b08b54caccdd9d2283c79149a7b08cf9d61a6 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate bug-codegen-the-collections-abc-coro-clo-138 |
| - | 23f14bb87e9594b30d40c024f86371be0432d91c | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate bug-codegen-the-collections-abc-coro-clo-138 |
| - | a69b7c66cfed2f9465e90134c3914f968fe992ca | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate bug-codegen-the-collections-abc-coro-clo-8576 |
| - | f6c92c9a324a0e856c219d3d6f401b8b4ab42a81 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate bug-codegen-dynamic-call-layer-residue-a |
| - | 50ec62cc128c901fab252ba45f70eba87a820cde | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate bug-codegen-the-collections-abc-coro-clo-7637 |
| - | 05589de05dabbf0c048f681018ec4343d3c8908a | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate bug-compile-fail-tools-c-analyzer-c-comm |
| - | 8abf2f223747c9622363a6f14046b4a9144d6c67 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fi-638349 |
| - | 06f7ba6246a5f7d32ed809946b62dd1f2c1ff6b7 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate bug-codegen-next-on-a-user-defined-itera |
| - | 4d53327bf87045cc15acc64351beab7050af7184 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate bug-codegen-the-collections-abc-coro-clo-5630 |
| - | 6a7b31721dbcfa7d2592e98920fcb1fb485f5178 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate bug-compile-fail-tools-c-analyzer-c-comm |
| - | e8a7aad117ebd46f3f7dfeb7ad1017aeb277c4cb | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fi-4 |
| - | 93eba12636ea0a01d688964b7056a3defb9f8892 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate bug-codegen-next-on-a-user-defined-itera |
| - | 7be2153e39131898eb58b358046620792085fae5 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate bug-codegen-dynamic-call-layer-residue-a |
| - | b176168c504c4d7e368fdfe3cc603d5c09ed02b3 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-merge-fix-leftover-bug-codegen-generator |
| - | e95c244904d582a1eece7993ff41c717cfdb70f0 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fi-417491 |
| - | 189b646729e310b6f1ba6bbfb0b0d465cc90e9c1 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-merge-fix-red-fix-leftover-bug-codegen-the-collections-a |
| - | e34ba73ce8c3c56b5c1f1b46eebc71931789c37b | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-merge-fix-leftover-bug-codegen-generator-functio |
| - | 81f9baa12ca34c2385df7097c783ed2085fad2d9 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fi-6 |
| - | 4aed95b9891309649f0fc56b4a88862946ad89ca | 2026-10-30 | merge | 0 | MERGE-LANDED | Merge commit 'e228dce4c' into HEAD |
| - | c3d8e84f22476eb0344e66b48b7d7ebe536a4994 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-leftover-bug-codegen-closure-env |
| - | c54f1e6f67728fd75b12e1ca1659c9f7d24e5fb5 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fi-639608 |
| - | 7cc4a2d2ed9fd109d776ed163b02ec91a043d2fa | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-leftover-bug-codegen-closure-env-and-box |
| - | 481ff8fef0cf31165209cddcb03ed57b71dae0cd | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fi-117677 |
| - | c2a28d2b1c55cdb8b66ca26f35951e78f142a834 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-leftover-bug-codegen-closure-env-and-boxed-local |
| - | 37b2e05eaeb08c3417146be8db8754eba10a6f49 | 2026-10-30 | merge | 0 | MERGE-LANDED | Merge commit '7c2224ee9' into HEAD |
| - | 4b4f1a193aaa849a97dbded2c74bc0bca8432f09 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fi-9 |
| - | 09fa20c0fd56cdad30f54bbaaa752f4be68f2833 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-merge-fix-leftover-bug-codegen-generator-function-lib-mo |
| - | 4590180ce28c01658d193a4780e8310b78de3eb9 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fi-9 |
| - | 831e8a98b680aaeb058a2a67b133b4c8d33e8d45 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-leftover-bug-codegen-the-collections-abc-coro-clo |
| - | be21e08c798820b0b11d957672bee7116913aeb8 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-leftover-bug-codegen-dict-literal-container-key-v-8985 |
| - | c5776dabefca5e800eeafbff4cebb10291866d01 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-leftover-bug-codegen-the-collections-abc-coro-clo |
| - | 9851dd645901ca00b99097d1bea7367201eba97a | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-leftover-bug-codegen-closure-env-and-boxed-local-8985 |
| - | 6dc722209a6db86dac08cee4fdcf6132f0792330 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-leftover-bug-codegen-the-collections-abc-coro-clo |
| - | 78de63ad5afcf03485b3f2ca28fca3b9a7b00aea | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fi-981691 |
| - | 0d784967bb7fc53b1948f54fa43faa6e2a5f4c3d | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-leftover-bug-codegen-closure-env-and-boxed-local-8985 |
| - | b5b51ab64ec1947b9cad7fc8e24bc91bf6e5ab38 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-leftover-bug-codegen-the-collections-abc-coro-clo |
| - | 279f1abee1ccbfddcd4544eacaecc654930fd4e6 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fi-149885 |
| - | fd4842fabb34150d7ff627d8351e8441b85b9021 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-red-fix-red-fix-merge-fix-merg-3 |
| - | 18a9086bcf4b3031ee77ad8aa4f89df4ce120971 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-red-fix-merge-fix-merg-342178 |
| - | e37078b3280bb7f6a68440524420b56ed20a2e43 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-merge-fix-merge-fix-merge-fix--8 |
| - | b0d73a0e1b4c3e796be6ddd50d93f99934843bc9 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-merge-fix-merge-fix-merge-fix--879501 |
| - | b345ca37cc342ffe62f2ae2dccf73f44348a5320 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-merge-fix-merge-fix-merge-fix-merge-fix-merge--9 |
| - | d9770596d383d7c75574bd76814653bb9c258607 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-merge-fix-merge-fix-merge-fix-merge-fix-merge--980834 |
| - | 95cdd73e7441ffdb3a12a26c1f75c8d9810286fc | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-merge-fix-gate-rthdrscan |
| - | d3338da4e728bed1f6b4cea1c70ae3122942902f | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fix- |
| - | b55250151f46bed29d01cd91bd8d2474bb78d19d | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fix-merge-fi |
| - | 2c4bb0cb51f0fbccf0bcee5c7eee9d78b54482df | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-red-fix-red-fix-merge-fix-merge- |
| - | 26c91ce04c19cfb588bb5dad2164c82e339211cb | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-red-fix-merge-fix-merge-fix-merg |
| - | 772fbb3e06542d3d83d341cb5c04d30011bdbaa8 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-merge-fix-merge-fix-merge-fix-me |
| - | 79990a7970edb1417febd82f2f9463a382e206a3 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-merge-fix-merge-fix-merge-fix-merge-fix- |
| - | 697fa0c2339802a4287cfa6ea35460764bf2dd8d | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-merge-fix-merge-fix-merge-fix-merge-fix-merge-fi |
| - | 2854d96fd8aa2d5150692930c9a15663bbfc0769 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-merge-fix-merge-fix-merge-fix-merge-fix-merge-fix-merge- |
| - | 0781fe8662a274b388e73ed20b76338538bd66df | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate bug-codegen-dylib-generic-inline-copies-353 |
| - | 6a1d3278312b1308727714558aeafeb7ecbd338b | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-gate-formal-doc-truth |
| - | 1829e24c040d6c138a1ab87735a6994d234d44d5 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate bug-compile-fail-tools-cases-generator-a |
| - | 4362493e28f470c743f54f0ed9aabc02b89c82e1 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate bug-codegen-rebound-container-param-is-t |
| - | 99ffa1196ed636b3e8d7f38cacd5a4d140d4cca1 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-merge-fix-merge-bug-compile-fail-tools-c-analyzer-c-comm |
| - | 7512d4b2e9b12581879918be12fed1ccaef4fb6f | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-gate-mojoc |
| - | d55fee36af0ed88e3d7cdfefc89e3cd237e5caff | 2026-10-30 | merge | 0 | MERGE-LANDED | Co-Authored-By: Claude Haiku 5.5 <noreply@anthropic.com> |
| - | 5ff5429a982e6aaa5f9e09a020cd9537b58cc2f5 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-gate-formal-host-import-shapes |
| - | 62159075105717456f70cb7bb8aad07ddaef5d67 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-red-bug-codegen-int-true-division-truncates |
| - | 1fb1a2eb2af7e9ad338ce8d2ed658c963ae475b2 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-merge-fix-merge-fix-merge-bug-codegen-next-on-a-user-def |
| - | 4b8a4979f6e11bc23917db9ee585e59f21c5a9a8 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate fix-merge-fix-gate-suite-self-test |
| - | aeaa5fd655034d969abcd261056ef3a801740280 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate bug-compile-fail-ctypes-util |
| - | 1ea24c2dfc598cebbafd790ba8c782bf8f12f316 | 2026-10-30 | merge | 0 | MERGE-LANDED | integrate bug-compile-fail-ctypes-util |
| - | 32794684f31694f2f4cf6f798feb97a983414150 | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate bug-codegen-a-bare-or-explicit-yield-of |
| - | 884486b993451f9afedeef67489ee012a11656af | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate bug-codegen-a-bare-or-explicit-yield-of-3467 |
| - | 8f46549318bbf60384f2de8b4e07b2c2695a97b4 | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate bug-mid-codegen-selfhost-binary-segfault |
| - | 36b616ecc25ab6fa198cc287da0148afe619930d | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate bug-mid-codegen-selfhost-binary-segfault |
| - | 980985d7b770f567d9dbe5df1dd637c5d801aefd | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate fix-merge-bug-codegen-generator-function-lib-glob |
| - | 01b73ae8875d15e04e87b69d9fa38e58157e1137 | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate fix-red-bug-codegen-dynamic-call-layer-residue-a |
| - | 1c209e2394e3280b05af55dbb554cf53456fed84 | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate bug-codegen-enum-runtime-class-creation |
| - | e8d2a1b8763a4205be73d1cc73b6f2268ba01560 | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate bug-codegen-dynamic-call-layer-residue-a |
| - | 996dd0a90d3fdfbebc340d2d9f88d7cc081f7337 | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-param-str-concat-i |
| - | 11dba33912defb8b35196f241ab4acba985f364e | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate bug-codegen-a-none-held-in-an-int64-loca |
| - | 9104225f52d1bdd6215ed71cf0ce66987608e6cc | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate bug-codegen-list-append-of-float-into-st |
| - | 2a520b4b123f912299638cb1dff430f7d31321d6 | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate bug-codegen-a-none-held-in-an-int64-loca |
| - | 58aef5538164664dce4f4fb5f31d18250b21b524 | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate bug-codegen-double-needle-in-a-str-or-mi |
| - | 7d190df22fe618732e6949232127c6061a44c3d2 | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-param-str-concat-i |
| - | 6f1f0d48e6b2dc4a8767470965f9db09f5a94dd1 | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate bug-codegen-int-in-mixed-str-int-list-se |
| - | d8d4b4f4c25cd3747a7487e317a6701ce77c644a | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-param-str-concat-i |
| - | da2293351e7bfad3c8c448bd55ffa50413ff44ec | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generic-struct-local-typed-i-3160 |
| - | 79a0f77c6b8290abc518fe87470bf8bb8db448b3 | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate fix-merge-bug-codegen-enum-runtime-class-creation-7854 |
| - | 26c81b97ea563b300886f992c0d430d275c4919f | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate bug-codegen-char-in-list-of-string-liter |
| - | d9506cfee54199b4d3c8bcb619eca21db9892306 | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate bug-codegen-str-encode-compiles-to-the-i |
| - | 4d994eac0df7275777b96d1efa59e16b7bc436d8 | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate bug-codegen-dynamic-call-layer-residue-a |
| - | 1d208ceab13298c47062c107c1dc4a72a42b8a03 | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate bug-codegen-str-encode-compiles-to-the-i |
| - | a274d5e051c689bdc98d66caedecd66ff73bab0c | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate bug-codegen-function-values-assigned-in |
| - | 285bee19c7cc92f634e8c432e64675a85e481bcb | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate bug-codegen-dynamic-call-layer-residue-a-7662 |
| - | 9cddcbb21cbcf9a706dfeac01608ffdbf6179d9f | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate bug-codegen-coro-list-param-int-element-6808 |
| - | 44cb5a407c56a8c1139395acb0fe70c8cad0c088 | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate bug-codegen-closure-str-return-is-lost-6808 |
| - | b10a40dffc649a955b6573d26f8a04a5ac3d50a6 | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate bug-compile-fail-tools-cases-generator-p |
| - | 9c811e7de8afdc9ead59371c09ab405fee59a6da | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate bug-codegen-glob-bytes-pattern-returns-e |
| - | 3c197409e6dc8445daf0cf7951a80acf9067d1e1 | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-bug-codegen-dylib-generic-inline-copies-370 |
| - | ed2f72bcf8c502e4d644f6758a3c6f5b224bb94f | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-enum |
| - | 5f2dde8fbf2faf18278117e31660b57346475d75 | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate fix-red-bug-codegen-dylib-generic-inline-copies-370 |
| - | cf420bc87ae5c11318fbb73112f873c2c60d682e | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate bug-codegen-dylib-generic-inline-copies-370 |
| - | f264b77393c09d064303b67562a17b9a88b94a9f | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-function-lib-glob |
| - | 710091bbc07ec89b0b232f54d5cf5fbfb1395790 | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate bug-codegen-dylib-generic-inline-copies-9804 |
| - | 0904ab0bf7659b4a40e606b36c0e3fbfcb9b03a7 | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate fix-merge-fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fi |
| - | d4ea10c8ff5d3dbceb39f3ff1b8ce0e274ee4159 | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate fix-merge-fix-leftover-bug-codegen-str-slice-tuple-return-se |
| - | d6997153ac3d501440a806c8c2c530e3d1a8ab35 | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate fix-merge-fix-leftover-bug-codegen-str-slice-tuple-return-se |
| - | 873b9218e8cc34de6efc52cd7a3600b50015e85f | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fi-7 |
| - | 36027b3c5781f71489b96ea62b98bf1b4149147a | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fi-734213 |
| - | 752dad7077f097eae003a0a1e1372120e598e6c0 | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fi-116224 |
| - | 0afcc455f97ac539cce367ab6d4e3363c9b81f50 | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate bug-hard-readme-4650 |
| - | 94cef85c5daa526ad726b21560ced673b7c17e1f | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fi-946271 |
| - | 644371c3b56ba5d4d7293bcd95c1631c54eb169f | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fi-308214 |
| - | 77c754c3d9c0143bfe99b3412c04eaf5fd9b3d74 | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate bug-hard-readme |
| - | d82fc27cc72715f57a645c7bf0976faee670b8da | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fi-143571 |
| - | a3a2b8ace68624aa1bf58acf035bbb224aaf4daf | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fi-978394 |
| - | 1f87bbf2e12dbec61e79ae29918d89851bf9931a | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate bug-compile-fail-tools-jit-targets |
| - | bcca1640dd877ac6f13ed04ca7d99888c9c2dbcf | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate bug-compile-fail-tools-jit-targets |
| - | c425641e95773c671d04f08a8d94f72fb83eae26 | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fi-3 |
| - | b88689dd47a664f4f1d92db1c7e577628d26f906 | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fi-391730 |
| - | a902ab3fad461b748c5d5992e5374c204331554d | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fi-103659 |
| - | 7f1eb53292d032cda35f1ed3fb4b4c77fc9ea81e | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fi-5 |
| - | ff7fd8add00c482cb2c60b5ab9aa47b9fabec84d | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fi-525724 |
| - | f8be611ae9b3300012bb1e20ad64c03c118f25c4 | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fi-9 |
| - | c8acbee9049fbabd5c61a61457367b916076bf60 | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fi-942048 |
| - | d36a05c8a1476c5cb36b8a465a51639543f973cd | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fix- |
| - | 23e4c346faef391fe7eb49a7783fdbca3ba557d5 | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-bug- |
| - | 3740fab0b4791eedb562d70e97c8d5647c835cbc | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-red-fix-red-fix-red-bug-codegen- |
| - | 9e157849d88b2fa28113d26da9ecab26214e20b2 | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate bug-codegen-gimplerunner-five-reds-at-th |
| - | 6702ae1eea635473c42f44ffc22059bc7bfa0920 | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate bug-codegen-gimplerunner-five-reds-at-th |
| - | f0de30b52500631956c3dc8fddcd2554feac0841 | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-red-fix-red-bug-codegen-dylib-ge |
| - | 27b559dfe47ebac40bff85b51a2fc8d16e428427 | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-fix-red-bug-codegen-dylib-generic-in |
| - | e56f92aed578fe3e781f46cec5735abc6a3379af | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate fix-decided-bug-compile-fail-tools-cases-generator-p |
| - | 1d2cc963da247b7bd4325422ccf8d0d587d8ed3c | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate bug-codegen-closure-env-and-boxed-local |
| - | d56a85e077b3a75a55a046508b0e869688e8aaed | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate bug-codegen-closure-env-and-boxed-local |
| - | 2dc095f75f510be8195898a15cb2e2af2471fa5e | 2026-10-31 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-fix-red-bug-codegen-dylib-generic-inline-cop |
| - | f9daf32492211f22c57a0e7ba678200c5a620cc1 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-merge-fix-red-fix-merge-bug-codegen-exception-ob |
| - | 027e5ee7330688c66cc7145494df2944b8ac3f57 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate fix-merge-fix-red-fix-merge-bug-codegen-exception-object-att |
| - | 802c6d1463bb26b7ed83e3c029cf85228ccd07ca | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate fix-merge-bug-codegen-exception-object-attributes-3163 |
| - | f60ac30fddc4053a0695556d939651cd05d6fe51 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-tuple-key-int-and-str-elemen |
| - | 8129b2aa30f50462647f3585bda59aeecd2275e2 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-test-stale-per-child-timeout-literal-3915 |
| - | 5743f1fd24b76c92ee0094aeb1c5cf03b5eccfab | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-mixed-str-variable-at-module-2226 |
| - | 0145ef14cbc80ddeeebaff2eaec6e23e0c3e500d | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-untested-9966 |
| - | 59e3dbba34af42b55625d3763a8ff951d538231a | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-mixed-list-and-str-call-site-8451 |
| - | a5dd2cb7049c313d8bf24824ef2366cbd0258111 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-untested-9149 |
| - | a5b7104314e1b69048bacdddb4e26c8163df9ba6 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-untested-7512 |
| - | d45dd720ff31ed133f76e633c93ae9ea70214721 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-merge-bug-codegen-closure-env-and-boxed-local |
| - | 0b5cd19a8a14699e931e9e83209ce7541eca0c38 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate fix-merge-bug-codegen-closure-env-and-boxed-local |
| - | 6875c7dda767d3bdd97068c9db79ad3ae55ebe8b | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-run-four-run-suite-failures-that-are-3487 |
| - | 1c5b0fd351e35fc8f266e5122c84ddbd3b84a9a3 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-gate-check-gimple-three-red-cases-in |
| - | 9dbaf73678ca53f06bbb3f7e5379606a5b74e6c8 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-runner-70-fails-em |
| - | 58438cd16db532ca66e17a1d9c70c57ce37b8ddb | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-gate-check-gimple-mixed-yield-types-320 |
| - | 3ecb27b7fac70c9ad8d8730f12b2628a9b5cc682 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-gate-check-gimple-ast-mutation-sites-9672 |
| - | 772bde8896a96ace1326ed54e18eb1ca527e3788 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-gate-check-doc-refs-ratchet-formal-p |
| - | bd2d2cd58583c42982ffb56de26c19b73c6e6b74 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-gate-check-gimple-yield-from-delegat |
| - | 5d50007d5a7b0f24876f8099a2509836864793ab | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-str-encode-errors-and-decode |
| - | c94617d403cf5412786ef0b56e4ac06f822bb11d | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-unresolved-method-receiver-r-6479 |
| - | 03cb8d69ccd70a7b25ccfec58efa9f8c0874b6ef | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-untyped-param-receives-conta |
| - | 880be65cd5bf38d760f9b7ebb1cac129b5880dbe | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generator-param-str-concat-i-2000 |
| - | 3a7ae132fdeeee603df7c809d3bb3151576f0bca | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-str-encode-compiles-to-the-i-2964 |
| - | 65d30cae5ced9276d2b7c910190ad98173ee02da | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-send-into-just-started-gener |
| - | 9bb4715057f7fca261f2df1ea75092ffd5e22230 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-dict-comprehension-repr-is-s-195 |
| - | 586bba036e0b80fd8e0dfbaa892b9718d1aaa4b4 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-gate-async-void-return-red-8732 |
| - | bd6a0bf7b0c99073a80e0d6836caf167c508fe78 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate fix-merge-bug-codegen-cpp-path-reads-stale-generat-5415 |
| - | d0b3c6f4e76404ca2f9a8b60d7e933ab14da1fac | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-ctor-temp-field-read-loses-e-6412 |
| - | b4ba1d20c16fc8a48e8e17ab21c5e8d1e4fe00a2 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-a-module-scope-global-bound |
| - | a124b1e538a8c6bdf3c9e5e89f3fbce316484163 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate fix-merge-bug-mid-codegen-gate-bootstrap-stage1-tr |
| - | 7c5b5bb5ef0c20e7a619bf43dae2393f5a7192b0 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-a-padded-zip-longest-struct-3614 |
| - | 50e489dcb0285f1c99d7bedd3aaf80c7b7f731fb | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-a-materialised-sequence-curs-3614 |
| - | 48709ab65b3f0caeb5456ef73da061c1519269dc | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-cpp-path-refuses-expression-8234 |
| - | 1f2e6c7973191f95a00470543884b8e2f84bff2b | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-cpp-path-plain-float-call-in |
| - | f3dec68ea305bfdf1248d32621bb1a591109f785 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-cpp-path-print-multi-arg-in-4880 |
| - | 2d68e93ef37fbebf5e5670892799634ff6fe0636 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-cpp-path-refuses-expression |
| - | 50c43764628fe79a99c8d74bf2b2ef5390d0d6f2 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-cpp-path-refuses-expression |
| - | c07b5c0634d6060f17029f85229fa2477c8ed232 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-enum-runtime-class-creation |
| - | cc6a761775743db9b676adb16eea2661bd03f31e | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-cpp-path-reads-stale-generat |
| - | 94eb247f189383176aaf6bfb5b29b06939f40c1a | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generic-struct-local-typed-i-1120 |
| - | 972f86caaca738d18b4221a0dc87d7661e708cab | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-nested-class-attr-reads-encl |
| - | e64c3cd4984d3ed9085b2278023ca46c998fa14b | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-cpp-path-refuses-expression |
| - | 5f7242bde6ef73b762f8042a404f50a79d21f93f | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate fix-merge-bug-codegen-cpp-path-reads-the-previous |
| - | 4772c0b224457602db4834099c6807264e37c83d | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generic-struct-local-typed-i-8360 |
| - | 22550070ee0ae410acfdd703436031ee87227f11 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-cpp-path-refuses-expression |
| - | 9d6854c5d7cff48740672fb35f688d1a8237d9ac | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-cpp-send-emits-default-path |
| - | 8b316d617cbf5cd7f851366aafde674d6ba19dc4 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-a-tagged-generator-passed-to |
| - | a01fb300b2859abf9d76fced7764551759d8694c | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-cpp-path-refuses-value-recei |
| - | 5545e9da889e1bf19d1c6b95384a33d45314309f | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-nested-class-attr-from-str-p |
| - | 0fd4dbea39b49c1e7f2d2466a74c480fb544f29d | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-a-tagged-generator-passed-to |
| - | 8b3fa750de63c43eea2c1a5e1ca3d2d7424380ad | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-unary-minus-on-a-received-fl |
| - | 4e0c40de76b2bd061eb90d6d0d8457906c8b6fca | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-tagged-int-times-int-prints |
| - | 9ee338e49c365ee56953fbc5a64d347cd8b888a3 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-enum-runtime-class-creation |
| - | 62f47bbf432860ea432abad6586b7317510009a2 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-a-tagged-generator-passed-to |
| - | a0d5cc840bd635c63783467110dcee55b9f104b7 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-arithmetic-on-a-received-non |
| - | 9ec1b82a8a83571bf91306ecba669ba3157c21bf | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-a-tagged-generator-passed-to |
| - | 1519bd0ea4ac0a6d544fd4aee73b6834f72ea5ce | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-module-dict-value-type-unkno |
| - | 5d080eefee56dae1412a0df1bc84ec97cb68101b | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate fix-merge-fix-merge-fix-merge-fix-merge-fix-merge--653970 |
| - | d84ae0503932547766bf60fb92aa85a2d214859f | 2026-11-01 | merge | 0 | MERGE-LANDED | Merge master into work/fix-merge-fix-merge-fix-merge-fix-merge-fix-merge--653970 |
| - | 56eb5cbfa86b85505bc64ca851b4f4d06dccafea | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-coro-callsite-visitors-calle-5724 |
| - | dd160ffbbb98d4381d1fa65d7485c84ed90483b4 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generic-struct-local-typed-i-2991 |
| - | f408832dd2531711f3f96e3e633f30899f1159a2 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate fix-merge-fix-merge-fix-merge-fix-merge-fix-merge--688684 |
| - | b8c521eacbf8d82f0552a9582c8884d582e894ad | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-module-attr-call-result-type |
| - | 3652e74af694fc2b952d12ab8e66387754efa4f0 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-read-of-unset-minted-field-r-3412 |
| - | c9db2350b1def0284a2ae6b74037e399e397d4cf | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-a-none-sent-into-a-generator |
| - | 4711003729c05aef1a21ebe64f297624349f080c | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-a-bare-or-explicit-yield-of |
| - | 780ec39bce756d4ed7f8e7a3a8e249b44c8b9924 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-enum-runtime-class-creation |
| - | 445f5032ed1d49928ff7845423c98ae5ad7ea606 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generic-struct-local-typed-i-1885 |
| - | 339473b58777daaa20eef14b066fc9c671cf03af | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-match-condition-uses-c-logic |
| - | 92628d3d320910acf638c0b0e61f73286bf4a063 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-hasattr-true-for-inferred-fi-1885 |
| - | d30eb3cd6fb408c31d6a02e19d5d401aa315b26f | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-enum-runtime-class-creation-6422 |
| - | 3535b39649afc12285ac8b57d69933af9cfcde1c | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generic-struct-local-typed-i-4952 |
| - | 9e9e2f5447044e806ae47fb14e5cd0a4ef4f09bf | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-enum-runtime-class-creation |
| - | f74837bad876e6949d997a29296470d21cd12a39 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-hasattr-true-for-inferred-fi |
| - | aeb532904d91ccaf9587cff3aeb376f512b4a812 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate fix-merge-bug-codegen-a-bare-or-explicit-yield-of |
| - | 3822f3226953f811ca25072cb71933a2735ad051 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-hasattr-true-for-inferred-fi |
| - | 4bb0ac66021d5014b2469d52cea2772352e36795 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generic-struct-local-typed-i-3812 |
| - | f593fe92d9b156b34130e531f791ca9d3364df53 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-enum-runtime-class-creation |
| - | 9b6ef9536fa4b185c4ba5813f1e6f22a25e7ab66 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-a-bare-or-explicit-yield-of |
| - | 205ba300608bd450af97766d90795c4a09699c02 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-dynamic-call-layer-residue-a |
| - | 6fd55515a0788a4a716445e8c2387a689feda134 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-a-bare-or-explicit-yield-of |
| - | 1f101f0beeffba3026e61fb3f5505e26bd331296 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-a-bare-or-explicit-yield-of |
| - | e8190a15ea4d34503c2e82b7c0058d57ce992b83 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-a-bare-or-explicit-yield-of |
| - | 0820e2c485dd1d9e7c3123ef38a588094eabcf17 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-int-true-division-truncates |
| - | 4d863a60cebec2dff0933532f8dd9c3f2173dba0 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-enum-runtime-class-creation |
| - | f4f69b1c51bd391eb95c2ca321c3a7e1356b8596 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-next-on-a-module-global-gene |
| - | 8e71132d05ee61036cc89b831dd61b992cf2871e | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-a-bare-or-explicit-yield-of |
| - | 013017f2b12f946682e108d6e8a479e342593f63 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-dynamic-call-layer-residue-a |
| - | 48e65b00486ca90ab63d0b21946890dff0f22ef0 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-dynamic-call-layer-residue-a |
| - | fdb9b97191102e999c34ae5f8db8de9bcbfe64ca | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-a-bare-or-explicit-yield-of |
| - | a726bd24e6b643f58b0cb07ecea70b622717dedd | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-enum-runtime-class-creation |
| - | dbcc6f80f0122fb27ef8942c2b83bfb2a787254b | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-generic-struct-local-typed-i-8190 |
| - | 041061fe91b102c0bd442a5fab549a1f629a5401 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-a-bare-or-explicit-yield-of |
| - | 44cf46fcccc5183e2e4ffa5705521362c01561ff | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-dynamic-call-layer-residue-a |
| - | 89877ec21fb48285c6e5a6da7544de667e4781f2 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-enum-runtime-class-creation |
| - | b55999a74b0f75d29992b7aa2119b9577fd448a7 | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-int-true-division-truncates |
| - | 7afb9c3a271e9ddbda38211a0ca8a79c2f02b2ad | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate fix-red-fix-red-bug-codegen-dynamic-call-layer-residue-a |
| - | 7353854baeeaaa1dd569fbb50e8d1439bae333fb | 2026-11-01 | merge | 0 | MERGE-LANDED | integrate bug-codegen-a-bare-or-explicit-yield-of |
| - | a1131d38951ff0800a0a14d571f2f5aa7d8e8e1c | 2026-11-02 | merge | 0 | MERGE-LANDED | integrate bug-codegen-hasattr-on-list-method-repor |
| - | 900b97974508e2807169ec2439adefe28591f3a1 | 2026-11-02 | merge | 0 | MERGE-LANDED | integrate bug-mid-codegen-mailbox-closure-remainin |
| - | 2654c31583f0d67dcb0155ebcc74e77d3c81f3e3 | 2026-11-02 | merge | 0 | MERGE-LANDED | integrate fix-merge-bug-codegen-cpp-path-and-or-on-received-5172 |
| - | 91b1de592a1d538311697d25c432a16ce6781a37 | 2026-11-02 | merge | 0 | MERGE-LANDED | integrate bug-codegen-bare-str-decode-call-stateme |
| - | 6f43bb1062afa744e925b603d0c5390ba677681c | 2026-11-02 | merge | 0 | MERGE-LANDED | integrate fix-merge-bug-mid-codegen-frame-f-locals-and-settr |
| - | 06b1f3812272cd5470b8e42250d75d0291514373 | 2026-11-02 | merge | 0 | MERGE-LANDED | integrate bug-codegen-re-match-group-and-repr-are |
| - | ee8f9f2efd8f0d27e89985ec08fcd94fc3055a1d | 2026-11-02 | merge | 0 | MERGE-LANDED | integrate bug-codegen-coroutine-os-path-split-lowe-7899 |
| - | 70835c7b6d28cfb9569f6bcc5c9dc39504926479 | 2026-11-02 | merge | 0 | MERGE-LANDED | integrate bug-mid-compile-fail-tools-c-analyzer-c-6778 |
| - | 904c426dbd5fe97c5ac9152149530634d8a95d6c | 2026-11-02 | merge | 0 | MERGE-LANDED | integrate fix-merge-bug-codegen-glob-bytes-pattern-returns-e-6620 |
| - | 8d6dcf69f259d9a6632d984fb6817f2c1dbbd7d9 | 2026-11-02 | merge | 0 | MERGE-LANDED | integrate bug-mid-codegen-selfhost-tokenize-region-6524 |
| - | 0fd812871cc94d13c87880bae8176b3d0f0e9d9f | 2026-11-02 | merge | 0 | MERGE-LANDED | integrate fix-merge-bug-codegen-len-of-a-non-ascii-string-co-2995 |
| - | 36ebe4d0fb83546e632a0257a547163c8772ae95 | 2026-11-02 | merge | 0 | MERGE-LANDED | integrate fix-merge-bug-codegen-coro-callsite-visitors-calle-9336 |
| - | 2b6cc181b8933c3dcfcef2a9727c6e29c27f514d | 2026-11-02 | merge | 0 | MERGE-LANDED | integrate bug-mid-codegen-nested-container-as-dict |
| - | a0e9612a44a7b5ade65ac7010cb70db39574500d | 2026-11-02 | merge | 0 | MERGE-LANDED | integrate bug-mid-codegen-nested-class-literal-att |
| - | ab7a5a6b55997f842319e9c49a066c40f2f2033e | 2026-11-02 | merge | 0 | MERGE-LANDED | integrate bug-partial-work-handoff-9122 |
| recover-8bb98d4fe | 8bb98d4febd6ba9a9d188e1d012f7bff53c8c9c6 | 2026-09-30 | merge | 0 | MERGE-UNIQUE | integrate fix-merge-compiled-silent-2 |
| recover-61d3c07e2 | 61d3c07e25800a667b0aceeae0363487da7c92df | 2026-09-30 | merge | 0 | MERGE-UNIQUE | integrate fix-merge-fix-merge-fix-merge-fix-merge-fix-merge-fix-round8 |
| recover-2f60724c8 | 2f60724c802aef79c098aa21a5a6dacb54dcbc56 | 2026-09-30 | merge | 0 | MERGE-UNIQUE | integrate fix-merge-fix-merge-fix-merge-fix-round8-selfhost |
| recover-93cdc68cf | 93cdc68cf9518441273b4fb5cab1a4e9a424eb22 | 2026-10-30 | merge | 0 | MERGE-UNIQUE | integrate fix-red-fix-red-fix-red-fix-red-fix-merge-fix-leftover-fix-s |
| recover-46a832e21 | 46a832e21749f30d6a8974773ef1d09d45e9c3f7 | 2026-10-30 | merge | 0 | MERGE-UNIQUE | integrate fix-red-fix-red-fix-red-fix-merge-fix-leftover-fix-screen-pe |
| recover-9d6245867 | 9d6245867bf3a8486836d90aa3da2d54253ea605 | 2026-10-30 | merge | 0 | MERGE-UNIQUE | integrate fix-red-fix-red-fix-merge-fix-leftover-fix-screen-perf-modul |
| recover-11870fed2 | 11870fed2e46a932f781e9cc54340f16c35cdda3 | 2026-10-30 | merge | 0 | MERGE-UNIQUE | integrate fix-red-fix-merge-fix-leftover-fix-screen-perf-module-walk |
| recover-1945a1a1c | 1945a1a1c4463d7955c5c05277b467a43c487a0c | 2026-10-30 | merge | 0 | MERGE-UNIQUE | integrate fix-red-fix-merge-fix-leftover-fix-screen-perf-module-walk |
| recover-61650970f | 61650970fc0f3d8061ae0060f88d79b900fccd30 | 2026-10-30 | merge | 0 | MERGE-UNIQUE | integrate fix-merge-fix-leftover-fix-screen-perf-module-walk |
| recover-f4e5261e8 | f4e5261e84290bcff11252e118844e1ce0a5be81 | 2026-11-01 | merge | 0 | MERGE-UNIQUE | integrate bug-codegen-dict-slot-read-loses-its-val-8899 |
| recover-b2d75f501 | b2d75f5011562623fba84215bc245242319b04a1 | 2026-11-01 | merge | 0 | MERGE-UNIQUE | integrate bug-codegen-dict-slot-read-loses-its-val-8246 |
| recover-f899f9d06 | f899f9d0674c3462dfba39b4c6dbe136a953b5ef | 2026-11-01 | merge | 0 | MERGE-UNIQUE | integrate fix-merge-bug-codegen-dict-slot-read-loses-its-val-6152 |
| recover-d901fb1bf | d901fb1bf4136e29b4af93b8b9dc3733b7a3bb08 | 2026-11-01 | merge | 0 | MERGE-UNIQUE | integrate fix-red-bug-codegen-linked-list-reflection-and-s-4681 |
| recover-5df6dbcf0 | 5df6dbcf08d5841240d01f4bb7ea2ba20f27ae54 | 2026-11-01 | merge | 0 | MERGE-UNIQUE | integrate bug-codegen-linked-list-reflection-and-s-4681 |
| recover-ef17e3c53 | ef17e3c53915be1cfe678a593fea9af3e782623d | 2026-11-01 | merge | 0 | MERGE-UNIQUE | integrate bug-codegen-dispatched-for-loop-shares-o-2362 |
| recover-ba2b61aee | ba2b61aeec7009fa92b3a9fc39e121ae8c896571 | 2026-11-02 | merge | 0 | MERGE-UNIQUE | integrate fix-merge-bug-codegen-dict-slot-read-loses-its-val-9672 |
| recover-762ecad4a | 762ecad4a6d8d732581b88758c96ad1f9e65db24 | 2026-11-02 | merge | 0 | MERGE-UNIQUE | WIP on work/ann: 4595162d6 wip marker (do not clean) |
| - | e25a7f4df35f63f5aade8ca6d343a1e93a7497c5 | 2026-10-30 | commit | 0 | NONMERGE-EMPTY | WIP: CODEGEN_generator_function_Lib_enum |
| - | 3eeb00c9eb7ccdf01abd42d498449e002b2b3df7 | 2026-10-30 | commit | 0 | NONMERGE-EMPTY | WIP: CODEGEN_generator_function_Lib_glob |
| - | f80f4e135bf8d60629291a24bc4d65c6afcf1ee4 | 2026-10-31 | commit | 0 | NONMERGE-EMPTY | WIP closure gen |
| - | 48254eabac46202d989d54104671109ee35d1fb2 | 2026-10-31 | commit | 0 | NONMERGE-EMPTY | WIP recursive kind |
| - | da03e31bd77e9a8d1307f28f9df649919f31a79c | 2026-10-31 | commit | 0 | NONMERGE-EMPTY | WIP glob3 |
| - | ecf7e885b7a94ab12479215d6ac3fa98299beff1 | 2026-10-31 | commit | 0 | NONMERGE-EMPTY | WIP: glob dyn-word params / yield from tagged |
| - | 97adcc14975b98c2a7a0f3abb60e25e19d9c15ea | 2026-11-01 | commit | 0 | NONMERGE-EMPTY | chk |
| - | ac0bf4add93aaa65de9cf0e98ba37709dbae9d08 | 2026-09-29 | commit | 2 | NONMERGE-ON-MASTER | One memoryview attribute table, shared by both spellings of the question |
| - | ff352a11367d6a439f190b82f34e03b52941dc30 | 2026-10-01 | commit | 1 | NONMERGE-ON-MASTER | codegen: rfind/index/rindex on a boxed receiver are string methods |
| - | 1b02d00b8e1abdf7e11f9fdd6e13173968ab36c2 | 2026-10-05 | commit | 7 | NONMERGE-ON-MASTER | Contract examples, and two defects the examples found in the run-time lowering |
| - | c77680bbf906f61ffb17a62c9222aa7d1aec4e66 | 2026-10-05 | commit | 4 | NONMERGE-ON-MASTER | Two docstrings that pointed at a limitation and a symbol that no longer exist |
| - | e3bb4c232cbbac8a417c962de611af22fa3aa2e6 | 2026-10-07 | commit | 1 | NONMERGE-ON-MASTER | formal: pin the raise exit's flush and delete the fixed doc |
| - | a93bf343a1b5f18a0115cc06fad204a30db30ae7 | 2026-10-12 | commit | 2 | NONMERGE-ON-MASTER | formal hostmods: `stat_dev` reads `st_dev` as the signed field it is |
| - | f2432dabe05dc562f229d68422aaa008ba1a2e96 | 2026-10-12 | commit | 1 | NONMERGE-ON-MASTER | formal: delete the arm64 compiler-trap/getrlimit doc — both halves fixed |
| - | e027087392db63e9e8e6a41169e22ee3a3944297 | 2026-10-24 | commit | 2 | NONMERGE-ON-MASTER | formal host import shapes: the tree's last dead host import is a stale `unittest.mock`, so the ratchet goes green and its bug doc is deleted |
| - | 7b8cedafbb5b4c76a95f31d558483af26065c1d5 | 2026-10-25 | commit | 1 | NONMERGE-ON-MASTER | codegen: the re.sub-callback scanner missed  forms, so the callback's static handle was never declared — the row-24 class-A _mojo_cb_ undeclared at glob.py:101:10 |
| - | 316b1d4daaba77e913273d47de7d80bea95efd3a | 2026-10-26 | commit | 2 | NONMERGE-ON-MASTER | bug-codegen-callable-return-type-lost-at-8777: remove fully-fixed doc, add pinning test |
| - | aa94466faff12fc200fe99197b8966f47de2d5b0 | 2026-10-29 | commit | 3 | NONMERGE-ON-MASTER | Fix cross-module async result kind: register kinds from closure_stmts |
| - | 83a26ac0a8784e3b6a851d8caf83f3cf5fcbf1e3 | 2026-10-29 | commit | 2 | NONMERGE-ON-MASTER | Fix cross-module async result kind: register kinds from closure_stmts |
| - | b5cfa3812012fd1f2f0b8bd16519ee163f807856 | 2026-10-30 | commit | 2 | NONMERGE-ON-MASTER | Fix: capturing nested def returning float truncates at the bound-method call site |
| - | b8f5a4e4c457bc803a4c136cef5fbba21fdab486 | 2026-10-31 | commit | 3 | NONMERGE-ON-MASTER | suite: a dependent waits for every job of a fanout dep, not the first; names the pending dep |
| - | c5e1684e9d4e5f74ec58f5135779f467a3b73591 | 2026-10-31 | commit | 2 | NONMERGE-ON-MASTER | bug-codegen-dylib-generic-inline-copies-370: extend seed to enqueue fn roots with type params |
| - | cef79769faf8e2deb8c540da7f18663621704578 | 2026-11-01 | commit | 3 | NONMERGE-ON-MASTER | a nested-def-captured bool local prints as True/False (the box hid its bool-ness) |
| - | 2ababa9380a966f815292c6f20682c1965eaca20 | 2026-11-01 | commit | 1 | NONMERGE-ON-MASTER | codegen: A3 stack-switch resume always passes mojo_box_none, not 0 |
| - | 3ea8f1c78648c9c62cadc7d7d3573fa01976c4d8 | 2026-11-01 | commit | 1 | NONMERGE-ON-MASTER | Retire stale mixed-yield refusal test |
| - | c48d997668cb264727d274a8854626af8eaeb4f3 | 2026-11-01 | commit | 1 | NONMERGE-ON-MASTER | fix: use boxed word accessor for yield-from of word-list functions |
| - | 3217cbdef96a356832b0a9415f2afe93867b7696 | 2026-11-01 | commit | 2 | NONMERGE-ON-MASTER | Fix CODEGEN_cpp_path_refuses_expression_position_yield: implement statement-level conditional lowering for yields in and/or/ternary; delete fixed doc |
| - | 4c1088fd53026f29698bc405753564e69c324664 | 2026-11-01 | commit | 1 | NONMERGE-ON-MASTER | Add regression test for conditional yield cpp lowering |
| - | cfc09afa48b270807c2448421076a6fe0e71fdfa | 2026-11-02 | commit | 2 | NONMERGE-ON-MASTER | fix: allow same-module class decorators in decorator rebinding and exemption |
| - | 382f468b72e6e032118fb28271458e094f81c964 | 2026-11-02 | commit | 5 | NONMERGE-ON-MASTER | fix: bytes-pattern glob via word os.path and call-site bytes param typing |
| - | 225f6674794852dce76465cdf9fb956ba09f24b0 | 2026-11-02 | commit | 3 | NONMERGE-ON-MASTER | fix: resolve scalar arity max/min params not treated as containers in link mode |
| - | cf1c9dbda96b22ebf69334bcc69618bae1fdcbd5 | 2026-09-02 | commit | 2 | NONMERGE-ON-MASTER(patch-id) | determinism: mojo_compiler.py --dump is byte-reproducible self-hosted |
| - | 3bfb29a0515cb6bbf63f89ba36a961e28d519715 | 2026-09-06 | commit | 6 | NONMERGE-ON-MASTER(patch-id) | codegen: bytes-typed struct fields + var/local-seeded return inference |
| - | 1c0ae9f37492705179c3113b51cfaee001ce531b | 2026-09-06 | commit | 3 | NONMERGE-ON-MASTER(patch-id) | codegen: bytes default parameter miscompile -- b\x27...\x27 default must type the param MojoBytes* |
| - | b757b10e67a33ce0e4bbb3249e9b1f14e3682ac0 | 2026-09-25 | commit | 2 | NONMERGE-ON-MASTER(patch-id) | x86-64: generalise the register-register ALU and movzx, clearing 54 blockers |
| - | 01d74e95a632dfc955514bc3345c5f26a3b351ff | 2026-09-29 | commit | 6 | NONMERGE-ON-MASTER(patch-id) | formal: the returned-frame convention — a caller-provided block for a frame a function hands back |
| - | 7751baa0ed52b50770ce7d9aea23d0d00b950a2e | 2026-09-29 | commit | 1 | NONMERGE-ON-MASTER(patch-id) | formal: a specialization call's root is a callee, not a read |
| - | bf9410bff8c0efb912a93209d8a0cd7d2500ede7 | 2026-09-29 | commit | 12 | NONMERGE-ON-MASTER(patch-id) | formal: move the backend's own os/sys/struct modules out of the repo root |
| - | ead8accc4c6b479021bb0a9a6649dbbe9b08fc6f | 2026-09-30 | commit | 5 | NONMERGE-ON-MASTER(patch-id) | formal: a string inside a module-global container is the INTERNED literal, not a copy |
| - | d5fa985cc14dd38a585b7511128006f145961eb8 | 2026-10-01 | commit | 5 | NONMERGE-ON-MASTER(patch-id) | codegen: an env field's C type is the FIELD's, not the capture's |
| - | 3d3447d3b87ffc0d2b675c9021b8a2c72cddf82b | 2026-10-01 | commit | 4 | NONMERGE-ON-MASTER(patch-id) | formal: the struct suite's flake was a half-published library, not a flaky struct table |
| - | c9d1636001237306eb48e6359fdbb0265af4b956 | 2026-10-01 | commit | 1 | NONMERGE-ON-MASTER(patch-id) | test_runtime_header_scan: 539 -> 541, the three other branches' entry points |
| - | cff703aa4e2601958420fda0e934ec85a8659176 | 2026-10-01 | commit | 2 | NONMERGE-ON-MASTER(patch-id) | formal_sweep_causes: the second split of `other refusal` — 50 -> 4 on arm64, 104 -> 4 on x86-64 |
| - | 1e21de376ca8f4dffaf68a901099a06ec0edd3c5 | 2026-10-01 | commit | 2 | NONMERGE-ON-MASTER(patch-id) | codegen: scope the per-slot-kinds marker to the function that set it |
| - | f2f7b7d2508a7ed1e2893c4a21dc904ccb10f7df | 2026-10-02 | commit | 14 | NONMERGE-ON-MASTER(patch-id) | The dangling-citation corpus could only grow, and that was the missing check |
| - | a06991d9d819ed36e6b6c41fc5cd82552f69abf4 | 2026-10-02 | commit | 11 | NONMERGE-ON-MASTER(patch-id) | One implementation per fix: the merged tree had two lowerings of each, and only one of each pair was reachable |
| - | 878f0f639ee29afd69030b3b972f5510b73bc7c1 | 2026-10-03 | commit | 7 | NONMERGE-ON-MASTER(patch-id) | formal: d[k] = v for an absent key is CPython's INSERT, on both backends |
| - | ef5ef46f7d052ee996f29b581229929f46737676 | 2026-10-03 | commit | 4 | NONMERGE-ON-MASTER(patch-id) | tempfile: `mkdtemp` is one `mkdtemp(3)` call, so it can tell a collision from a failure |
| - | 0daae1d2de5e0d9290cee7f887f0211f4604fa3b | 2026-10-03 | commit | 6 | NONMERGE-ON-MASTER(patch-id) | formal: em-dashes in the three new modules docs, not the six-character sequences |
| - | 227fd9ae28dddd074712dd663149ffa5d178267b | 2026-10-03 | commit | 1 | NONMERGE-ON-MASTER(patch-id) | bugs: the host-import row re-measured — eleven of thirteen rows are closure, and `glob` is the only one left |
| - | 9644b4f97858dbbc4c8d15726b062105f7232d13 | 2026-10-03 | commit | 1 | NONMERGE-ON-MASTER(patch-id) | formal: `html` — escape, the 1132 answers a five-replacement function can be wrong about |
| - | 199c23154d3149642855c3a061548c2715521fd6 | 2026-10-03 | commit | 1 | NONMERGE-ON-MASTER(patch-id) | formal: `html` — escape, the 1132 answers a five-replacement function can be wrong about |
| - | 69f66b883eff02f241bb8795876d3ab8e186e78f | 2026-10-03 | commit | 1 | NONMERGE-ON-MASTER(patch-id) | bugs: the host-import row re-measured — eleven of thirteen rows are closure, and `glob` is the only one left |
| - | 23b03160fa562d60515ed0961df2c041214c65b5 | 2026-10-03 | commit | 1 | NONMERGE-ON-MASTER(patch-id) | bugs: the host-import row re-measured \u2014 eleven of thirteen rows are closure, and `glob` is the only one left |
| - | 0e3e0f527333a9493e01273511d426de4d2db11f | 2026-10-03 | commit | 2 | NONMERGE-ON-MASTER(patch-id) | formal_sweep: read the third import wording, and the host module's TIER |
| - | 3a8c4453cc17d18937710c3dbbdfbee95911ff3e | 2026-10-03 | commit | 3 | NONMERGE-ON-MASTER(patch-id) | formal: a `**` spread is a MAPPING, not a positional — and a literal one works |
| - | 1b0c1ec8fd198ae4df76acc10beb3edfa820b0e5 | 2026-10-03 | commit | 3 | NONMERGE-ON-MASTER(patch-id) | formal: a `**` spread is a MAPPING, not a positional — and a literal one works |
| - | 5174e0e2503c317c59045be40946354b0a6b53e9 | 2026-10-03 | commit | 3 | NONMERGE-ON-MASTER(patch-id) | formal: a `**` spread is a MAPPING, not a positional — and a literal one works |
| - | 398af7eedd3cd91b353c3c83c82d55e03de01f70 | 2026-10-03 | commit | 3 | NONMERGE-ON-MASTER(patch-id) | formal: a `**` spread is a MAPPING, not a positional \u2014 and a literal one works |
| - | 657700320e7a7efaf53d7f185eac3f1bdb2b33ff | 2026-10-03 | commit | 8 | NONMERGE-ON-MASTER(patch-id) | bugs: both blob docs are fixed by the refusal and the corrected declarations |
| - | 4cb92c6f2d0c47d2906ae2e9df23d26a1685d76b | 2026-10-03 | commit | 6 | NONMERGE-ON-MASTER(patch-id) | formal_sweep: -t is a bound PER POPULATION, and the report says which one a file hit |
| - | e68619607ad62cba03ff9aedd5caa5fdff611eb8 | 2026-10-03 | commit | 4 | NONMERGE-ON-MASTER(patch-id) | formal: an ambiguous method name is settled by the RECEIVER's own binding, not refused |
| - | d806a5e49c9fb92fc136d95492bccb80892499ca | 2026-10-04 | commit | 1 | NONMERGE-ON-MASTER(patch-id) | sweep b12: the map's numbers, re-derived per file and corrected |
| - | 6c6af116a1d01b34aa1c522c25a838ee2da17586 | 2026-10-04 | commit | 10 | NONMERGE-ON-MASTER(patch-id) | a raise a try cannot catch is refused, by name, before anything is emitted |
| - | 59fcc1686bcc4998309e3112a1a9abd6da16974a | 2026-10-04 | commit | 3 | NONMERGE-ON-MASTER(patch-id) | rm bugs/PERF_struct_field_split_asked_once_per_function (doc deleted): every residue it named is closed |
| - | cd35c500bf9a66191a90a898ba2aaa0c44f2471d | 2026-10-04 | commit | 7 | NONMERGE-ON-MASTER(patch-id) | formal: file the four arm64 model findings the fuzzer could not close |
| - | 4a40d00e5943bb033987a33e71415ae75c9bd563 | 2026-10-05 | commit | 5 | NONMERGE-ON-MASTER(patch-id) | test_formal_loop_invariants.py + tools/formal_loop_invariants_baseline.json: the oracle, the synthesis, the discharge, and what rejects a wrong invariant |
| - | 3b6541db84d5aafd4bac4a3ded5556443c73c5db | 2026-10-05 | commit | 2 | NONMERGE-ON-MASTER(patch-id) | with: refuse an `as` clause that is not a bare name, and stop blaming the wrong dunder |
| - | 75d1326b339536816cac7812acb7dd8f1a9afa88 | 2026-10-05 | commit | 4 | NONMERGE-ON-MASTER(patch-id) | re: the SCOPED inline flag form `(?i: … )` is compiled, per-node flags |
| - | fbe521a0f15f9b25ac0ef081a31ed15cca32edc0 | 2026-10-05 | commit | 44 | NONMERGE-ON-MASTER(patch-id) | 44 new formal examples: one per codegen path the 52-example corpus had none of |
| - | 7284a86f6487dfa3d40d8248688fa3fa85fc4931 | 2026-10-05 | commit | 3 | NONMERGE-ON-MASTER(patch-id) | Two stale pins the batch inherited, and the coverage hole one of them sits in |
| - | c680fd8a0c9f42ffc957e7974591607e2cea6e78 | 2026-10-05 | commit | 5 | NONMERGE-ON-MASTER(patch-id) | re: the SCOPED inline flag form `(?x: ... )` compiles and matches |
| - | 4821b868ce87b574f7bb07f1269af1601cffebd3 | 2026-10-07 | commit | 4 | NONMERGE-ON-MASTER(patch-id) | formal139-docs: the two five-red-rows docs are resolved; delete them |
| - | 031ece4cc345ac8cf10f28e13f159283878da164 | 2026-10-07 | commit | 2 | NONMERGE-ON-MASTER(patch-id) | test_formal_call_proof_gen: the div0 guard class fails by NAME when its own mechanism did not fire |
| - | 1883edabcd345db747a80895bdbcfbc4c9ffdb62 | 2026-10-08 | commit | 3 | NONMERGE-ON-MASTER(patch-id) | formal: pin that a Lean bound breach is never written to the verdict cache |
| - | b011fc717add9169f5bdd15b04ef48b79dc95ca9 | 2026-10-08 | commit | 1 | NONMERGE-ON-MASTER(patch-id) | bugs/OPEN_WORK.md: regenerate the doc index after the two retirements |
| - | 37b2388ca606d34f3346aad8213892b23496989d | 2026-10-08 | commit | 3 | NONMERGE-ON-MASTER(patch-id) | formal: a literal container's emptiness decides a for target, and a spread's by its literal operand |
| - | 9a1233c39d27742066a2a4542a6c33ca565ae702 | 2026-10-08 | commit | 5 | NONMERGE-ON-MASTER(patch-id) | formal imports: the export-rule refusal names the ONE rule, or 'no such name' |
| - | 1b85ce2b8f195a3ebe2a2fb3819636ccbf183e7e | 2026-10-08 | commit | 2 | NONMERGE-ON-MASTER(patch-id) | formal: a one-field struct returned from a function is its field |
| - | 2ca8791efe255678e561730a58aa925a0917df73 | 2026-10-08 | commit | 2 | NONMERGE-ON-MASTER(patch-id) | arm64 proofs: the sign-extend decision reads the immediate's OWN sign bit |
| - | d1cb94d81fb6075e7e56cd942dcaa888249d9472 | 2026-10-09 | commit | 6 | NONMERGE-ON-MASTER(patch-id) | formal: imported-callee refusal names the ONE export rule that applied |
| - | 70852b9cad586c7b4a632eb766efbd70c1f2b097 | 2026-10-10 | commit | 11 | NONMERGE-ON-MASTER(patch-id) | bugs: delete the two settled std-os-io scope audits; every item closed |
| - | da4f5f956111754eece42a4f038457a8b02883f8 | 2026-10-12 | commit | 5 | NONMERGE-ON-MASTER(patch-id) | formal: a set literal's word-canonical duplicates are dropped, so len agrees with CPython |
| - | f46f029138945f8cc536ed170614b24dc0bca83d | 2026-10-12 | commit | 1 | NONMERGE-ON-MASTER(patch-id) | bugs: module_state §(3)'s `len()` remainder is closed, and the paragraph was false |
| - | d3a41b59435fe6e47f5a13fe2f61f50b4f470f4b | 2026-10-12 | commit | 9 | NONMERGE-ON-MASTER(patch-id) | formal/arm64 proof gen: the SP trackers dropped the frame's `sh` bit, so four dec1 examples admitted |
| - | 6eca3857d00be21f37f5d2f86ac69ab54795a5b0 | 2026-10-13 | commit | 4 | NONMERGE-ON-MASTER(patch-id) | formal build: a local bound from a zero-field struct's constructor joins the receiver-binding table |
| - | 4ecbff681205728a8ce48010ba9c69188597eed9 | 2026-10-13 | commit | 2 | NONMERGE-ON-MASTER(patch-id) | arm64 proofs: delete the immediate-on-the-left doc, fixed on master by 6b072096 |
| - | b0ea467c86ee46a389117ff556c84589d25a1025 | 2026-10-13 | commit | 3 | NONMERGE-ON-MASTER(patch-id) | formal: an external_call pointer result is a POINTER_KIND, not an int; unshadow SET_ALGEBRA_OPS |
| - | 2d0fd8d2bcf01c3f49667300127230d8b1b176c9 | 2026-10-13 | commit | 6 | NONMERGE-ON-MASTER(patch-id) | formal: \`for a, *rest in …\` binds the rest tail on BOTH backends |
| - | bac22b2d85fc77b9b78a761f4a13435e6aadb45b | 2026-10-13 | commit | 3 | NONMERGE-ON-MASTER(patch-id) | formal_metamorph: swap_add's operand predicate was declining decidable programs |
| - | e7365ebb6c0450c930078afa70904ebbe6dcbd7d | 2026-10-13 | commit | 1 | NONMERGE-ON-MASTER(patch-id) | formal: SET_ALGEBRA_OPS was bound twice, silently shadowing the first |
| - | 7073e33a9e42d232735b5e3e4d525023764b5195 | 2026-10-24 | commit | 3 | NONMERGE-ON-MASTER(patch-id) | scanner: the importer's text scan registered a nested `def` as a module-level function export, and the 0-arg prototype it produced for an unannotated param is the `os_fsdecode`/`os_fsencode` class on rows 10/24/25 — `too many arguments to function 'os_fsdecode'; expected 0, have 1` at Lib/ntpath.py:317/373/387/461 and Lib/posixpath.py:266/278/325 (27 error lines in build/remes/r24post_kwfix.log, 14 in r25post_kwfix.log; the standalone ntpath dump pair build/remes/fsdec_ntpath_prefix_6b80a973.ci / fsdec_ntpath_postfix_5ad80ae8.ci shows `extern int64_t os_fsdecode (void);  /* from os */` + 13 direct calls). Root cause, measured: `fsencode`/`fsdecode` are nested defs inside a factory in Lib/os.py (`def _fscodec(): ... def fsdecode(filename): ...`), bound at module level by `fsencode, fsdecode = _fscodec()`; `_scan_source` in module_loader.py stripped every line before matching, so the nested def registered as a top-level export, and its param extraction keeps only ANNOTATED params (`if ':' in param`) while stdlib's nested defs are unannotated — the entry came out `int64_t fsdecode (void)`. The prototype was doubly wrong: the C function a nested def compiles to is named after the ENCLOSING function (`closure_lifted_name`: `outer_inner`), so the `module_name` symbol the extern names does not exist at all — the module-level binding is a VALUE, and its cross-module call belongs to the fallback path. The fix is the indent block stack in `_scan_source`: a `def`/`fn` line whose innermost open block is a function body is a nested closure and is skipped; module-level defs under module-level control flow and class methods (innermost block 'other') register exactly as before, and the overload-COUNTING pre-pass is deliberately left byte-identical, so a module-level def that merely shares a name with a nested one keeps its measured variadic treatment. Blast radius measured, not inferred: on Lib/os.py the scan went 61 → 55 entries and the six removed are EXACTLY the six indented defs (`fsdecode`, `fsencode`, `encode`, `decode`, `encodekey`, `check_str` — each verified indented in the source), with nothing added; and a cross-module STATIC call to a nested def could never have linked pre-fix (the symbol does not exist under the advertised name), so no previously-working behavior moves — the affected population was already-broken code, now on the loud fallback. Post-fix the `os.fsdecode(name)` call sites lower to the weak "unavailable in compiled mode" stub (`__attribute__((weak)) int64_t fsdecode (...)` — a per-call `mojo_print("fsdecode: unavailable in compiled mode")` + return 0): loud, not a silent fold, and rows 24/25 die at gcc long before the runtime is reached. Measured fails-before (the pre-fix tree, 8 GB ceiling): the minimal 2-file same-name-shadow shape — `def _mk(): def f(x): ... return f` / `f = _mk()` / `import a_os; print(a_os.f(41))`, the exact os.py shape — dies at gcc with `too many arguments to function 'a_os_f'; expected 0, have 1` (build/remes/fsdec_osname_prefix_765117ff.log), verified on the driver path too (the pre-fix worktree's own _build_and_run raises at the gcc step). Three-row verification (uniform fixed compiler + kw63 fix + this fix, like-for-like single-file builds into build/remes/): row 24 (zipfile) first gcc error UNCHANGED at ntpath.py:287:9 (implicit declaration of `abspath_9f63a2`), the fsdecode class 27 → 0 error lines, gcc lines 329 → 302, rejections unchanged (62, first byte-identical: the `_collections_abc` generator `.close()` class), 2.5 → 2.6 GB; row 25 (mailbox) first gcc UNCHANGED at reprlib.py:71:7, the class 14 → 0, gcc lines 273 → 259, the calendar.py:663 persistence unchanged (9 lines), rejections unchanged (68), 3.0 → 3.0 GB; row 10 (ctypes/util.py) is UNCHANGED in its own blocker — the import-closure phase still breaches the ceiling (9.6 → 8.2 GB, run-to-run variance, both > 8.0), 34 module rejections both runs, gcc never runs — the fsdecode class it names downstream of the kill is what this fix removes (the ntpath/posixpath TUs in its closure emitted the class; the ntpath dump pair above shows it gone). Post-fix runtime of the minimal shape, measured and named as the next blockers rather than papered over: (1) the same-name shadow (the exact os.py shape) builds and its enclosing `return f` resolves to the module GLOBAL `f` — its own still-zero global; the emitted C shows `_mk` reading `_root_globals.f` — and the call segfaults (rc -11, no output): a separate NAME-RESOLUTION defect (local nested def vs module global of the same name), pinned as measured behavior; (2) the non-shadow shape (`g = _mk()`) stays on the loud dispatch refusal (`Unhandled exception: NotImplementedError: ... module 'a_ns' is not compiled into this binary`, exit 1, stderr) — the function-object value class is not wired cross-module; CPython prints 42 for both, and a fix that compiled either to a quiet 0 would be the row-10-fold false-green. New regression test_link_mode.py::test_nested_def_is_not_a_module_level_fn_export pins: the scan of the exact os.py shape must not export the nested `f` (and must still export the module-level factory `_mk`, a def under module-level control flow `ctrl`, and a class method `C.m`); the same-name-shadow build must exist (binary present) and crash loudly with no output (rc -11 — the measured shadowing class; the pin marks a known-bad loud outcome and must be re-measured against CPython the moment the shape stops crashing); the non-shadow shape must stay on exit 1 + the loud stderr refusal. 53-job gate under /opt/local 3.14.8: 53 passed / 0 failed / 0 skipped with the fix in tree. The first gate run this session was 51/53, and BOTH failing jobs were this commit's own bookkeeping, not the scanner fix: (1) doc-refs — a comment in this commit's test_suite.py delta spelled the `FORMAL_x` placeholder in its dot-md form, and the ratchet reads this very file, so the comment itself was the 7th prefixed citation in test_suite.py (baseline 6): the same trap the owner's control.py line hit; the comment now names the placeholder without spelling it, and the ratchet exits 0. (2) suite-self-test — the new test's non-shadow stderr probe adds a `timeout=` keyword call, which the STALE_PER_CHILD_BUDGETS residue census counts: test_link_mode.py 2 -> 3, updated with a dated comment. Direct re-verification before the green gate: the ratchet exits 0 and test_suite.py 374 passed / 0 failed. test_suite.py is in this commit for exactly those two bookkeeping lines (its census row plus that comment) and nothing else. The row-10 doc and the rows 10/24/25 roadmap blocks carry the dated measurements (working tree, per the campaign's append-only pattern). |
| - | fb5ae58adf1ea2719d0cd3a2633b073a46c6578f | 2026-10-26 | commit | 1 | NONMERGE-ON-MASTER(patch-id) | codegen: emit generator typedef ahead of method prototypes (row-25 entry C cascade) |
| - | 0db0faf191c867f1553e21d5e224fb095c76eb50 | 2026-10-27 | commit | 1 | NONMERGE-ON-MASTER(patch-id) | gate fixups: suite-self-test residue census to the walk (test_formal_admitted.py dropped, test_container_constructor_arg_um.py 0 -> 1) |
| - | 52085495fb02ad8db67aaf09a015e4c12dd3720b | 2026-10-27 | commit | 1 | NONMERGE-ON-MASTER(patch-id) | gate fixups: no-new-casts baseline 26 -> 27, the generated repr's bytes arm (a0790e16f, in via the 768dea0e1 merge) |
| - | 7c10dc6f2d9aa05253a32f863520aec00f5fc477 | 2026-10-27 | commit | 3 | NONMERGE-ON-MASTER(patch-id) | regRESSION fix: proof verdict key fully keys on lib_dir and proof directory |
| - | 8c0e0444f4d547da342d0b2a28f114ebd20eb6b3 | 2026-10-29 | commit | 29 | NONMERGE-ON-MASTER(patch-id) | docrefs: rewrite the citations of deleted docs that merges added, and ratchet down |
| - | aaf57f39591efce7e9fa5a0e25e2603073b18baf | 2026-10-29 | commit | 4 | NONMERGE-ON-MASTER(patch-id) | File the coroutine element and kwargs gaps; record the contextlib status |
| - | 937dbd654cb952db2f5486620b9b8e4ee0b289a3 | 2026-10-29 | commit | 10 | NONMERGE-ON-MASTER(patch-id) | Fix PERF_struct_self_assign_scan_uncached: memoize self-assign scan and self-reads |
| - | c47a8fd2b65ffaf45538dab57fdc0508fc579009 | 2026-10-31 | commit | 2 | NONMERGE-ON-MASTER(patch-id) | perf: memoise realpath in the selfhost-source predicates (realpath 6.7% -> 1.1% of the fire.py compile); test_selfhost 3/3 |
| - | 9782f00a37b16a7083941d451210d316472f2295 | 2026-10-31 | commit | 3 | NONMERGE-ON-MASTER(patch-id) | codegen: struct method signature registration is idempotent per overload id (retried module no longer multiplies methods into fake overloads) |
| - | ca92cdddf9db49846683ed446d10844e15a7ead1 | 2026-10-31 | commit | 3 | NONMERGE-ON-MASTER(patch-id) | codegen: a module-scope binding of a builtin name (repr = aRepr.repr) shadows the builtin; module-scope bound-method globals keep their return type |
| - | 04b7bf870ea2085851d42e4092cd94ed4f60c3bf | 2026-11-01 | commit | 10 | NONMERGE-ON-MASTER(patch-id) | gen.gi_frame is a frame object; clear() refuses a suspended generator frame |
| - | 5d683ad64ce562d5ec23f5a6b3c8a51f1e6f3b79 | 2026-11-01 | commit | 7 | NONMERGE-ON-MASTER(patch-id) | frame.clear() refuses an executing frame; frame activations carry an identity |
| - | 8fa752969d416248e47bf9950301b5129b7819b0 | 2026-11-01 | commit | 4 | NONMERGE-ON-MASTER(patch-id) | mojo_bytes_from_str callers pass errors (self-host was red); frame doc status |
| - | 4605292aa891cf12fe173462d54f62ebab9f075a | 2026-11-01 | commit | 5 | NONMERGE-ON-MASTER(patch-id) | generator frames: a coroutine yield detaches its frame/cleanup records, resume re-pushes them; frame name is the source function's |
| - | 8ac1bb99e8a29d34a214cf22f8b1fd78c60371c5 | 2026-11-01 | commit | 5 | NONMERGE-ON-MASTER(patch-id) | generator frames: a coroutine yield detaches its frame/cleanup records, resume re-pushes them; frame name is the source function's |
| - | 684fa1a9a5ffe6d785ccf7ef28dc7732b00feca3 | 2026-11-01 | commit | 4 | NONMERGE-ON-MASTER(patch-id) | print() of a user struct uses __str__/__repr__; namedtuple typename may differ from bound name; functools walls recorded |
| - | a04243c898f1e9b040348df62a82b8a3fc695a8d | 2026-11-01 | commit | 5 | NONMERGE-ON-MASTER(patch-id) | property getter reads call the getter; @x.setter becomes a callable setter; mailbox doc |
| - | 9e142f899edea97e5dde3508e797b87981973425 | 2026-11-01 | commit | 5 | NONMERGE-ON-MASTER(patch-id) | nested class methods capture enclosing locals; user-struct ordering dunders dispatch; delete fixed doc |
| - | 7f7eb289688050047ac6edc19ccb1eba9d66ddaa | 2026-11-01 | commit | 4 | NONMERGE-ON-MASTER(patch-id) | match: or-patterns in Python sources; return type inferred through match arms and loop else clauses |
| - | f454765a08773b46ae924c158eb82d0b8c7a3b48 | 2026-11-01 | commit | 7 | NONMERGE-ON-MASTER(patch-id) | for over a call through a function value (callable param / loop var) + tuple slot kinds for tuples with None; census synced |
| - | c0114c7a0e904672cc20ef4b552b9f036045143d | 2026-11-01 | commit | 7 | NONMERGE-ON-MASTER(patch-id) | wip: dynamic for over a call through a function value, tuple slot kinds with None |
| - | e34253828a3219c09cd103bfc1f94f3c20af664d | 2026-11-01 | commit | 2 | NONMERGE-ON-MASTER(patch-id) | bugs: delete the cpp value-receiving-yield doc; file the two gaps it leaves |
| - | 67a261d9de3e55479b4eb0206c97ce8142c7b03c | 2026-11-01 | commit | 17 | NONMERGE-ON-MASTER(patch-id) | frames (stage 1): sys._getframe / f_back / f_lineno / f_code.co_name via a shadow frame stack, per module that says _getframe |
| - | a12540771106d978345369808dbc8bc7b6d44688 | 2026-11-01 | commit | 5 | NONMERGE-ON-MASTER(patch-id) | codegen: a capturing nested function used as a VALUE inside another nested function gets its env (sibling env from the current closure's env; value references join the shared-env call group) |
| - | f839521cc5a2d8e309d2f163d4f98656057b3648 | 2026-11-01 | commit | 6 | NONMERGE-ON-MASTER(patch-id) | coro: call the callsite visitors by name (a capturing closure passed on as a value from another closure has a NULL env: the self-hosted compiler crashed on every program with a call); test_selfhost compiles a call+f-string program; file the closure bug |
| - | 6c6fd8c545df892ab0a88eefa328e3f69f4bebee | 2026-11-01 | commit | 1 | NONMERGE-ON-MASTER(patch-id) | coro: callsite scan iterates _walk with an isinstance test per node (no cached helper-returned call list); keeps the lazy _static_env |
| recover-1b22f11c6 | 1b22f11c69d3bdd379432a6f62308a26703bff87 | 2026-07-16 | commit | 1 | NONMERGE-UNIQUE | Add enum keyword support as a mojo.py extension (mojolib BUG-2026-024) |
| recover-a40ce6a55 | a40ce6a5564507e5b2b5ef6fe4fdb48a56146099 | 2026-09-06 | commit | 1 | NONMERGE-UNIQUE | bugs: update zipfile Status -- os.path.splitdrive/splitroot + reversed() landed |
| recover-f04048b87 | f04048b87090fde422e105ea5fcce603b6a8da46 | 2026-09-15 | commit | 157 | NONMERGE-UNIQUE | Rename mojo.py to fire.py and mojo_compiler.py to fire_compiler.py across entire repository |
| recover-abf5638ba | abf5638ba35f40098fc7851dc9c115dcdba59e5f | 2026-09-25 | commit | 14 | NONMERGE-UNIQUE | formal: struct types, methods, and a one-word layout that actually works |
| recover-e552ae5d0 | e552ae5d006a495119a8df6141019cac5a429b74 | 2026-09-25 | commit | 6 | NONMERGE-UNIQUE | formal: widen the sweep, and stop the dylib path failing for the wrong reason |
| recover-0d71c2e43 | 0d71c2e434709fc6c61cb5507241e110296ddb55 | 2026-09-30 | commit | 1 | NONMERGE-UNIQUE | Move _static_arg_elems out from under the METHOD-half comment it was never about |
| recover-f563ac810 | f563ac8102f969bf9f705e460c590af78febf206 | 2026-10-01 | commit | 6 | NONMERGE-UNIQUE | tests: gate the fourteen registered tests nothing ran, and make an `expect=` marker's stated count checkable |
| recover-42f2531a3 | 42f2531a39c5e142f4f78fde8e1b7c18107e12ca | 2026-10-01 | commit | 18 | NONMERGE-UNIQUE | parser+codegen: a 1-tuple for-target and a parenthesised single name are two targets |
| recover-737b5b00e | 737b5b00e1657802222c409eb64d0ce34232885d | 2026-10-01 | commit | 3 | NONMERGE-UNIQUE | the 15 registered tests that no bucket ever ran, now run — and a check |
| recover-144a2b145 | 144a2b1455a92565f8aca121f4b19dc57baf75fa | 2026-10-02 | commit | 4 | NONMERGE-UNIQUE | formal: a dict from a CALL has a shape, and a string index against an unstated base is refused |
| recover-ba212ef21 | ba212ef2194aad0b810c1d4d87c6150b2415fa89 | 2026-10-02 | commit | 4 | NONMERGE-UNIQUE | A local rebound to two container kinds is the box in a closure too, and the box survives a hop |
| recover-791e53d7e | 791e53d7e04e1263f0dffa7c75b3b26d31410099 | 2026-10-02 | commit | 6 | NONMERGE-UNIQUE | A module global rebound inside a function has no single kind: box the field, keep the semantic |
| recover-6126ab815 | 6126ab8150a6cfea627d06c1d2eda25862918f38 | 2026-10-02 | commit | 3 | NONMERGE-UNIQUE | formal: the field-access refusal no longer claims a binding it cannot see |
| recover-511e44b01 | 511e44b0100c8e02ba671f2857b67cc537a2aec1 | 2026-10-03 | commit | 3 | NONMERGE-UNIQUE | formal: a subscript through an UNANNOTATED parameter takes the convention its call sites use, and a base declared an integer is refused |
| recover-7dfa6575f | 7dfa6575fe1348f3ace4b5fed7ead7379a6a3c66 | 2026-10-03 | commit | 6 | NONMERGE-UNIQUE | formal: a store into a module-owned blob is REFUSED, and so is an untyped one |
| recover-b20a4544b | b20a4544b25720336d6cf5281f9e12309e38fa09 | 2026-10-03 | commit | 2 | NONMERGE-UNIQUE | formal/imports: `html` has a tier now, so it leaves the UNCLASSIFIED row |
| recover-da444a039 | da444a0394a30485cfad58a134b46b8db0cb682a | 2026-10-03 | commit | 9 | NONMERGE-UNIQUE | formal: a dylib runs its module body at load time (`__init_offsets`/`.init_array`) |
| recover-8957d1231 | 8957d1231b4edb6ba12e6a420bbd1e003c03c34d | 2026-10-03 | commit | 3 | NONMERGE-UNIQUE | formal: a target query in a CLASS-LEVEL initializer is a query, not storage |
| recover-8b97ba5a2 | 8b97ba5a28c6362298e58b72e86b6e26047b90f2 | 2026-10-03 | commit | 6 | NONMERGE-UNIQUE | formal: a one-field mutator may not rebind its receiver to a name of its own type |
| recover-2a6572795 | 2a6572795d33e0287eb3d03de3f7359bf5ad0005 | 2026-10-03 | commit | 5 | NONMERGE-UNIQUE | formal: `recv.f()[k](x)` is the same call as `recv.f()(x)`, and is refused like one |
| recover-30acf7ed5 | 30acf7ed5222c72f9660a4b456cd8056a84e3b76 | 2026-10-04 | commit | 4 | NONMERGE-UNIQUE | bugs: the b11 formal sweep, both architectures, 722 files, no file unclassified |
| recover-84eccd26a | 84eccd26a93558b9f3a33a307f67e4135f68867d | 2026-10-04 | commit | 4 | NONMERGE-UNIQUE | bugs: the b11 formal sweep, both architectures, 722 files, no file unclassified |
| recover-88c2a1d21 | 88c2a1d2174308c9c357a7f61402be768eb8414d | 2026-10-04 | commit | 4 | NONMERGE-UNIQUE | formal_sweep: name string composition, the corpus's largest unowned row |
| recover-d7f5d7fbf | d7f5d7fbf1ba7b704b3b6320801d3f487747cb42 | 2026-10-04 | commit | 4 | NONMERGE-UNIQUE | bugs: the b11 formal sweep, both architectures, 722 files, no file unclassified |
| recover-38f84dbfc | 38f84dbfc99b93922a6f2b4ce7b9eb2ca8d4860b | 2026-10-04 | commit | 1 | NONMERGE-UNIQUE | tests: the stack-floor guard is pinned as what gates the x86-64 value theorem |
| recover-38c7c07f7 | 38c7c07f78a03ac1cb4a419cbdf8d8374b5c3108 | 2026-10-04 | commit | 2 | NONMERGE-UNIQUE | tests: the twelve red examples are eleven generations and one owned refusal |
| recover-202d50f5b | 202d50f5be9a105622e9e8601b82f70cae0c8ded | 2026-10-04 | commit | 1 | NONMERGE-UNIQUE | tests: the twelve red examples are eleven generations and one owned refusal |
| recover-e2391d64e | e2391d64eb9b2186eaae90087b72456458a2f812 | 2026-10-05 | commit | 6 | NONMERGE-UNIQUE | formal: a container ELEMENT the build can fold was refused as 'computed by a call' |
| recover-c61e17b65 | c61e17b652858a289e49047d330d2fb7cabd2bff | 2026-10-05 | commit | 2 | NONMERGE-UNIQUE | formal: the export gate's bare-call refusal names the method, on 133 of 145 |
| recover-89b504983 | 89b5049833d20895973a87da62d7ca07fc7ef55f | 2026-10-05 | commit | 9 | NONMERGE-UNIQUE | formal: a printf conversion that disagrees with its operand's kind is refused |
| recover-7e961fb7e | 7e961fb7e4f407ac978318306e56b3112f398266 | 2026-10-08 | commit | 1 | NONMERGE-UNIQUE | bugs: `stat_dev` is a 32-bit field read two ways, and test_formal_os_backing's oracle compares them with %d |
| recover-7ef0fea50 | 7ef0fea508ba3108e8389e9537306f8a85428fb5 | 2026-10-08 | commit | 5 | NONMERGE-UNIQUE | formal: a bare-literal comptime value parameter instantiates |
| recover-0937b30ee | 0937b30ee647a928b2afd94b243297605ec5f21f | 2026-10-08 | commit | 7 | NONMERGE-UNIQUE | formal: a starred for/comprehension target is refused by BOTH backends |
| recover-d54ca9e23 | d54ca9e2394947642842b755e12a515bdf09ce05 | 2026-10-08 | commit | 4 | NONMERGE-UNIQUE | formal: an f-string that interpolates nothing is folded, not refused |
| recover-47bde1508 | 47bde150845d1e0f12b541148d12b9bd5199a15d | 2026-10-08 | commit | 2 | NONMERGE-UNIQUE | formal: record that the div0 class's fixture now refuses to generate |
| recover-8a81db37e | 8a81db37ecf28550a29739d706faed9e32271422 | 2026-10-08 | commit | 7 | NONMERGE-UNIQUE | formal: x86-64 nested for/comprehension target unpack, via one shared target tree |
| recover-5f0525a37 | 5f0525a37e5195223f86eafcec9fabd827aa3117 | 2026-10-12 | commit | 1 | NONMERGE-UNIQUE | bugs: regenerate the formal doc index, which the new doc references moved |
| recover-5a505a741 | 5a505a741a993d294a2340cf4ed7152f89092ab7 | 2026-10-12 | commit | 5 | NONMERGE-UNIQUE | formal/arm64 proof gen: the SP trackers dropped the frame's `sh` bit, so four dec1 examples failed |
| recover-f19a3c4fe | f19a3c4feab8395bfe723213e140b0e41e3bba2f | 2026-10-12 | commit | 4 | NONMERGE-UNIQUE | formal/arm64: a length-changing slice store resizes the blob |
| recover-14065e4e2 | 14065e4e223e8fb053409ef47dd52b84a20c7b04 | 2026-10-12 | commit | 2 | NONMERGE-UNIQUE | bugs: module_state §(3)'s `len()` remainder is closed, and the paragraph was false |
| recover-48f0f9131 | 48f0f9131ba65ab70e7de77012a147ecfc68d2ce | 2026-10-12 | commit | 1 | NONMERGE-UNIQUE | docs: subprocess_run — option 1's real blocker is the return-type binding, measured |
| recover-bb2f36a71 | bb2f36a71b40ec39c0dd9176d2b30ca53b042afb | 2026-10-12 | commit | 3 | NONMERGE-UNIQUE | docs: fold the unreached-div0-residual doc into the division doc |
| recover-e0f2d2ce8 | e0f2d2ce884ea192e03c53cb3225f9a25d78fdfe | 2026-10-12 | commit | 2 | NONMERGE-UNIQUE | census: re-bank `fact`'s row after its source changed |
| recover-9ef31ad0d | 9ef31ad0d02c02ecfedbd938ffb4006e1fb81bf9 | 2026-10-12 | commit | 8 | NONMERGE-UNIQUE | formal/macho: three latent spec details match ld's dylib, and three fixed docs go |
| recover-277ad54bd | 277ad54bdea7eeea4e39aa2ef3ed722ded4a3bc6 | 2026-10-12 | commit | 8 | NONMERGE-UNIQUE | formal/macho: three latent spec details match ld's dylib, and three fixed docs go |
| recover-ebaedb8ce | ebaedb8ce1d47201cb831510c5aa3d0e44ffd518 | 2026-10-12 | commit | 8 | NONMERGE-UNIQUE | formal/macho: three latent spec details match ld's dylib, and three fixed docs go |
| recover-d406d8ad2 | d406d8ad291e47cc439f04e1582d6874f5775985 | 2026-10-12 | commit | 3 | NONMERGE-UNIQUE | FORMAL.md: the runtime ABI triple reads 273/217/177, and the check parses it |
| recover-dfea763b1 | dfea763b129ad434da640dcd9c58d095ed65675d | 2026-10-12 | commit | 3 | NONMERGE-UNIQUE | formal: declare the three undeclared dec1 reds (fact, sum, sqsum) |
| recover-a100e3290 | a100e32903b11135c3ec15e2edf3fe173824f835 | 2026-10-13 | commit | 1 | NONMERGE-UNIQUE | formal build: a module-qualified callee is not claimed when a struct declares the member |
| recover-9eaae456c | 9eaae456c6b645852b762555560b7e023a687103 | 2026-10-13 | commit | 5 | NONMERGE-UNIQUE | formal: a module-level literal sequence decides a loop's emptiness |
| recover-abee33ece | abee33ecefbeb6cc022bcf06037830c4d23b3068 | 2026-10-13 | commit | 5 | NONMERGE-UNIQUE | formal: a module-level literal sequence decides a loop's emptiness |
| recover-d055134c9 | d055134c9a53b861b2387a821f7713d67039284f | 2026-10-13 | commit | 4 | NONMERGE-UNIQUE | build_stdlib_dylib: build()'s mojostdlib_* work directory is removed on every exit |
| recover-fa549cfc4 | fa549cfc40a9dbcf630b483d8e369234f138a95a | 2026-10-13 | commit | 1 | NONMERGE-UNIQUE | bugs: file the generator's ADD/SUB-immediate shift drop (a second cause of the call_proofgen reds) |
| recover-162cbfe6e | 162cbfe6e9a8b3b5c48b7973fa4e9719b40593be | 2026-10-13 | commit | 1 | NONMERGE-UNIQUE | bugs: file the generator's ADD/SUB-immediate shift drop (a second cause of the call_proofgen reds) |
| recover-219808ef7 | 219808ef775d5bad135eeab229cb6e2c7056a853 | 2026-10-13 | commit | 1 | NONMERGE-UNIQUE | bugs/FORMAL_set_value_model (doc deleted): the model table says what the lowering does |
| recover-f94e00e5a | f94e00e5ad64d9ab78b37df8da2f7a69bed5b632 | 2026-10-13 | commit | 1 | NONMERGE-UNIQUE | bugs/TEST_formal_os_backing_is_red_with_no_marker: CLOSED, the job is green 70/70 |
| recover-c92e2a277 | c92e2a2776a50b0696c7086c7bda698152124d3d | 2026-10-13 | commit | 2 | NONMERGE-UNIQUE | formal: the ext-imm12 shift fix is verified; drop its doc |
| recover-911133564 | 91113356480dc2d5ba9f5e0e42eab6e41880a1e9 | 2026-10-13 | commit | 1 | NONMERGE-UNIQUE | bugs: the known-proof-gaps census's stack-floor reason is stale |
| recover-c216f2acd | c216f2acdc1fba8366943b6d9cf0446cf2889ccb | 2026-10-13 | commit | 4 | NONMERGE-UNIQUE | formal: refuse a `with` whose construction makes __exit__ provably truthy |
| recover-fadd1e3c1 | fadd1e3c19768f54c01f84b47c8458f667c28390 | 2026-10-13 | commit | 7 | NONMERGE-UNIQUE | formal: `return g(…)` for a return-less `g` is refused, on both backends |
| recover-5fe80477a | 5fe80477a3623b7e69536607ef2ed43f8ab0d44f | 2026-10-13 | commit | 5 | NONMERGE-UNIQUE | formal: lower ==/!= between two word-element blobs, both backends |
| recover-71ab994a5 | 71ab994a5edb3968a64b70332e17a9f16ef27ad5 | 2026-10-13 | commit | 5 | NONMERGE-UNIQUE | formal: a nested comprehension element is per-iteration on both backends |
| recover-b1ad993bf | b1ad993bfc96c630cc0fa1ad4469c40b9dc55759 | 2026-10-13 | commit | 6 | NONMERGE-UNIQUE | formal/x86_64: the ISA census has no BACKLOG row left, and its test exits 0 |
| recover-6cd2a0bee | 6cd2a0bee6c3f76067c929a5be2b13c5feac782b | 2026-10-13 | commit | 8 | NONMERGE-UNIQUE | formal: the three registered x86-64 drivers never imported on Python 3.14 |
| recover-a9dfc7472 | a9dfc74726f2a2b8840f35144eced68a9d3739f2 | 2026-10-13 | commit | 4 | NONMERGE-UNIQUE | formal monomorph: a scalar value literal is a demand at a declared value parameter |
| recover-2ca08188a | 2ca08188aead70b4d4f642f863d2e88a50e9476d | 2026-10-13 | commit | 7 | NONMERGE-UNIQUE | formal: stat_dev sign-extends the signed 32-bit dev_t |
| recover-af309c28f | af309c28f3b926dc8eae654ba7698ff9d13b7597 | 2026-10-14 | commit | 7 | NONMERGE-UNIQUE | formal: a kernel string through a `String` parameter answered `len` in bytes |
| recover-d300bbfe1 | d300bbfe146a75500a4f24151f087cb17fbb0717 | 2026-10-16 | commit | 1 | NONMERGE-UNIQUE | dangling-refs ledger: re-bank after the 98-branch merge |
| recover-2a5d54a5a | 2a5d54a5ac40a1eaedb308b954d03be7caf41b35 | 2026-10-18 | commit | 2 | NONMERGE-UNIQUE | proofgen: the B.cond arm stops interpolating a Python `w`, and three stale pins move |
| recover-c529e7f4d | c529e7f4d1f84e42d245d861585533b1635875b5 | 2026-10-19 | commit | 12 | NONMERGE-UNIQUE | formal: three wrong answers at a call boundary, fixed at their roots |
| recover-86bafecae | 86bafecaee454df944035d9a11d7f8adfcb4e560 | 2026-10-19 | commit | 12 | NONMERGE-UNIQUE | formal: three wrong answers at a call boundary, fixed at their roots |
| recover-f2ef4a61f | f2ef4a61fc2f5fbdfa50ae55ae7b510d1a4040fa | 2026-10-19 | commit | 12 | NONMERGE-UNIQUE | formal: three wrong answers at a call boundary, fixed at their roots |
| recover-0e93df24b | 0e93df24b8de1e9c73eb14747ac0e7f24c9a94b3 | 2026-10-24 | commit | 3 | NONMERGE-UNIQUE | orchestration: 'Model unavailable' is a dead model, not a worker to replace |
| recover-b23a0083d | b23a0083d75e0205446ee4c45d8fe9aee48444c9 | 2026-10-26 | commit | 4 | NONMERGE-UNIQUE | Fix: reject heterogeneous float+ptr tuple inference to prevent Span* mis-type |
| recover-af1671395 | af1671395d7979341a9f297a057a019934bc05f0 | 2026-10-26 | commit | 3 | NONMERGE-UNIQUE | CODEGEN: fix comptime function-type alias erasure (part 3) |
| recover-6eead0a37 | 6eead0a373c394214b506d0f4d01a3e3421ee153 | 2026-10-27 | commit | 4 | NONMERGE-UNIQUE | fix RUNTIME_int64_key_above_2gb: char*-declared local uses provenance; discard on MultiAssign |
| recover-1bea28d8e | 1bea28d8ecb846e34a8b9df43de393b0a4c72957 | 2026-10-27 | commit | 2 | NONMERGE-UNIQUE | Fix PARTIAL_WORK_HANDOFF (doc deleted): remove stale advice, clean deleted-doc citations, add pinning test |
| recover-a03699ec0 | a03699ec0028ee711986de509c155d8dc3a7c9f0 | 2026-10-27 | commit | 2 | NONMERGE-UNIQUE | procrun: add per-process unique-memory instrument (max RSS, not summed) |
| recover-a4c53051d | a4c53051d809a54b7eef702fcea4ab28b72dc8ae | 2026-10-27 | commit | 2 | NONMERGE-UNIQUE | Fix PARTIAL_WORK_HANDOFF (doc deleted): remove stale advice, clean deleted-doc citations, add pinning test |
| recover-4ef1d610c | 4ef1d610cce6d426eee37dc55884e9214df8034f | 2026-10-28 | commit | 3 | NONMERGE-UNIQUE | Fix CODEGEN_polymorphic_struct_param_degrades_to_a_pointer: refuse loud at struct-evidence loop for non-unanimous all-struct-pointer receiver slots |
| recover-ddb3d8f17 | ddb3d8f1766e90c149a6ac19c99d01fae8ae6454 | 2026-10-28 | commit | 3 | NONMERGE-UNIQUE | fix(CODEGEN): dict loop target rebind outside zip/enumerate (force char* when previous type differs) |
| recover-af4ed1bd7 | af4ed1bd7de3eddca3e148e216b9e77db0283597 | 2026-10-29 | commit | 1 | NONMERGE-UNIQUE | bugs: file DOCS_dangling_doc_refs_ratchet_red_preexisting |
| recover-2d84bdd89 | 2d84bdd89acf9b329eb54c9914f60a4b5e4c1e87 | 2026-10-29 | commit | 4 | NONMERGE-UNIQUE | File the coroutine element and kwargs gaps; record the contextlib status |
| recover-88bba386c | 88bba386c3afeb916fcf290694efeadb614e7b0c | 2026-10-29 | commit | 2 | NONMERGE-UNIQUE | fix: pad compile_to_gimple auto_gpu default |
| recover-2cd1fc4b5 | 2cd1fc4b5e7ec8e0d5ba4d8a80f222175d7f7d1b | 2026-10-30 | commit | 4 | NONMERGE-UNIQUE | Partial fix class-pattern positional capture (bug COMPILE_FAIL_Tools_cases_generator_analyzer): model kind + emit guard; regression test; doc updated |
| recover-f3d5f43ba | f3d5f43baa5d357cfd2a8bac80f7ed4a20cef4a4 | 2026-10-31 | commit | 1 | NONMERGE-UNIQUE | bugs/mid: f-string self-host segfault - planning guide: candidate fault sites outside the except, decision and plan |
| recover-e1ffdde85 | e1ffdde851faa598b815d6ea70c79214c4b8f1b5 | 2026-10-31 | commit | 14 | NONMERGE-UNIQUE | gate: fix the doc-refs, rthdrscan and formal-doc-truth reds |
| recover-488d1be86 | 488d1be861ab0507bbf10e761ef669a0f9ca44fe | 2026-10-31 | commit | 3 | NONMERGE-UNIQUE | bug-hard-readme: remove completed CODEGEN_gate_linked_list doc from index |
| recover-11e677c9e | 11e677c9ead5b1eece4d0bf67ac974de73982724 | 2026-10-31 | commit | 3 | NONMERGE-UNIQUE | Cherry-pick fix commits 8cda11b64 and a98f133ed (mixed-list kind copy) |
| recover-f6eb3c9aa | f6eb3c9aa00a71c93b9072b16c6a72d4820a0916 | 2026-11-01 | commit | 4 | NONMERGE-UNIQUE | Fix GIMPLE invalid-operand: use MojoExc* direct assignment, no (void*) cast on mojo_exc_new call Root cause: emit_stmts emitted (void*)mojo_exc_new(...) which GCC GIMPLE rejects as 'invalid operand in unary operation' (see gimple_codegen.py line 2618). Declare result as MojoExc* and emit plain assignment; register mojo_exc_new in _RUNTIME_FUNCS. Fixes compiled-path build for exception object args. |
| recover-4970a5506 | 4970a55064977aa7b24befc7f75193a15e3db33f | 2026-11-01 | commit | 1 | NONMERGE-UNIQUE | base marker (do not clean) |
| recover-5d20c342c | 5d20c342cc9c7d1585e86e6e2462ec57674f3ea1 | 2026-11-01 | commit | 1 | NONMERGE-UNIQUE | chk marker (do not clean) |
| recover-40b980b91 | 40b980b91b3eb95abd3d98b6c57ed370712389e4 | 2026-11-01 | commit | 4 | NONMERGE-UNIQUE | codegen: fix the three gate reds the dispatched-loop change exposed |
| recover-7ab77803d | 7ab77803d73ebdb3a0fb987624a4e3f420245b6f | 2026-11-01 | commit | 4 | NONMERGE-UNIQUE | bugs: file three gaps found while fixing the received-None arithmetic bug |
| recover-69bb45659 | 69bb4565956c9a493c403a7773fbc4a945ca11ee | 2026-11-01 | commit | 4 | NONMERGE-UNIQUE | codegen: a capturing nested function used as a VALUE inside another nested function gets its env (sibling env from the current closure's env; value references join the shared-env call group) |
| recover-3fe727f14 | 3fe727f143d8e90d1124567993ad2983243455be | 2026-11-01 | commit | 4 | NONMERGE-UNIQUE | cpp: refuse a bare yield in the emitter instead of writing a 0 literal |
| recover-4501f6b56 | 4501f6b5692c4ca9074df668ae3f91b6ebdc8f95 | 2026-11-02 | commit | 3 | NONMERGE-UNIQUE | codegen: os.path.split in a C++-emitted generator lowers to the real pair |
