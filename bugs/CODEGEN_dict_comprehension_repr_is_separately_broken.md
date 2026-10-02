# CODEGEN: a dict comprehension's repr is broken three ways, independently of its clause count

**State: OPEN, measured, NOT fixed.** Found 2026-10-01 while fixing
`CODEGEN_set_dict_comprehension_multi_clause_dropped.md`, whose repro used a
tuple key and so tripped these too. Deliberately left as its own doc: all three
are single-clause-reproducible, none is about how many `for` clauses the
comprehension has, and fixing them needs a different mechanism (the dict's
per-slot kind table) than that fix did.

## What I ran and what I saw

Three separate programs, each on its own, all `python3 fire.py --jit`-style
compiled runs against CPython's text.

### 1. An int key is stringified

    def main():
        print({i: 1 for i in range(3)})

| | CPython | compiled |
|---|---|---|
| | `{0: 1, 1: 1, 2: 1}` | `{'0': 1, '1': 1, '2': 1}` |

### 2. A 0 value renders as `None`

    def main():
        print({i: i for i in range(2)})

| | CPython | compiled |
|---|---|---|
| | `{0: 0, 1: 1}` | `{'0': None, '1': 1}` |

This is the generic dict repr's None-sentinel heuristic reading a raw 0 slot —
the same mechanism as `_list_repr_fn`'s, and the reason a dict comprehension
cannot be pinned by its repr: with the key stringified the two bugs share one
line of output, so a repr-based test cannot tell "key wrong" from "value wrong".

### 3. A tuple key prints as a heap address

    def main():
        pairs = [(0, 0), (0, 1), (1, 0), (1, 1)]
        print({k: 1 for k in pairs})

| | CPython | compiled |
|---|---|---|
| | `{(0, 0): 1, (0, 1): 1, (1, 0): 1, (1, 1): 1}` | `{'ؙ\x08\x05\x01': 1, '\x18�\x08\x05\x01': 1, ...}` |

The key is the tuple's `MojoList *` printed as a decimal, **different every
run** (ASLR). This is the class `bugs/CODEGEN_noshim_dumpfull_preexisting_
divergence.md` tracks as the "erased `_slit` string pool reference — a raw heap
address baked into the generated C as a decimal literal" symptom, and the
reason it is an ASLR-dependent wrong answer rather than a merely ugly one.

Note this one is not specific to comprehensions: `{k: 1 for k in pairs}` is a
single-clause comprehension, but the underlying cause is the dict KEY path
(`_char_to_cstr` on a non-`char *` key), so a dict literal with a tuple key
is worth checking too before assuming comprehension-specific.

## Why this is not folded into the multi-clause doc

The multi-clause fix is asserted STRUCTURALLY in
`test_runtime_diff.py::set_and_dict_comprehension_two_clauses` — `len`, `in`,
subscript — and that is deliberate. A repr-based assertion here would measure
these three bugs instead of the clause count: the broken output before the
multi-clause fix was a 2-entry dict, and the broken output after it is a
3-entry dict whose keys are stringified, which look almost the same. `len`
separates them cleanly.

## Exact next step

The dict's key and value kinds are known statically at every
`mojo_dict_set_*` call site (the `kt`/`vt` the comprehension arm already
computes and dispatches on). `mojo_repr_list_kinds` +
`_struct_slot_kind_bytes` is the mechanism that already exists for
`struct.unpack` results — a per-slot kind string handed to a kinds-aware repr
— and `mojo_list_get_kinds` / `mojo_mark_dict_bool_values` are the marking
side. So:

1. Extend that marking so a dict comprehension records its key and value
   kinds (there is already a `mojo_mark_dict_bool_values` precedent for a
   per-dict property that only repr reads).
2. Route the dict repr through the kinds-aware helper when those kinds are
   present, as `mojo_repr_list_doubles`/`_ints`/`_bytes` already do via
   `_mojo_repr_defers_to_kinds`.
3. For (3), teach the key coercion a container kind: a `MojoList *` key is
   already a boxed value and must not go through `_char_to_cstr`'s
   `mojo_str_from_int`.

Steps 1-2 and step 3 are separable; step 3 is the one that fixes the ASLR
output and is the more urgent, because it is the only one of the three that is
non-deterministic.