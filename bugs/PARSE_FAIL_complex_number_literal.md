# PARSE_FAIL: complex/imaginary number literals (`0j`, `1+0j`) unsupported

## Status
**Fixed 2026-07-20.** Deliberately partial per this doc's own scope
guidance — see "Fix" below for exactly what's covered vs. left out.

## Fix

**`mojo_compiler.py`**: added an `IMAG` token group to `_TOKEN_RE` (a
number-shaped pattern — reusing the exact same digit/underscore/exponent
sub-pattern the earlier float-underscore fix already established — followed
by a `j`/`J` suffix), tried before the plain `FLOAT` group so `0j`/`1.5j`
aren't first swallowed as a bare float with a stray `j` identifier after it.
A new `ImagLiteral(value: float)` AST node holds the magnitude BEFORE the
implicit multiply-by-i (i.e. the digits preceding `j`/`J`, parsed exactly
like a `FloatLiteral`'s mantissa). `_parse_primary` and the `emit()`
pretty-printer both got matching cases; the pre-existing `await`-as-identifier
disambiguation's next-token allowlist was extended to include `IMAG` too
(same reasoning as its existing `FLOAT` entry).

**`myinterpreter.py`**: added a minimal `MojoComplex` runtime value
(`real`/`imag` float pair) and `eval_ImagLiteral` (`Nj` → `MojoComplex(0.0,
N)`). Per this doc's own scope guidance, this is intentionally NOT a full
Python `complex` implementation:
- **Implemented**: construction from a literal, `+`/`-` against
  int/float/other `MojoComplex` (via `__add__`/`__radd__`/`__sub__`/
  `__rsub__`, which is all `eval_BinaryOp` needs — no changes to it),
  `==` (value equality), and `__repr__`/`__str__` matching Python's actual
  complex formatting (`3j` for pure-imaginary, `(a+bj)`/`(a-bj)` otherwise,
  matching sign and Python's "no trailing `.0` on a whole part" rule).
- **Deliberately NOT implemented**: `*`, `/`, `conjugate()`, `abs()`,
  ordering comparisons, and — notably — real Python-compatible hashing.
  `__hash__` is `id(self)`-based (matching this same file's pre-existing
  `_MojoDeviceContext.__hash__` precedent for the same eq-by-value/
  hash-by-identity tradeoff), NOT `hash((real, imag))`, because
  `gimple_codegen.py`'s self-hosted compile of this exact file only stubs
  Python's `hash()` builtin as an unimplemented extern, and the
  `int(float_expr)`-based workaround tried instead hit an unrelated
  pre-existing gimple_codegen miscompile (an `int()` call's return type
  inferred as `char *` in that context). Practical consequence: a set
  literal like `{1, 1.0, True, 1 + 0j}` does NOT collapse `1 + 0j` into the
  same bucket as `1`/`1.0`/`True` the way real Python's value-hashing does
  (real Python: `len({1, 1.0, True, 1+0j}) == 1`; this interpreter:
  `== 2`) — construction/storage/printing work correctly, but full
  cross-type numeric-hash unification was out of scope.

## Verification
- Original repro (`1 + 0j`) → prints `(1+0j)`.
- Bare imaginary literal (`3j`) → prints `3j`.
- The two real stdlib patterns from this doc run without crashing:
  `{1, 1.0, True, 1 + 0j}` (constructs; length differs from real Python per
  the hashing tradeoff above, documented not fixed) and
  `[0, 1, 2.0, 3.0+0j]` (constructs and stores correctly, `x[3]` prints
  `(3+0j)`).
- Ordinary numeric literals (int, float, float-with-underscores from the
  earlier fix today) unaffected.
- `python3 test_gimple.py`: 161 passed, 0 failed. `python3
  test_module_cache.py`: 64 passed, 0 failed. `make check-selfhost`: passes.
  From-scratch stdlib dylib build: 0 skipped modules. All re-verified on
  `master` after merging (not just in the isolated dev worktree).

## Original report

## Reproduction
```mojo
def f():
    var x = 1 + 0j
    print(x)
f()
```
Run: `python3 mojo.py run test.mojo`

## Actual Behavior
```
NameError: test.mojo:2:13: name 'j' is not defined
```
The tokenizer reads `0` as a plain numeric literal and then treats the `j`
suffix as a totally separate identifier token (`NameError: name 'j' is not
defined` when it's later evaluated as a bare reference) — Python's
imaginary-number literal suffix (`j`/`J` after an int or float literal,
e.g. `0j`, `1.5j`, `3J`) isn't recognized as part of the number at all.

## Expected Behavior
`1 + 0j` should evaluate to the complex number `(1+0j)`, matching Python's
`complex` type semantics (a pair of floats: real and imaginary parts,
supporting `+`, `-`, `*`, `/`, equality, and `str()`/`repr()` formatting
like `(1+0j)`, `3j`, `(2-1j)`, etc.)

## Real-world impact
Confirmed via the CPython 3.14 stdlib scan that populated this `bugs/`
directory: `Lib/test/test_ast/test_ast.py:736` (`{1, 1.0, True, 1 + 0j}`, a
set literal) and `Lib/test/pickletester.py:714`
(`x = [0, 1, 2.0, 3.0+0j]`, a list literal) both use complex literals as
ordinary test data.

## Scope guidance
This is a bigger lift than the other numeric-literal bug fixed earlier today
(underscore digit-separators in float fractions) — that was purely a
tokenizer fix; this one additionally needs SOME runtime representation for
complex values (arithmetic + string formatting), not just successful
parsing. Use judgment on how much runtime support to add:
- Minimum viable: tokenize `<number>[jJ]` into a literal that evaluates to
  *some* representation of a complex number (even a minimal one — e.g. a
  small struct/tuple-like value with `.real`/`.imag` fields) that at least
  supports being constructed, printed, and used in the two real-world
  patterns above (as a plain collection element — those two examples don't
  actually do complex ARITHMETIC on the value, just construct and store it).
- Don't feel obligated to implement the full Python `complex` builtin API
  (conjugate(), abs(), full operator coverage against int/float/other
  complex) if that's disproportionate — get tokenization + construction +
  basic `+`/`-` (since `1 + 0j` itself needs `+` between a real number and
  an imaginary literal to work) + printing right, and note anything
  deliberately left unimplemented as a follow-up rather than silently
  skipping it.

## Files Likely Affected
- `mojo_compiler.py` — the tokenizer's numeric-literal regex/scanning logic
  (same area as today's earlier `_TOKEN_RE` FLOAT-group fix, if this
  codebase's tokenizer is regex-based — check for a `COMPLEX`/`IMAG` token
  kind or whether it needs to be added) and wherever a numeric literal
  token becomes an AST node (may need a new literal AST node kind, or reuse
  an existing one with a flag).
- `myinterpreter.py` — evaluating a complex literal into a runtime value,
  and whatever the `+`/`-`/etc. binary-operator evaluator needs to combine
  a real (int/float) operand with an imaginary/complex operand.
