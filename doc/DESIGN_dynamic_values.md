# Dynamic values in the compiled path

Status: decision recorded 2026-11-11. Implementation not started.

## Problem

The compiled path gives each value one C type, chosen at compile time. A dict has one recorded value type
(`gen._dict_val_types`), and every read uses the accessor for that type. That is correct only while every value
stored in the dict has that type. Python dicts do not have that property, so the compiled path answers wrong, and
silently:

- `d = {"a": "s", "b": 2}`, then `x = d["b"]`, then `print(x + 1)`: prints `1`. CPython prints `3`. The read uses
  `mojo_dict_get_str` on an integer slot, and `x + 1` becomes a string concatenation.
- `d = {"n": None, "z": 0, "b": False, "f": 1.5}`, then `print(d[k])` for each key: prints `0.0 0.0 0.0 1.5`.
  CPython prints `None 0 False 1.5`.

The same gap appears for a name or parameter that takes two kinds (`val = d["k"]` as a float, then `val = "text"`),
which is refused today (see `CODEGEN_mixed_kind_names_need_a_representation.md`).

## Root cause (measured)

1. The value type of a dict is recorded in about eight places (`emit_stmts.py` store path; `emit_exprs.py` dict-display
   paths; `calls_shared.py`; copy paths). They do not agree on what gets recorded. The store path joins only `char *`,
   `double`, and container types, so an integer store is never recorded. A dict literal such as `{"a": "s", "b": 2}`
   is typed `char *` and reads take the string accessor.
2. Where a dict is recorded as `mixed`, reads take a boxed path, `mojo_dict_slot_boxed_*`. The boxed word then flows
   into arithmetic and printing, which were written for plain words. Those consumers do not dispatch on the box's kind.
3. The integer box is a 64-bit word whose box-or-integer question is answered by address (`mojo_is_boxed`), and boxes
   are never freed. A float or string in a box costs a heap allocation per value.

## Options considered

| | Option | Correct for all kinds | Keeps typed fast path | Internals |
|---|---|---|---|---|
| 1 | Refuse mixed dicts at compile time | yes, by fallback | yes | simple, but not full Python |
| 2 | Extend the word-plus-box design | partly | yes | address-tagged, leaks, a heap box per float or string |
| 3 | Hybrid: typed where uniform, tagged value where not | yes | yes | one tagged type for the dynamic case |
| 4 | Tagged value everywhere | yes | no | simplest model, too slow for numeric code |

## Decision: option 3 (hybrid)

- A value whose kind is provably one kind keeps its static C type and its fast accessors. Most code stays this way.
- A value whose kind is not provable is a `MojoValue`: a two-word struct, `{ int64_t tag; union { int64_t i; double f;
  void *p; } }`, with tags for int, bool, float, str, None, and the container kinds. No heap allocation for ints, bools,
  or floats.
- The dict records a value kind per slot already (`mojo_dict_set_*` writes it). A read from a mixed dict returns a
  `MojoValue` built from that slot. Arithmetic, comparison, `str`, `repr`, and `print` dispatch on the tag.
- Names and parameters that see more than one kind use `MojoValue` as their type. This subsumes the refusal in
  `CODEGEN_mixed_kind_names_need_a_representation.md`.
- The address-tagged box is retired for the dynamic path once `MojoValue` covers its uses.

Why this option: it keeps the performance of typed code where types are known, it is correct for mixed kinds without
heap allocation for scalars, and it gives one representation for the dynamic case instead of a box plus a refusal.

## Plan

Phase 0, consolidate the dict value-type join. One function in one module records a dict's value kind, and every
writer calls it. Its rule: an integer, a bool, a float, a string, or a container store all join. Disagreement records
`mixed`. Done when every dict-literal and dict-store path goes through it, with a test that a mixed literal is `mixed`.

Phase 1, the `MojoValue` runtime type and its operations (`mojo_value_from_*`, `mojo_value_add`, `mojo_value_str`,
and comparisons), with C tests. Then reads from mixed dicts return `MojoValue`, and print and the arithmetic operators
dispatch on the tag. Done when the CPython-comparison test (`test_subscript_read_of_each_value_kind`) and the
`mixed_str_first` probe match CPython.

Phase 2, names and parameters. A name or parameter with more than one kind uses `MojoValue`. Retires the mixed-kind
refusal. Done when `CODEGEN_mixed_kind_names_need_a_representation.md`'s done-when holds.

Phase 3, retire the address-tagged box on the dynamic path, once no consumer uses it.

## What this decision does not do

- It does not change how uniform dicts are read. Their fast accessors stay.
- It does not make the interpreter fall back less often. Fallback happens only on a refusal, and Phase 1 removes the
  need for one on mixed dict reads.
- It does not settle the design of general objects; those keep their existing representation.

## Evidence

- `mixed_str_first` and the each-kind print on master: see `doc/` history and `CODEGEN_dict_slot_reads_refuse_compiler_sources.md`.
- The chain's commit `ab1358422` fixes the each-kind print with a per-temp record of word and kind. It is a partial,
  parallel mechanism; it is not the consolidated design above, and it conflicts with master's boxed read path.
