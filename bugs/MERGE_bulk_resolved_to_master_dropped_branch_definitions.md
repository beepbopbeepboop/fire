# MERGE: the bulk `merge-qwen4-r2` merges resolved every conflict to master, which dropped the branch half of some signatures and definitions

**Status: PARTIAL.** All the branches on the task list were merged (except the two
`merge-*` branches that touch `mojo/`/`gimple_codegen.py`/`runtime/`), the
interrupted `work/formal59-docs` merge is resolved, the doc index and the
dangling-refs ratchet are green, and every `.py` file in the tree `compile()`s.
What is NOT finished is the interactive cleanup of the conflict resolution itself,
and this doc is the queue for it.

## What happened

The merge list has ~110 branches, almost all of them cut from an old master and
now largely superseded. The reconciliation used for most of them was mechanical:
**master's side wins every conflicting hunk, and the branch's non-conflicting
additions land**. That is right for a parallel *implementation* (the landed one
wins), and it is wrong for anything where the branch **extended** a shared
signature, import block, or function the master side also edited — there the
merge kept the branch's *body* and master's *signature*, so the name the body
uses is not bound.

The fixtures found so far, and the fixes already landed:

* `formal/arm64_proof_gen.py::_gen_extern_test` — `func_entry` twice in the
  signature and twice at the caller (a duplicate-argument SyntaxError, which
  `ast.parse` does **not** raise; only `compile()` does).
* `formal/model.py` — `ValueKinds.__init__` lost `bool_names`, `callee_is_bool`
  and `pointer_pointee_kind`; `bare_c_callee_is_project_function` and
  `fold_interpolated_literal` were absent; `bind_call_arguments` passed a stray
  fourth argument (`mappings`) to `_unspread_keyword_mappings`.
* `formal/monomorph.py` — `_template_call_shapes` and
  `_layout_independent_struct` absent (and `from contextvars import ContextVar`
  in `model.py`).
* `formal/x86_64_codegen.py` — `_for_target_refusal` absent.
* `formal/arm64_codegen.py` / `formal/x86_64_codegen.py` — the comprehension
  element-storage machinery was a mix of master's and the branch's; restored to
  master's `_emit_comprehension`/`_emit_compr_gen` and
  `_compr_append_elem`/`_compr_append_pair`.
* `tools/formal_isa_census.py` — `encode_call_r64` was in both `HARNESS_LIMITS`
  and `BACKLOG`.
* `tools/dangling_doc_refs.py` — `--ratchet` referenced an undefined
  `bare_regressions`.
* test files — missing test functions their `TESTS`/`ALL` lists named
  (`test_formal_monomorph.py` x4, `test_formal_contracts.py`,
  `test_formal_x86_64_dylib.py`), a `copy`/`copies` and an `om_got`/`omit_got`
  mixup, and a `must_refuse` leftover.

## How to find the rest

    python3 - <<'EOF'
    import subprocess
    bad=[]
    for f in subprocess.run(['git','ls-files','*.py'],capture_output=True,text=True).stdout.split():
        try: compile(open(f).read(), f, 'exec')
        except SyntaxError as e: bad.append((f, e.lineno, e.msg))
    print(bad)
    EOF

catches duplicate arguments and the like. Undefined *names* need a scope-aware
walk (AST or `symtable`); `git grep -n 'def NAME'` across the branch tips decides
whether a flagged name is a dropped definition (search `git log master..HEAD
-SNAME` for the commit that used it, then `git branch --contains` for the tip that
still defines it). Then run the touched suites:

    git diff --name-only master..HEAD | grep '^test_formal' 
    python3 tools/memslot.py --gb 8 --label t -- python3 <file>

## Known-open interaction failures

`test_formal_value_model.py` is **134 pass / 3 fail**:

* `a_comprehension_whose_element_is_a_call_returning_a_container_gives_each_one`
  — arm64 answers `90` where CPython answers `60`. This is the defect
  `bugs/FORMAL_a_comprehension_container_element_needs_a_runtime_blob_base.md`
  records, and the `work/formal40-1-r2` branch fixed it with a per-element span
  copy keyed on `_ret_blob_sites`. Master's `_materialize_compr_element` keys only
  on the frame-ledger delta, which does not move for a returned blob, so it
  aliases. **The decision this doc leaves open is whether to keep master's
  mechanism (safe refusal for non-flat containers, this aliasing for returned
  blobs) or land the branch's (answers more, needs `expr.key`→`expr.value` fixed
  here and its own test rows)._**
* `a_comprehension_whose_element_is_a_concat_of_displays_gives_each_one` — master
  refuses it (the branch answered it); the branch's test row expects an answer.
* `an_extremum_of_a_container_and_a_literal_is_refused_by_the_blob_table` — a
  refusal wording mismatch; likely pre-existing.

The rest of the touched `test_formal_*.py` files (about forty) have NOT been run
— running them all is the integrator's call, and any failure in one of them is a
candidate for this same class of dropped-definition breakage.
