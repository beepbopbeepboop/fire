# INTERP/CODEGEN: `yield` (generator functions) is entirely unimplemented

## Scope note

Unlike the other bugs in this directory, this is not a small, single-syntax
parser gap — it's a missing foundational language feature. Flagging it
clearly rather than quietly attempting a "quick fix": implementing real
generator semantics (suspend/resume, iterator-protocol integration, and for
the compiled path an actual state-machine transform in the C codegen) is a
substantial feature project, not a bounded bug fix, and deserves its own
dedicated planning session rather than being folded into the same
small-fix/quality-gate loop as e.g. commits 52ea4d7 / e387af9.

## What's there today

`mojo_compiler.py` has no `YieldExpr`/`YieldStmt` AST node at all. `yield`
is not even in `_KEYWORDS` (`mojo_compiler.py:605`) — it lexes as a plain
`NAME` token. The only place `yield` is mentioned is a narrow special case
for `yield from EXPR` (`mojo_compiler.py:1398-1403`) that parses (and
discards) the delegated expression and emits a stub
`ExprStmt(value=IdentExpr(name='yield'))` — i.e. even `yield from` doesn't
actually do anything at runtime, it's a parse-only no-op stub.

Plain `yield expr` (by far the common case) isn't special-cased at all, so
it's parsed as a bare expression statement starting with the identifier
`yield`, and blows up in one of two ways depending on what follows:

```python
def f():
    yield 5          # NameError: name 'yield' is not defined (interpreter evaluates
                      # `yield` as a plain identifier reference, then chokes on
                      # the trailing `5` / whatever expression grammar doesn't fit)

def g():
    yield [1, 2, 3]   # `yield` parses as bare identifier, then `[1, 2, 3]` is parsed
                      # as a SUBSCRIPT on it (yield[1,2,3]) instead of a yielded list
                      # literal -> also NameError: name 'yield' is not defined

def h():
    for line in data:
        yield [x.strip() for x in line.split(';')]   # PARSE_FAIL: "Expected RBRACKET got KW('for')"
                                                        # — the subscript-misparse above breaks down
                                                        # completely once the bracketed content is a
                                                        # comprehension instead of a plain list.
```

Minimal repro of the third form saved as a file and run via
`python3 mojo.py run <file>.py`:
```
Error: <file>.py:3:21: Expected RBRACKET got KW('for')
```

## Why this matters

Generator functions are pervasive in the Python standard library (this
project's whole purpose is running real Python 3.14 stdlib source), so this
gap is very likely the actual root cause behind a significant fraction of
the still-open `PARSE_FAIL_*`/`COMPILE_FAIL_*` reports in this directory,
including (at minimum) `PARSE_FAIL_Tools_unicode_makeunicodedata.md`
(`yield [field.strip() for field in line.split(';')]` at
`Tools/unicode/makeunicodedata.py:860`).

## Suggested next step

Do NOT attempt this as a drop-in small patch. It needs its own scoped plan
covering at least:
- Lexer/parser: add `yield` and `yield from` as real expression forms
  (`YieldExpr`/`YieldFromExpr` AST nodes), correctly precedence-scoped so
  `yield [comprehension]`, `yield a, b` (implicit tuple), `x = yield y`, etc.
  all parse.
- Interpreter (`myinterpreter.py`): decide a strategy for suspend/resume —
  likely a Python-generator-backed implementation (a real Python generator
  wrapping the interpreter's own execution of the function body) is far
  cheaper here than a hand-rolled continuation scheme, since the interpreter
  already runs on top of real Python.
- Compiled path (`gimple_codegen.py`): generator functions can't lower to a
  single straight-line C function the way non-generator functions do — this
  needs an explicit state-machine transform (or, as a first cut, detect
  generator functions and always fall back to source/interpreter rather than
  attempting to compile them, which is far less work than full codegen
  support and may be an acceptable interim stance — check whether the
  existing "skip module, fall back to source" mechanism referenced in
  CLAUDE.md's quality gate section can be reused/extended for
  "skip generator function, fall back" instead of module-level granularity).
