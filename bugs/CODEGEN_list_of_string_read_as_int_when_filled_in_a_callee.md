# CODEGEN: a `List[String]` filled only inside a callee reads back as ints in the caller

## Status (2026-09-30 — the ANNOTATED form is FIXED; the unannotated one is not, and cannot be)

Cause found and fixed. The declaration's own annotation is real evidence
about a container's element type, and it was being dropped on one of the
three paths that can consume a binding statement: the owned-local stack
allocation (`maybe_stack_alloc_owned_ctor` in
`mojo/backend_gimple/emit_infra.py`), which handles `kept: List[String] =
[]` WHOLE — because `[]` is an empty constructor and the local is an
ownership candidate — and therefore ran neither of the two ordinary
statement paths that seed `_elem_types` from `node.type_ann`. The two
inline copies of that seeding are now one shared helper
(`_annotation_container_elem_type`, `mojo/middle/stmts_shared.py`, the
list/set counterpart of the existing `_annotation_dict_val_type`), and the
stack-allocation path passes the answer to `_declare_var`'s own `elem`
parameter. So the doc's repro — verbatim, `String("cde")` and all — now
prints `3` / `cde` / `True`, verified against CPython on the same text;
regression test `gimple_annotated_list_string_filled_in_a_callee` in
`test_gimple_runner.py` (which also pins `List[Int]` and an f-string over
the element, both of which were right already).

**Still open, and not fixable this way**: the same program with an
UNANNOTATED binding (`other = []` then `fill(other)`) still reads back as
ints. There is genuinely no static evidence anywhere in that program — no
annotation on the declaration, and the only `append` is inside the callee,
whose parameter is untyped too. Answering it needs either a real
cross-function element-type contract (what `_param_elem_types` starts to
do, one call at a time) or a runtime element-tag on the list, which is a
feature rather than a fix. Measured, not assumed: CPython and the compiled
path agree on every line of the annotated form and disagree on all three
reads of the unannotated one.

The doc's original observation — "the element type of a list is recorded by
the code that lowers `append`; a caller that only sees the list through a
call never learns it" — is correct and is why the annotation was the only
available fix. `bugs/CODEGEN_return_type_not_inferred_from_a_method_call_
result.md` is the same class of gap on the return-type side, fixed in the
same pass.

## Earlier status (2026-09-28 — OPEN, reproduced, cause not investigated)

```mojo
def fill(kept: List[String]):
    kept.append(String("cde"))

def main():
    var kept: List[String] = []
    fill(kept)
    print(len(kept[0]))      # 6581285 (garbage)   -- CPython: 3
    print(kept[0])           # 4364882704 (a pointer) -- CPython: cde
    print(kept[0] == "cde")  # True                -- correct
```

If the elements are appended in the same function as the reads, all three lines are
correct. Ownership on/off makes no difference (checked with every ownership analysis
disabled), so this predates the ownership work. The element type of a list is recorded
by the code that lowers `append`; a caller that only sees the list through a call never
learns it, so `kept[0]` is typed as an int: `len` of it reads the pointer's bits as a
list header, `print` formats it with `%ld`, and only the comparison (which dispatches on
the string literal side) still works.

Found while building a regression test for string ownership: reading a `List[String]`
element with `len`/`print` is unreliable across a call boundary, so the test compares
with `==`.

## Done when

The repro prints `3`, `cde`, `True`. Likely fix: honour the `List[String]` annotation on
the declaration/parameter as the element type instead of relying on `append` sites.
