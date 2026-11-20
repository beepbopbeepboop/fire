# CODEGEN: a parameter annotated `str` that the body contradicts (rebinds to a list, receives None/True) gives wrong values

Found 2026-11-20 while closing `c_common/scriptutil.py` (the module now builds). CPython does not enforce
annotations, so real code lies in them. The compiler treats a `str` annotation as the parameter's C type
(`char *`) for the whole body and at every call site, and a program that contradicts it computes the wrong
thing without a diagnostic.

## Reproduction

`Tools/c-analyzer/c_common/scriptutil.py` (copied under `build/remes/ca/c_common/`), reduced:

```python
def normalize_selection(selected: str, *, possible=None):
    if selected in (None, True, False):
        return selected
    elif isinstance(selected, str):
        selected = [selected]          # rebinds a `str` parameter to a LIST
    elif not selected:
        return ()
    ...
    if 'all' in _selected:
        return True
    return frozenset(selected)         # selected is the list here
```

Each call run alone and compared with CPython (2026-11-19, after the tagged-return fixes):

| call | CPython | compiled |
|---|---|---|
| `normalize_selection(None)` | `None` | `None` (fixed: `mojo_box_from_str(NULL)` is the None box) |
| `normalize_selection(True)` | `True` | a decimal number: the call site converts the `True` argument to a `char *` with `mojo_bool_to_str`, so `selected` is the string `"True"` and no arm matches |
| `normalize_selection('')` | `frozenset({''})` | `{<five addresses>}`: `selected = [selected]` stores a `MojoList *` in the `char *` variable, so `frozenset(selected)` iterates the characters of the list struct |

The unannotated spelling is no better (`None` -> `0`, `True` -> `1`, the rest segfault): a parameter of unknown
kind is an `int64_t` word and the membership/`isinstance` arms do not recover its kind.

## Why it matters

`normalize_selection(None)` is what `c_analyzer` calls. It no longer crashes, but any caller passing a
bool, or a string that takes the list path, gets a silently wrong value.

## What a fix needs (decisions first)

1. A parameter whose body REBINDS it to a different kind (here `str` -> list) cannot keep the annotation's C
   type. Either the local takes the tagged word for its whole life (the multi-kind-locals machinery the
   non-parameter case already uses) or the rebinding is refused with a diagnostic that names the parameter,
   its annotation and the rebinding's kind. Silent reinterpretation, the current behaviour, is the one answer
   that cannot stay.
2. A call-site argument whose kind contradicts a `str` annotation (`True`, `5`) is converted by
   `mojo_bool_to_str` / `mojo_str_from_int` today. Real Mojo would reject the call. Decide: refuse at the
   call with a type diagnostic, or pass the tagged word through when the callee's body reads the parameter
   as a word.
3. The membership arm `selected in (None, True, False)` on a `char *` needle already works for the NULL
   needle (`mojo_list_contains_str` matches a None-kind slot).

## Tests that will prove it

A compiled-vs-CPython case in `test_gimple_runner.py` over the five calls above (the set arm sorted so its
order is deterministic), plus the general shape in both directions (`int` parameter rebound to a list,
`str` parameter rebound to an int, and a same-kind `str` rebound that must keep its string type).

## Done when

`test_gimple_runner.py::test_param_annotation_contradicted_by_the_body` passes: the annotated parameter
rebound to a list (and the int/str neighbours) matches CPython, with the set arms compared by sorted content
because this runtime's `frozenset` has no frozen marker to spell.
