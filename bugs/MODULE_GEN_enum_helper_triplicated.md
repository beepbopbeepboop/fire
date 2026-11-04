# module_gen.py: `_is_enum_class_def` helper pasted in three times, import-order comment truncated

Found during the merge round for bug:PLAN_enum-rtc_stage4-repr
(work/fix-merge-fix-merge-fix-merge-bug-plan-enum-rtc-stage4-repr,
2026-11-04), reading `mojo/backend_gimple/module_gen.py` at master
4c687bb62 to check merge coherence.

## What I saw

At module level, the identical block

```python
_ENUM_BASES = {'Enum', 'IntEnum', 'StrEnum', 'Flag', 'IntFlag', 'ReprEnum'}


def _is_enum_class_def(node):
    try:
        bases = getattr(node, 'bases', None) or []
        ...
```

appears **three** times (lines 54, 91, 105 at 4c687bb62), and the
multi-line comment explaining why this file must not import
`mojo.middle.infra_infer` at top level is truncated at its first copy:
line 52 reads `# `import gimple_codegen` and the original sentence
("...`import gimple_codegen` then leads `emit_infra`'s top-level
`from mojo.middle.infra_infer import _FC_SEP, ...` back into a
half-built `infra_infer`") is cut where the helper was pasted into the
comment block. The pattern (insertion mid-comment, repeated per commit)
points at the enum-rtc / linked-list commits that added the helper
(bb3df4817, fea5f75b2, 62c3ed946, 5782d6e83 area — see
`git log 30d02519a..master -- mojo/backend_gimple/module_gen.py`).

## What I expected

One definition of `_ENUM_BASES` / `_is_enum_class_def`, and the
import-order comment intact (CLAUDE.md: "Consolidate duplicates rather
than maintaining parallel implementations").

## Functional impact

None known: the three copies are textually identical (the last
definition wins), and `test_runtime_class_creation.py` passes 27/27 on
the merged tree (2026-11-04, incl. `enum_via_metaclass_transformation`
and `metaclass_prepare_returns_namespace_dict`, which exercise the
helper's use in `gen_module_impl`).

## Exact next step

Keep one copy of the block (at the location whose surrounding comment
is intact), restore the truncated sentence in the import-order
comment, delete the other two copies, and re-run
`python3 tools/memslot.py --gb 8 --label module-gen-dedup -- python3
test_runtime_class_creation.py`. Area owner: whichever enum-rtc /
linked-list worker next touches `mojo/backend_gimple/module_gen.py`.
