# PARSE_FAIL: `...` (Ellipsis) in a type-annotation position misparses

## Repro

```python
def f(g: ...):
    pass
print("ok")
```

```
$ python3 mojo.py run repro.py
SyntaxError: repro.py:1:10: Expected NAME or KW got DOT('.')
```

Note `x = ...` (Ellipsis as an ordinary expression, not in an annotation
position) already works fine — this is specifically about the annotation
grammar.

Real stdlib trigger: `Lib/test/test_annotationlib.py`'s `test_literals`
(~line 447): `g: ...,` — found immediately after fixing
`bugs/PARSE_FAIL_annotation_leading_literal_trailing_op.md` (commit
`bb28e80`), whose own verification pass hit this as the next, separate
issue in the same file.

## Root cause

`mojo_compiler.py`'s tokenizer produces THREE separate `DOT` tokens for
`...` (confirmed via direct `py_tokenize` call) — there is no single
`ELLIPSIS` token kind. The general expression parser (`_parse_primary`,
~line 3350) explicitly recognizes this three-token sequence:

```python
if t.kind == "DOT" and self._peek(1).kind == "DOT" and self._peek(2).kind == "DOT":
    self._advance(); self._advance(); self._advance()
    return EllipsisLiteral(line=line, col=col)
```

`_parse_type_ann_inner` (the separate, narrower "type name" grammar used
for annotations — see the recent `6ee8291`/`6e6020f`/`bb28e80` fixes for
its general shape and the established "capture arbitrary annotation
expressions as opaque text" philosophy) has no equivalent case. When its
dispatch sees a `DOT` as the annotation's first token, none of its
branches (`NAME`/`KW`/`STRING`/`LPAREN`/`LBRACKET`/`LBRACE`) match, so it
falls to the generic catch-all fallback (added by `6ee8291`, extended by
`bb28e80` to route through `_consume_trailing_annotation_ops`):

```python
else:
    return self._consume_trailing_annotation_ops(prefix + self._advance().value)
```

This consumes only the FIRST `.` as the whole annotation's opaque text,
then calls `_consume_trailing_annotation_ops`, which only knows how to
continue consuming `OP`-kind tokens (`|`, `&`, or other stray operators per
`6e6020f`) — a `DOT`-kind token doesn't match, so it returns immediately,
leaving the other two dots dangling. The caller (`_parse_funcdef`'s
parameter loop) then chokes on the leftover `DOT` token expecting a new
parameter name, raising the confusingly-located `Expected NAME or KW got
DOT('.')`.

## Suggested fix

Add an explicit three-DOT-lookahead case to `_parse_type_ann_inner`'s
dispatch (mirroring `_parse_primary`'s existing detection above), before
falling through to the generic single-token catch-all: if the current
token and the next two are all `DOT`, consume all three and return `"..."`
as the annotation text (through `_consume_trailing_annotation_ops` too, for
consistency with every other branch, in case `...` is itself followed by a
trailing operator like `g: ... | None`). Since annotation text is never
semantically type-checked downstream (per the tracing already done in
`6ee8291`), returning the literal string `"..."` is a safe, sufficient
representation — no need to model a real `EllipsisLiteral` type-annotation
node.
