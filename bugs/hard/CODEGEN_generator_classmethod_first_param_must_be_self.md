# HARD BUG: a generator method's first parameter must be literally named `self` — a `@classmethod` generator (first param `cls`) is refused outright

## Status (updated 2026-08-07)

**FIXED** (`gimple_codegen.py`, three call sites — see below). Root-caused
2026-08-06 while classifying the `CODEGEN_generator_function_Lib_*.md`
cluster (tasks #95-135) — found via `Lib/test/test_finalization.py`, one
of this cluster's 41 target files.

Implemented the "minimal safe fix" this doc originally sketched (widen
the first-param check to also accept `cls`, refuse if the body actually
touches `cls`) — plus TWO more instances of the identical root-cause
pattern that turned up during implementation, not mentioned in the
original write-up:

1. `_gen_cpp_generator_unit`'s method-eligibility check (the one this
   doc originally documented) now accepts `cls` as well as `self` for a
   generator method's first parameter. When the first param is `cls`,
   the method's body is scanned (`_walk_ast`) for ANY reference to `cls`
   (bare, `cls.attr`, or `cls.method(...)`) — this codegen has no
   class-level attribute/method-call story, so if `cls` is genuinely
   used, the method is refused with an accurate message instead of
   being silently accepted; if `cls` is provably unused, it's compiled
   with an opaque, never-read `int64_t cls` placeholder parameter purely
   to keep the emitted C++ signature's parameter count/position correct
   (the method-call CallExpr lowering already passes the receiver
   positionally, so nothing downstream depends on this parameter's name
   or value).

2. **Found while verifying fix #1 against a hand-built minimal repro**:
   `gen_module`'s "second + third passes" free-function generator loop
   (the one that retries generators with unresolved `yield from`
   dependencies) has its OWN, separate `s.params[0][0] == 'self'` check
   meant to skip generator METHODS (deferring them to the dedicated
   per-struct method loop). Unlike the first-pass loop (which only ever
   sees TOP-LEVEL `stmts`, so a real struct method can never reach it),
   this loop iterates `_generator_fns` directly — a dict built from a
   DEEP `_walk_ast(stmts)` scan, keyed by object identity — so it DOES
   see nested struct methods, including classmethod generators. Before
   this was widened to also recognize `'cls'`, a `@classmethod`
   generator method slipped past this "skip" check entirely and got
   compiled HERE instead, as if it were an ordinary free function
   (`struct_name=None`, `cls` treated as a plain scalar parameter,
   popped out of `_generator_fns` before the dedicated per-struct method
   loop — where fix #1 lives — ever got a turn). This was silently wrong
   two ways:
   - The compiled unit registers under the bare function name in
     `_generator_api`, which a `ClassName.method(...)` call site never
     looks up (call sites for a generator METHOD only ever consult
     `_generator_method_api`, keyed by `(struct_name, method)`) — so the
     unit was simply dead, unreachable code.
   - Worse: if the body ever read `cls.<attr>` (a REAL shape — see
     `Lib/test/test_finalization.py`'s `test`, confirmed below),
     `_cpp_expr`'s `MemberExpr` case falls to its "non-self member
     access" branch (`obj_expr.member`) since the receiver isn't
     literally named `self`, emitting `cls.attr` on a plain `int64_t
     cls` parameter — INVALID C++ (member access on a scalar), a hard
     g++ compile failure instead of a graceful source-level fallback.
     Hand-verified: before this second fix, a classmethod generator
     using `cls.count` (a struct field) produced `co_yield cls.count;`
     against an `int64_t cls` parameter in the generated `.cpp` — after
     the fix, it's correctly refused at the eligibility gate instead
     (falls back to interpreting that one function from source, same as
     any other not-yet-supported shape).

3. The identical `s.params[0][0] == 'self'` check in the FIRST-pass
   free-function loop was also widened to `('self', 'cls')` for
   consistency/defense-in-depth even though it's provably dead for this
   exact scenario today (that loop only iterates top-level `stmts`,
   which a struct method can never appear in) — kept in sync so the two
   checks don't silently diverge again.

## Real-world impact correction

This doc's ORIGINAL text claimed "`test`'s own body here doesn't
actually touch `cls`" as the basis for expecting the minimal fix to make
`Lib/test/test_finalization.py`'s `test` method compile. **That claim was
wrong** — rereading the real source (`Lib/test/test_finalization.py`
~line 54-70), `test`'s body reads `cls.del_calls`, `cls.tp_del_calls`,
`cls.errors` (twice) repeatedly:
```python
@classmethod
@contextlib.contextmanager
def test(cls):
    with support.disable_gc():
        cls.del_calls.clear()
        cls.tp_del_calls.clear()
        NonGCSimpleBase._cleaning = False
        try:
            yield
            if cls.errors:
                raise cls.errors[0]
        finally:
            NonGCSimpleBase._cleaning = True
            ...
```
So per item 1 above, `test` is (correctly) STILL refused post-fix — just
with the new, accurate "@classmethod generator that references `cls` in
its body is not supported" message instead of the old, misleading "must
take `self`" one. Confirmed via `MOJO_DEBUG=1`: all 16 inherited-subclass
refusals (`NonGCSimpleBase`, `SimpleBase`, `NonGC`, `NonGCResurrector`,
`Simple`, `SimpleResurrector`, `SimpleSelfCycle`, `SelfCycleResurrector`,
`SuicidalSelfCycle`, `SimpleChained`, `ChainedResurrector`,
`SuicidalChained`, `LegacyBase`, `Legacy`, `LegacyResurrector`,
`LegacySelfCycle`) now emit the corrected message, and the module still
falls back to interpreting `test` from source (unchanged end-to-end
outcome for THIS file: `compile_to_gimple` still raises the same
whole-module "cannot compile module: function(s) test ..." — the fix's
observable win for this exact file is entirely about the ACCURACY of the
refusal reason and eliminating the C++ miscompile risk item 2 above
found, not about newly compiling this file). A hand-built minimal repro
with a `cls`-UNUSED classmethod generator (this doc's own "Minimal
repro" below) DOES now compile successfully end-to-end (verified: g++
`-fsyntax-only` on the generated `.cpp` returns 0), confirming the fix
genuinely unblocks the case it was designed for — this file's `test`
method just isn't an instance of that case, contrary to this doc's
original (incorrect) claim.

## Gate

All five gates in CLAUDE.md's quality-gate section passed after this
fix: `test_gimple.py` (247 passed, 0 failed), `test_module_cache.py` (76
passed, 0 failed), `make check-selfhost` (self-host compiles + links
clean), a from-scratch `libmojostdlib.dylib` rebuild (0 `skip <module>:`
lines), and `compile_stdlib.py -j8` (664/664 passed, 0 unexpected
failures — same count as before this change).

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
