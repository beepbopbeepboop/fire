# CODEGEN: `{id(a), id(b)}` keeps one element when the two containers have equal content

Found 2026-11-20 by `test_gimple_runner.py`'s `gimple_id_is_an_integer`, which is
red on master (650 passed / 1 failed). The finding is pre-existing: the same
program gives the same answer on a pristine `git archive HEAD` tree.

`gimple_id_is_an_integer` builds `ids = {id(a), id(b), id(a)}` with
`a = [1, 2]` and `b = [1, 2]`, and CPython answers `len(ids) == 2` while the
compiled binary answers `1`. With `b = [3, 4]` the compiled answer is `2`, so
the element being deduped depends on the LISTS' CONTENT, not on their identity.

## Repro `id_set.py`

```python
def main():
    a = [1, 2]
    b = [1, 2]
    ids = {id(a), id(b), id(a)}
    print(len(ids))
main()
```

`python3 tools/pydiff.py id_set.py`:

```
line 1: CPython '2'   compiled '1'
```

## Why

`mojo_id` (runtime/fire_runtime.c) returns a kind-`'i'` `MojoBox` holding the
object's word, one per object. `mojo_set_add_word` sees `mojo_is_boxed(w)`,
finds a kind that is neither `'n'` nor `'s'`, and does `w = bx->bits` — it
unwraps the token back to the CONTAINER POINTER. `mojo_set_add_int` then calls
`_set_word_key(v)`, and `mojo_is_registered_list(v)` is true for that pointer,
so the slot is probed with `_container_key_str(v)` — a CONTENT key. Two lists
whose contents are equal therefore collapse into one set element, and
`id(a) == id(b)` becomes false while the set says they are the same element.

## Next step

An id token has to stay an integer all the way through, so the container-key
path never sees it. Do one of:

1. Make the kind-`'i'` box a first-class int word: `mojo_int_of_word` answers
   the box WORD (its address) for kind `'i'` instead of `bx->bits`, and
   `mojo_set_add_word` / `mojo_set_contains_word` / `mojo_set_discard_word`
   keep that same word instead of unwrapping. Then `id(x) == int(id(x))` still
   holds, two objects get two set elements, and a dict keyed by `int(id(x))`
   still finds what it stored. Check `mojo_box_int`, which has the same
   unwrap.
2. Or give `mojo_id` a token representation that is not a live pointer at all
   (an index into `_id_tab`, biased out of the `mojo_boxed_is_str` window), so
   no predicate can classify it as a container or a string.

Then `python3 test_gimple_runner.py` must be green again, and this program must
be added as a `test_gimple_matches_cpython` case beside
`gimple_id_is_an_integer` (that case is the wider contract; this one is the
minimal shape).
