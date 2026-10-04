# CODEGEN: a merge dropped `GimpleGen._emit_dict_int_value_store`, and four dict/bytes tests die with `AttributeError`

## What was run

```sh
python3 test_gimple_runner.py          # 293 passed, 10 failed
```

and, to pin the class of failure rather than the count:

```python
>>> import gimple_codegen
>>> hasattr(gimple_codegen.GimpleGen(), '_emit_dict_int_value_store')
False
>>> hasattr(gimple_codegen.GimpleGen(), '_note_dict_callable_ret')   # its neighbour
True
```

## What was seen

Four of the ten failures are one bug, not four:

```
FAIL  gimple_bytes_membership_in_containers: 'GimpleGen' object has no attribute '_emit_dict_int_value_store'
FAIL  gimple_bytes_membership_across_domains: 'GimpleGen' object has no attribute '_emit_dict_int_value_store'
FAIL  gimple_bytes_dict_key_domain: 'GimpleGen' object has no attribute '_emit_dict_int_value_store'
FAIL  gimple_bytes_dict_get_pop_bytes_key: 'GimpleGen' object has no attribute '_emit_dict_int_value_store'
```

The one call site is `mojo/backend_gimple/emit_stmts.py:1513` — the
`d[bytes_key] = <non-str value>` store, the arm that keeps a bytes key in
the runtime's own key domain (`_DictSlot.keykind`) instead of casting the
`MojoBytes *` to `char *`:

```python
if vtype == 'char *':
    gen._emit_call('void', '', 'mojo_dict_set_bytes_str', [...])
else:
    gen._emit_dict_int_value_store(obj_v, 'MojoBytes *', idx_v, vtype, v, node.value)
```

`mojo/backend_gimple/emit_infra.py:4500` defines the implementation
(`emit_dict_int_value_store`) and its docstring names all five callers it
was consolidated from. What is missing is only the `GimpleGen` method that
delegates to it — the same one-line delegation every other `ginf.*` helper
has.

## What was expected

`gimple_codegen.py`'s `GimpleGen` to carry

```python
def _emit_dict_int_value_store(self, dict_val: str, key_ctype: str,
                               key_val: str, val_ctype: str, val: str,
                               val_node=None) -> None:
    return ginf.emit_dict_int_value_store(self, dict_val, key_ctype, key_val,
                                          val_ctype, val, val_node)
```

## Root cause: a merge resolution took one side of `gimple_codegen.py` and the other side of `emit_stmts.py`

`git log -S '_emit_dict_int_value_store(self, dict_val' -- gimple_codegen.py`
names exactly one commit, `38ca3691` ("A bool-annotated struct field prints
as True/False, and a bool dict value no longer poisons its neighbours"),
which added the delegate. Per-commit presence across the merge range:

| commit | delegate in `gimple_codegen.py` |
|---|---|
| `38ca3691` | yes |
| `a1d0c8a1` (merge of `work/bugs3-codegen-1-r2`) | **no** |
| `HEAD` | no |

`a1d0c8a1`'s own message records that the conflict was resolved file by
file — "the other seven files take theirs — which is where the actual fixes
are". `gimple_codegen.py` is the aggregator of `mojo/backend_gimple/*`, so
taking master's copy of it wholesale kept every delegation master had and
none of the ones the branch added, while `emit_stmts.py` took the branch's
copy and kept its new call site. The result is a call to a method that does
not exist, which is an `AttributeError` at codegen time — so these four
tests fail on a name that never reaches gcc, and no exit code anywhere else
in the tree reports it.

Not attributable to `bugs4-*`: `gimple_codegen.py`'s `GimpleGen` block is
outside every doc those branches hold, and the four tests are `do_imports=False`
single-file programs, so nothing about their behaviour changed.

## Next step

Restore the five-line delegation above next to its `_note_dict_callable_ret`
neighbour in `gimple_codegen.py` (it is still absent, and
`mojo/backend_gimple/emit_infra.py:4500` is the implementation to forward
to), then re-run `test_gimple_runner.py` and confirm the four
`gimple_bytes_*` names pass.

Worth checking alongside it, because the same merge is the suspect: the
other six failures in that run are
`gimple_sorted_string_key_runtime_built`
(`CODEGEN_sorted_key_of_runtime_built_strings_sorts_by_address`),
`gimple_tuple_dict_key_is_content_keyed`
(`bugs/CODEGEN_dict_comprehension_repr_is_separately_broken.md`),
`gimple_bool_annotated_struct_field` ×2
(`bugs/CODEGEN_bool_annotated_struct_field_prints_as_int.md`) and
`gimple_char_scan_allocates_nothing_per_character`
(`“PERF: the per-character `str` scan allocated one `malloc(2)` per character”`),
`gimple_dict_of_bool_values`. Each has a doc, so each is a separate
question — but `gimplerunner` carries no `expect=` marker in
`tools/suite.py`, so all ten are currently red against a gate that reports
no known failures there.
