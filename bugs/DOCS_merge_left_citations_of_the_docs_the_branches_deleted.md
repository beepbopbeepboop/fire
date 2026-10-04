# DOCS: merging eight formal branches deleted 14 bug docs and left 12 citations of them in `.py` files

**Status: NOT FIXED, inventoried with a measured split, and the one citation
that was actively harmful is fixed. Found while merging `work/formal3-5`,
`-3-10-r2`, `-3-8-r2`, `-3-3-r2`, `-3-2-r2-r2`, `work/formal4-sweep-{std-a,
x86-a,repo-a-r2-r2}` into `work/merge-formal4` (2026-10-02).** This is the
fourth instance of a shape `bugs/DOCS_deleted_bug_doc_still_cited_in_three_places.md`
already records, which says of its own eleven that "the rest are spread across
claims that are not mine, which is why it is recorded here rather than fixed" —
this is that sentence's arithmetic catching up, and it now has its own list.

Not a live defect in the sense that document means: **nothing computes anything
from these strings.** Every one is a comment or an index row. It is a dangling
reference in a file that exists to be believed, which is the same class as a
stale test name — and this time one of them was in a file that IS a test, in a
`precondition` assertion, so the failure mode is already demonstrated rather than
hypothetical (see `test_formal_sweep.py` below).

## What I ran

A walk of every `.py` / `.md` / `.mojo` / `.lean` in the tree against the list of
docs the eight branches `git rm`'d:

    $ python3 - <<'PY'   # the 14 stems, checked against bugs/ and every file
    ...
    FORMAL_x86_64_formal_backend_gaps: 3
    FORMAL_dataclass_partial_construction: 4
    FORMAL_class_level_default_flips_a_nested_frames_width: 4
    FORMAL_cross_image_frame_contract_is_not_published_for_a_free_function: 4
    FORMAL_dylib_export_gate_ceiling: 9
    … one more each for six of them
    ---- present in bugs/?  []
    PY

`git ls-tree <branch> bugs/ --name-only` confirms every one of the 14 is gone.

## The split, which is why only one is fixed here

**Harmful (2), both fixed or trivially fixable:**

  * `bugs/OPEN_WORK.md` — the TRIAGE INDEX had a row whose subject is a file
    that is not there. FIXED: the row is now a `*(deleted 2026-10-02)*` row in
    the table's existing convention, naming what the two gaps were and which two
    branches closed them. An index that names a missing file is the one kind of
    dangling reference a reader follows by construction.
  * `test_formal_sweep.py:450` — `test_a_relative_imports_underscored_symbol_resolves_and_the_image_runs`
    asserts `all(n.startswith("_") for n in names)` and the bind name is
    `relpkg__helper_twice_9f63a2`, i.e. a relative import's ABI prefix is now the
    PACKAGE-qualified `relpkg__helper` rather than the `_helper` the precondition
    expects. This is a stale precondition, **byte-identical on `master`**
    (75/76 on both trees, same assertion, same string), so it predates this merge
    and is not fixed here. It is the demonstration: a comment-shaped assumption
    that became a test-shaped one.

**Harmless in a `bugs/` document (about 20 sites).** They say "was
`…`.md`, deleted", "now closed", or are sweep work-map rows naming the cause the
way a work map names a cause. The convention the branches themselves established
(formal3-5's `FORMAL_struct_eq_compares_frame_addresses:4` reads "now
fixed and `git rm`'d") is fine and this doc does not argue with it.

**Harmful in a `.py` comment (11 sites, NOT fixed):**

    formal/model.py:3327            FORMAL_x86_64_formal_backend_gaps
    formal/model.py:1196            FORMAL_external_call_a_multiparameter_type_in_the_bracket
    formal/model.py:10396           FORMAL_cross_module_call_arity_is_never_checked
    formal/model.py:14252           FORMAL_class_level_default_flips_a_nested_frames_width
    formal/model.py:15684           FORMAL_dataclass_partial_construction
    formal/build.py:4735            FORMAL_eq_does_not_dispatch_to_a_user_dunder
    test_formal_x86_64_parity.py:206  FORMAL_x86_64_formal_backend_gaps
    test_formal_run.py:4598         FORMAL_x86_64_tuple_assignment_member_target
    test_formal_run.py:5876         FORMAL_class_level_default_flips_a_nested_frames_width
    test_formal_run.py:6331         FORMAL_dataclass_partial_construction
    test_formal_hostmods_census.py:48  FORMAL_cas_verdict_key_ignores_the_hostmod_sources_it_compiles
    test_formal_cross_module.py:1114   FORMAL_cross_image_frame_contract_is_not_published_for_a_free_function
    test_dataclasses_formal.py:164, :449  FORMAL_dataclass_partial_construction

## Why not fixed here, precisely

Because deciding what each sentence should say INSTEAD requires re-deriving the
fix each one documents, and eleven sites are eleven fixes to re-measure — which
is not a merge's job and would be nine commits' worth of work spread over a
branch whose subject is eight merges. Two of them are one-line repoints and were
done during the merges for exactly that reason (formal4-sweep-x86-a's
`aug_division_through_a_frame_slot` cited `FORMAL_method_param_field_access.md`
and now cites `model.struct_fits_one_word`; formal3-2-r2-r2's
`struct_comptime_aliases` comment cited `FORMAL_comptime_class_attribute_read_
through_a_receiver.md` and now cites `formal/imports.py`'s
`_attach_declared_census`). The other nine need the re-measurement.

## Exact next step

1. For each of the eleven, name the SYMPTOM and the fix's own commit rather than
   the doc, which is what `bugs/DOCS_deleted_bug_doc_still_cited_in_three_places.md`§2
   already concluded (`git log -S` on the sentence the doc quotes). Two of the
   eleven are already done above, as the worked examples of what "done" looks
   like.
2. Fix `test_formal_sweep.py:450`'s precondition first, on its own: decide
   whether a relative import's ABI prefix SHOULD be package-qualified, re-measure
   `abi_module_name('._helper')` on `master` and after, and either correct the
   assertion or file the divergence. It is a red line in a file eight workers run.
3. Then add the check that document asks for and this one re-asks: a `bugs/*.md`
   path mentioned in a `.py`, `.mojo` or another `.md`, verified to exist,
   allowing the three historical conventions above (`was X, deleted` / `now
   closed` / a work-map cause column). It is a five-line walk in `test_suite.py`,
   which already walks the repo for `test_*.py` and for stale `UNREGISTERED`
   entries — the same "an inventory that can go stale" shape, and `bugs/` is an
   inventory. **Allowing the three conventions is the whole design problem here**,
   and it is why this is a decision rather than a script: a check with no
   exceptions reports every historical citation in the tree (about 20, from this
   doc's own neighbours), and a check with a loose exception stops catching the
   thing it is for.