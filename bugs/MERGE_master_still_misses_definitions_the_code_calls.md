# MERGE: master still calls definitions it does not define (the bulk merge's dropped half, round 2)

**Status: OPEN.** `bugs/MERGE_bulk_resolved_to_master_dropped_branch_definitions.md`
records the first round of this and the fixtures that were already put back.
The round two of the same class is still live on `master` at `f4cc426c`, and the
98-branch merge on `work/merge-qwen5-r2-r2` inherits it. Each row is a name a
file CALLS that no file DEFINES, so the call is an `AttributeError`/`NameError`
at run time and a test that reaches the path is red for a reason that is not the
code it tests.

## Measured (2026-10-16, `master` at `f4cc426c`)

A cross-module undefined-attribute walk (`M.foo` where `formal/model.py` has no
`foo`, and the same for the other imported modules) over `git ls-files '*.py'`
reports these on a pristine master tree:

| caller | calls | defining module |
|---|---|---|
| `formal/build.py::_one_with_item` | `M.context_enter_returns_receiver`, `M.context_exit_suppression_at_site` | `formal/model.py` |
| `formal/build.py::_export_rule_for` | `M.EXPORT_RULE_DECLARED`, `M.EXPORT_RULE_ABSENT` | `formal/model.py` |
| `formal/{arm64,x86_64}_codegen.py` | `M.comprehension_element_not_sized`, `M.is_list_expr` | `formal/model.py` |
| `formal/arm64_codegen.py` (`_emit_binop`'s `+`/`\|` arm) | `self._emit_set_union` | `formal/arm64_codegen.py` |
| `formal/build.py` | `monomorph.clear_failed_demands`, `monomorph.failed_demand_reason` (`_FAILED_DEMANDS`, `_record_failed_demands`) | `formal/monomorph.py` |
| `test_formal_run.py` | `M.integer_text_width`, `M.interpolated_field_shape`, `M.interpolated_literal_bound` | `formal/model.py` |

The last row is the worst: `test_formal_run.py::main` calls the two
`interpolated` censuses before any row runs, so on master the file dies with
`AttributeError: module 'formal.model' has no attribute 'interpolated_field_shape'`
having run **0** of its 1300-odd rows.

## What this branch already put back

`work/merge-qwen5-r2-r2` restores, verbatim from the commits that added them:

* `integer_text_width` / `interpolated_field_shape` / `interpolated_literal_bound`
  (`a802bbf0`);
* `context_enter_returns_receiver` (`4db6d7c2`),
  `context_exit_suppression_at_site` and `_constructor_argument_for`
  (`d4215a0b`);
* `is_list_expr` (`c598abe9`), `comprehension_element_not_sized` (`517dacd4`);
* the `limit` parameter of `arm64_proof_gen._gen_step_result_lemmas` (`ade542581`
  added it; a later merge reverted only that def line).

With those, `test_formal_run.py` runs again and goes 1276 pass / 32 fail on
master-plus-only-that-fix, and 1283 / 26 with this branch's `with`/kind work.

## Still open (do NOT read these as the merging branch's regressions)

* `formal/arm64_codegen.py`'s `_emit_set_union` — arm64's union emitter. The
  def exists on `batchfix-841541` (added by `089ceb34`); copying the Sep-24 body
  back makes the three `set_union_*` rows BUILD but answer one element short
  (`5` where CPython answers `6`), so restoring that verbatim turns a loud
  `AttributeError` into a silent wrong answer. The correct fix is the union
  emitter the later set-algebra work (`232733bc` on x86, its arm64 twin) expects,
  not the old body.
* `formal/model.py`'s `EXPORT_RULE_ABSENT` / `EXPORT_RULE_DECLARED` — two
  `reflect.EXCL_*`-shaped constants `_export_rule_for` returns; the defining
  commit is not in this tree's history under that spelling (`git log -S "def
  EXPORT_RULE_ABSENT" --all` finds nothing), so they have to be written from
  `_export_rule_for`'s own docstring, which names both.
* `formal/monomorph.py`'s failed-demand table (`_FAILED_DEMANDS` and its three
  readers) — `formal343-docs` (`0c3db7ff`) has the coherent block; it was not
  landed here because the merge that would carry it also carried a conflicting
  `record` hybrid.
* The `printf("%d", <container>)` refusal rows in `test_formal_run.py` expect a
  wording (`... and \`xs\` is \`list:int\``) the code no longer emits. Pre-existing
  on master and only visible now that the census no longer dies first.
