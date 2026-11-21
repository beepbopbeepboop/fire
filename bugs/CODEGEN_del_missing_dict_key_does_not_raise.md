# CODEGEN: `del d[missing]` silently does nothing instead of raising KeyError

Found 2026-11-20 while fixing
`CODEGEN_try_except_around_builtin_errors` (a bare dict subscript of a missing
key now raises). This one is pre-existing: identical on a pristine
`git archive HEAD` tree.

`mojo/backend_gimple/emit_stmts.py::_gen_stmt_DelStmt` lowers `del d[k]` to
`mojo_dict_pop_int(d, k, 0)` — the *defaulted* pop, whose miss arm returns the
default. CPython's delete is not a pop with a default: a missing key raises
KeyError, and a handler is expected to run.

## Repro `del_missing.py`

```python
def main():
    d = {"a": 1}
    try:
        del d["y"]
    except KeyError:
        print("del caught")
    print(len(d))
main()
```

`python3 tools/pydiff.py del_missing.py`:

```
line 1: CPython 'del caught'   compiled '1'
```

## Next step

Add a runtime `void mojo_dict_del_item(MojoDict *d, char *key)` (plus the
`_kw` twin for a word key, and put the pair in `_KW_DICT_FNS`): a frozen dict
raises the existing TypeError, an absent key raises `mojo_raise_key_error(key)`
through the same typed-exception path the new `mojo_dict_subscript_*` family
uses, and a present key runs `_dict_remove_slot`. Emit it from both `del`
branches in `_gen_stmt_DelStmt` (the statically typed `MojoDict *` arm and the
dynamic dict/list dispatch arm). Add the program above as a
`test_gimple_matches_cpython` case.
