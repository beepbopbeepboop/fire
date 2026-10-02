# FORMAL_comptime_names_called_with_a_string_receiver: `_overridden_comptime_names` raises `AttributeError` on a parameter declared with a bare name, so `formal-dataclasses` is red

**Area:** CODEGEN/FORMAL: `formal/build.py`'s `_overridden_comptime_names` and
its two call sites. Found 2026-10-02 while landing the dataclass partial-fill
capability; **not fixed here**, because the comptime class-attribute area is
another worker's claim (`FORMAL_comptime_class_attribute_read_through_a_receiver`,
`FORMAL_class_level_default_flips_a_nested_frames_width`) and a wrong edit to
that function is expensive to untangle from two directions.

---

## What it is

`_overridden_comptime_names(struct_defs, st)` is documented to take a
`StructDef` and reads `st.name`:

```python
def _overridden_comptime_names(struct_defs: dict, st) -> set:
    out = set()
    for derived in M.struct_derived_names(struct_defs.values(), st.name):
```

Both call sites hand it something that is not always a `StructDef`:

```
formal/build.py:5782   shadowed = _overridden_comptime_names(structs_by_name, st)
formal/build.py:5806   shadowed = _overridden_comptime_names(structs_by_name, owner)
```

and the 5782 one iterates a table this file itself builds:

```python
    locals_ = dict(_constant_constructor_bindings(fn, structs_by_name)[0])
    for local, st in M.parameter_declared_structs(
            fn, structs_by_name, owner).items():
        locals_.setdefault(local, st)
    for local, st in locals_.items():
        publish(local, st, comptime_only=False)
        shadowed = _overridden_comptime_names(structs_by_name, st)
```

so a `locals_` entry whose value is a NAME STRING reaches `st.name` and the
compiler raises instead of classifying the file.

## What it costs

`formal-dataclasses` is a registered job with **no `expect=` marker**, and it is
red because of this:

```
$ python3 tools/memslot.py --gb 8 --label dc -- python3 test_dataclasses_formal.py
FAIL  the_repositorys_own_dataclasses_are_classified_not_crashed:
      formal/build.py is classified, not crashed: …
      File "formal/build.py", line 6015, in _overridden_comptime_names
        for derived in M.struct_derived_names(struct_defs.values(), st.name):
      AttributeError: 'str' object has no attribute 'name'
54 passed, 1 failed
```

The case is the corpus one — "every `@dataclass` in THIS repository is
classified, not skipped" — and the file it cannot classify is
**`formal/build.py`**, this compiler's own front end. So the transform is being
asked to handle a real `@dataclass` in a real file and answers with a Python
traceback, which is the exact failure that case exists to catch.

**Pre-existing, verified both ways**: `python3 -c "import formal.build;
B.compile_formal(<HEAD's formal/build.py>)"` raises the same `AttributeError`
with this branch's `formal/model.py`, and so does the worktree copy. Nothing in
the change that found it touches this function.

## The exact next step

Make the two call sites agree with the signature, and make the signature
defensive rather than trusting its callers:

1. `parameter_declared_structs`'s values should be `StructDef`s; find the branch
   that returns a bare name for a parameter it could not resolve to a struct, and
   decide whether that entry belongs in a table `_overridden_comptime_names`
   walks at all. A parameter declared with a name this image cannot resolve to a
   struct of this module has no derived classes to consult, so the honest answer
   for it is the empty set.
2. Whatever (1) decides, give `_overridden_comptime_names` a `getattr(st, "name",
   None)` early return so a table this file builds can never take the compiler
   down — the same "classified, not crashed" contract `formal-dataclasses`
   asserts for the dataclass transform.

Both halves are one line each, and (2) alone turns the red suite green.
