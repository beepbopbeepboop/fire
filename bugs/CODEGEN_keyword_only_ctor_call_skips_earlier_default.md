# CODEGEN: keyword-only constructor call to a non-varargs `__init__` leaves an earlier defaulted param at 0 instead of its real default

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
