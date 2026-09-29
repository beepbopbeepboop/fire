# CODEGEN: iterating a `Dict[Int, V]` yields the keys as strings, so integer use of them is wrong

## Status (2026-09-28 — OPEN, reproduced; predates the integer-slot work)

```mojo
def main():
    var d: Dict[Int, Int] = {}
    d[5] = 50
    d[7] = 70
    d[1] = 10
    var ks = 0
    for k in d:
        ks += k
    print(ks)              # 59030320 before; a different garbage number now  -- CPython: 13
    var tot = 0
    for kv in d.items():
        tot += kv[0] + kv[1]
    print(tot)             # 177053250 before; garbage now                     -- CPython: 143
```

`d[k]` lookups, `len`, `in`, `.get`, `.pop` and `.setdefault` are all correct; only the
keys that come back OUT of iteration are wrong. The runtime hands back each key as the
decimal string it has always stored (`mojo_dict_keys`/`items`, `MojoDictIter`), and codegen
types the loop variable `char *`, so `ks += k` adds string POINTERS. Printing `k` still
works (it is the string "5"), which is why this hides easily.

Integer keys are now stored as integer slots (`keykind == 2`, with the decimal string kept
in `key` for exactly this reason: nothing that reads a key as a string changed), so the
fix is available at the runtime level. It needs codegen to know a dict is Int-keyed:

- record the key type from the annotation (`Dict[Int, V]`, a parameter annotation, a
  dict literal with integer-literal keys) alongside `_dict_val_types`, which is tracked in
  ~100 places and is unreliable across a call boundary;
- for such a dict, iterate through `mojo_dict_keys_int`/`items_int` (returning integers,
  element type `int64_t`) instead of the string ones.

Not done here: an untyped consumer of an Int-keyed dict would then need the string form,
so the runtime must keep serving both, and the key-type tracking must fail closed (unknown
=> strings, as today).

## Done when

The repro prints `13` and `143`. Add both as `test_gimple_runner.py` cases.
