# CODEGEN: keyword-only constructor call to a non-varargs `__init__` leaves an earlier defaulted param at 0 instead of its real default

## Status (FIXED 2026-08-23)

Root-caused and fixed. The bug was NOT in default-padding (that tail loop
already consulted each param's own default) but in all FOUR keyword-
overlay gap-fill sites in `gimple_gen_calls.py`'s constructor lowering,
which hardcoded a blanket `('int', '0')` for every slot a keyword binding
skipped over:

1. `_build_call_args_for_candidate`, non-varargs keyword-overlay loop
   (overload-resolution path): `while len(out) <= idx: out.append(('int','0'))`.
2. Same function, the `**kwargs`-pack slot fill.
3. `_lower_struct_constructor`, single-signature/reflection path's
   keyword-overlay loop (identical shape).
4. Same function, its own `**kwargs`-pack slot fill.

For `Derived(b=99)` against `(a=1, b=2, c=3)`: site 1 filled index 0 with
literal `0` instead of `a`'s declared default `1`, then overwrote index 1
with `99`; the tail-padding loop then correctly supplied `c=3` — exactly
the observed "only the param BEFORE the matched one is wrong" signature.
All four sites now fill gaps via the existing `_default_expr_to_pair`
helper with each skipped param's OWN declared default (`defaults`/`
init_defaults` lookup; no-default params still fall back to `('int','0')`
via `_default_expr_to_pair(None)`). While there, the two inline
default-literal-dispatch copies of that helper in this same file
(`_build_call_args_for_candidate`'s tail padding and
`_lower_struct_constructor`'s tail padding) were consolidated into calls
to it — identical behavior for every shape they handled, plus the
helper's extra IdentExpr True/False/None cases.

**Verification**: real compile+link+run repros — the doc's own
inherited-`Derived(b=99)` shape now prints `1/99/3` (was `0/99/3`);
direct non-inherited `Base(b=99)` → `1/99/3`; cross-module reflection-path
ctor `Far(b=7)` against `(a=11, b=22)` → `11/7`; **kwargs-slot shape
`KwRest(x=5)` against `(verbose...)`-style `(a=1, **rest)` → `a==1`;
string-default gap shape `Mixed(n=42)` against
`(name="hi", n=7)` → prints `hi`/`42`. Two new stdout-asserting regression
tests added to `test_gimple_runner.py`
(`gimple_ctor_kwarg_skipped_earlier_defaults`,
`gimple_ctor_kwargs_pack_keeps_earlier_default`) — both confirmed FAILING
on the unfixed code (git stash A/B: got `0\n99\n3\n` / `0\n`) and passing
after. Full quality gate results recorded in this branch's final gate run
(2026-08-23).

## Status (found 2026-08-20, not fixed — separate from, and pre-dating, this session's varargs constructor-arity fix)

Found while verifying commit `f7...`'s (this session's) fix for
`Lib/calendar.py`'s `_CLIDemoCalendar(highlight_day=today)` — that fix
targets constructors whose (possibly inherited) `__init__` has
`*args`/`**kwargs` (the `chosen.get('has_varargs')` branch in the
constructor-call lowering, `gimple_codegen.py` ~line 17406). This is a
**different, pre-existing** bug in the sibling NON-varargs branch,
confirmed present identically before and after that fix (bisected via
`git show <pre-fix commit>:gimple_codegen.py`, byte-identical wrong
output both times) — not a regression, not the same code path.

## Minimal repro

```mojo
struct Base:
    var a: Int
    var b: Int
    var c: Int
    fn __init__(out self, a: Int = 1, b: Int = 2, c: Int = 3):
        self.a = a
        self.b = b
        self.c = c

struct Derived(Base):
    fn dummy(self):
        pass

fn main():
    var d = Derived(b=99)
    print(d.a)   # prints 0, should print 1 (a's real default)
    print(d.b)   # prints 99, correct
    print(d.c)   # prints 3, correct
```

Compiled via `gimple_codegen.compile_to_gimple(src, do_imports=True, ...)`
+ real `gcc -fgimple` compile+link+run (not just a compile-error check —
this is a silent WRONG VALUE, not a compile failure): `d.a` reads back
`0` instead of `1`. `b` (the one keyword actually passed) and `c` (a
later, untouched default) both come back correct — only `a`, the
param BEFORE the one keyword arg supplied, is wrong.

## Not root-caused yet

Not investigated further this session (found opportunistically while
verifying an unrelated fix, no budget spent tracing it). Likely
candidate area: the non-varargs constructor-call argument-filling
branch in the same function area as the varargs fix above (search
nearby in `gimple_codegen.py`'s constructor/`_lower_opaque_ctor`-style
call lowering for wherever positional defaults get filled when a call
supplies ONLY later keyword arguments) — plausibly an off-by-one or
"only fills defaults for params AFTER the last matched one" bug, since
`c` (after `b`) came back correct but `a` (before `b`) did not.

Whether this is narrow or feature-sized is unknown — not assessed.
