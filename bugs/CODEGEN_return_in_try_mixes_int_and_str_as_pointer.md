# CODEGEN: `try: return d[key]` beside `except: return "missing"` returns the int slot as a pointer

Found 2026-11-20 by `tools/pydiff.py` on
`tools/pydiff_corpus/flow/13_try_except_builtin.py` while fixing
`CODEGEN_try_except_around_builtin_errors`. Pre-existing: the same program
SIGSEGVs on a pristine `git archive HEAD` tree.

The corpus program's first four prints now match; it then dies in `lookup`
(`d[key]` inside `try`, `"missing"` in the `except`), which has two return arms
of different types. The same crash is visible in a five-line program.

## Repro `lookup_try.py`

```python
def lookup(d, key):
    try:
        return d[key]
    except KeyError:
        return "missing"

def main():
    d = {"a": 1}
    print(lookup(d, "a"))
    print(lookup(d, "zz"))
main()
```

`python3 tools/pydiff.py lookup_try.py` reports `CRASH`, exit `-11` after
printing nothing (the crash happens before the first print flushes).

## Why

The generated C declares `lookup` as `char *` (the `return "missing"` arm) but
the present arm returns the dict slot without converting it:

```
bb_3:
  _t7 = mojo_dict_subscript_boxed (d, key);
  _t8 = mojo_dict_slot_boxed (d, key);   # escape re-read of the same slot
  _t9 = (char *)(int64_t)_t8;            # integer 1 becomes address 0x1
  ...
  return _t9;
```

`print` then treats `0x1` as a `char *` and dereferences it. The mixed
int/string return needs the tagged-word representation (`_ret_may_hold_mixed` /
`mojo_box_int`/`mojo_box_from_str`) or an honest refusal; a `try` arm is not
joining the representation the rest of the function's returns use.

## Next step

Find where the return type is chosen for a function whose arms are
`d[k]` (unknown/boxed value) and a `str`: it is picking `char *` from one arm
instead of the erased `int64_t` tagged word. Reproduce with the program above,
dump the generated C (`compile_to_gimple`) and follow the return-arm join;
then add this program as a `test_gimple_matches_cpython` case and re-run
`python3 tools/pydiff.py tools/pydiff_corpus/flow/13_try_except_builtin.py`.
Do not fold this into the dict-subscript KeyError fix — the crash is in the
mixed return representation, not in the presence test.
