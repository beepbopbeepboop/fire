# `formal/model.py` is a corrupt merge, shadowed by the `formal/model/` package

**Area:** FORMAL (shared value model, module layout). **Found 2026-11-03** while
landing the augmented `Pointer[Float64]` subscript store
(`FORMAL_float_pointer_augmented_subscript`).

## Symptom

Every arm64 subscript store on this branch's HEAD crashes in the emitter, before
any float logic is reached:

    python3 test_formal_run.py deref_a_binary64_subscript_store_of_a_double_is_exact
      File "formal/arm64_codegen.py", line 6479, in _emit_subscript_store
        if M.subscript_float_element(self._cur_fn, target.obj, self._structs,
    AttributeError: module 'formal.model' has no attribute 'subscript_float_element'

`subscript_base_lowering` is also called with `element_kind_ok=`, which the
package does not accept (`TypeError`), so the float-element refusal path is
dead too.

## What is actually there

- `formal/model/__init__.py` (tracked, 56152 lines) is a stale copy of the
  reorganised model. `python3 -c "import formal.model as m; print(m.__file__)"`
  resolves to it, because a package directory takes precedence over a sibling
  `model.py`. It has `pointer_store_lowering` but NOT `subscript_float_element`
  and NOT `subscript_base_lowering(..., element_kind_ok=)`.
- `formal/model.py` (111808 lines, tracked) starts with a literal
  `<<<<<<< HEAD` line (line 1) and has a diff3 base marker `||||||| e59011446`
  at line 55920. It has no `=======` or `>>>>>>>`. It is not parseable Python;
  the HEAD side (lines 2–55919) parses and contains every newer function.
  `python3 -c "import ast; ast.parse(open('formal/model.py').read())"` fails.
- Commit `47adc1347` (merge into the float-subscript branch, "keep both sides")
  is where the branch's model additions went into `model.py`, and
  `31ca1c149` ("Reorganize formal/model.py into formal/model/*.py") is where the
  package became the real module. The two were never reconciled, so the newer
  code lives only in the file Python ignores.
- `formal/model/` also has `_model_original.py` and eleven `fNN_*.py` files,
  which look like the split the reorganisation intended. Their content was not
  compared against either copy.

Measured: `cmp` of the package against the HEAD side of `model.py` differs in
about 230 hunks (`diff -u` output 2347 lines), so this is not a one-line drift.

## Expected

One module is the value model. `import formal.model` resolves to the file that
contains the newest code, the other copy is removed, and no file under
`formal/` contains a conflict marker.

## Exact next step (needs a decision first)

1. **Decide the canonical location.** The working reading is: the package
   `__init__.py` is canonical (the reorganisation made it so), and the HEAD side
   of `model.py` holds the branch's additions. Confirm by checking that every
   function `formal/*.py` calls on `M.` exists in the chosen source. Also check
   whether the `fNN_*.py` / `_model_original.py` files are generated from, or
   duplicates of, the same text. If they are generated, regenerate; if they are
   stale copies, delete them (CLAUDE.md: consolidate duplicates).
2. Port the HEAD side of `model.py` into `formal/model/__init__.py`. Delete
   `formal/model.py`. Re-run `python3 tools/dangling_doc_refs.py --ratchet`
   if any doc names it.
3. Verify with the float-subscript rows and `test_formal_run.py` on the
   subscript group, then the controller's gate. A grep for `^<<<<<<<\|^||||||||\|^=======\|^>>>>>>>`
   under `formal/` and `tools/` should be empty; add it to `doc-refs` or a
   test so a corrupt merge cannot be committed silently again.

## Quick reproduction

    git show HEAD:formal/model.py | head -1          # <<<<<<< HEAD
    git show HEAD:formal/model/__init__.py | grep -c 'def subscript_float_element'   # 0
    python3 test_formal_run.py deref_a_binary64_subscript_store_of_a_double_is_exact  # AttributeError
