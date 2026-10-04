# The bracketed-method field-set suite asks for exactly one census on the path that never makes one

**Area:** `test_formal_bracketed_method_field_set.py` (the four
`a_*_is_a_field` rows) · **filed 2026-10-04 during the formal21 merge, NOT
fixed** · pre-existing on `master` (`8b1ab466`), not a merge regression

Four of that file's 26 cases fail, all four with the same message:

```
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_bracketed_method_field_set.py
  FAIL  a_declared_name_that_is_also_a_method_stays_a_field: deriving the field
        set of a 2-method struct asked struct_receiver_stores 0 times; it is a
        property of the STRUCT, so it is asked once
  FAIL  a_store_in_another_method_keeps_the_name_a_field: … 3-method struct …
        asked struct_receiver_stores 0 times …
  FAIL  a_store_through_this_and_inside_a_nested_def_is_a_field: … 1-method …
  FAIL  chained_augmented_and_tuple_stores_are_all_stores: … 1-method …
bracketed method field set: PASS=22 FAIL=4
```

## Why it is not a merge regression

The whole chain the assertion walks is byte-identical to `master`'s, and none of
the seven merged branches touched it:

```
$ git diff master HEAD -- formal/model.py formal/build.py \
    | grep -E '^[-+].*(_split_declaration|parse_module|struct_field_names|_pre_rule_field_names|_own_field_names|struct_demoted_method_names|struct_method_receiver_reads)'
0
$ git diff master HEAD --stat -- test_formal_bracketed_method_field_set.py
(empty)
```

## What the file says against itself

`struct_field_names` answers from the inheritance MERGE when one is attached and
only falls through to the walk when it is not (`formal/model.py`, unchanged):

```python
    merged = struct_merged_field_names(struct_def)
    if merged is not None:
        return list(merged)
    return _own_field_names(struct_def)
```

and `struct_receiver_stores` is reached only from
`_pre_rule_field_names` → `struct_method_receiver_reads`. The case runner sets
that merge up on purpose — its own docstring says so:

> Read through `formal.build.parse_module` rather than `fire_compiler` alone
> because the evidence `_split_declaration` needs is attached there — a struct
> with no evidence attached reports no split at all …

So on the path the runner builds, `struct_field_names` returns the merged list
and the census is not made; the assertion then demands exactly one census. The
file's other field-set rows go through the `_pre_rule_field_names` path on
purpose, and those rows are the ones the "asked once" claim is really about.

## Next step

Decide which of the two is the claim, and make the file say it once:

* **The census IS asked once per struct** — then assert it where it is made:
  drop the evidence (or call `_pre_rule_field_names` directly) in the counting
  step, so the count is measured on the path that makes it. That keeps the
  property the assertion was written for — "a per-method question must not
  become a per-method-squared census" — and it is the property
  `struct_demoted_method_names`'s own docstring argues.
* **The census is NOT asked on this path** — then the assertion is measuring the
  wrong thing and should be dropped rather than relaxed: what it wants to know
  is that the answer is not recomputed per method, and the answer being a
  constant-time lookup of a merged list satisfies that more strongly.

Either way the file's docstring and its assertion have to stop disagreeing, which
is the only reason this is filed rather than fixed: the choice above is a
statement about what the field-set rule is FOR, and it belongs to whoever owns
`struct_field_names`.