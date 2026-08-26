# CODEGEN_generator_function: Lib/dis.py

## Status (updated 2026-08-26, worktree fix/rest-remainder19d — checked against today's super()/self.__class__ fix (bdfb825) and generator-value-return-slot fix (326db78); neither applies, unchanged)

Fresh isolated `compile_to_gimple_with_cpp(do_imports=False)` repro:
byte-identical single refusal — `_get_instructions_bytes` on the same
`*`/`**`-unpack call-argument guard (`Positions(*next(co_positions,
()))`, a spread argument into a dynamically-constructed
`collections.namedtuple` type this codegen has no static representation
for). Neither of today's two landed fixes is relevant (unpack-call-
argument/namedtuple representation, unrelated to `super()`/
`self.__class__` or generator value-carrying `return`). No code change;
doc stays open.

## Status (updated 2026-08-26, worktree fix/rest-remainder16 — re-verified unchanged)

Fresh re-verify against this worktree (branched from master `a913ab8`).
Direct isolated `gimple_codegen.compile_to_gimple_with_cpp(...,
do_imports=False)` call: byte-for-byte identical single refusal —
`_get_instructions_bytes` on "a `*`/`**`-unpack call argument is not
supported in a compiled generator/coroutine body" (`Positions(*next(
co_positions, ()))`). No shared mechanism landed since the 2026-08-25
pass touches unpack-call-arguments or `collections.namedtuple`
representation. Still a two-feature stack (namedtuple-as-struct support
+ unpack-call-argument support), genuinely feature-sized. No change;
doc stays open.

## Status (updated 2026-08-25, worktree fix/rest-remainder14 — re-verified unchanged; deeper gap found)

Fresh re-verify against this worktree (branched from master `f65502d`).
Same single refusal, same site: `_get_instructions_bytes` refused for
"a `*`/`**`-unpack call argument is not supported in a compiled
generator/coroutine body" at `positions = Positions(*next(co_positions,
()))` (dis.py line 780). None of the fixes that have landed since the
last pass touch unpack-call-arguments.

Also checked whether the narrower "`KnownStruct(*expr)` special case"
previously proposed as a possible scoped-down fix is actually tractable:
it is not, for a reason not previously called out. `Positions` (line 284)
is `collections.namedtuple('Positions', (...))` — a DYNAMICALLY
constructed type, not a `struct`/`class` this codegen has any static
declaration for. `grep -n namedtuple gimple_codegen.py` returns zero
hits: this codegen has no representation for `collections.namedtuple`
at all, anywhere, so even a hypothetical `*`-unpack-into-known-arity-
constructor special case would have nothing to dispatch to here — the
"constructor" isn't a struct constructor in this codegen's model to
begin with. This makes the real gap strictly larger than "the same
`*`/`**`-unpack gap as codecs.py", closer to a two-feature stack
(namedtuple-as-struct support, PLUS unpack-call-argument support).
Genuinely feature-sized, not attempted. Doc stays open.

## Status (updated 2026-08-25, worktree fix/rest-remainder11 — re-verified unchanged)

Re-verified fresh against this worktree. `_get_instructions_bytes` still
refuses on `Positions(*next(co_positions, ()))` (line 799) — a spread
CALL ARGUMENT into a statically-known-arity struct constructor. This is
the same `*`/`**`-unpack-call-argument gap as codecs.py's blocker
(`bugs/CODEGEN_generator_function_Lib_codecs.md`), just against a known
struct constructor instead of a dynamic callee — still needs either a
general unpack-argument feature or a narrow `KnownStruct(*expr)` special
case, neither of which any of this session's or recent sessions' shared
fixes (struct-method extern-decl param typing, generator-consumption
ordering, `**kwargs`-forward slot alignment, `int()`/`float()` builtin
support, weak variadic stubs, `cls.attr` writes, classmethod-generator
receiver passing, mixed-yield refusal, chained-assignment type-hint
propagation) touch. Not attempted (feature-sized for this pass's scope).
Doc stays open.

## Status (updated 2026-08-24 — re-verified unchanged; confirmed via `MOJO_DEBUG=1 mojo.py build`)

Re-confirmed the 2026-08-23 entry exactly: `_get_instructions_bytes` is
retried across the multi-pass loop (its FIRST-pass refusal reason,
recorded via `_cpp_refusal_reasons.setdefault`, is a stale "consumed
generator must be defined earlier" message that a plain single-shot
build's error text still surfaces even though a LATER pass gets further
— confirmed via `MOJO_DEBUG=1`, which shows the refusal reason actually
change pass-to-pass, settling on "a `*`/`**`-unpack call argument is not
supported" by pass 4). The concrete blocker remains
`Positions(*next(co_positions, ()))` at line 799 — unchanged, no new
mechanism found. Not attempted (same reasoning as before: a dynamic-
arity spread call argument needs either a general unpack-argument
feature or a narrow special case for `KnownStruct(*expr)` against a
statically-known-arity constructor; out of scope for this pass). Doc
stays open.


## Status (updated 2026-08-23 — re-verified; refusal set narrowed to ONE function, whose blocker is the `*`-unpack call argument)

Fresh triage: the isolated compile now aborts on exactly ONE generator —
`_get_instructions_bytes`, refused with "a `*`/`**`-unpack call argument is
not supported in a compiled generator/coroutine body". The concrete site is
line 799's `Positions(*next(co_positions, ()))` — a spread CALL ARGUMENT
(the same honest-refusal guard codecs.py's iterencode hits), NOT a new
shape. All four generators named in the older entries below no longer
refuse together: `_unpack_opargs`, `findlinestarts`, and `_find_imports`
now pass eligibility and reach real coroutine generation (tuple-yield,
nested-tuple-enumerate, and delegate fixes all holding). The whole-program
build's `dis.py:915 variable or field 'instrs' declared void` /
`:904 invalid use of void expression` errors are DOWNSTREAM symptoms of
that single refusal: the ordinary-path fallback emits `_get_instructions_
bytes` as a void-returning C function and its caller assigns it. Making
THIS file build needs: (a) `*`-unpack call-argument support or a narrower
special case for the `f(*next(it, ()))` idiom, plus the previously-documented
`code.co_lines()` introspection / module-level-dict-globals (`opmap`) gaps
for the rest of the file. Still open; no new mechanism discovered.


## Status (updated 2026-08-18 — `_find_imports`'s NESTED-tuple-`enumerate` target FIXED; file still doesn't build)

**Fixed**: `_find_imports`'s `for i, (op, oparg) in enumerate(opargs):` —
one of the two remaining gaps this doc's "2026-08-10" status section
listed for `_find_imports` (the other, `code.co_lines()` native
code-object introspection in `findlinestarts`, is untouched, see below).
`_cpp_for_stmt`'s existing `enumerate` branch only ever recognized a FLAT
2-name unpack target (`for i, x in enumerate(...):`); a NESTED second
element like `(op, oparg)` fell through to the generic string-target
fallback, which naively comma-split the WHOLE target string —
`"i, (op, oparg)"` — into 3 bogus pieces and emitted `for (auto i, (op,
oparg) : opargs)`, invalid C++ ("declaration of variable 'i' with
deduced type 'auto' requires an initializer" / "expected ')'"). Same
shared gap independently confirmed in `calendar.py`'s `itermonthdays4`
(see that doc), fixed together in the same pass.

Fix (full mechanism in `bugs/CODEGEN_generator_function_Lib_calendar.md`'s
matching status entry, not duplicated here): `_cpp_for_stmt`'s target
string is now split with the existing `_split_top_level_commas` helper
(depth-aware) instead of a naive `.split(',')`, and a new case handles
`(idx, (a, b, ...))` paired with `enumerate(...)`. `opargs` here is a
plain `MojoList *` local (built earlier in the function by a list
comprehension over `_unpack_opargs(...)` — that comprehension's own
codegen is untouched/unrelated), so this hits the new "plain collection"
branch: an indexed loop reading each element back as a boxed-tuple
`MojoList *` via `mojo_list_get_int`, then each of `op`/`oparg` via
`mojo_list_get_int` per slot (default int64_t) — mirroring the
plain-GIMPLE `_gen_for_list` tuple-target convention. (`itermonthdays4`'s
own real case instead hits the OTHER new branch — `enumerate` wrapping a
call to another compiled generator, composed with the existing
`_cpp_for_generator_delegate` sub-generator drive loop — dis.py has no
real-corpus example of that composition, but it's exercised by an
isolated end-to-end repro below and by `itermonthdays4` itself.)

**Verification**:
- Isolated compile (`GimpleGen(do_imports=False, relaxed_imports=True)`
  direct call — bypasses `_get_instructions_bytes`'s unrelated, currently
  totally-unsupported generator shape so the rest of the module still
  gets a `.cpp` emitted instead of a hard `RuntimeError`, matching the
  spirit of this doc's own "isolated compile" methodology) +
  `g++ -std=c++20 -fsyntax-only` on real `Lib/dis.py`: the specific
  "declaration of variable 'i' ... requires an initializer" / "expected
  ')'" error pair at the `for i, (op, oparg) in enumerate(opargs):` site
  is gone — `grep`-confirmed zero remaining occurrences of that error
  shape anywhere in the output. The loop now lowers to a real indexed
  loop over `opargs` with `op`/`oparg` correctly unpacked per iteration.
  (Total error count in this isolated compile went from 20 to 28 — NOT a
  regression: the previous broken-syntax emission silently swallowed/
  mangled everything textually downstream of it, so several PRE-EXISTING,
  unrelated errors inside `_find_imports`'s own loop body — `opmap`
  module-global-dict resolution, `op == IMPORT_NAME` comparing an
  `int64_t` against a `char *`, `opargs[i-1]` raw-pointer subscripting —
  are now reachable/visible for the first time rather than newly
  introduced. Confirmed each new error line is inside `_find_imports`'s
  loop BODY, never the loop statement itself.)
- Two standalone end-to-end compiled-and-RUN repros (via
  `test_gimple_generator_runner.py`'s harness — real compile ->
  `gcc -fgimple`/`g++ -std=c++20` -> link -> RUN, asserting on actual
  stdout): `for i, (a, b, c) in enumerate(<3-tuple generator>()):` and
  `for i, (a, b) in enumerate(<list[tuple] parameter>):` both produced
  the correct index AND correctly unpacked values for every iteration,
  exact stdout match. (Full detail, including the one confirmed-unrelated
  gap found along the way — inline list-of-tuples LITERAL locals inside a
  coroutine body don't compile, matching the FLAT enumerate case's
  identical pre-existing limitation — is in the calendar.py doc's
  matching status entry.)

**Quality gate** (CLAUDE.md mandatory gate): `python3 test_gimple.py`
(248 passed, 0 failed), `python3 test_module_cache.py` (76 passed, 0
failed), `make check-selfhost` (clean), and a from-scratch stdlib dylib
rebuild compared byte-for-byte against a `git stash`-baseline rebuild:
**0 skip lines before, 0 skip lines after**, full stderr build log
byte-identical. No regression.

**dis.py as a whole still does not build.** Remaining, still-open,
unrelated gaps (unchanged from the "2026-08-10" status below):
`findlinestarts`'s `code.co_lines()` native code-object introspection,
module-level dict globals (`opmap`) unresolved inside a coroutine body,
`opargs[i-1]`-style raw-pointer subscripting, and the whole-program
(`do_imports=True`) build's hundreds of unrelated pre-existing errors in
transitively-imported files. Doc kept open.

## Status (updated 2026-08-10 — tuple-yield now FIXED, a separate pre-existing `_cpp_for_stmt` gap found+fixed too; file still doesn't build)

Re-verified against current master. The tuple-valued-`yield` fix landed
earlier this session (`_cpp_yield_tuple`/`_generator_tuple_yield_slot_
ctypes`, boxes a tuple yield into a real runtime `MojoList *`) resolves
the "every `yield` must carry a value..." refusal this doc's 2026-08-09
status documented for `_unpack_opargs`/`findlinestarts`/`_find_imports`
— confirmed via `MOJO_DEBUG=1 python3 mojo.py build .../Lib/dis.py`: none
of the three appear in the refusal list anymore.

**Found and fixed a SEPARATE, pre-existing bug this exposed**: dis.py's
`_get_instructions_bytes` and `_find_store_names` each consume
`_unpack_opargs` (a real tuple-yielding generator) via a PLAIN
(non-`yield from`) `for` loop —
```python
for offset, start_offset, op, arg in _unpack_opargs(original_code):   # _get_instructions_bytes
for _, _, op, arg in _unpack_opargs(co.co_code):                       # _find_store_names
```
`gimple_codegen.py`'s coroutine-body `for`-loop lowering (`_cpp_for_stmt`)
had no case at all for "iterable is a call to another compiled
generator" — only `enumerate(...)` got real tuple-target handling, and
the generic fallback treated a non-`enumerate` tuple target as one bogus
comma-joined C++ identifier (`for (auto offset, start_offset, op, arg :
...)` — invalid C++) while also calling the callee through the wrong
(non-coroutine) extern "C" stub gen_module's "unknown module-level
symbol" preamble falls back to for an unrecognized callee. Also
independently confirmed as the SAME gap in `calendar.py`'s and
`weakref.py`'s own generators (see those docs) — this was a real, shared,
previously-undocumented `_cpp_for_stmt` limitation, not the tuple-yield
promise/ABI gap the earlier fix targeted.

**Fixed**: new `_cpp_for_generator_delegate` (`gimple_codegen.py`) drives
the sub-generator via its own `<base>_start/_resume/_value/_destroy` API
— the same calling convention and `_mojogen_sub_guard` RAII cleanup
`_cpp_yield_from`'s existing `yield from`-delegation already uses —
assigning each produced value into the loop target(s) (tuple-unpacked via
the same `MojoList*`-of-boxed-elements convention `_cpp_yield_tuple`/
`_emit_generator_tuple_unpack` already established) instead of
re-`co_yield`ing it. Source-order dependency (`_unpack_opargs` is defined
AFTER its callers in dis.py's real source) is handled the same way
`yield from` already handles it: a new `self._all_generator_names`
(every generator name in the module, computed once up front) lets the
new code tell "real generator, just not compiled yet" apart from "not a
generator at all", raising `_UnsupportedGeneratorShape` for the former so
gen_module's existing multi-pass retry loop picks the caller back up once
the callee is compiled.

Verified via an isolated compile: both `_unpack_opargs`-consuming
for-loops now lower through the correct `_mojogen_` API and are free of
the previous errors. Also verified END-TO-END with a standalone
compiled-and-run test program (a `for a, b in <2-tuple generator>():`
loop, a `for a, b, c in <3-tuple generator>():` loop, and an early
`break` mid-loop) — all produced the correct runtime values. Commit:
`5d8839d`.

**dis.py as a whole still does not build** — separate, unrelated gaps
remain, confirmed via a fresh isolated compile + `g++ -fsyntax-only`
after the fix (58 → 54 errors; the specific `_unpack_opargs`-for-loop
error clusters are gone, everything else is pre-existing/unrelated):
- `findlinestarts`: `for start, end, line in code.co_lines():` — a
  method call on a real Python `code` object, which this codegen has no
  native representation for at all (unrelated feature: code-object
  introspection).
- `_find_imports`: `opargs = [(op, arg) for _, _, op, arg in
  _unpack_opargs(...) if op != EXTENDED_ARG]` (a list comprehension with
  tuple-target unpack over a generator call, a DIFFERENT emission path
  from the plain-`for`-statement one just fixed) followed by
  `for i, (op, oparg) in enumerate(opargs):` — a NESTED tuple target
  inside `enumerate()`, which the existing enumage-handling branch (flat
  2-name unpack only) doesn't support either.
- Module-level dict globals (`opmap`) and the `code`/`co` parameter's real
  type aren't resolved inside a coroutine body in several of these
  functions, producing `'opmap' was not declared in this scope`-style
  errors independent of the for-loop shape.
- The whole-program (`do_imports=True`) build was already failing for
  hundreds of unrelated pre-existing errors in transitively-imported
  files before reaching dis.py's own coroutine compile at all (same
  pattern already documented for `calendar.py`/`codecs.py`) — the
  whole-program error count (500) is unchanged before/after this fix,
  confirming it wasn't reaching this stage either way.

Doc kept open — real progress made and independently verified, but
dis.py genuinely still doesn't build, for the separate reasons above.

## Status (updated 2026-08-09, re-diagnosed — root cause changed)

**STILL FAILING, but the symptom described below is now STALE.** The
previously-documented failure (`_get_instructions_bytes`'s `arg_resolver`
struct-typed parameter being refused) is **fixed** — that was
`bugs/hard/CODEGEN_generator_struct_typed_param_refused.md` (task #147,
commit `5d22b29`, doc since removed per project convention after the
fix landed). Confirmed: a fresh `MOJO_DEBUG=1` run no longer emits any
"unsupported type ... ArgResolver" refusal, and `_get_instructions_bytes`
itself is never even reached — the build now fails earlier, on three
DIFFERENT generators:

```
$ MOJO_DEBUG=1 python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/dis.py
[gimple_codegen] generator '_unpack_opargs' not eligible for C++ coroutine path, falling back to honest refusal: _unpack_opargs: every `yield` must carry a value, and all values must agree on one scalar type (int64_t/double/_Bool)
[gimple_codegen] generator 'findlinestarts' not eligible for C++ coroutine path, falling back to honest refusal: findlinestarts: every `yield` must carry a value, and all values must agree on one scalar type (int64_t/double/_Bool)
[gimple_codegen] generator '_find_imports' not eligible for C++ coroutine path, falling back to honest refusal: _find_imports: every `yield` must carry a value, and all values must agree on one scalar type (int64_t/double/_Bool)
Error building: cannot compile module: function(s) _find_imports, _unpack_opargs, findlinestarts (generator function(s), contain a `yield`/`yield from`) — ... falling back to interpreting this module from source instead
```

**Classification: tuple-valued `yield`** — this is the well-known,
already-catalogued C++20-coroutine-promise scope boundary (the promise
only carries a single scalar `int64_t`/`double`/`_Bool`; there is no
representation for a tuple/struct value crossing a suspend point), the
same family as `bugs/CODEGEN_generator_function_Lib_ftplib.md`'s `mlsd`
case. Confirmed by reading the exact `yield` sites in
`/Users/mrs/net/Python-3.14.6/Lib/dis.py`:

- `_unpack_opargs` (line 934): `yield (i, i, op, arg)` and
  `yield (i, start_offset, op, arg)` — a 4-tuple.
- `findlinestarts` (line 981): `yield start, line` — a 2-tuple.
- `_find_imports` (line 995): `yield (names[oparg], level, fromlist)` —
  a 3-tuple.

Because this is a module-level (not imported) generator refusal, it
escalates to a fatal whole-module `RuntimeError` for `mojo.py build`'s
CLI path (the error text's claimed graceful fallback isn't actually
taken for the root file being built).

Since these three generators are earlier in the file than
`_get_instructions_bytes`, that function's own struct-typed-parameter
codepath is never reached in the current build; whether it now compiles
cleanly (post the #147 fix) is unverified and moot until the
tuple-yield limitation is addressed.

Not fixed here — this is the same genuine, already-assessed
feature-sized coroutine-codegen scope boundary (widening the C++20
coroutine promise type to carry a tuple/struct value across suspend
points is a real feature, not a narrow bug fix), and per this session's
scope, only narrow/safe fixes clearly outside the shared inference
machinery were in scope for this pass.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/dis.py
