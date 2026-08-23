# CODEGEN_generator_function: Lib/calendar.py

## Status (updated 2026-08-23 — LAST own-file gap closed: flat-target `enumerate(<generator call>, start)` now delegates; calendar.py's own code compiles with ZERO errors)

**Fixed**: `itermonthdays2`'s `for i, d in enumerate(self.itermonthdays(year,
month), self.firstweekday):` — the "generator call as `enumerate`'s OWN
first argument" gap this doc's earlier entries documented as open. The FLAT
2-name-target enumerate branch in `_cpp_for_stmt` (gimple_cpp_core.py)
previously called `_cpp_expr(s.iterable.args[0])` directly on the generator
call, routing it through the ordinary void-returning extern "C" stub
("void value not ignored as it ought to be" ×2 at g++ time — the only two
remaining own-file errors in an isolated compile). It now mirrors the
NESTED-tuple-target case's existing composition: when enumerate's first
argument is itself a delegatable generator call (`_cpp_iterable_is_
delegatable_generator_call`) and there is no for/else, the whole loop
delegates through `_cpp_for_generator_delegate` with its existing
`index_var`/`index_start_expr` index tracking (the optional 2nd argument
supplies the start offset; the value slot comes from the sub-generator's
registered `value_ctype`). Commit: `0d59f49`.

**Verified**: isolated compile (`compile_to_gimple_with_cpp(do_imports=
False)` + `g++ -std=c++20 -fsyntax-only`) of real Lib/calendar.py:
cpp_errors went 2 → **0**, ci_errors already 0. Two new compiled-and-RUN
regression tests in `test_gimple_generator_runner.py`
(`enumerate_generator_method_arg_start`: `Cal.iterdaynum` consuming
`enumerate(self.iterdays(n), self.firstweekday)` with tuple yield + %7;
`enumerate_generator_free_fn_arg_start`: free-function callee) both assert
exact stdout. Whole-program `mojo.py build .../Lib/calendar.py`: **zero**
errors attributed to calendar.py itself (169 errors, ALL in
transitively-imported files — operator.py, posixpath.py, locale.py,
os.py, threading.py, dis.py, enum.py — none this doc's concern).
Note: `MOJO_DEBUG=1` still prints pass-1 "not eligible" lines naming
itermonthdates — those are benign retry-loop noise (pass 2 rescues them;
confirmed via generated .cpp containing `_mojogen_Calendar_itermonthdates_`).

Quality gate (CLAUDE.md): test_gimple.py 250/250, test_module_cache.py
76/76, make check-selfhost clean, from-scratch stdlib dylib rebuild 0
`skip <module>:` lines before and after (baseline captured before any edit).

calendar.py's OWN generator-codegen concerns are now exhausted — every
remaining build blocker is another module's separate, tracked-elsewhere
bug. Doc kept open only per the "file still doesn't build end-to-end"
convention; nothing calendar-specific remains.


## Status (updated 2026-08-20 — `_CLIDemoCalendar___init__` "too few arguments" arity bug FIXED; file still blocked by other, separate, already-documented gaps)

**Fixed**: `cal = _CLIDemoCalendar(highlight_day=today)` (line 904) produced
`error: too few arguments to function '_CLIDemoCalendar___init__'; expected
4, have 3` (isolated `compile_to_gimple(..., do_imports=False)` +
`gcc -fgimple -fsyntax-only`). `_CLIDemoCalendar.__init__(self,
highlight_day=None, *args, **kwargs)` is a LOCALLY-defined `__init__` (not
inherited — an earlier read of the task that assumed inheritance was
wrong), called with a single KEYWORD argument and no positional args at
all, against a `*args`/`**kwargs`-taking signature.

Root cause, in `gimple_codegen.py`'s `_build_call_args_for_candidate`
(struct-constructor/method overload-call arg builder, used by
`_lower_struct_constructor` via `_resolve_overload`'s chosen candidate):
the `chosen.get('has_varargs')` branch (constructor/method has a `*args`
pack param) built the params BEFORE the pack ("pre-star" params) with
`out = [self.lower_expr(a) for a in args[:pre_n]]` — POSITIONAL args
ONLY, never consulting the call's keyword arguments or the params' real
defaults at all. Real Python allows a pre-star param to be passed by
keyword too (`def f(x=None, *args, **kwargs)` called as `f(x=1)` is
completely ordinary Python) — when it was, this loop produced **no
entry whatsoever** for that param (not even a placeholder `0`), silently
dropping the value and shrinking the whole trailing arg list by one slot
system-wide, not just miscoercing it. For `_CLIDemoCalendar(highlight_day=
today)`: `pre_n=1` (`highlight_day` is the one pre-star param), `args=[]`
(no positional args — the call is keyword-only), so the pre-star loop
appended nothing at all; `today` was never emitted anywhere, and the
final call was `(self, <empty-args-pack>, <kwargs-slot>)` — 3 arguments
against the real 4-argument C signature `(self, highlight_day, args,
kwargs)`. (Separately, and fixed in the same pass: the post-star loop's
`**kwargs` slot handling in that same branch only ever checked whether
the literal string `'**kwargs'` was a key of the call's keyword-arg dict
— never true, since call sites use their real keyword names, not that
sentinel — so any keyword args that didn't bind to a named parameter
were silently dropped instead of being packed into the real `**kwargs`
dict the non-varargs sibling branch already does via `_pack_kwargs_dict`.)

Fix: the pre-star loop now tries, per param, (1) the positional arg at
that index if the call supplied one, else (2) the call's keyword
argument by that param's real name (popped from the working `kw` dict so
it isn't double-counted later), else (3) the param's real declared
default via the existing `_default_expr_to_pair` helper (already used
elsewhere in this file for the identical "pad a call that omitted a
defaulted trailing param" pattern — reused here rather than
re-implementing the same literal-default-to-C-pair logic a third time).
The post-star loop's `**kwargs` handling was fixed to match the
non-varargs branch: after pre-star and named post-star params consume
their matching keyword args (via `.pop`), any keyword args still left
unconsumed in `kw` are packed into a real `MojoDict *` via
`_pack_kwargs_dict` for the `**kwargs` slot, instead of always leaving it
null.

**Verification**:
- Isolated compile of the real `Lib/calendar.py` (`compile_to_gimple(...,
  do_imports=False)` + `gcc -fgimple -fsyntax-only -I runtime`): the
  `_CLIDemoCalendar___init__` arity error is gone; the file now produces
  **zero** gcc errors on this isolated-compile path (previously this one
  error was the only one surfaced at this compile mode — the many other
  errors this doc documents below only show up in the whole-program
  `do_imports=True` build, which pulls in the huge transitive import
  closure; not re-attempted here, out of scope for this narrow fix).
- Minimal standalone repro, compiled AND RUN end-to-end (`driver.
  compile_program`, real `gcc -fgimple` compile + link against the real
  stdlib dylib + execute the binary, not just a syntax check): a base
  struct `ZQBaseA.__init__(self, x=100, y=200, *args, **kwargs)`, a
  subclass `ZQSubA(ZQBaseA)` with **no `__init__` of its own** (genuinely
  inherited, matching this bug's original triggering shape) —
  `ZQSubA(x=42)` produced `a=42, b=200, c=0` (the keyword-bound pre-star
  param got its real value, the other pre-star param and the ordinary
  field both kept their real declared/hardcoded defaults) and `ZQSubA()`
  produced `a=100, b=200` (both real defaults, not zeroed) — confirmed
  ALL fields correct, not just "compiles". (A DIFFERENT repro shape where
  the SUBCLASS itself declares a brand-new field — e.g. `self.d = 999` —
  hit a separate, PRE-EXISTING, unrelated struct-layout bug: the
  generated C `struct` for such a subclass reorders/mistypes the
  inherited fields relative to the base struct's own layout, e.g. `int64_t
  a` becoming a 4-byte `int a` and the base's `c` field vanishing
  entirely, corrupting any `(Base *)self`-cast write. Confirmed
  bit-for-bit identical on the unpatched baseline tree — NOT a regression
  from this fix, not investigated further here, out of scope for this
  narrow arity fix. Real `calendar.py`'s own `_CLIDemoCalendar` struct
  shows the same symptom, e.g. phantom `int setfirstweekday`/`int
  formatyearpage` fields from an unrelated dynamic-attribute scan.)

**Quality gate** (CLAUDE.md mandatory gate): `python3 test_gimple.py`
(248 passed, 0 failed), `python3 test_module_cache.py` (76 passed, 0
failed), `make check-selfhost` (clean: "self-host compiles + links clean
(mojo.py compiling mojo.py)", 1 passed / 0 failed). From-scratch stdlib
dylib rebuild (`rm -f build/libmojostdlib.dylib` +
`build_stdlib_dylib.build_stdlib(jobs=8)`), compared against a baseline
rebuild on the pre-fix tree (baseline captured by checking out
`gimple_codegen.py` at the pre-fix commit `f0bdc29` in-place inside this
same worktree, building, then restoring the fixed file — NOT `git
stash`, per this session's explicit instruction to avoid the shared
`refs/stash` given other agents may be concurrently active in this
repo's object store): **0 skip lines before, 0 skip lines after**. Also
ran `python3 compile_stdlib.py -j8` before/after: **664/664 passed, 0
failed, both before and after** (this repo's own stdlib corpus doesn't
happen to exercise the specific "keyword-only call against a
pre-star-named param on a `*args`-taking struct `__init__`" shape this
bug required, so no count change either way — expected, not a red flag,
given the fix is a strict superset of the old behavior for every other
shape).

**calendar.py as a whole still does not build** (whole-program
`do_imports=True`) — the remaining blockers are exactly the ones already
documented below (the separate generator/enumerate/itertools gaps), plus
the pre-existing unrelated struct-inheritance-layout bug noted above for
subclasses that add their own new fields. Doc kept open.

## Status (updated 2026-08-18, later same day — `itermonthdays4`'s NESTED-tuple-`enumerate` target FIXED; file still blocked by the other, separate, already-documented gaps)

**Fixed**: `itermonthdays4`'s `for i, (y, m, d) in
enumerate(self.itermonthdays3(year, month)):` — the NESTED-tuple-target
`enumerate()` gap this doc's "2026-08-18" and "2026-08-10, later same
session" status sections both documented as open (`_cpp_for_stmt`'s
existing `enumerate` branch only ever recognized a FLAT 2-name unpack,
e.g. `for i, x in enumerate(...):`; a nested second element like `(y, m,
d)` fell through to the generic string-target fallback, which naively
comma-split the WHOLE target string — `"i, (y, m, d)"` — into 4 bogus
pieces and emitted `for (auto i, (y, m, d) : ...)`, invalid C++:
"declaration of 'auto i' has no initializer" / "expected ')' before ','
token"). Confirmed via `bugs/CODEGEN_generator_function_Lib_dis.md`'s
`_find_imports` as the SAME shared gap (its own `for i, (op, oparg) in
enumerate(opargs):`), fixed in the same pass.

`gimple_codegen.py`'s `_cpp_for_stmt`: the target string is now split with
the existing (previously module-scoped-but-unused-here)
`_split_top_level_commas` helper instead of a naive `.split(',')`
(depth-aware, so a nested tuple's own inner comma no longer corrupts the
outer split), and a new case recognizes `(idx, (a, b, ...))` — a flat
depth-1 nested tuple as the second element — paired with an
`enumerate(...)` iterable. `enumerate`'s own iterable argument can be
EITHER a call to another compiled generator (composed with the existing
`_cpp_for_generator_delegate` sub-generator drive loop — see that
method's extended signature below) OR a plain collection expression
(a `MojoList *` of boxed tuples, read back via the same
`mojo_list_get_int`-per-slot convention the plain-GIMPLE `_gen_for_list`
tuple-target case already uses, default int64_t per slot — matching the
existing FLAT-target enumerate case's own scalar-only assumption, not a
new limitation).

`_cpp_for_generator_delegate` gained two new optional parameters,
`index_var`/`index_start_expr`, so the nested-target case can compose an
`enumerate()` index with its existing sub-generator drive loop instead of
duplicating it: `index_var` is declared as `int64_t` OUTSIDE the drive
`while` loop (so it survives across iterations, unlike the tuple slots'
per-iteration locals), initialized to `index_start_expr` (also finally
plumbing `enumerate(x, start)`'s optional 2nd argument into this
composed path), and incremented once at the end of each iteration — the
rest of the method (tuple-slot unpack, single-value consumption,
self-recursion, exception re-throw) is completely unchanged.

**Verification**:
- Isolated compile (`relaxed_imports=True` `GimpleGen` direct call, the
  same methodology this doc's own prior status entries use to get past
  dis.py's/calendar.py's OTHER, unrelated hard-refusal generators without
  raising) + `g++ -std=c++20 -fsyntax-only` on real `Lib/calendar.py`:
  error count dropped from 10 (baseline, matching the "2026-08-18" status
  entry's own count) to 2 — the only 2 remaining are `itermonthdays2`'s
  SEPARATE, still-open "generator call as enumerate's own argument" gap
  (`cannot cast from type 'void' to pointer type 'MojoList *'`, lines
  275/277 in the isolated compile). `grep`-confirmed: zero occurrences of
  `auto i`/`no initializer`/`expected ')'` anywhere in the new error
  output — `itermonthdays4` itself is now completely clean.
- Two standalone end-to-end compiled-and-RUN repros (via
  `test_gimple_generator_runner.py`'s own harness — real compile ->
  `gcc -fgimple`/`g++ -std=c++20` -> link -> RUN, asserting on actual
  stdout):
  - `for i, (a, b, c) in enumerate(pairs()):` where `pairs()` is another
    compiled generator yielding 3-tuples (the `itermonthdays4`-shaped
    case, generator-delegate composition): correct index AND correct
    unpacked values for all 3 iterations, exact stdout match.
  - `for i, (a, b) in enumerate(xs):` where `xs` is a `list[tuple]`
    PARAMETER (a real `MojoList *`, not an inline list-of-tuples
    literal — see note below): correct index AND correct unpacked values,
    exact stdout match.
  - Note: an inline list-of-tuples LITERAL assigned to a local inside a
    generator body (`xs = [(1, 2), (3, 4)]`) fails to compile — but this
    is confirmed to be a PRE-EXISTING, unrelated gap shared identically
    by the FLAT (non-nested) enumerate case (`xs = [10, 20, 30]` alone,
    with no nested tuple involved, fails with the exact same "cannot
    convert '<brace-enclosed initializer list>' to 'int64_t'" error) —
    list-literal-to-local assignment inside a coroutine body has no
    codegen at all yet, orthogonal to this fix. Not attempted here.

**Quality gate** (CLAUDE.md mandatory gate): `python3 test_gimple.py`
(248 passed, 0 failed), `python3 test_module_cache.py` (76 passed, 0
failed), `make check-selfhost` (clean), and a from-scratch stdlib dylib
rebuild (`rm -f build/libmojostdlib.dylib` +
`build_stdlib_dylib.build_stdlib(jobs=8)`) compared against a baseline
rebuild on the pre-fix tree via `git stash`: **0 skip lines before, 0
skip lines after**, and the full stderr build log is **byte-identical**
before/after (`diff` clean). No regression.

**calendar.py as a whole still does not build.** The remaining blockers
are exactly `itermonthdays2`'s separate generator-call-as-enumerate's-
own-argument gap and the whole-program (`do_imports=True`) build's
hundreds of unrelated, pre-existing errors in transitively-imported
files — both already documented above, neither touched by this fix.
Doc kept open.

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
