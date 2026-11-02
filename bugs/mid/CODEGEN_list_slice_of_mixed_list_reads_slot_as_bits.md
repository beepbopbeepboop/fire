# CODEGEN: a slice of a kind-mixed list reads its int slot as a double

## Status 2026-10-30 — found, not fixed

Found while merging master's `a98f133ed` (mixed-kind list copies) into
`work/bug-codegen-gate-gimplerunner-red`. Pre-existing: identical output on
pristine `HEAD` and on `master`. No test covers it.

Repro (`.tmp/probe_literal.py` in the worker worktree; the core is):

```
def main():
    a = [1, 2.5]
    b = a[:]
    print(b)
    print(b[0])
main()
```

Saw: `[1, 2.5]` then `5e-324`. Expected: `[1, 2.5]` then `1`.

Cause: `_lower_slice` in `mojo/backend_gimple/emit_calls.py` (the
`# propagate elem type` block after the `mojo_list_slice` call, ~line 10206)
copies `gen._elem_types[ov]` onto the slice's temp. For `[1, 2.5]` that is
`double`, the promoted element type, so the compile-time read `b[0]` goes
through `mojo_list_get_double` and prints the int slot's bit pattern. The
runtime is correct: `mojo_list_slice` (`runtime/fire_runtime.c`, ~line 2055)
copies the raw words and calls `mojo_list_inherit_kinds`, so the row travels;
`print(b)` is right for that reason.

Next step: in `_lower_slice`, when `ov` is in `gen._maybe_kinds_vals`, add the
result to `_maybe_kinds_vals` and do not propagate the promoted `_elem_types`
entry; carry `_struct_slot_kinds` across instead. This is the same rule the
`list(x)` copy in `_lower_ctor_from_iterable` now follows. Pin it with a
`test_gimple_runner.py` case (`b[0]`, `b[1]`, and `a[1:]` of a mixed list),
then delete this doc in the same commit and run
`python3 tools/dangling_doc_refs.py --ratchet`.
