# `test_formal_bracketed_method_field_set.py`'s ask-COUNT rows ask a question the
# EVIDENCE/PRE-RULE split made unanswerable, and the file is in no bucket

**Class:** a stale test assertion plus a coverage hole. **Area:**
`test_formal_bracketed_method_field_set.py`'s "module table" group (four rows)
against `formal/model.py`'s `_split_declaration` / `_pre_rule_field_names`.

Found 2026-10-03 on `work/formal19-2` while landing
`formal/model.py`'s `iter_statement_nodes` (the `struct_receiver_stores` walk —
`bugs/FORMAL_build_cost_2026-10-03.md` §6, second bullet, which cites THIS file
for the drift measurement). **It is pre-existing and not that change's:** it
reproduces with `formal/model.py` at `master` byte for byte, measured by writing
master's copy over the edited one, running the file, and restoring — never
`git checkout <path>`.

## What I ran

```console
$ python3 tools/memslot.py --gb 8 --label t -- \
      python3 test_formal_bracketed_method_field_set.py
  FAIL  a_declared_name_that_is_also_a_method_stays_a_field: deriving the field
        set of a 2-method struct asked struct_receiver_stores 0 times; it is a
        property of the STRUCT, so it is asked once
  FAIL  a_store_in_another_method_keeps_the_name_a_field: … a 3-method struct …
        0 times …
  FAIL  a_store_through_this_and_inside_a_nested_def_is_a_field: … a 1-method
        struct … 0 times …
  FAIL  chained_augmented_and_tuple_stores_are_all_stores: … a 1-method struct …
        0 times …

bracketed method field set: PASS=22 FAIL=4
```

22 of 26 rows pass, and the four that fail all fail the same way: the
ask-counting assertion sees **zero** calls where it expects one.

## Why, and it is not a bug in the compiler

`_field_set_case` (line ~1070) reads the struct through `formal.build.parse_module`
— deliberately, and its own docstring says why: "the evidence `_split_declaration`
needs is attached there". It then derives `M.struct_field_names(st)`, patches
`M.struct_receiver_stores` with a counter, calls `M.struct_field_names(st)` a
SECOND time, and asserts the counter saw exactly one call.

**That second call does not derive anything.** `struct_field_names` is

```python
merged = struct_merged_field_names(struct_def)
if merged is not None:
    return list(merged)
return _own_field_names(struct_def)
```

and `struct_merged_field_names` is `getattr(struct_def, "_merged_field_names",
None)` — a value PUBLISHED by `attach_inherited_fields`, which `parse_module` has
already run. So for a struct prepared the way this file prepares it, the field set
is a published value and the counter sees nothing. Measured:

```console
$ python3 - <<'PY'
… FB.parse_module(src); wrap M.struct_receiver_stores; parse; unwrap …
struct_receiver_stores calls during parse_module: ['S']
merged published: ('x',)
split (a fresh derivation): (['x'], [])
PY
```

**The derivation it wanted to count happens exactly once, during
`parse_module`, and that is the correct number** — one ask per struct, which is
the whole claim these four rows exist to hold down. The rows are asking it in the
one place where the answer is already published.

The failure mode this hides is worth stating: **the rows are the only place that
asserts the ask COUNT**, so if the threading regressed — a per-function asker
reappearing in `_prepare_functions`, which is
`bugs/PERF_struct_field_split_asked_once_per_function.md` and
`bugs/FORMAL_build_cost_2026-10-03.md` §3 — nothing in the everyday suite would
say so. The four rows are currently not saying anything at all, in either
direction.

## The second half, which is why it survived four rounds

**`test_formal_bracketed_method_field_set.py` is registered in NO BUCKET.**
`grep -n bracketed_method_field_set tools/suite.py` returns nothing, and it is
one of the formal files whose job is the field-set table. So this file is red and
nobody runs it: the four failures have been invisible, and `make gate` is green
over them. That is the shape
`TEST_registered_tests_in_no_bucket_never_run` was about, with the
stronger version — this one is not even registered.

## The exact next step

One change for the rows, and it is a small one: **count the asks where the work
happens.** Wrap `M.struct_receiver_stores` around the `FB.parse_module(...)` call
in `_field_set_case` instead of around the second `struct_field_names` call, and
assert the count there. That is the number the row wants (1 per struct, measured
above) and it is asserted at the point the derivation runs rather than at a
reader of its published result. `_split_declaration` is the alternative
counting point — it does derive — and it is the worse one because
`struct_field_names` no longer goes through it for a struct `parse_module`
prepared, so the count would be measuring a path no caller takes.

Then **register the file in a bucket** (`tools/suite.py`), so the next red is
visible. `test_formal_frame_field_census.py` and `test_formal_field_walk.py` are
the same area and are the rows to put it beside; `CLAUDE.md`'s rule is that a
registered test is a bucket member unless it declares `dep=True`, and
`test_suite.py`'s `the buckets:` checks it in both directions.

Verify with

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_bracketed_method_field_set.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_suite.py
```