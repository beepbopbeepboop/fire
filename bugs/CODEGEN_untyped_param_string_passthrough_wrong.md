# CODEGEN: an untyped function parameter that just holds/returns a string produces a garbage integer when printed (compiled path)

## Repro

```python
def g(a):
    return a
print(g("ab"))
```

- `python3 mojo.py run repro.py` (interpreter): correct — prints `ab`.
- `python3 mojo.py build repro.py -o out && ./out`: compiles with no error
  or warning, but prints a garbage large integer (e.g. `4371762728`) —
  clearly the raw pointer value of the `MojoStr *`/`char *` being
  misinterpreted as an `int64_t`.

Adding explicit type annotations makes it work correctly:
```python
def g(a: str) -> str:
    return a
print(g("ab"))     # prints "ab" correctly, compiled and interpreted
```

This is a silent-wrong-result bug (no compiler diagnostic at all), and is
about as minimal/fundamental as this class of bug gets: a plain identity
function called with a string argument.

Found while investigating `bugs/PARSE_FAIL_fstring_same_quote_reuse.md`'s
own verification pass, which noted (as an aside, confirmed pre-existing
and unrelated to that fix) that interpolating a run-time-computed string
value into an f-string produced garbage in the compiled path — that
turned out to be a special case of this same, more general bug (any
untyped-parameter function merely holding/returning/passing through a
string value, not just ones used inside f-string interpolation).

## Root cause

Not yet traced into `gimple_codegen.py` — needs investigation into the
parameter-type-inference pass (the same general area fixed for a
different untyped-parameter-usage shape in commit `e387af9`,
"Fix map() over an untyped parameter miscompiling" — read that commit for
the established pattern/location of `_infer_param_types` and how it walks
a function body's usages of each unannotated parameter to decide its real
C type). That fix taught the inference pass to recognize `map(fn, param)`
as evidence a parameter is pointer-shaped; this bug suggests the inference
pass ALSO doesn't recognize "parameter is called with / assigned a string
literal argument at some call site" (or perhaps more precisely: "parameter
is directly returned with no other operation performed on it, and at
least one call site passes a string") as evidence the parameter (and
correspondingly the function's inferred return type) should be
string-shaped rather than defaulting to `int64_t`.

## Impact

Untyped "pass-through"/identity-like helper functions that happen to be
called with string arguments are an extremely common pattern in real
Python code (thin wrappers, default-argument-shimming helpers, decorators,
etc. that don't bother annotating parameter types since Python doesn't
require it). This is likely a significant, widespread source of silent
wrong output in the compiled path — arguably a more foundational
correctness gap than several of the narrower bugs fixed earlier this
session, since it doesn't require anything unusual (no builtins, no
special syntax) to trigger, just an ordinary unannotated function whose
argument happens to be a string.

## Suggested fix

Not yet planned — needs investigation into how the parameter-type
inference pass currently decides an unannotated parameter's type (walking
the function body for usage evidence, per `e387af9`) and why "directly
returned, called with a string literal/value at some call site" isn't
already sufflent evidence. Given how foundational this is, consider
whether the inference pass should look at CALL-SITE argument types too
(not just how the parameter is used inside the function body) as a more
general signal — check whether this codegen already does any form of
call-site-argument-type propagation elsewhere for similar inference
decisions, and prefer extending/reusing that mechanism over adding a third,
narrower special case (matching CLAUDE.md's consolidation guidance). Given
the scope and potential blast radius of this fix, treat it carefully:
verify thoroughly against the existing stdlib-compile-cleanliness baseline
(the quality gate's "0 skip" ceiling) since a change to core parameter-type
inference could easily regress previously-working code in subtle ways.
