# PARSER: a Mojo keyword used as an ordinary identifier refuses the whole module

**Found:** 2026-11-14, when the self-host stopped compiling
`mojo/middle/mojoc_conformance.py`:

```
# ERROR: compiling imported module 'mojo.middle.mojoc_conformance' ...
  106:15: Expected NAME got ASSIGN('=')
```

Line 106 is a plain assignment:

```python
trait = (records or {}).get(_split_bound(bound))
```

`trait` is in `fire_compiler._KEYWORDS`, and the statement-level dispatch did
`if t.value == "trait": return self._parse_trait()` with NO guard, so the
parser read `trait` as a trait declaration and then demanded the trait's NAME —
finding `=`. The module was refused, and because every whole-program compile of
the self-host imports it, `fire.py --dump-full …`, `make mojoc` and the
bootstrap gate jobs all stopped.

## Isolation

```
def f():
    trait = 1                      # FAIL 2:11: Expected NAME got ASSIGN('=')
def f():
    trait = (r or {}).get(y)      # FAIL (same)
def f():
    for i in x:
        if not b:
            continue
        trait = 1                  # FAIL 5:15 (same)
```

Measured before the fix; all three parse after it.

## Why the compiler must accept this

The compiler compiles its OWN Python sources as Mojo (the self-host). Python
has no `trait` keyword, so `trait` is an ordinary, natural variable name in
that code — and it is not the only collision waiting: every Mojo keyword that
is a legal Python identifier (`struct`, `class`, `enum`, `var`, `let`, `fn`,
`alias`, `trait`, …) can appear as one. The dispatch already carves out
`enum`, `comptime` and `param` ("only commit to the declaration parse when the
next token could actually start one"); `trait` was simply missing from that
treatment.

## Fix

`fire_compiler.py`'s statement dispatch now requires the token after `trait` to
be a NAME (or a backtick string) before committing to `_parse_trait()`;
anything else falls through to expression/assignment parsing, exactly as
`enum`/`comptime`/`param` already do. A real declaration (`trait Foo:`,
`trait Foo[U]:`) is unaffected — measured both still parse.

## Done when

`python3 -c "import elaborate as E; E.Parser(E.py_tokenize('def f():\n    trait = 1\n')).parse_module()"`
parses, `mojo/middle/mojoc_conformance.py` parses, `trait Foo:` / `trait Foo[U]:`
still parse, and a regression pins all four.
