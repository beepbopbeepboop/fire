# TOOLS_the_integ_merge_deleted_13_docs_and_left_17_dead_targets: 14 citations of a `bugs/*.md` that the merge itself deleted

**Area:** TOOLS / repo documentation discipline — the same subject as
`TOOLS_deleting_a_bug_doc_leaves_dangling_pointers.md`, which predicted this and
is where the mechanism argument lives. This is the instance, measured.

**Found while:** merging `integ` into
`work/fix-merge-fix-merge-fix-merge-formal-cross-module`
(the `construct:cross-module-link` claim), 2026-09-30.

**Status: OPEN. Not this branch's to fix.** Every site below is in a file
another worker holds a claim on, and this branch did not edit any of them. The
four files this branch DOES own (`formal/model.py`, `formal/build.py`,
`formal/arm64_codegen.py`, `formal/x86_64_codegen.py`, plus
`test_struct_formal.py`) were done in the same merge commit; this doc is the
remainder.

## What I ran

```console
$ MB=86d862fc                                   # the merge base of HEAD and integ
$ comm -13 <(git ls-tree -r --name-only $MB bugs/ | sort) \
          <(git ls-files bugs/ | sort)           # 27 docs gone, 25 of them real fixes
$ git grep -h -o -E 'bugs/[A-Za-z0-9_./-]+\.md' $MB | … resolve against bugs/ …
  86d862fc   dead targets= 99   docs=132
  integ      dead targets=116   docs=119        # +17 from a batch of correct deletions
  merged     dead targets=117   docs=118
$ python3 - <<'PY'   # per-site: which side ADDED the citation, which side DELETED the doc
...                   # 27 sites where both are the merge's own doing; 14 of them are below
PY
```

`integ` deleted 13 bug docs. Every one of those deletions was CORRECT — CLAUDE.md
requires a fixed bug's doc to be removed rather than left listed — and every one
of them is what this repo's own `TOOLS_deleting_a_bug_doc_leaves_dangling_pointers`
doc says produces a dangling pointer. The count went 99 → 116 with no code
change. That is the argument in that doc, now with a measurement on it.

## The 14 sites, by the claim that owns the file

Every line is a citation of a doc that does not exist in the merged tree, added
by `integ` in the same commit that deleted the doc it names.

| site | dead target | owning claim |
|---|---|---|
| `formal/hostmods/json.mojo:898` | `FORMAL_arm64_lsl_imm_is_wrong_for_every_amount_above_8` | `construct:arm64-silent-wrong-answers` |
| `formal/hostmods/pathlib.mojo:23` | `FORMAL_arm64_lsl_imm_is_wrong_for_every_amount_above_8` | `construct:arm64-silent-wrong-answers` |
| `test_arm64_encoders.py:137` | `FORMAL_arm64_lsl_imm_is_wrong_for_every_amount_above_8` | `construct:arm64-silent-wrong-answers` |
| `formal/hostmods/os/__init__.mojo:67` | `FORMAL_string_equality_of_two_unclassified_words` | `construct:arm64-silent-wrong-answers` |
| `formal/hostmods/os/path/__init__.mojo:46` | `FORMAL_string_equality_of_two_unclassified_words` | `construct:arm64-silent-wrong-answers` |
| `gimple_codegen.py:1395` | `CODEGEN_aliased_imported_struct_construction_unresolved` | `construct:decorators-and-import-qualifiers` (already integrated) |
| `mojo/backend_gimple/emit_calls.py:2020` | same | same |
| `mojo/middle/funcs_shared.py:582` | same | same |
| `test_gimple.py:6504` | same | same |
| `formal/hostmods/os/_syscalls.mojo:558` | `FORMAL_stat_out_parameter_is_unreadable` | `construct:os-backing-constructs` |
| `test_formal_os_backing.py:24` | same | `construct:os-backing-constructs` |
| `test_formal_os_backing.py:15` | `CODEGEN_string_parameter_subscript_reads_count_field` | `construct:os-backing-constructs` |
| `test_formal_os_backing.py:20` | `FORMAL_subscript_of_a_pointer_reads_a_blob_count` | `construct:os-backing-constructs` |
| `test_formal_os_backing.py:104` | `FORMAL_x86_64_dylib_with_an_extern_call_does_not_load` | `construct:os-backing-constructs` |

Line numbers are as of the merged tree at
`work/fix-merge-fix-merge-fix-merge-formal-cross-module`; re-run the scan above
rather than trusting them, because a file is a file and these move.

## The exact next step

One line each, and it is the same line every time: **keep the sentence, drop the
dead path, name the slug and say the doc was deleted because the bug is fixed.**
The substance is already there in all fourteen — they are provenance notes, and
the provenance is "this used to be wrong and the measurement that showed it" —
so the rewrite is mechanical and no test should move.

Two shapes need care:

- `test_formal_os_backing.py:15,20,24,104` are in a file whose HEADER enumerates
  what the suite covers, so the citation is part of a claim the reader relies on.
  Rewrite it to the slug form rather than dropping the clause.
- `gimple_codegen.py`, `mojo/backend_gimple/emit_calls.py` and
  `mojo/middle/funcs_shared.py` are compiled-path files, so per CLAUDE.md any
  edit there owes a full `make gate`. A comment-only edit should not, but that is
  a judgement the integrator makes, not the worker who owns the claim.

**Do not restore the deleted docs.** `TOOLS_deleting_a_bug_doc_leaves_dangling_pointers`
§"Not this" is explicit and is right: a fixed bug still listed is
indistinguishable from an open one, and re-adding thirteen docs to make fourteen
comments resolve is the wrong trade.

## Related, already filed

- `TOOLS_deleting_a_bug_doc_leaves_dangling_pointers.md` — the mechanism, and the
  proposal for the check that would have caught this (a `test_suite.py` scan
  beside `test_every_test_file_is_registered`, or a pre-commit check on
  `git rm bugs/*.md`). This doc is the argument for landing one of those two:
  the mechanism is now demonstrated twice, on one merge.
- `TOOLS_the_test_estate_check_has_been_red_since_eight_formal_suites_landed.md`
  — the other direction of the same gap, and the reason a `test_suite.py` check
  would not run under the gate until its step 2 is done.
