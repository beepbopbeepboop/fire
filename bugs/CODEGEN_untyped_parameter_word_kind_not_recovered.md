# CODEGEN: an UNANNOTATED parameter that holds more than one kind does not recover its kind

Found 2026-11-20 while fixing the annotated spelling of the same shape
(`CODEGEN_param_annotation_contradicted_by_the_body`, deleted with its fix).
A parameter with NO annotation is declared the `int64_t` word, and every call
site passes the argument as a bare word: `None` is 0, `True` is 1, a string is
its pointer. The body's membership, `isinstance`, list construction and set
construction then read that word by one static kind and silently produce wrong
values (or crash). There is no annotation to contradict, so the fix that tags
an annotated parameter's slot does not fire for this spelling.

## Reproduction

```python
def normalize_selection(selected, *, possible=None):
    if selected in (None, True, False):
        return selected
    elif isinstance(selected, str):
        selected = [selected]
    elif not selected:
        return ()
    return frozenset(selected)

print(normalize_selection(None))
print(normalize_selection(True))
print(normalize_selection(False))
print(normalize_selection(''))
print(normalize_selection('a'))
```

Measured on this tree, `python3 tools/memslot.py --gb 8 --label untyped-param --
python3 <driver>`, compiled against CPython 3.14:

| call | CPython | compiled |
|---|---|---|
| `normalize_selection(None)` | `None` | `0` |
| `normalize_selection(True)` | `True` | `1` |
| `normalize_selection(False)` | `False` | `0` |
| `normalize_selection('')` | `frozenset({''})` | SIGSEGV |
| `normalize_selection('a')` | `frozenset({'a'})` | (not reached) |

The body lowers `selected in (None, True, False)` as
`mojo_list_contains_int` over the raw word, so a string's pointer is compared
as an integer and the first arm is never taken for it. `isinstance(selected,
str)` on a bare pointer is the runtime registry question and works for a
registered literal, but the rebind `selected = [selected]` then appends the
word through `mojo_list_append_int`, so `frozenset(selected)` iterates the
list slot as the pointer's integer value.

## Why it matters

The documented caller (`c_analyzer`'s `normalize_selection`, from
`Tools/c-analyzer/c_common/scriptutil.py`) is annotated `selected: str`, and
that spelling is now correct. Real Python code also contains the same function
without the annotation (and any parameter whose only evidence is body use),
where the compiler has no annotation to trust and currently guesses one kind.

## What a fix needs

1. Decide the representation for an unannotated parameter that the body uses
   as more than one kind. The annotated case's answer is the tagged
   `int64_t` word: calls box the argument by kind (`emit_infra._box_param_call_args`
   + `box_word_value`), a list literal appends a box word under its runtime
   kind (`emit_exprs._lower_list_literal`), membership asks the runtime
   (`mojo_in_dispatch_int`), and print/str/truthiness dispatch by kind.
   Applying the same model needs a DETECTOR: `_param_ctype` has no annotation
   to compare, so the evidence has to come from body use — a parameter read
   as a string/bool and also rebound to a container, or passed differently at
   call sites. `infra_infer._infer_local_var_types` already collects the
   binding kinds; `_infer_param_types`/Pass 1.3d already collect the call-site
   kinds.
2. Alternatively refuse the ambiguous parameter with a diagnostic naming it
   and the two observed kinds. Both answers end the silent reinterpretation;
   boxing is the one that keeps real Python code compiling.

## Done when

A compiled-vs-CPython case in `test_gimple_runner.py` over the five calls above
(annotated with the set arms sorted so their order is deterministic, exactly
as the deleted annotated doc's test does) matches CPython.
