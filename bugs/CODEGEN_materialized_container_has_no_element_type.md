# CODEGEN: `list(<a boxed dict>)` reads every key as the decimal of its own address

Found 2026-10-01 while fixing `“CODEGEN: `list(x)` of an erased tuple element is an empty list”`
(removed with that fix). That fix made `list(x)` dispatch an argument whose
kind is not statically knowable through `_materialize_as_list`, which is the
right chokepoint and answers list / dict-keys / set correctly **by count and
order**. The ELEMENT TYPE of that answer is still a compile-time question, and
for the dict branch the compile-time answer is the wrong one.

## Status: OPEN. Measured, narrow, and the fix is a shape that does not exist yet.**

## What it does

```python
def ident(x):
    return x
def main():
    d = {"k": 1, "j": 2}
    print(list(ident(d)))
main()
```

CPython: `['k', 'j']`. Compiled (both pipelines, exit 0):

```
[4313651808, 4313651824]
```

The count and the order are right — those are two keys' own addresses, in
insertion order. Only the accessor is wrong: `mojo_dict_keys` builds a list of
`char *`, and the comprehension reads it with `mojo_list_get_int`.

## Why the obvious fix is wrong (measured, and it is a trap worth recording)

`_materialize_as_list`'s opaque arm merges FOUR different containers into one
temp: dict-keys, set-elements, a registered list, and a boxed value. The
element type is a property of WHICH ONE. Recording `char *` on the merged temp
for the dict branch is therefore a lie for the other three, and it was tried:

`a, b = <a boxed int tuple>` — the shape every generator's tagged stack slot
takes, and two rows of `test_gimple_generator_runner.py` —
`generator_pops_heterogeneous_tagged_stack` and
`generator_pops_stack_two_level_tuple_unpack` — went from `7 / 99 / 3` to
`4382923312 / 99 / 4382923328` and `151 / 60` to `4380056144 / 4380056160`
on that one line, because the loop variable became `char *` and every slot was
read with `mojo_list_get_str`.

The static `src_type == 'MojoDict *'` arm can record `char *` because there is
exactly ONE arm. There is no static answer here, and there will not be one.

## What was run

```
python3 .tmp/probe2.py <fixture>       # compile_to_gimple, both do_imports and
                                      # link_mode, gcc -fgimple + fire_runtime.c,
                                      # diff stdout against CPython
```

* with the `_elem_types` record: two generator rows fail as above;
* without it: `list(<boxed dict>)` prints the two addresses;
* without either (this doc's state): the two generator rows pass and the
  addresses are printed.

## Next step

Per-ELEMENT runtime typing, not per-temp compile-time typing. The pieces
already exist and this is the first consumer that needs all three at once:

1. `mojo_list_get_boxed` (`runtime/fire_runtime.c`) reads one slot with the
   kinds side table deciding how — used today for a `double` slot.
2. `gen._maybe_kinds_vals` is the codegen's "this value may be boxed" registry
   that `emit_exprs` / `emit_calls` / `emit_loops` already consult to choose
   `mojo_list_get_boxed`.
3. `_tagged_dyn_read` (`emit_infra.py`) is the reader that turns such a slot
   back into a `char *` / list / double / int at the use site.

So the shape is: `mojo_dict_keys` marks its own result as all-`char *`
(`mojo_list_set_kinds(keys, "ssss…")`), the merged temp is registered in
`_maybe_kinds_vals` whenever the dispatch was reached through an AMBIGUOUS
handle, and `_compr_list_loop`'s accessor choice (it currently reads
`gen._elem_of(_iv)`) consults that registry the way `emit_exprs` does. Every
one of the five other `_materialize_as_list` consumers — `all`, `any`,
`enumerate`, `str.join`, `bytes.join`, `shlex.join` — has the same hole today
and is fixed by the same change, which is the argument for doing it here
rather than per-call-site.

Not a `list()` problem: `list(<a registered dict>)` is already correct, and
`list(<a dict through a `MojoDict *`-typed local>)` too. It is specifically a
value whose container KIND is a runtime fact.

## Status (2026-10-02, `work/bugs4-3-c`) — the CONSUMER half of this fix already exists; only the producer half is missing

Re-measured on this tree, unchanged: `print(list(ident(d)))` prints two
addresses where CPython prints `['k', 'j']` (`[4335802768, 4335802784]`, exit
0). Nothing here is fixed and nothing regressed.

What did change is that this doc's "Next step" describes a three-part shape as
if all three had to be built. Two of the three are already there, and naming
them turns a large change into two lines:

1. **`mojo_list_set_kinds`** — exists (`fire_runtime.{c,h}`; called from
   `_lower_list_literal`'s per-element byte alphabet,
   `_list_literal_slot_kind`'s `TypeLattice.slot_kind_byte`).
2. **The registry** — `gen._maybe_kinds_vals` (declared in `gimple_codegen.py`
   with its own rationale).
3. **The reader** — `mojo_list_get_boxed`, and the consumer half is ALREADY
   WIRED in two places:
   * `emit_loops.py`'s list-loop accessor takes the `_mkv` arm
     (`it_val in _maybe_kinds_vals or list_ptr in _maybe_kinds_vals`) and emits
     `mojo_list_get_boxed (list_ptr, i)`, marking the loop target in
     `gen._boxed_vals` so `print`/`str` resolve the box;
   * `emit_exprs.py`'s subscript path consults `_maybe_kinds_vals` the same
     way (its `kind != 'dict'` guard).

So `_compr_list_loop`'s accessor does NOT need to be taught anything — it
already asks. What is missing is the PRODUCER side, and it is exactly two
statements in `_materialize_as_list`'s opaque arm: emit
`mojo_list_set_kinds(result, "ssss…")` inside the `bb_dict` branch (the length
is a runtime fact — `mojo_list_len` of the keys list — so the alphabet has to
be built from it, or `mojo_list_set_kinds` must accept a sentinel), and add
`result` to `gen._maybe_kinds_vals`.

**The trap to re-measure first is the one this doc already names.** Marking the
MERGED temp means the set / registered-list / boxed-value branches are read
through `mojo_list_get_boxed` too, which is a different accessor from the
uniform-suffix one they take today (`emit_loops`'s own comment says a list with
no kinds of its own "takes the identical accessor it always did and yields the
identical word" — that sentence stops being true the moment the temp is marked,
so the property has to be re-established rather than assumed). The two rows to
watch are `test_gimple_generator_runner.py`'s
`generator_pops_heterogeneous_tagged_stack` and
`generator_pops_stack_two_level_tuple_unpack`, which are the ones the earlier
`_elem_types` attempt broke (`7 / 99 / 3` -> `4382923312 / 99 / 4382923328`).
