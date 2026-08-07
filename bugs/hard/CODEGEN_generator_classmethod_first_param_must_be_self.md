# HARD BUG: a generator method's first parameter must be literally named `self` — a `@classmethod` generator (first param `cls`) is refused outright

## Status

Unfixed. Root-caused 2026-08-06 while classifying the
`CODEGEN_generator_function_Lib_*.md` cluster (tasks #95-135) — found via
`Lib/test/test_finalization.py`, one of this cluster's 41 target files.
Not attempted — narrow-LOOKING (a literal string-equality check), but
widening it correctly needs real design (see "What a fix needs" below),
not a one-line change, so left for a dedicated pass per this task's
guidance on the less-mature coroutine codegen path.

## Symptom

One single root cause producing an unusually large blast radius in this
file — 18 distinct refusal messages, one per subclass that inherits the
affected method:
```
[gimple_codegen] generator method Simple.'test' not eligible (pass 2): test: a generator method must take `self` as its first parameter
[gimple_codegen] generator method SimpleBase.'test' not eligible (pass 2): test: a generator method must take `self` as its first parameter
[gimple_codegen] generator method NonGC.'test' not eligible (pass 2): test: a generator method must take `self` as its first parameter
... (15 more, one per subclass: NonGCResurrector, NonGCSimpleBase,
    LegacyResurrector, LegacySelfCycle, Legacy, LegacyBase,
    SimpleChained, SimpleResurrector, SimpleSelfCycle, SuicidalChained,
    SuicidalSelfCycle, SelfCycleResurrector, ChainedResurrector, and the
    module-level standalone `test` too)
```

## Root cause

The base method (`Lib/test/test_finalization.py`, ~line 54-57):
```python
@classmethod
@contextlib.contextmanager
def test(cls):
    ...
    yield
    ...
```
`test` is a `@classmethod` generator — its first parameter is `cls`, not
`self` (ordinary, correct Python: a classmethod's first parameter is
conventionally named `cls`, bound to the class rather than an instance).

`_gen_cpp_generator_unit`'s method-parameter handling
(`gimple_codegen.py`) does:
```python
if struct_name is not None:
    if not fn_params or fn_params[0][0] != 'self':
        raise _UnsupportedGeneratorShape(
            f"{fn.name}: a generator method must take `self` as its "
            "first parameter")
```
This is a literal STRING-EQUALITY check against the exact spelling
`'self'` — it doesn't ask "is this a bound method with a receiver
parameter" (which would be true for `cls` too, just bound to the class
object rather than an instance), it asks "is the first parameter's name
exactly the four characters `s-e-l-f`". Any classmethod generator —
regardless of what it does — fails this check and is refused outright,
even though nothing about being a classmethod is otherwise incompatible
with the generator machinery (the check exists to know what pointer TYPE
to give the receiver parameter — `f"{struct_name} *"` for `self` — a
classmethod's `cls` would need a different, but equally mechanical,
representation).

Since `test` is inherited by every listed subclass, and each subclass
gets its OWN entry in this codegen's per-struct method-compilation loop
(not deduplicated against the base class's own compile), one classmethod
generator produces one refusal PER subclass — explaining the unusually
large (18x) blast radius from a single root cause in this one file.

## Why this matters

`@classmethod` generators (`@classmethod` combined with `yield`, often
also wrapped in `@contextlib.contextmanager` as here) are a real,
if less common than plain instance-method generators, Python idiom —
worth fixing given how disproportionately large the observed blast
radius already is in just one file.

## What a fix needs

Not just relaxing the string check to also accept `cls` — the receiver
parameter's semantics genuinely differ:
1. A classmethod's `self`-equivalent (`cls`) represents the CLASS
   object, not an instance — this codegen's `self.<field>` MemberExpr
   support inside a generator (`_cpp_expr`'s existing, already-narrow
   "self field reads only" scope per `_gen_cpp_generator_unit`'s own
   docstring) has no analogous "class-level attribute" story at all
   today, compiled or otherwise, so a classmethod generator's body would
   need to either avoid touching `cls.anything` entirely (this file's
   own `test` example doesn't reference `cls` in its body at all, so it
   would happen to work if just the eligibility gate were widened) or a
   real class-attribute-access story would need to exist first.
2. The C++ signature convention (`<base>_start(params...)`) would need
   a way to represent "this is a classmethod, not an instance method" —
   currently every generator method assumes an instance receiver typed
   `{struct_name} *`; a classmethod has no instance at all.

Given `test`'s own body here doesn't actually touch `cls`, the MINIMAL
safe fix (widen the check to accept `cls` as an alternate literal name,
give it a scalar/opaque placeholder type since it's unused) might be
enough for this specific real-world case — but a general fix needs (1)
and (2) above resolved properly to avoid silently mishandling a
classmethod generator that DOES use `cls`.

## Minimal repro

```python
class Widget:
    @classmethod
    def make_range(cls, n):
        i = 0
        while i < n:
            yield i
            i += 1

def main():
    for x in Widget.make_range(3):
        print(x)

main()
```
Expected (per root cause above): `Widget.make_range` refused at the
generator-eligibility pre-filter with "a generator method must take
`self` as its first parameter", before any C++ is emitted, even though
`make_range`'s body never references `cls`.
