# A bytes-keyed dict store with a non-str value calls `gen._emit_dict_int_value_store`, which does not exist

Found 2026-10-02 while narrowing a different doc's blast radius. **Not**
mine and not in anyone's claim: it is the bytes-KEY domain of the dict store
path, and no registered doc names it.

## What I saw

Four registered tests in `test_gimple_runner.py` fail with a hard
`AttributeError` rather than a wrong value:

```
FAIL  gimple_bytes_membership_in_containers: 'GimpleGen' object has no attribute '_emit_dict_int_value_store'
FAIL  gimple_bytes_membership_across_domains: 'GimpleGen' object has no attribute '_emit_dict_int_value_store'
FAIL  gimple_bytes_dict_key_domain: 'GimpleGen' object has no attribute '_emit_dict_int_value_store'
FAIL  gimple_bytes_dict_get_pop_bytes_key: 'GimpleGen' object has no attribute '_emit_dict_int_value_store'
```

Verified on this branch and on its base (reverting every change in the branch
reproduces all four identically), under `python3 test_gimple_runner.py`:
`300 passed, 10 failed`, these four among the ten.

## The mechanism

`mojo/backend_gimple/emit_stmts.py:1561`, inside the `d[key] = value`
statement lowering's bytes-key arm:

```python
            if it == 'MojoBytes *':
                # A bytes KEY is its own key domain in the runtime ...
                if vtype == 'char *':
                    gen._emit_call('void', '', 'mojo_dict_set_bytes_str',
                                    [('MojoDict *', obj_v), ('MojoBytes *', idx_v), ('char *', v)])
                else:
                    gen._emit_dict_int_value_store(obj_v, 'MojoBytes *', idx_v,
                                                  vtype, v, node.value)
```

The function it calls does not exist. The one that does is
`mojo/backend_gimple/emit_infra.py:4510`:

```python
def emit_dict_int_value_store(gen, dict_val: str, key_ctype: str, key_val: str, ...
```

— no leading underscore, and (checked) **not** among `gimple_codegen.py`'s
`GimpleGen` delegates, which is the only way a `gen._…` name in this codebase
resolves. The sibling `str`-keyed branch two lines above calls
`gen._emit_call`, which is a real delegate; this one is the odd spelling out.

So the trigger is precise: **a bytes key with a value that is not a `char *`**.
`d[b'x'] = 1` reaches the `else` and raises; `d[b'x'] = 's'` does not, and
`{b'x': 1.5}` at a literal store goes through `_emit_dict_pair_store` rather
than this statement path, which is why only some of the four cases fail.

## Why it matters beyond the four tests

* It is an **`AttributeError` during compilation**, i.e. a compiler crash on a
  perfectly ordinary line of Mojo. A hard failure is better than a silent
  wrong value, but it is a hole in a registered gate test, and a
  `d[b'k'] = <non-str>` in real code takes the whole module down.
* The docstring right below the call site describes `emit_dict_int_value_store`
  as if it is the thing that routes a bool RHS through `mojo_dict_set_bool`
  and tags that slot — so the intended target is unambiguous. This is a
  rename/delegate that was missed, not a design question.

## Exact next step

Add the delegate, beside its siblings in `gimple_codegen.py`'s `GimpleGen`:

```python
    def _emit_dict_int_value_store(self, *args):
        return ginf.emit_dict_int_value_store(self, *args)
```

then run `python3 test_gimple_runner.py` and check what the four cases
actually assert — they were written against a build where this path worked,
so they may well pass, and they may equally expose a second gap behind this
one. Do that before assuming one line was the whole thing.

An `emit_stmts.py` import of `emit_infra` would be the alternative, but the
delegate is what every other `gen._…` call in this file already uses, and
mixing the two spellings in one file is how this happened.