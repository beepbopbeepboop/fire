# HARD BUG: a function/method whose sole `return` is a bare list/dict/set comprehension gets its inferred return type wrongly defaulted to `int64_t`

## Status (updated 2026-08-07)

**Re-verified FIXED 2026-08-23**: this doc's own minimal repro
(`Widget.make_rows`) builds clean via `python3 mojo.py build` (exit 0)
on current `fix/perf-triage` and the binary runs, printing the
correctly-shaped nested list `[[None, 1], [2, 3], [4, 5]]` — same
result as the original verification including the documented,
unrelated "0 prints as None in a list" display quirk. No regression.

**FIXED** (task #145), with the extra-careful verification this doc's
own "What a fix needs" section called for (`_quick_type` is shared
inference machinery — full 5-step gate re-run, not just the two fast
unit-test suites). Root-caused 2026-08-06 while classifying the
`CODEGEN_generator_function_Lib_*.md` cluster (tasks #95-135) — found
via `Lib/calendar.py`, fixed 2026-08-07.

Added exactly the `Comprehension` case this doc's own "What a fix
needs" section described: `_quick_type` now returns `MojoDict *`/
`MojoSet *`/`MojoList *` per `node.kind` (`dict`/`set`/`list` or
`generator`, mirroring `_lower_comprehension`'s own kind->type mapping
exactly — a generator-expression converts to a list there too, so this
does the same rather than inventing a second, possibly-diverging
mapping), instead of falling through to the method's int64_t default.
An unrecognized `kind` still falls to int64_t, matching `_lower_
comprehension`'s own TODO-kind fallback (a plain scalar 0, not a
pointer) — no NEW unhandled-shape risk introduced beyond what emission
itself already tolerates.

## Verification

Hand-verified via a real `mojo.py build` on this doc's own minimal
repro (`Widget.make_rows`): confirmed via `git stash` that the exact
documented `-fgimple` errors ("non-trivial conversion in
'integer_cst'"/"type mismatch in binary expression") reproduce on
unmodified code, and are GONE after this fix — clean build (exit 0),
AND the compiled binary actually RUNS and returns a real, correctly-
shaped nested-list result (not just a clean compile). A second,
simpler repro (`return [i * i for i in range(n)]`) also builds and
runs correctly.

Noticed, NOT a regression: the printed values show `None` where `0`
is expected (e.g. `[None, 1, 4, 9, 16]` instead of `[0, 1, 4, 9, 16]`)
— confirmed via a THIRD, minimal repro (a plain top-level `items = [i
* i for i in range(5)]; print(items)`, which never touches `_quick_
type`'s new Comprehension case at all, since it's a local variable
typed by the ordinary, always-correct emission-time lowering, not by
return-type inference) that this is a separate, pre-existing "0 prints
as None in a list" display/boxing quirk, unrelated to this fix.

## Gate

All five gates in CLAUDE.md's quality-gate section passed, including
the extra care this doc's own "What a fix needs" section called for:
`test_gimple.py` (247/247), `test_module_cache.py` (76/76), `make
check-selfhost` clean, from-scratch `libmojostdlib.dylib` rebuild (0
`skip <module>:` lines, same as before), `compile_stdlib.py -j8`
(664/664, 0 unexpected — unchanged count). Also ran `test_gimple_
generator_runner.py` (32/34, 2 pre-existing failures, confirmed
identical via `git stash`) and `test_gimple_async_runner.py` (31/36, 5
pre-existing failures, confirmed identical via `git stash`) as extra
due diligence given this touches shared type-inference machinery used
by both the generator and async codegen paths — no new failures in
either.

## Follow-up (2026-08-18): the `isinstance`/`all`/`any` related data point

Confirmed and fixed the separate, related gap this doc's "Confirmed
occurrences" section flagged but left unconfirmed: `_quick_type`'s
`CallExpr`-on-`IdentExpr` handling (`_BUILTIN_SCALARS`) had no entry for
the builtins `isinstance`/`all`/`any` — all three always return a plain
Python `bool` regardless of their arguments, same "no argument-type
inspection needed" reasoning that made the `len`/`ord` addition safe —
so a bare `return isinstance(...)`/`return all(...)`/`return any(...)`
fell through to the `int64_t` default, same as this doc's own now-fixed
`Comprehension` gap.

**Important correction to this doc's original speculation:** extensive
isolated testing did **NOT** reproduce the same class of `-fgimple`
hard error ("non-trivial conversion in 'integer_cst'"/"type mismatch")
that the `Comprehension` bug produced. Tried, all clean (`gcc -fgimple
-fsyntax-only`, isolated `do_imports=False` compiles):
- A bare `return isinstance(x, int)` (single-return, unannotated).
- The literal shape from `Lib/functools.py:920`'s `_is_valid_dispatch_
  type` (`return True` / `return isinstance(cls, UnionType) and
  all(isinstance(arg, type) for arg in cls.__args__)`), reproduced
  verbatim as a `.mojo` repro AND compiled from the **real**
  `Lib/functools.py` in isolation (`compile_to_gimple(src,
  do_imports=False)` + `gcc -fgimple -fsyntax-only`) — no errors either
  way.
- A deliberately adversarial mixed-return-path shape (`if isinstance(x,
  str): return "text: " + x` / `return isinstance(x, int)`, forcing
  `TypeLattice.join` to pick `char *` as the declared return type over
  the isinstance branch's int64_t-defaulted guess) — still compiled
  clean. Inspecting the emitted `.ci`: `_safe_coerce_emit` always
  routes the int64_t→pointer coercion through an explicit `(char
  *)_tN;` cast **statement**, which `-fgimple`'s verifier accepts even
  for a pointer/int mismatch — unlike the original `Comprehension` bug,
  where GCC's complaint was specifically about an *implicit* mismatch
  against a raw integer constant, not an explicit cast assignment.

So the real `functools.py:920` function does NOT currently fail to
compile — this doc's original "same class of error" concern doesn't
hold up under direct testing. The gap in `_quick_type` is nonetheless
real (a genuinely wrong `int64_t` type estimate where the true value is
`_Bool`), so the fix was still applied as a narrow, mechanical, low-risk
precision correction mirroring the `len`/`ord` precedent exactly — not
because a live crash was confirmed.

### Fix

Added `'isinstance': '_Bool', 'all': '_Bool', 'any': '_Bool'` to
`_quick_type`'s `_BUILTIN_SCALARS` dict (`gimple_codegen.py`), same
dict `len`/`ord`/`float`/`int`/`str`/`chr`/`bool`/`repr` already live
in. No existing/partial handling of these three names elsewhere in
`_quick_type` (confirmed via grep for `'isinstance'`/`'all'`/`'any'`
across the whole file before adding — the only other hits are the real
LOWERING code for these builtins, `_lower_builtin_isinstance`/
`_lower_builtin_all_any`, a separate method). No name-shadowing guard
added, matching `len`/`ord`'s own precedent (neither of those guards
against a local variable named `len`/`ord` either).

### Verification

Two standalone repros, both compile AND run with correct boolean
output (not just clean compiles):
- `isinstance` against a user-defined class (`Animal`/`Rock`):
  `is_animal(Animal())` -> `True`, `is_animal(Rock())` -> `False`.
- `all`/`any` over a generator-expression argument: `all(x > 0 for x in
  [1,2,3])` -> `1`, `any(x < 0 for x in [1,2,3])` -> `0`, `any(x < 0
  for x in [1,-2,3])` -> `1`.

Also confirmed via `git stash` that a pre-existing, unrelated bug
(`isinstance(x, int)` against a plain `int64_t` scalar value doesn't
match — a separate `mojo_isinstance`/type-tag gap, out of this fix's
scope) reproduces identically before and after this change — not a
regression introduced here.

### Gate

All five gates in CLAUDE.md's quality-gate section passed, no
regression: `test_gimple.py` (248/248), `test_module_cache.py`
(76/76), `make check-selfhost` clean (self-host compiles + links,
`mojo_selfhost` runs), from-scratch `libmojostdlib.dylib` rebuild (0
`skip <module>:` lines, same as baseline), `compile_stdlib.py -j8`
(664/664, 0 unexpected — unchanged count, matching this doc's own
`Comprehension`-fix precedent exactly).

## Original diagnosis (unfixed-era notes, kept for history)

Not attempted at the time — see "What a fix needs" below for the
original scoping/risk analysis (still accurate; followed exactly).

## Why this belongs in this cluster (even though it isn't a coroutine bug)

Filed alongside the `CODEGEN_generator_function_Lib_*` cluster because
that's exactly where it was found and because it's the dominant reason
several of those files currently fail — but it is important to note
explicitly: **this is NOT a bug in the C++20-coroutine generator codegen
path** (`_gen_cpp_generator_unit` et al.). It's a bug in `_quick_type`,
the ordinary/general-purpose plain-C `.ci` (GIMPLE) return-type inference
used for EVERY function in the program. It surfaces disproportionately
often in this generator-codegen cluster's files because those files'
authors habitually write the idiom "consume a generator into a list via
`list(self.some_generator(...))`, then `return [transform(x) for x in
that_list]`" — i.e. the generator-consuming caller (not the generator
itself) is what trips this bug.

## Symptom

```
$ python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/calendar.py
/Users/mrs/net/Python-3.14.6/Lib/calendar.py:281:1: error: non-trivial conversion in 'integer_cst'
/Users/mrs/net/Python-3.14.6/Lib/calendar.py:281:1: error: type mismatch in binary expression
```//repeated at :291, :299, :309, :319, :328, once per subclass that
inherits the affected method (7 classes total in calendar.py alone, so
this one root cause produces 7x2=14 distinct GCC errors from one bug).

## Root cause

`GimpleGen._quick_type(self, node)` (`gimple_codegen.py`) is the
syntactic, no-emission expression-type estimator used by
`_collect_return_types`/`_infer_return_type` (which populates
`func_return_types` for every unannotated function/method, Pass 2/2b of
`gen_module`) and by several other inference passes. It has explicit
`isinstance` branches for `IntLiteral`, `FloatLiteral`, `BoolLiteral`,
`StringLiteral`, `IdentExpr`, `BinaryOp`, `CompareChain`, `UnaryOp`,
`TernaryExpr`, `CallExpr` (both `IdentExpr` and `MemberExpr` callees),
`MemberExpr`, `ListExpr`, `DictExpr`, `SetExpr`, `TupleExpr`,
`SliceExpr`, `SubscriptExpr` — but **no case at all for `Comprehension`**
(`mojo_compiler.py`'s AST node for `[x for x in y]`/`{k: v for ...}`/
`{x for x in y}`/generator-expressions, distinct from the literal
`ListExpr`/`DictExpr`/`SetExpr` nodes, which ARE handled). Because
`Comprehension` matches none of the `isinstance` checks, control falls
through to the method's final line, `return 'int64_t'`.

`return [ dates[i:i+7] for i in range(0, len(dates), 7) ]` parses to a
`Comprehension(kind="list", ...)` node. `_collect_return_types` calls
`self._quick_type(node.value)` on it, gets `'int64_t'` back, and that
becomes the method's registered return type in `func_return_types` (and
therefore its forward declaration's return type in the emitted C).

The method's *body*, however, is lowered correctly at emission time by
the SEPARATE, more thorough `_lower_Comprehension` — which knows a list
comprehension really produces a `MojoList *` — so the generated C ends up
with a mismatch: a forward declaration promising `int64_t`, and a `return`
statement that actually constructs a `MojoList *`, then pointer-casts it
down to `int64_t` to satisfy the wrong declared type:

```c
int64_t __GIMPLE Calendar_monthdatescalendar (Calendar * self, int64_t year, int64_t month)
{
  ...
  MojoList * _t8;              /* the REAL comprehension result */
  ...
  _t19 = (void *)_t8;
  _t20 = (int64_t)_t19;        /* pointer-to-int cast to fit the WRONG decl */
  _t18 = _t20;
  return _t18;
}
```

`gcc -fgimple` correctly refuses this shape ("non-trivial conversion in
'integer_cst'" / "type mismatch in binary expression") — the intermediate
list-slicing loop inside the comprehension (`mojo_list_slice`,
`mojo_list_append_int`, `i < _t9` comparisons) mixes the real
`MojoList *`-typed temporaries with the `int64_t`-typed ones the wrong
declared return forces elsewhere, producing several distinct GIMPLE
verifier complaints from the one root cause per affected method.

## Why this wasn't caught by the routine `compile_stdlib.py`/dylib gates

`return <comprehension>` as literally the SOLE, entire return expression
of a function (not stored in a local first, not one of several
differently-shaped return paths) is common but not universal — many
real-world comprehension-returning functions in the wider stdlib corpus
assign to a local first (`result = [x for x in y]; return result`, where
`_quick_type` on the local's own IdentExpr resolves through
`self.var_types`, which — populated by the ACTUAL, correct emission-time
lowering by the time a later statement references it — masks the bug for
that shape) or have multiple return paths that also include a
differently-typed non-comprehension branch. The specific "bare `return
[comprehension]`, nothing else" shape is what calendar.py's six sibling
methods all hit identically, which is likely why it surfaced so
consistently there but plausibly not everywhere a comprehension appears
in a return position across the full 664-file corpus.

## Confirmed occurrences

- `Lib/calendar.py`: `Calendar.monthdatescalendar`, `monthdays2calendar`,
  `monthdayscalendar`, `yeardatescalendar`, `yeardays2calendar`,
  `yeardayscalendar` (and every subclass that inherits them — 7 classes
  total) — see `bugs/CODEGEN_generator_function_Lib_calendar.md`.

Not yet independently confirmed in a second file with a full trace (a
few OTHER errors seen in this session's broader build logs — e.g.
`Lib/functools.py:920`'s `_is_valid_dispatch_type`, whose sole return is
`isinstance(...) and all(isinstance(arg, type) for arg in
cls.__args__)` — are a RELATED but distinct trigger: `_quick_type` has no
`CallExpr` case for the builtins `isinstance`/`all`/`any` either, so
those also silently default to `int64_t` where the real value is
`_Bool`. Same missing-case root cause in the same method, different AST
node shape; left as a related-but-unconfirmed data point rather than
folded into this doc's "confirmed occurrences" list, since it wasn't one
of this cluster's 41 target files and wasn't independently traced end to
end the way calendar.py was.)

## What a fix needs

Add a `Comprehension` case to `_quick_type` that estimates
`'MojoList *'`/`'MojoDict *'`/`'MojoSet *'` per `node.kind`, mirroring
the existing `ListExpr`/`DictExpr`/`SetExpr` literal cases. This alone is
a small, mechanical addition — but per this project's own "narrow scope"
discipline, it should be scoped/tested carefully: `_quick_type` is
consulted from many call sites beyond just return-type inference (call-
argument coercion, container-element-type pre-passes, etc. — grep shows
dozens of call sites throughout `gimple_codegen.py`), so changing its
behavior for ANY node shape is exactly the kind of "shared inference
machinery" change that has previously caused confident-looking
regressions elsewhere in this codebase (see this session's own guidance
citing the `_tuplegetter`/unannotated-`__init__`-param investigations).
A real fix should re-run the FULL 5-step quality gate (test_gimple.py,
test_module_cache.py, make check-selfhost, from-scratch stdlib dylib
rebuild comparing skip count, compile_stdlib.py -j8 comparing 664/664),
not just the two fast unit-test suites, exactly as CLAUDE.md's own
codegen quality-gate section already mandates for any `gimple_codegen.py`
change.

## Minimal repro

```python
class Widget:
    def make_rows(self, n):
        items = [i for i in range(n)]
        return [items[i:i+2] for i in range(0, len(items), 2)]

def main():
    w = Widget()
    print(w.make_rows(6))

main()
```
Expected (per root cause above): `Widget_make_rows` gets forward-declared
`int64_t` while its body constructs and returns a real `MojoList *`,
producing the same "non-trivial conversion"/"type mismatch" `-fgimple`
errors as the real `calendar.py` case.
