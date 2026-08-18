# CODEGEN_generator_function: Lib/calendar.py

## Status (updated 2026-08-18 — item 2 (`itertools.repeat` in `yield from`) FIXED; file still blocked by other, separate, already-documented gaps)

**Item 2 FIXED**: `itermonthdays`'s `yield from repeat(0, days_before)` /
`yield from repeat(0, days_after)` (the finite 2-argument `itertools.repeat`
form — `from itertools import repeat` at the top of the file) previously
had no lowering anywhere in the coroutine-body (`.cpp`) emitter: `repeat`
isn't a list/tuple literal, isn't a generator this compile has itself
translated, so it fell into `_cpp_yield_from`'s generic "plain collection
expression" fallback, which tried to evaluate `repeat(0, days_before)` as
an ordinary call via `_cpp_expr` — `repeat` has no C symbol anywhere in
this codegen, producing `'repeat' was not declared in this scope`.

Fixed in `gimple_codegen.py` with a new narrow, shared helper
`_is_itertools_repeat2_call(call)` (matches bare `repeat(value, times)` or
qualified `itertools.repeat(value, times)`, exactly 2 positional args, no
kwargs — deliberately NOT the 1-arg infinite form) used at three call
sites:
- `_yield_from_delegate_ctype`: a `yield from repeat(value, times)` site
  now contributes `value`'s own inferred type (via
  `_infer_simple_expr_ctype`, default `int64_t`) to the enclosing
  generator's unified promise type, instead of falling to the function's
  generic "anything else -> char *" default.
- `_cpp_yield_from`: emits a native counted loop — evaluate `value` and
  `times` ONCE (matching Python's own one-time-evaluation semantics), then
  `co_yield value` exactly `times` times:
  ```cpp
  {
      auto _rep_val = <value-expr>;
      int64_t _rep_n = <times-expr>;
      for (int64_t _rep_i = 0; _rep_i < _rep_n; _rep_i++) {
          co_yield _rep_val;
      }
  }
  ```
- `_cpp_for_stmt`: the analogous PLAIN (non-`yield from`) `for x in
  repeat(value, times):` consumption path got the same native-loop
  treatment for completeness (mirroring how `range(...)` already gets its
  own indexed-loop special case there), though no real corpus source this
  doc covers actually uses that shape — `_cpp_for_stmt` and
  `_cpp_yield_from` are genuinely separate code paths, each needed its own
  case, not a shared one.

**A second, closely-related gap surfaced and was fixed in the same pass**:
`itermonthdays`'s THREE `yield from` sites are `repeat(0, days_before)`,
`range(1, ndays + 1)`, `repeat(0, days_after)` — all three must agree on
one promise type. Fixing `repeat` alone (contributing `int64_t`) exposed
that `yield from range(...)` had NO special case in either
`_yield_from_delegate_ctype` (fell to the generic "anything else -> char
*" default, clobbering the whole function's promise type to `char *`) or
`_cpp_yield_from` (fell to the generic `mojo_range()`-as-`MojoList*`-of-
strings fallback, `co_yield`-ing `mojo_list_get_str(...)` — char*, wrong
for a promise now correctly typed `int64_t`, and wrong even on its own
terms since `range()`'s elements are always integers). This was
previously invisible because `repeat`'s own hard "not declared" compile
error always fired first. Fixed by adding the same-shape pair of cases for
`range(...)` (mirroring `_cpp_for_stmt`'s own pre-existing, working
`range()` indexed-loop special case): `_yield_from_delegate_ctype` now
returns `int64_t` for any `range(...)` yield-from (1-3 args), and
`_cpp_yield_from` emits a native indexed counted loop instead of the
generic string-based fallback.

**Verification**:
- Two isolated runtime repros via `test_gimple_generator_runner.py`'s own
  `_build_generator_program`/`test_generator_stdout` harness (real
  compile -> `gcc -fgimple`/`g++ -std=c++20` -> link -> RUN, asserting on
  actual stdout, not just "compiles clean"): `yield from repeat(0, 3)`
  interleaved with a sibling scalar `yield 99` and a second
  `repeat(0, 2)` site produces `0\n0\n0\n99\n0\n0\n` exactly; a second
  repro mixing `repeat(0, n)` / `range(1, 4)` / `repeat(0, 2)` in one
  generator (mirroring `itermonthdays`'s exact real shape) produces
  `0\n0\n0\n1\n2\n3\n0\n0\n` exactly. Both PASS.
- Real `Lib/calendar.py`, isolated `compile_to_gimple_with_cpp(src,
  do_imports=False)` + `g++ -std=c++20 -fsyntax-only`: **zero** occurrences
  of `repeat` or `range`/type-mismatch errors anywhere in the output.
  `Calendar.itermonthdays` and `Calendar.itermonthdays3` now compile
  completely cleanly. The g++ syntax check's remaining 11 errors are
  ALL inside `itermonthdays2`/`itermonthdays4` and are exactly the two
  separate, already-documented, unrelated gaps from this doc's own
  "2026-08-10, later same session" status below: `itermonthdays2`'s
  `for i, d in enumerate(self.itermonthdays(...), self.firstweekday):`
  (generator call as `enumerate`'s own argument, wrong extern "C" stub —
  "void value not ignored") and `itermonthdays4`'s `for i, (y, m, d) in
  enumerate(...)` (nested tuple target inside `enumerate` — "declaration
  of 'auto i' has no initializer"). Neither touched by this fix; both
  remain open, as before.

**Quality gate** (CLAUDE.md mandatory gate for `gimple_codegen.py`
changes): `python3 test_gimple.py` (248 passed, 0 failed), `python3
test_module_cache.py` (76 passed, 0 failed), `make check-selfhost` (clean:
"self-host compiles + links clean"), and a from-scratch stdlib dylib
rebuild (`rm -f build/libmojostdlib.dylib` +
`build_stdlib_dylib.build_stdlib(jobs=8)`) compared byte-for-byte against
a baseline rebuild on the pre-fix tree via `git stash`: **0 skips before,
0 skips after**, and the full stderr build log (160 "drop stale export"
lines, 1 "localize" line, 0 "exclude" lines) is **byte-identical**
before/after. No regression.

**calendar.py as a whole still does not build end-to-end** — this was
never in scope for item 2. The remaining blockers are exactly the ones
already documented elsewhere in this file: the nested-tuple-target
`enumerate()` gap and the generator-call-as-`enumerate`'s-own-argument gap
(both `itermonthdays2`/`itermonthdays4`, see above), and the whole-program
(`do_imports=True`) build's hundreds of unrelated, pre-existing errors in
transitively-imported files. Doc kept open.

## Status (updated 2026-08-10, later same session — item 1's `_cpp_for_stmt` gap FIXED for the plain-tuple-target case; file still blocked by other, separate gaps)

Item 1 below (`_cpp_for_stmt` treating a non-`enumerate` tuple target as
one bogus C++ identifier) is **fixed** for the shape that actually
affects `itermonthdates`: `for y, m, d in self.itermonthdays3(year,
month):` — a PLAIN tuple-target `for` loop delegating to a generator
METHOD (`self.<method>(...)`, not a free function). This was fixed in
two steps this session, both shared with `bugs/CODEGEN_generator_
function_Lib_dis.md` (see that doc for the full mechanism writeup):
first a new `_cpp_for_generator_delegate` added real support for a plain
`for`-loop consuming ANOTHER COMPILED GENERATOR via its own
`<base>_start/_resume/_value/_destroy` API (mirroring `_cpp_yield_from`'s
existing delegation drive-loop) for a bare free-function callee
(commit `5d8839d`); then a follow-up extended the SAME mechanism to also
resolve a `self.<method>(...)` callee via `self._generator_method_api`
(commit `05bcb91`), passing `self` as the receiver argument to
`<base>_start` exactly like an ordinary compiled method already does.

Verified via an isolated compile + `g++ -fsyntax-only`:
`Calendar.itermonthdates`'s for-loop over `self.itermonthdays3(...)` now
lowers through the correct `_mojogen_Calendar_itermonthdays3_*` API and
is completely free of errors (previously: 5 errors — "declaration of
'auto y' has no initializer" etc.). Confirmed with `grep`: zero remaining
occurrences of `itermonthdates` in the isolated compile's error output.

**Re-reading `itermonthdays4`'s REAL source** (this doc's item 1, below,
mis-described its shape — it's not a second instance of the SAME plain
tuple-target loop; it's a nested-tuple target INSIDE `enumerate()`):
```python
def itermonthdays4(self, year, month):
    for i, (y, m, d) in enumerate(self.itermonthdays3(year, month)):
        yield y, m, d, (self.firstweekday + i) % 7
```
`for i, (y, m, d) in enumerate(...)` is a NESTED tuple target (an outer
2-tuple `(i, (y, m, d))` whose second element is itself a 3-tuple) —
`_cpp_for_stmt`'s existing `enumerate` branch only ever supported a FLAT
2-name unpack (`for a, b in enumerate(x):`), so this shape is still
refused (`declaration of 'auto i' has no initializer` / `expected ')'
before ',' token`), unrelated to the fix above. Similarly,
`itermonthdays2` does `for i, d in enumerate(self.itermonthdays(...),
self.firstweekday):` — here the GENERATOR CALL is `enumerate`'s OWN
first argument, not the loop's iterable directly; the existing
`enumerate` branch's `_src = self._cpp_expr(s.iterable.args[0])` calls
`_cpp_expr` directly on that generator call, which routes through the
ordinary (non-coroutine) `self.method(...)` call lowering and picks up
the wrong extern "C" stub — a third, separate `_cpp_for_stmt`/`_cpp_expr`
gap this fix doesn't reach either. Neither of these two was attempted
this pass (both are distinct, additional shapes beyond the one item 1
actually described and this fix targeted).

Also unaffected: item 2 below (`itertools.repeat` unimplemented in the
coroutine-body expression emitter) and item 3 (hundreds of unrelated
pre-existing errors in transitively-imported files blocking the
whole-program `do_imports=True` build regardless) — both still apply
verbatim.

**calendar.py as a whole still does not build.** Doc kept open — real,
verified progress on item 1's actual (non-nested) case, but two
further, distinct tuple/enumerate-interaction gaps plus items 2-3 remain.

## Status (updated 2026-08-10 — tuple-valued yield now FIXED; file still blocked by other, unrelated gaps)

Implemented real tuple-valued-`yield` support this session (`yield a,
b, ...` boxes the tuple's elements into a real runtime `MojoList *`
at the yield site — `_cpp_yield_tuple`, `gimple_codegen.py` — and
unboxes it on the consumer side via `_gen_for_generator_iter`'s/
`_compr_generator_loop`'s new tuple-target handling, keyed off
`_generator_tuple_yield_slot_ctypes`). Confirmed via an isolated
compile (`compile_to_gimple_with_cpp(..., do_imports=False)` +
`g++ -fsyntax-only`) that `itermonthdays2`/`itermonthdays3`/
`itermonthdays4` (the three generators this doc's 2026-08-09 status
identified as tuple-yield-refused) now compile past the eligibility
gate, and their own `co_yield`/tuple-boxing lines are syntactically
valid C++ with no errors.

**calendar.py still does not build clean**, for reasons independent of
tuple-yield:

1. `itermonthdates`'s and `itermonthdays4`'s own bodies do
   `for y, m, d in self.itermonthdays3(...):` — a PLAIN (non-`yield
   from`) `for` loop, inside a coroutine body, over another compiled
   generator, with a non-`enumerate()` tuple target. `_cpp_for_stmt`
   only special-cases a tuple target for `enumerate(...)`; any other
   tuple-target iterable (including a sibling generator call) falls
   through to treating the WHOLE comma-joined target string as one bogus
   C++ identifier, e.g. `for (auto y, m, d : Calendar_itermonthdays3(...))`
   — real, malformed C++. This is a separate, pre-existing gap in the
   coroutine-body `for`-loop lowering (not the yield/promise machinery
   this session's fix touches) — also confirmed independently in
   `weakref.py`'s and `Tools/c-analyzer/c_parser/datafiles.py`'s own
   generators (see those docs). Not attempted here.
2. `itermonthdays`'s own body calls `itertools.repeat(...)` inside a
   `yield from` — `repeat` has no lowering in the coroutine-body
   expression emitter (`'repeat' was not declared in this scope`),
   unrelated to tuple-yield.
3. The whole-program (`do_imports=True`) build still hits hundreds of
   unrelated, pre-existing errors in transitively-imported files
   (`operator.py`, `posixpath.py`, `enum.py`, ...) — same situation the
   2026-08-07 status below already documented for this exact file.

Doc kept open (not deleted) — tuple-yield is no longer this file's
blocker, but the file genuinely still doesn't build.

## Status (updated 2026-08-09)

Re-verified against current master (`3d36ccd`) via `python3 mojo.py build
/Users/mrs/net/Python-3.14.6/Lib/calendar.py`. The comprehension-return-
type fix below is confirmed still in effect (no "non-trivial conversion"/
"type mismatch" errors), but the whole-program build now fails earlier,
with a clean, honest refusal instead of a GCC error:

```
Error building: cannot compile module: function(s) itermonthdays2,
itermonthdays3, itermonthdays4 (generator function(s), contain a
`yield`/`yield from`) — this codegen compiles every function into a
single straight-line C function and has no suspend/resume state-machine
transform for generators, nor an event loop / suspend-resume codegen for
async functions, yet, so these cannot be represented as compiled C
without emitting silently wrong or broken code; falling back to
interpreting this module from source instead
```

**Root cause: this is the known, already-documented "tuple-valued
`yield`" sub-gap** (`_generator_yield_ctype` in `gimple_codegen.py`,
~line 2647): the C++20-coroutine promise type this codegen emits for a
generator only supports a single scalar value (`int64_t`/`double`/
`_Bool`/`char *`), and `_generator_yield_ctype`'s own `YieldExpr` case
explicitly detects a `TupleExpr` yield value and returns `None` (by
design — see the long comment at that call site, which cites this exact
family of bug as its rationale) so the caller (`_gen_cpp_generator_unit`)
raises `_UnsupportedGeneratorShape`, correctly falling the whole method
back to "not eligible for the C++ coroutine path" rather than emitting
invalid/miscompiled C++.

Confirmed against `calendar.py`'s real source
(`Calendar.itermonthdays2`/`itermonthdays3`/`itermonthdays4`, lines
240-272):
- `itermonthdays2`: `yield d, i % 7` — a 2-tuple.
- `itermonthdays3`: `yield y, m, d` — a 3-tuple.
- `itermonthdays4`: `yield y, m, d, (self.firstweekday + i) % 7` — a
  4-tuple.

`itermonthdates`/`itermonthdays` (lines 219-238), which yield a single
scalar/struct value each (`yield datetime.date(y, m, d)` /
`yield from repeat(...)` / `yield from range(...)`), are NOT affected —
confirmed absent from the current refusal list, consistent with the
"Calendar's OWN generator methods now compile cleanly" note from the
2026-08-06 status below, which only ever covered the non-tuple-yield
methods.

Per this session's mandate for the generator/coroutine family: this is
an already-known, out-of-scope structural gap (no tuple-yield
representation in the coroutine promise), not attempted here. Not
fixed — doc kept and updated with the precise confirming instance per
the standing "check fresh, update accurately" instruction for this
family.

## Status (updated 2026-08-07, superseded above)

**Classification bug FIXED** (`bugs/hard/CODEGEN_comprehension_return_
type_defaults_int64.md`, task #145) — `_quick_type` now has a
`Comprehension` case. Confirmed via a direct, isolated compile
(`compile_to_gimple(..., do_imports=False)` on `calendar.py`'s own
source, then `gcc -fgimple -fsyntax-only` on the result): **0 errors**
— both the "non-trivial conversion"/"type mismatch" errors this doc
originally reported AND the trailing `_CLIDemoCalendar___init__` arity
error are gone. `calendar.py`'s OWN code now compiles cleanly in
isolation.

`python3 mojo.py build .../Lib/calendar.py` (the full whole-program,
`do_imports=True` build) still fails — but now entirely due to
UNRELATED, pre-existing issues in OTHER, transitively-imported files
(`os.py`'s `relpath`-ambiguity refusal, several distinct pre-existing
`operator.py` errors) that have nothing to do with calendar.py's own
code or this bug. Not investigated further (out of scope for this
comprehension-return-type fix).

## Status (updated 2026-08-06, superseded above)

**STILL FAILING**, but the failure has moved and is NOT actually inside
the coroutine-codegen path anymore. Re-diagnosed from scratch against
current master (`2b0c4c5`) via `python3 mojo.py build
/Users/mrs/net/Python-3.14.6/Lib/calendar.py`. The old 2026-07-30 error
("`y` was not declared" in a generator .cpp) no longer reproduces —
`Calendar.itermonthdates`/`itermonthdays`/etc. (calendar.py's own
generator methods) now compile cleanly through the C++20-coroutine path.

The CURRENT failure is a plain-C `.ci`/GIMPLE-stage error, in
NON-generator methods that merely *consume* a generator:

```
/Users/mrs/net/Python-3.14.6/Lib/calendar.py:281:1: error: non-trivial conversion in 'integer_cst'
/Users/mrs/net/Python-3.14.6/Lib/calendar.py:281:1: error: type mismatch in binary expression
[... same pair repeated at :291, :299, :309, :319, :328, once per each of
Calendar's 7 subclasses (TextCalendar, HTMLCalendar,
LocaleTextCalendar, LocaleHTMLCalendar, _CLIDemoCalendar,
_CLIDemoLocaleCalendar) that inherit the affected methods ...]
/Users/mrs/net/Python-3.14.6/Lib/calendar.py:904:3: error: too few arguments to function '_CLIDemoCalendar___init__'; expected 4, have 3
```

**Root cause (confirmed by reading the generated `calendar.ci`):**
`Calendar.monthdatescalendar`/`monthdays2calendar`/`monthdayscalendar`/
`yeardatescalendar`/`yeardays2calendar`/`yeardayscalendar` each look like:

```python
def monthdatescalendar(self, year, month):
    dates = list(self.itermonthdates(year, month))
    return [ dates[i:i+7] for i in range(0, len(dates), 7) ]
```

`dates = list(self.itermonthdates(...))` (consuming the real generator)
lowers correctly into an inline drive-loop
(`_mojogen_Calendar_itermonthdates_start/_resume/_value/_destroy`) that
builds a real `MojoList *`. The problem is the method's OWN declared
return type: `_infer_return_type`/`_collect_return_types` (used to
populate `func_return_types` for unannotated methods, gimple_codegen.py's
Pass 2b) calls `_quick_type(node.value)` on the `return [...]` statement's
value — a `Comprehension(kind="list", ...)` AST node — but `_quick_type`
has **no `isinstance(node, Comprehension)` case at all**, so it silently
falls through to the final default and returns `'int64_t'`. The method's
real body (correctly, via the separate `_lower_Comprehension`/emission-
time lowering) builds and returns an actual `MojoList *`, so the
generated C has a forward declaration/return type of `int64_t` while the
body constructs and casts a `MojoList *` through a pointer-to-int cast
to satisfy it — `gcc -fgimple` correctly rejects the resulting cast/
comparison shapes as "non-trivial conversion"/"type mismatch".

**This is NOT a generator-codegen-path bug** — `_quick_type` is the
general-purpose, project-wide return/expression-type estimator used for
ALL functions (generator-adjacent or not); any function whose ONLY
`return` statement is a bare list/dict/set comprehension is affected.
It surfaces here specifically because calendar.py's own idiom style is
"consume a generator into a list, then return a comprehension over
slices of it" for six sibling methods in a row. Documented in detail,
with root cause and fix-scope notes, in
`bugs/hard/CODEGEN_comprehension_return_type_defaults_int64.md` — this
file is one of the confirming instances for that hard bug (recurs
identically in at least `Lib/glob.py`; see that file's own bug doc).
Not fixed here (see that hard-bug doc for why: this is
`_quick_type`, the same broad, high-blast-radius inference surface this
project's existing guidance says to change only with great care).

The trailing `_CLIDemoCalendar___init__` arity error (line 904) is a
distinct, apparently unrelated pre-existing issue not investigated
further here (out of scope for this generator-codegen cluster).

## Build error (current, 2026-08-06)

```
/Users/mrs/net/Python-3.14.6/Lib/calendar.py:281:1: error: non-trivial conversion in 'integer_cst'
/Users/mrs/net/Python-3.14.6/Lib/calendar.py:281:1: error: type mismatch in binary expression
```

Source file: /Users/mrs/net/Python-3.14.6/Lib/calendar.py
