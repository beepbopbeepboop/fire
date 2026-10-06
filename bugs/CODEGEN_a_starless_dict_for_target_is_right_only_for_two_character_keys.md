# CODEGEN: a starless `for k, v in <dict>` is right only for keys of exactly two characters

**Area:** `mojo/backend_gimple/emit_loops.py::_gen_for_dict` (the `star_idx < 0`
branch of the store side, lines ~2588-2612). **Found 2026-10-04** while landing
`for k, *rest in <dict>` (the star half of the same loop is now correct — this
is about the shape NEXT to it, which that change did not touch). Pre-existing
and not introduced by it: the `literal 0` stand-in is stated in the code's own
comment and predates the star work.

## What I ran

```console
$ cat .tmp/k/t7.mojo
def main():
    d = {"abc": 1, "de": 2}
    for k1, v1 in d:
        print(k1, v1)
    ...

$ python3 .tmp/k/t7.py
ValueError: too many values to unpack (expected 2)

$ python3 tools/memslot.py --gb 8 --label t -- python3 fire.py --jit .tmp/k/t7.mojo
abc 0
de 0
```

CPython refuses the whole loop, because a dict item is the KEY and `"abc"` is
three characters, so there is no second value to bind. The compiled path binds
`k1` to the whole key and `v1` to the literal 0 — which is its documented
stand-in:

```python
        # row (slot 0 is the key; every later slot is the literal 0, the
        # starless lowering's stand-in for a pair's value).
```

That is right for a **list of pairs** (`for k, v in d.items()` yields a
2-element list) and wrong for a **dict**, whose item is a key and has whatever
length the key has.

## Why it is not free to fix by "just arity-check it"

`for name, func in self.funcs:` is real source in this repository, and there
`funcs` is a list of `(name, fnptr)` tuples — a shape `_gen_for_list` handles
and this branch's `int_keys` sibling does not touch. The `_gen_for_dict`
starless branch exists for `for k, v in d` spelled over a DICT, and CPython
refuses exactly that spelling whenever a key is not two characters. So the
honest fix is a runtime length check here of the same kind the star branch now
emits (`mojo_raise_value_error`, the mechanism `emit_calls.py`'s slice-step check
uses): `_klen != <number of slots>` means the key is not a pair at all.

The check must be `!=` and not `<`: a 3-character key over a 2-slot target is
the case that currently produces `abc 0` silently, and `!=` catches it and the
1-character case in one test.

The interpreter is already right about this one (it raises ValueError, measured
in the commit that added the arity check there), so today the two engines
disagree, and the disagreement is invisible to `test_runtime_diff.py` because
the shape has no case there.

## Exact next step

1. In `_gen_for_dict`'s `star_idx < 0` store branch, read
   `mojo_strlen ((char *) key_tmp)` once and, when `len(var_names) != 2`,
   `mojo_raise_value_error` — the same emission shape as the star branch's
   `_klen < _req` check added with the dict-star lowering, and the same
   `gen._emit_call('void', '', 'mojo_raise_value_error', [('char *',
   gen._intern_string(...))])` form.
   **When `len(var_names) == 2`, emit nothing extra**: that is the two-character
   case the existing `key` / `0` pair is right about, and it is the shape real
   code relies on.
2. Add `for_target_starless_pair_over_a_dict_key` to
   `test_runtime_diff.py`'s `BUILTIN_PROGRAMS` **and** to `CPYTHON_COMPARABLE`,
   with a key that is three characters so the check is exercised. A `!=` check
   that only guards `<` would pass that case's stdout comparison and still be
   wrong; make the case print the key length as well as the pair.
3. `make gate`'s `gimple` + `stdlib-dylib` skip count: `emit_loops.py` is in the
   self-hosted compile closure, so a change there owes the `mojoc` and `stage*`
   steps and `stdlib-syntax`'s unexpected count.