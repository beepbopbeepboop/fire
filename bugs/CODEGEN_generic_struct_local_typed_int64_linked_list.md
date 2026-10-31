# A local bound to a generic struct instance is typed `int64_t`, so `test/collections/test_linked_list.mojo` fails gcc

## Status (2026-10-30): OPEN. Found while landing `work/fix-red-fix-leftover-bug-codegen-dict-literal-container-key-`; NOT caused by that branch.

The `stdlib-syntax` job's only unexpected failure in `test/collections` is
`test/collections/test_linked_list.mojo`. Its generated C does not compile.

### Evidence

- `python3 compile_stdlib.py --roots test/collections -j1` on **pure master**
  (`git archive master`): `PASSED: 58 / FAILED: 1 (0 expected, 1 unexpected)`,
  the failure being `test_linked_list.mojo`.
- The same sweep on the **merge of master and the leftover-fix branch**
  (`git merge-tree --write-tree master HEAD`): identical result.
- The generated C for `test_linked_list.mojo` is **byte-identical** between
  master and the merge (`diff` empty), so the branch's change
  (`_literal_needs_kinds` tuple row, `emit_exprs.py`) does not reach this file.
- gcc (`gcc-mp-15 -fgimple -fsyntax-only -D__MOJO_STDLIB_MODE__`, with the
  tree's own `runtime/` include) reports two errors, both in
  `test_linked_list_test_iter`:
  - `test_linked_list.mojo:657`: `assignment to 'int64_t' from 'MojoList *'`
    (`check_write_to(...)`).
  - `test_linked_list.mojo:631`: `mojo_list_get_int` passed an `int64_t`
    where a `MojoList *` is expected (`_ = it.__next__()`).

### Root cause (what is wrong in the generated C)

In `test_linked_list_test_iter` the locals are declared as scalars:

    int64_t l;
    int64_t it;
    int64_t riter;

`l` is `var l = LinkedList[Int](1, 2, 3)` and `it` is `l.__iter__()`. A
`LinkedList` / `_LinkedListIter` value is a struct, so it must be a pointer
or struct type. The generic-struct elaboration of `LinkedList[Int]` now
succeeds on master (commit that made `elaborate._struct_layout_anns` accept
`AssignStmt` fields), so the constructor call is lowered, but the local's
type is still resolved to the scalar default. Every use of `it`/`riter` then
goes through the scalar `mojo_list_get_int` / `int64_t` path.

Minimal repro (master tree, `compile_module_to_c_cached` on this program):

    from collections import LinkedList
    def main():
        var l = LinkedList[Int](1, 2, 3)
        var it = l.__iter__()
        print(it.__next__())

emits `int64_t l;` and `int64_t it;` (see the C near `int64_t l;` in the
generated `main`).

### Why it was previously hidden

Before master's `elaborate.py` fix, `LinkedList[Int]` failed to elaborate
(`AttributeError: 'AssignStmt' object has no attribute 'name'`, recorded in
`_generic_struct_elaboration_failures`). Those modules then fall back to
source and the file compiled. Once elaboration succeeds, the local-typing gap
is reached and gcc sees it. So the gap predates the fix; the fix exposed it.

### Exact next step

1. Find where a `VarDecl`/`AssignStmt` whose RHS is a generic-struct
   constructor call (`Struct[Args](...)`) gets its declared type. Likely
   candidates: `emit_resolve._elaborate_generic_struct_call` (returns the
   constructed name only for the call itself) and the local-type inference
   in `gimple_codegen` / `mojo/backend_gimple` that falls back to `int64_t`
   when the call is not a known struct name at inference time.
2. Make the local take the elaborated struct's name (`LinkedList_int64_t *`
   or the typedef the registration produced), and make `l.__iter__()` return
   the iterator struct, not a scalar.
3. Narrow check: compile the minimal repro above and gcc-check the generated C;
   then `compile_stdlib.py --roots test/collections` must report
   `FAILED: 0`. The gate's `stdlib-syntax` job is the integrator's to run.

Area: codegen, generic-struct locals. Not in the dict-literal claim.
