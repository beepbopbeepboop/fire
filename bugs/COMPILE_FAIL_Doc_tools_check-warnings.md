# COMPILE_FAIL: Doc/tools/check-warnings.py

Source file: `/Users/mrs/net/Python-3.14.6/Doc/tools/check-warnings.py`

## Status (updated 2026-08-06): FIXED (commit 9a2bb86)

```
error: passing argument 2 of 'mojo_range' makes integer from pointer without a cast
```
at:
```python
line_ranges = [
    range(line_b, line_b + added) for line_b, added in line_ints
]
```
where `line_ints = [(int(...), int(...)) for match_value in line_match_values]`
— a list of `(int, int)` tuples.

## Root cause

`_compr_list_loop` (gimple_codegen.py, the codegen for `[... for a, b in
X]`-shaped list/set/dict comprehensions) had a tuple-unpacking branch
that unconditionally read every unpacked slot via `mojo_list_get_str`
(treating every tuple as a string tuple), then always tagged the
resulting variable `self._actual_types[vn] = 'char *'` regardless of the
tuple's real element type.

For a genuinely NUMERIC tuple list (`[(1, 2), (3, 4)]`), the underlying
runtime storage is untyped 64-bit slots (`mojo_list_get_str`/`get_int`
are just different reinterpret-cast VIEWS onto the same raw `int64_t`
storage — confirmed in `runtime/mojo_runtime.c`), so the VALUE happens to
round-trip correctly (get_str's pointer reinterpretation, then cast back
to int64_t, preserves the original bit pattern) — but the STATIC type
tag was still wrong. `_lower_binary_tail` consults
`self._actual_types.get(rv, ...)` to override a variable's declared C
type when resolving a binary op's result type, so `a + b` (with `b`
wrongly tagged `char *`) was treated as pointer-typed, and the whole
`line_b + added` expression got passed to `mojo_range`'s int64_t `stop`
parameter without a cast — the reported error.

Minimally reproduced standalone:
```python
def main():
    pairs = [(1, 2), (3, 4)]
    ranges = [range(a, a + b) for a, b in pairs]   # was: compile error
```
and confirmed the underlying VALUE bug too (not just a compile error) via:
```python
def main():
    pairs = [(1, 2), (3, 4)]
    sums = [a + b for a, b in pairs]   # was: would have printed correctly
    for s in sums: print(s)            # by luck (bit-preserving round trip),
                                        # but any downstream check treating
                                        # a/b as pointers would have been wrong
```

## Fix

This exact bug (assuming every tuple slot is a string) was ALREADY found
and fixed once before, for the regular (non-comprehension) `for a, b in
pairs:` statement form — `_gen_for_list` (gimple_codegen.py:19374) picks
the accessor PER SLOT via three existing type-tracking mechanisms:
- `_dict_items_val_elems` — `dict.items()` pairs (key is always `char *`,
  value's type comes from the dict's own value type).
- `_tuple_slot_types` — heterogeneous tuple literals (`(name, func)` →
  `[char*, void*]`).
- `_nested_elem_types` — homogeneous tuple-literal lists.

`_compr_list_loop` (the comprehension-specific twin of that same
tuple-unpacking shape) never received the equivalent fix — it still had
the OLD, string-only logic `_gen_for_list` itself used to have (per that
function's own inline comment about the `dict.items()` regression it
fixed). Ported the exact same per-slot logic from `_gen_for_list` into
`_compr_list_loop`, rather than inventing new logic — a proven, already-
shipped pattern applied to its missed sibling.

Full quality gate verified clean: test_gimple.py 247/247,
test_module_cache.py 76/76, make check-selfhost clean, from-scratch
stdlib dylib rebuild 0 skips, compile_stdlib.py -j8 664/664 0 unexpected.
