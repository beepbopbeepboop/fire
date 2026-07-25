# PARSE_FAIL: a type-annotation position followed by a trailing binary/comparison operator misparses

## Repro

```python
some = 1
obj = 2
def f(gamma: some < obj):
    pass
print("ok")
```

```
$ python3 mojo.py run repro.py
SyntaxError: repro.py:3:18: Expected NAME or KW got OP('<')
```

Real stdlib trigger: `Lib/test/test_annotationlib.py`'s `test_nonexistent_attribute`
(lines 99-124), which deliberately exercises a whole battery of
nonsensical-but-syntactically-legal annotation expressions on function
parameters — `x: some.module`, `y: some[module]`, `z: some(module)`,
`alpha: some | obj`, `beta: +some`, `gamma: some < obj`, `delta: some |
{obj: module}`, `epsilon: some | {obj}`, `zeta: some | [obj, module]`,
`eta: some | ()` — per PEP 649, annotations accept an arbitrary expression
with no semantic type-checking at all. Every one of these EXCEPT `gamma`
(the `<` comparison case) already parses correctly.

## Root cause

This is the same underlying issue as `bugs/PARSE_FAIL_annotation_arbitrary_expression.md`
(fixed in commit `6ee8291`, "Fix annotation position occupied by a
non-type-shaped expression (-> {}:)") — Python's grammar allows a fully
arbitrary expression in an annotation position — but that fix only handles
the case where the annotation's *first* token is unusual (a bare
`[`/`{`/other single stray token occupying the whole annotation). It didn't
address a valid type-shaped prefix (a real NAME like `some`) being followed
by a *trailing* operator that continues the expression.

`mojo_compiler.py`'s `_parse_type_ann_inner` (~line 3625-3800) builds a type
annotation as an opaque string via a narrow "type name" grammar: dotted
names, `[TypeArgs]` subscripts, `(...)` call-shaped types, and — since
6ee8291 — a few opaque-capture fallbacks for the leading-token case. After
building the base `name`, it explicitly continues consuming ONLY two
specific trailing binary operators, for real Mojo/PEP-604 union-type syntax
(~line 3787-3791):

```python
if self._peek().kind != "LBRACKET":
    while self._peek().kind == "OP" and self._peek().value in ("|", "&"):
        op = self._advance().value
        rhs = self._parse_type_ann()
        name = name + f" {op} " + rhs
    return name
```

Any OTHER trailing operator — `<`, `>`, `==`, `+` (binary), `-`, `*`, `%`,
etc. — isn't consumed here and is left dangling once `name` is returned.
Back in the caller (e.g. `_parse_funcdef`'s parameter-list loop, ~line
2229-2239), the annotation is treated as "done" at that point; the loop
then goes back around expecting either a `,`/`)` or the start of another
parameter, sees the stray `OP('<')` instead, and raises `Expected NAME or
KW got OP('<')` from the parameter-name-read branch (~line 2228) — a
confusing error that points at the wrong place (parameter-name parsing)
for what's actually an annotation-parsing gap.

## Status
**Fixed**

`mojo_compiler.py`'s `_parse_type_ann_inner` had two exit points that only
consumed `|`/`&` as trailing operators (~line 3854-3860 and ~3903-3909 after
the fix). Both were changed to call a new shared helper,
`_consume_trailing_annotation_ops(name)` (added just before
`_capture_bracketed_text`, ~line 1287), which keeps the existing `|`/`&`
union/intersection loop unchanged and then — if the next token is still some
other `OP` (deliberately excluding `?`, the optional-type suffix handled by
the caller `_parse_type_ann`) — consumes that operator plus the rest of the
expression as opaque text via a new `_capture_opaque_annotation_tail()`
helper. That helper is bracket-depth-aware (nested `(`/`[`/`{` don't
prematurely trip a terminator check) and stops before any of the terminator
token kinds the various `_parse_type_ann` call sites rely on (`COMMA`,
`COLON`, `ASSIGN`, `ARROW`, `NEWLINE`, `EOF`, `INDENT`, `DEDENT`, or an
unmatched closing `)`/`]`/`}` back at depth 0).

Also added a test to `test_gimple.py` (`annotation_trailing_binary_op_battery`,
test #172) covering the ENTIRE `test_nonexistent_attribute` battery of shapes
in one function signature (`x: some.module`, `y: some[module]`,
`z: some(module)`, `alpha: some | obj`, `beta: +some`, `gamma: some < obj`,
`delta: some | {obj: module}`, `epsilon: some | {obj}`,
`zeta: some | [obj, module]`, `eta: some | ()`), to guard against fixing
`gamma` while regressing a sibling shape.

### Quality gate results

- `python3 test_gimple.py`: 174 passed, 0 failed (was 173 passed before adding
  the new test).
- `python3 test_module_cache.py`: 64 passed, 0 failed.
- `make check-selfhost`: passes clean (mojo.py compiling its own source).
- From-scratch stdlib dylib build
  (`rm -f build/libmojostdlib.dylib && python3 -c "import build_stdlib_dylib as bsd; bsd.build_stdlib(jobs=8)"`):
  **0 skips before, 0 skips after** — no regression.

### Manual verification

- Minimal repro (`gamma: some < obj`) now parses and runs, printing `ok`.
- The full `test_nonexistent_attribute` battery (all 10 annotation shapes) in
  one function signature parses and runs, printing `ok`.
- Real stdlib file re-check:
  `python3 mojo.py run /Users/mrs/net/Python-3.14.6/Lib/test/test_annotationlib.py`
  no longer fails at `test_nonexistent_attribute`'s `gamma` case (line ~122).
  The parse now proceeds further into the file and hits a **different,
  pre-existing, out-of-scope** SyntaxError at line 334
  (`test_reverse_ops`'s `radd: 1 + a`) — a leading NUMBER-token annotation
  (not a NAME-shaped prefix followed by a trailing operator), which 6ee8291's
  fallback branch handles by returning immediately without ever reaching the
  trailing-operator consumption added here. This is a separate, not-yet-root-caused
  gap in the same general "arbitrary expression in annotation position"
  feature family; left unfixed per this task's scope (only the trailing-operator-after-a-real-NAME
  case described above).

## Suggested fix

Extend the same "arbitrary expression is syntactically legal here, and this
annotation string is never semantically type-checked downstream" reasoning
already established by commit `6ee8291` to also swallow a trailing
binary/comparison operator (and its right-hand operand, which may itself
be another arbitrary expression) as opaque text, rather than only handling
`|`/`&`. Since 6ee8291 already confirmed (by tracing every consumer) that
nothing downstream re-parses the annotation string assuming real type
syntax, this should be safe to do generically: after the existing `|`/`&`
loop (or replacing it with something more general), if the next token is
still some other `OP` that isn't a recognized annotation terminator
(`COMMA`, `RPAREN`, `ASSIGN`, `COLON`, `ARROW`, `NEWLINE`, `EOF`, etc. —
whatever set of terminators the various call sites of `_parse_type_ann`
actually rely on), consume the rest of the expression as opaque token text
(bracket-depth-aware, so nested parens/brackets/braces in the tail don't
prematurely trip a terminator check) and append it to `name`, matching the
existing opaque-capture style rather than raising.

Watch for interaction with the different call sites of `_parse_type_ann`
(parameter types, return types, variable declarations, struct fields) —
each has a different natural terminator token, so make sure whatever
generic "capture the rest as opaque text" logic you add correctly stops at
the right place for all of them, and doesn't regress any of the
already-working cases in the same test (`alpha: some | obj`,
`beta: +some`, `delta: some | {obj: module}`, etc. — write a test covering
ALL of `test_nonexistent_attribute`'s parameter annotation shapes, not just
the failing `gamma` one, since it's easy to fix one shape while
regressing a sibling).
