# CODEGEN: a dict subclass's `__missing__` value is discarded and the absent slot read as 0

Found 2026-11-20 while fixing
`CODEGEN_try_except_around_builtin_errors` (dict subscripts now raise a real
KeyError). This one is pre-existing: the same program prints `0` on a pristine
`git archive HEAD` tree.

## Repro `missing_method.py`

```python
class D(dict):
    def __missing__(self, k):
        return "miss:" + k

def main():
    d = D()
    d["a"] = 1
    print(d["a"], d["zz"])
main()
```

`python3 tools/pydiff.py missing_method.py`:

```
line 1: CPython '1 miss:zz'   compiled '1 0'
```

## Why

The generated C for `print(d["a"], d["zz"])` computes the `__missing__` arm
correctly:

```
bb_4:                              # the key is absent
  _t11 = D___missing__ (d, _t5);
  _t13 = (int64_t)_t11;
  _t8  = _t13;
  goto bb_5;
bb_5:
  _t14 = mojo_dict_slot_boxed (_t6, _t5);   # <-- re-read, absent -> 0
  mojo_cstr_or_int_str (_t14) ...
```

The value that is printed is `_t14`, a fresh `mojo_dict_slot_boxed` read of the
same key, not `_t8`/`_t18` that the subscript computed. That re-read is
`_box_escaping_dict_slot_read` (mojo/backend_gimple/emit_calls.py) acting on the
`_dict_slot_reads` entry `_ls_dict_subclass` recorded: the escape path assumes
the read named a SLOT, and a `__missing__` result is not in the dict at all.

## Next step

The `__missing__` arm of `_ls_dict_subclass` must hand back the computed word as
already-boxed (the method's return type is unknown, so it is a tagged word) and
must not record a `_dict_slot_reads` entry for it, so neither the print path nor
the return path re-reads the dict. The plain (no `__missing__`) subclass arm can
keep the slot boxing. Add the repro above as a `test_gimple_matches_cpython` case
beside `gimple_caught_exception_message`; it fails before the change and passes
after.
