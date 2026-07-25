# PARSE_FAIL: an annotation starting with a non-name token (literal, `[`, `{`) still doesn't consume a trailing binary op

## Repro

```python
a = 1
def f(radd: 1 + a):
    pass
print("ok")
```

```
$ python3 mojo.py run repro.py
SyntaxError: repro.py:2:14: Expected NAME or KW got OP('+')
```

Real stdlib trigger: `Lib/test/test_annotationlib.py`'s `test_reverse_ops`
(around line 334): `radd: 1 + a` — found immediately after fixing the
sibling bug in `bugs/PARSE_FAIL_annotation_trailing_binary_op.md` (commit
`6e6020f`), which fixed a NAME-shaped annotation prefix followed by a
trailing operator (`gamma: some < obj`) but explicitly left this case
(a NUMBER/literal-shaped prefix followed by a trailing operator) open, per
that task's scope.

## Root cause

`mojo_compiler.py`'s `_parse_type_ann_inner` has several branches for a
non-name-shaped token occupying the annotation's first position — the
`LBRACKET` opaque-capture branch, the `LBRACE` opaque-capture branch, and
the final catch-all single-token fallback (`else: return prefix +
self._advance().value`), all added by commit `6ee8291`. Commit `6e6020f`
then added `_consume_trailing_annotation_ops(name)`, a shared helper that
swallows a trailing `|`/`&`/other-operator continuation as opaque text —
but only wired it into the two exit points reached by the NAME/KW path
(the normal fall-through after building a dotted/subscripted name). The
`LBRACKET`/`LBRACE`/catch-all branches all `return` immediately without
ever calling `_consume_trailing_annotation_ops`, so an annotation starting
with e.g. a bare `1` (a NUMBER token, hitting the catch-all `else` branch)
returns right after consuming just that one token, leaving `+ a` dangling
for the caller to choke on — the exact same class of bug as the one just
fixed in `6e6020f`, just via a different entry branch.

## Suggested fix

Route the `LBRACKET`, `LBRACE`, and catch-all single-token branches through
the same `_consume_trailing_annotation_ops(name)` helper before returning,
instead of returning the bare captured text directly — mirroring how the
NAME/KW path already does this since `6e6020f`. Should be a small,
mechanical change now that the shared helper exists; the main risk is
making sure the helper's terminator-detection still behaves correctly when
called from these different entry shapes (verify by testing all of
`test_reverse_ops`'s / `test_nonexistent_attribute`'s annotation shapes
together, not just `radd: 1 + a` in isolation).
