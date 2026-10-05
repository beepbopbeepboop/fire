# RUNTIME: `for k, *rest in <dict>` binds the whole key instead of unpacking it

Found 2026-10-02 while fixing the `*rest` element in a `for` target that was
lowered as a C slot literally named `*rest` (fixed and deleted; the mechanism
is `mojo/middle/loops_shared.py`'s `starred_slot_index` /
`starred_slot_name` / `_emit_starred_slot_list`, consumed by
`emit_loops.py::_gen_for_list`, with `for_target_starred_rest` in
`test_runtime_diff.py` as the regression). Its compiled-path half is fixed;
this is the OTHER engine, and the compiled path now refuses the shape rather
than disagreeing with this one.

## What I ran

```python
def main():
    d = {"abc": 1, "de": 2}
    for k, *vs in d:
        print(k, vs)
main()
```

| engine | output |
|---|---|
| `python3` (CPython 3.14) | `a ['b', 'c']` then `d ['e']` |
| `python3 fire.py run` (interpreter) | `abc []` then `de []` |

Iterating a dict yields its KEYS, and a key is a `str`, so the target unpacks
the key string: `k` is its first character and `vs` is the list of the
remaining ones. The interpreter binds the whole key to `k` and hands `vs` an
empty list.

## Why this is a separate bug from the compiled-path one

The compiled path had the same shape wrong in a much louder way — `*vs`
reached the C declarator as `int64_t *vs;` and the store after it was a write
through an uninitialised pointer (SIGBUS, exit -10). That is fixed and
deleted. What remains is that the INTERPRETER is wrong about what the star
means here, and the compiled path cannot be moved to CPython's reading without
the two engines then disagreeing with each other on a shape
`test_runtime_diff.py` checks (interp vs jit, plus CPython where the program
runs under all three).

So today the compiled path emits the standard loud refusal
(`_emit_unsupported_iter`, "for loop over unsupported iterable type dict") and
the interpreter keeps its own wrong answer. Both need the same fix, in the
interpreter's binder first — which is where CPython's own
`UNPACK_EX`/`before`/`star`/`after` arithmetic has to be mirrored for a
`str` item rather than a sequence.

## Exact next step

1. `myinterpreter.py`, the binder `_bind_comprehension_target` (or whichever
   function `_gen_stmt_ForStmt` reaches for a for-loop target — the same
   `star_idx` branch the CODEGEN doc names). It handles a LIST item today; a
   `str` item needs the same before/star/after split over the string, with
   each remainder element a 1-character string.
2. Only then: `mojo/backend_gimple/emit_loops.py::_gen_for_dict`'s refusal
   becomes a lowering (a counted loop of `mojo_cstr_slice(key, i, i + 1)`
   appends, with the slots after the star counted from the END of the key),
   and the refusal in place of it is deleted.
3. Regression: `test_runtime_diff.py`, a CPython-comparable case
   `for_target_starred_rest_over_a_dict` with this exact program. It must not
   be added before step 1 — `test_runtime_diff` would go red on the
   interpreter, not on the compiled path.
