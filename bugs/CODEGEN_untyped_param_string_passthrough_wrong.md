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

## Status
**Fixed**

Root cause: `gimple_codegen.py` already has a call-site-argument-type
propagation mechanism — the "cross-call scalar contract" (`ce10107`,
originally added only for `double`), which observes each call site's
argument type and, when unanimous across all call sites of an unannotated
parameter, promotes that parameter off the `int64_t` default. It just
never observed string-literal (or already-string) arguments, and — the
deeper part of the bug — three consumers of the resulting types ran too
early, before that observation pass, and were never refreshed afterward:

1. The scalar contract's call-site scan (`gen_module`'s "Pass 1.3d") only
   walked calls found *inside other functions' bodies*, never top-level
   module statements — so `print(g("ab"))` sitting directly at module scope
   was invisible to it entirely.
2. `func_return_types` for an unannotated function is first computed early
   ("Pass 2", seeded with each unannotated param's naive `int64_t`
   default) — long before parameter-type inference (`_infer_param_types`)
   or the cross-call contract run — and was only ever re-synced when that
   specific function's own `gen_func` body-emission pass happened to run.
   Any caller compiled/type-scanned before that point (a module-level
   `y = g(...)`, or another function's local-variable-type pre-pass) still
   saw the stale `int64_t` return type.
3. The local-variable-type pre-pass (`_infer_local_var_types`, "Pass
   1.3b") runs before the cross-call contract too, so `y = g("a", "b")`
   got `y` declared `int64_t` even once `g` itself was fixed.

Fix (`gimple_codegen.py`):
- Extended the existing scalar contract (not a new mechanism) to also
  recognize a `StringLiteral` call argument, or an identifier already
  known to be `char *`, as evidence, unified with the existing `double`
  case (unanimous-across-call-sites, only overrides the `int`/`int64_t`
  default, respects explicit annotations) — same code path as the
  `map()` fix's `_infer_param_types`, per CLAUDE.md's consolidation
  guidance.
- Extended that pass's call-site scan to also observe calls made directly
  from module-top-level statements (`_TOPLEVEL_CALLER`), not just from
  inside other functions' bodies.
- Added "Pass 1.3e" (re-infer `func_return_types` for every unannotated
  function using the now-final, cross-call-corrected parameter types) and
  "Pass 1.3f" (re-run `_infer_local_var_types`) immediately after the
  cross-call contract, so every later consumer (the module-level-global
  type scan, `gen_func`'s per-function codegen) sees the corrected types
  instead of racing against whichever function happens to be emitted
  first.
- Generalized `AssignStmt`'s local-variable-declare fallback (previously
  only trusted the actually-lowered value's type over a stale pre-pass
  hint for `double` and for `MojoDict*/MojoList*/MojoSet*`) to trust it
  for any pointer-shaped value, closing the same gap for `char *` and any
  other pointer type reached by a path Pass 1.3e/1.3f doesn't cover.

Also fixed a self-inflicted self-host regression found by the mandatory
`make check-selfhost` gate: the first attempt picked the corrected type
via `next(iter(types))`, which failed to link (`undefined symbol _next`)
when `gimple_codegen.py` compiled itself, because its own compiled-path
lowering of the `next()` builtin over a freshly-constructed set iterator
doesn't cover that shape. Replaced with a plain two-way conditional
(`'double' if types == {'double'} else 'char *'`) — no interpreter-vs-
compiled-path discrepancy, no `next()`/`iter()` call at all.

Verified: `test_gimple.py` (186/186), `test_gimple_runner.py` (15/15,
including new stdout-value checks — not just exit codes — since this bug
class runs successfully and exits 0 both broken and fixed),
`test_module_cache.py` (64/64), `make check-selfhost`, and a from-scratch
`build_stdlib_dylib.py` rebuild with `use_cache=False`: byte-identical,
0-skip build log before and after (full stdlib compiles clean in both
cases — no regression). Manually verified the compiled binary's actual
printed output for the identity-function repro, the explicitly-annotated
sibling, the two-parameter string-concatenation shape, and that same
shape read back through an f-string interpolation — all print the correct
string, not a garbage integer.
