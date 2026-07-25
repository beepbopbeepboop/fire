# PARSE_FAIL: a parenthesized annotation followed by `.attr` (or other continuation) misparses

## Repro

```python
def f(y: (1).__class__):
    pass
print("ok")
```

```
$ python3 mojo.py run repro.py
SyntaxError: repro.py:1:12: Expected NAME or KW got DOT('.')
```

Real stdlib trigger: `Lib/test/test_annotationlib.py`'s `test_shenanigans`
(~line 540): `y: (1).__class__` — found immediately after fixing
`bugs/PARSE_FAIL_annotation_ellipsis.md` (commit `c2933a7`), whose own
verification pass hit this as the next issue in the same file (this is now
the fourth in this same chain of annotation-parsing gaps: `6ee8291` →
`6e6020f` → `bb28e80` → `c2933a7` → this one).

## Root cause

`mojo_compiler.py`'s `_parse_type_ann_inner`'s `LPAREN` branch (~line
3708-3727) captures a balanced `(...)` span as opaque text for annotations
like `() ` (unit type) or other parenthesized-expression-shaped
annotations, but returns it directly:

```python
if self._peek().kind == "LPAREN":
    name = prefix + "("
    ...
    name += ")"
    return name
```

Unlike the `LBRACKET`/`LBRACE`/catch-all branches (fixed in `bb28e80` to
route through `_consume_trailing_annotation_ops` before returning), this
`LPAREN` branch was NOT updated and still returns immediately — so any
trailing continuation after the parenthesized span (a `.attr` member
access, a trailing `|`/`&` union, or another stray operator) is left
dangling for the caller to choke on. For `(1).__class__`, after consuming
`(1)` the function returns `"(1)"` immediately, leaving `.__class__` (a
`DOT` then `NAME` chain) unconsumed.

Note this is worse than the three-branches-fixed-in-`bb28e80` case in one
respect: even routing through `_consume_trailing_annotation_ops` (the
helper added in `6e6020f`) wouldn't be sufficient on its own here, because
that helper only knows how to continue consuming `OP`-kind tokens (`|`,
`&`, other stray binary operators) — it has no handling for a trailing
`DOT`-chain (member access) continuation at all. Meanwhile,
`_parse_type_ann_inner` DOES already have working dotted-name-continuation
logic (~line 3820-3827, the "Support dotted type names" `while
self._peek().kind == "DOT":` loop) — but that loop only runs for the
NAME/KW dispatch path, since every other branch (`LPAREN`, `LBRACKET`,
`LBRACE`, catch-all) `return`s before ever reaching it.

## Suggested fix

Restructure so the `LPAREN` branch (and ideally review whether `LBRACKET`/
`LBRACE`/catch-all have the same latent gap for a trailing `.attr` chain,
even though their immediate reported symptom so far has only been about
trailing operators) can also fall through into the existing dotted-name
continuation loop and/or `_consume_trailing_annotation_ops`, instead of
returning immediately — e.g. by not `return`-ing early from each branch,
and instead falling through to a shared tail that runs BOTH the
dotted-name loop and `_consume_trailing_annotation_ops` regardless of
which branch produced the base `name`. Given how many small,
narrowly-scoped follow-on fixes this exact function has already needed
this session (four so far), it may be worth this subagent's judgment call
on whether a slightly more structural refactor (one shared exit path that
every branch flows through, rather than N early-returns each needing their
own fix) is the more production-quality approach here per CLAUDE.md's
"never pick the simple/quick fix" guidance — vs. another narrowly-targeted
patch matching the existing style. Use your judgment on which best serves
long-term maintainability without over-engineering.
