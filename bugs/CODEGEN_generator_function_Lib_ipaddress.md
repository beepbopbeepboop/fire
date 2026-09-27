# CODEGEN_generator_function: Lib/ipaddress.py

## Status (2026-09-05 — cluster E MISCOMPILE fixed -> honest refusal; module still not buildable)

The cluster-E miscompile below is fixed. `gimple_gen_coro._eligible` now
refuses a generator method whose body *calls* the result of a `@property`
getter — `self.<prop>(args)` where `<prop>` is a `@property` on the struct
or any of its in-module base classes (new `_property_call_ok` /
`_seed_prop_names`, the latter walking `StructDef.bases` so an inherited
property like `_BaseNetwork._address_class` is recognised on
`IPv6Network`). `_BaseNetwork.__iter__`, `_BaseNetwork.hosts` and
`IPv6Network.hosts` (all doing `self._address_class(x)`) now fall through
to the cpp path's own honest refusal instead of the A3 path emitting
`_BaseNetwork__address_class(self, x)` (arity 2 vs the getter's 1) —
broken, non-compiling C.

Verified: fresh isolated `compile_to_gimple_with_cpp(do_imports=False)`
generated `.c` now passes `gcc -fgimple -fsyntax-only` clean (was 3 hard
`too many arguments to function '..._address_class'` errors). Regression
test `generator_calls_property_getter_result` in
`test_gimple_generator_runner.py`.

**Still not buildable end-to-end**: the cpp companion unit for the 3
refused generators still has the pre-existing ~12 errors this doc's
history already attributes to feature-sized gaps (a `@property` read
leaving a raw `std::function`, `IPv4Network`/`IPv6Network` name
resolution inside a coroutine body, the unannotated-param int64_t family).
Compiling `self._address_class(x)` *correctly* needs a
dynamic-class-object-as-callable-value model (the property returns the
`IPv4Address`/`IPv6Address` class, then constructs from it) — genuinely
feature-sized, not attempted. Doc stays open.

## Status (2026-09-05 — A3 stack-switch cutover: no longer refused, but MISCOMPILES, cluster E)

Fresh isolated `compile_to_gimple_with_cpp(do_imports=False)` no longer
raises a generator refusal — all 8 generators
(`_find_address_range`, `summarize_address_range`,
`_collapse_addresses_internal`, `_BaseNetwork.hosts` / `.__iter__` /
`.address_exclude` / `.subnets`, `IPv6Network.hosts`) lower through the
A3 path. **However** `_BaseNetwork.__iter__` and `IPv6Network.hosts`
emit broken C:

```
ipaddress.py:696: error: too many arguments to function '_BaseNetwork__address_class'; expected 1, have 2
ipaddress.py:2351: error: too many arguments to function 'IPv6Network__address_class'; expected 1, have 2
```

`self._address_class(x)` — `_address_class` is a `@property` returning a
class object, which is then *called* to construct an address. The
compiled generator body lowers `self._address_class(x)` as a direct
method call `_BaseNetwork__address_class(self, x)` (arity 2) instead of
`(<property getter>(self))(x)`. This is **cluster E** (property that
returns a callable, then invoked) — likely shared with the non-generator
compiled path. Needs property-call detection in the generator-body
call emitter.

## Status (2026-09-03 — resumable list-iterator value model landed; `_find_address_range` no longer refused; refusal set 4 -> 2)

Landed in `gimple_cpp_core.py` a genuine iterator-object value model for
compiled generator/coroutine bodies (the gap the 2026-08-11 entry's
finding (a) called for — "invent a genuine resumable-list-iterator
representation ... an explicit index cursor threaded alongside the list"):

- **`it = iter(<list-expr>)`** binds `it` to the underlying `MojoList *`
  plus a companion `int64_t` cursor local (tracked in a new per-unit
  `_cpp_list_iter_cursor` map). Fires when the argument is statically a
  `MojoList *` / boxed-`int64_t` container.
- **`next(it)`** reads `mojo_list_get_int(list, cur++)`; on exhaustion
  throws a tagged `StopIteration` `_MojoCppExc` (catchable by an
  enclosing try/except in this body). **`next(it, default)`** returns the
  default instead. Both emitted as a single inline lambda expression.
- **`for x in it:`** continues from the shared cursor (which `next(it)`
  may already have advanced) and leaves it exhausted — real Python
  single-pass semantics, not a restart from element 0.
- **`min(iterable)` / `max(iterable)`** over a list -> `mojo_min` /
  `mojo_max`; multi-arg **`min(a, b, ...)` / `max(...)`** -> inline
  ternary/if fold. Neither existed in this emitter before.

Fresh isolated `compile_to_gimple_with_cpp(do_imports=False)`: the
refused-generator list shrank from `_collapse_addresses_internal,
_find_address_range, subnets, summarize_address_range` (4) to **`subnets,
summarize_address_range` (2)**. `_find_address_range`'s
`it = iter(addresses); first = last = next(it); for ip in it: ...`
compiles through the coroutine path now.

New end-to-end regression tests in `test_gimple_generator_runner.py`
(`generator_list_iterator_cursor_and_minmax`,
`generator_list_iterator_stopiteration_caught`) compile+link+run real
binaries.

**Still open for a full close of this file** (all unrelated to
iterators): `subnets` yields heterogeneous types across sites (str +
tuple) and needs `IPv4Network`/`IPv6Network` name resolution +
struct-object-keyed dicts; `summarize_address_range` hits an unresolved
`ip(...)` callee (address-class constructor). `_find_address_range`
still won't LINK end-to-end because its loop body does `ip._ip` on a
list element (the unannotated-param/struct-in-list int64_t-defaulting
family), but it is no longer a generator-eligibility refusal. Doc stays
open.

## Status (2026-09-03 — coroutine-body infra landed; this file's 3 refused generators unchanged)

Fresh isolated `compile_to_gimple_with_cpp(do_imports=False)`:
`_find_address_range` (`next(it)` on a plain external iterator),
`subnets` (`every yield must carry a value...` — yields str/tuple across
sites plus needs `IPv4Network`/`IPv6Network` name resolution and a
struct-object-keyed dict), and `summarize_address_range` (`min(...)`
over an iterable) all still refused, byte-identical reasons to the
entries below. Each is independently feature-sized; none attempted this
session. General coroutine-body infra landed this session (`var x =
<expr>` VarDecl lowering; type-dispatched `String(x)`/`str(x)` for
body-built strings — see the imaplib doc's 2026-09-03 entry) does not
reach these blockers. Doc stays open.

## Status (re-verified 2026-08-26, later same day — full current blocker set precisely enumerated; all STRUCTURAL, not attempted)

Fresh re-verify: `_collapse_addresses_internal`'s own `list(...)` gap
stays fixed (see the entry below), but the function itself is still
refused, now on `to_merge.pop(0)` — no `.pop()` support on `MojoList *`
anywhere in the coroutine-body emitter — and the SAME function
immediately behind that needs a struct-object-KEYED dict (`subnets[
supernet] = net`, keyed by `IPv4Network`/`IPv6Network` instances), which
has no representation in this codegen's dict model (keys are always
scalar/string today). Plus 3 more independently-refused generators in
this file: a `min(...)` call (no min-over-iterable support, unlike the
already-landed `sorted(...)`), a `next(it)` cursor-advance pattern
(distinct from imaplib.py's `next(self)` shape this session's `next()`
yield-type fix targets — see `bugs/CODEGEN_generator_function_Lib_
imaplib.md` — this one needs a real external-iterator-state
representation, not just return-type inference), and a `@property`
read as a bound method value. Adding `.pop(0)` alone would not unblock
the file (the struct-keyed-dict gap sits immediately behind it), so not
attempted in isolation — each of the 4 remaining gaps is independently
feature-sized. Doc stays open.

## Status (updated 2026-08-26 — loop-as-expression codegen landed; ADVANCED, not closed: `_collapse_addresses_internal`'s `list(...)` refusal is FIXED, a deeper `.pop()` gap now blocks it)

Implemented real loop-as-expression codegen in the compiled-generator/
coroutine C++ emitter this session (`gimple_cpp_core.py`'s new
`_cpp_build_container_from_iterable`/`_cpp_rename_ident`, wired into
`_cpp_expr`'s `Comprehension` case and a new `list(x)`/`set(x)`
single-arg `CallExpr` case; matching `_infer_simple_expr_ctype` widening
in `gimple_exprtypes.py`) — see `bugs/CODEGEN_generator_function_Lib_
codecs.md`'s entry of the same date for the full implementation writeup
(this doc's own repro was one of the two confirmed real-world targets).

Fresh isolated `compile_to_gimple_with_cpp(do_imports=False)` (strict)
repro, A/B'd against the pre-fix tree via `git stash`: the strict-mode
refused-generator list shrank from **4 to 3** —
`_collapse_addresses_internal` (blocked by `list(addresses)`, "a call to
unresolved callee 'list(...)'") no longer appears in the refusal at all.
`_find_address_range` (`next(it)` on a plain iterator — unrelated,
untouched), `subnets`, and `summarize_address_range` (`min(...)` —
unrelated) remain refused, byte-identical reasons to before.

Relaxed-mode (`GimpleGen(do_imports=False, relaxed_imports=True)`, this
doc's own established methodology) `.cpp` syntax-check went from 23 to
**24** errors (A/B'd via the same stash): `_collapse_addresses_internal`
now compiles far enough to reach the next real gap the 2026-08-25
"rest-remainder14" entry below already flagged as separate and deeper —
`to_merge.pop(0)` (a `.pop()` call on a `MojoList *`, "request for
member 'pop' in 'to_merge', which is of pointer type 'MojoList*'") — no
`.pop()` support anywhere in this coroutine-body emitter. The other 23
errors are byte-identical to the prior entry's 4 families (`IPv4Network`/
`IPv6Network` name resolution, `@property`-as-bound-method leaving a raw
`std::function`, `_address_class` too-many-arguments, the unannotated-
param pointer/int comparison) — confirmed unaffected.

**Net effect for this file**: real, concrete progress (one whole
generator's primary blocker eliminated), but the file's other three
refused generators and `_collapse_addresses_internal`'s own new `.pop()`
gap are untouched — still does not build. `min()`/`.pop()`/struct-keyed-
dict/property-as-value/the unannotated-param family remain feature-sized,
not attempted here. Quality gate: `test_gimple.py` 264/264 (263 + 1 new
regression test for this shape), `test_module_cache.py` 76/76, `make
check-selfhost` clean, from-scratch stdlib dylib rebuild 0 skip lines.
Doc stays open.

## Status (re-verified 2026-08-26, worktree agent-aac0d33be914873b5 — independent re-verify, byte-identical, no change)

Independent fresh isolated `compile_to_gimple_with_cpp(do_imports=False,
MOJO_DEBUG=1)` (strict, not relaxed) repro on the real file:
byte-identical 4-generator refusal — `_collapse_addresses_internal`,
`_find_address_range`, `subnets` (both `IPv4Network`/`IPv6Network`), and
`summarize_address_range`, all "every `yield` must carry a value.../
unresolved callee" family shapes. Confirms the opencode-genlib2 entry
immediately below. Aggregate remains feature-sized (min/list builtins,
struct-dict keys, property-as-bound-method, plus the excluded
unannotated-init-param family); not attempted. No code change; doc
stays open.

## Status (re-verified 2026-08-26, worktree fix/opencode-genlib2 — exactly the 19d entry's 23 errors, same families)

Fresh relaxed isolated compile (`GimpleGen(do_imports=False,
relaxed_imports=True)`, matching this doc's own methodology) +
`g++-mp-15 -std=c++20 -fsyntax-only`: **23 errors**, byte-consistent
with the 2026-08-26 rest-remainder19d entry — same four families:
the `IPv4Network`-not-declared cluster at its `subnets`-adjacent sites
(IPv4Network's typedef/methods absent while IPv6Network's are present,
consistent with IPv4Network.subnets being one of the relaxed-skipped
generators), 3× `invalid cast from type 'std::function<long long int()>'
to int64_t` + "void value not ignored" (`@property`-as-bound-method:
`self.address_class` leaving a raw callable value where a value is
needed), 3× `_address_class` too-many-arguments/void-use, and 1× ISO C++
pointer/int comparison (the excluded unannotated-param family). The
strict-mode refusal list (`_collapse_addresses_internal` on `list(...)`,
`_find_address_range` on `next(...)`, `summarize_address_range` on
`min(...)`, `subnets`) was not re-derived separately this pass; nothing
landed touches any of these families. Aggregate remains feature-sized;
not attempted. No code change; doc stays open.

## Status (updated 2026-08-26, worktree fix/rest-remainder19d — checked against today's super()/self.__class__ fix (bdfb825) and generator-value-return-slot fix (326db78); neither applies)

Fresh isolated `GimpleGen(do_imports=False, relaxed_imports=True)` repro
(matching this doc's own established methodology) + `g++-mp-15 -std=c++20
-fsyntax-only`: **23 errors** now (vs 19 in the 2026-08-25 entry), and
the strict (non-relaxed) refusal list grew from 3 to 4 generators —
`subnets` now also refuses, alongside `_collapse_addresses_internal`/
`_find_address_range`/`summarize_address_range`. Spot-checked that this
isn't a regression from today's two fixes: none of the new/changed error
lines involve `super()`, `self.__class__`, or a generator's own value-
carrying `return` — they're the same already-documented families
(`@property`-as-bound-method leaving a raw `std::function<...>` instead
of invoking it, `IPv4Network`/`IPv6Network` name resolution inside a
coroutine body, `_address_class` too-many-arguments, unannotated-param
pointer/int comparisons — all pre-existing shapes this doc's history
already attributes to `min()`/`list()`/struct-keyed-dict/property-as-
value gaps, none touched by either of today's landed fixes). Given the
excluded HIGH-RISK unannotated-init-param-type family underlies several
of these, and the remainder (min/list builtins, struct-dict keys,
property-as-bound-method) is genuinely feature-sized in aggregate, not
attempted here — consistent with every prior entry's classification. Not
investigated further why the exact count/generator-set shifted slightly
(23 vs 19, +1 refused generator) — plausibly just more of the module
being reachable now due to unrelated upstream fixes changing which
functions get far enough to reach these g++-stage errors, not a
regression in anything this run touched. No code change; doc stays open.

## Status (updated 2026-08-25, worktree fix/rest-remainder14 — re-verified; picture is WORSE/more complex than the "1 remaining error" the last pass recorded)

Fresh re-verify against this worktree (branched from master `f65502d`).
A strict isolated compile (`compile_to_gimple_with_cpp(...,
do_imports=False)`, no `relaxed_imports`) now hard-refuses the WHOLE
module up front — 3 generators, none of which is the previously-cited
`other == self` blocker: `_collapse_addresses_internal` ("a call to
unresolved callee 'list(...)'"), `_find_address_range` ("...'next(...)'"
— the already-tracked plain-iterator-cursor gap (a)), and
`summarize_address_range` ("...'min(...)'"). Re-ran with
`GimpleGen(do_imports=False, relaxed_imports=True)` (matching this doc's
own established methodology, since the current `compile_to_gimple_with_
cpp` wrapper doesn't plumb `relaxed_imports` through at all — confirmed
by reading `_run_pipeline`, `gimple_codegen.py`) to skip those 3 and let
the rest of the module still emit a `.cpp`: `g++-mp-15 -std=c++20
-fsyntax-only` on the result now reports **19 errors**, not 1 — the
2026-08-24 "15 -> 1" count evidently only reflected the errors reachable
in that particular pass's set of eligible generators, not the true
current count once these newly-surfaced unresolved-builtin refusals are
accounted for.

New findings, none previously documented for this file:
- `summarize_address_range` (ipaddress.py:200) uses 2-arg `min(a, b)` —
  no `min()`/`max()` builtin support anywhere in the coroutine-body
  emitter (`gimple_cpp_core.py` has `len`/`str`/`int`/`float`/`sorted`
  cases only, confirmed via direct grep — no `min`/`max`/`list`).
- `_collapse_addresses_internal` (ipaddress.py:255) uses `list(addresses)`
  (copy-construct), then goes considerably further than a narrow `list()`
  gap would fix: `subnets = {}` keyed by NETWORK-OBJECT instances
  (`subnets[supernet] = net`, `subnets.get(supernet)`,
  `del subnets[supernet]`), `sorted(subnets.values())` over struct
  pointers, and `>=`/`!=` struct-instance comparisons via dunder methods
  — a dict-keyed-by-struct-object representation this coroutine model has
  no support for at all. Fixing just `list()` would not make this
  function compile; the real gap here is struct-object dict keys/values
  iteration inside a coroutine body, itself feature-sized.
- The 19 g++ errors in the surviving `.cpp` are dominated by a
  `@property`-as-bound-method pattern (`_address_class` accessed as
  `self.address_class` inside another method, leaving a raw
  `std::function<int64_t()>` instead of invoking it — 3 occurrences) plus
  the already-documented `other == self` pointer/int comparison
  (unannotated ordinary-function-parameter family).

None of this is addressed by any recently-landed shared mechanism (none
add `min`/`list` builtin support or struct-keyed-dict/property-as-value
handling to the coroutine path). Given the added scope found here, this
file's real remaining gap is larger than "1 pointer/int comparison" —
correcting the record. Not attempted (feature-sized in aggregate). Doc
stays open.

## Status (updated 2026-08-25, worktree fix/rest-remainder11 — re-verified unchanged)

Re-verified fresh against this worktree (the 2026-08-24 `%`-format fix
is present/holding). ipaddress.py's own isolated `.cpp` still has exactly
the 1 remaining error: `if ((other == self))` — an ISO C++ pointer/int
comparison, the same unannotated-parameter-defaults-to-int64_t hard bug
(`bugs/hard/CODEGEN_ctor_arg_field_type_scalars_only.md`, which
supersedes the removed
`CODEGEN_unannotated_init_param_field_type_defaults_int64.md`)
extended to ordinary function params. Not this pass's to fix (same
high-regression-risk shared machinery that doc's own history documents).
Whole-program build still separately blocked by transitively-imported-
file errors, unrelated to ipaddress.py's own code. No change; doc stays
open.

## Status (updated 2026-08-24 — the `%`-format tuple/scalar RHS crash FIXED; own-.cpp errors 15 -> 1)

Re-verified via a fresh isolated compile (`GimpleGen(do_imports=False,
relaxed_imports=True)` + `gcc-mp-15 -fgimple -fsyntax-only` / `g++-mp-15
-std=c++20 -fsyntax-only`): `.ci` side is clean (0 errors, matches prior
sessions); the `.cpp` side had grown to 15 errors since the last status
entry below (not a regression from anything in THIS cluster — the file
just reaches further now than when "72 errors" was last measured).
12 of those 15 were one shared root cause: `BaseNetwork.address_exclude`
building raise-messages via `"%s and %s are not of the same version" %
(self, other)`/`"%s is not a network object" % other`/`"%s not contained
in %s" % (other, self)` — the coroutine-body expression emitter (`_cpp_
expr` in `gimple_cpp_core.py`) had NO case at all for Python's `%`-string-
format operator; a scalar RHS produced an invalid raw C++ `%` on a `const
char *` operand, and a TUPLE RHS produced literal garbage syntax
(`"fmt" % {self, other}`, a brace-init-list as the right operand of `%`).

**Fixed** (`gimple_cpp_core.py`): new `_cpp_percent_format` helper — the
coroutine-body counterpart of the ordinary GIMPLE path's existing
`_lower_percent_format` (`gimple_gen_exprs.py`), which can't be reused
directly since it emits GIMPLE temp-declaration statements via `gen.
_new_val` and this emitter only ever returns one inline C++ expression
string. Builds the equivalent as a nested `mojo_str_cat(...)` expression
tree, dispatching each `%s`/`%r`/`%d`/`%i` operand's stringification off
`_infer_simple_expr_ctype` (`mojo_str`'s existing int/pointer heuristic
for a generically-typed `int64_t` operand — the same one `str(x)` already
uses in this emitter — for anything not statically `char *`/`double`).
Deliberately narrow: only bare specs (no width/precision) with a matched
spec/operand count; anything else falls through to the previous
(unchanged) behavior. Wired into `_cpp_expr`'s `BinaryOp` `%` case ahead
of the generic numeric-modulo fallback.

Verified: `ipaddress.py`'s own isolated `.cpp` errors 15 -> 1 (the
remaining one, `if ((other == self))` — an ISO C++ pointer/int comparison
— is the SAME unannotated-parameter-defaults-to-int64_t hard bug tracked
in `bugs/hard/CODEGEN_ctor_arg_field_type_scalars_only.md`
extended to ordinary function params, not this fix's concern). Also fixed
the same crash class in `enum.py` (`_iter_bits_lsb`'s `%r`) and
`ftplib.py` (`FTP.mlsd`'s `"MLSD %s" % path`) — see those docs.

Full mandatory gate: `test_gimple.py` 252/252, `test_module_cache.py`
76/76, `make check-selfhost` clean, from-scratch stdlib dylib rebuild 0
skip lines (unchanged from baseline). Commit `d3154a6`.

`ipaddress.py` as a whole still does not build end-to-end — the
remaining pointer/int-comparison error above, plus the usual
transitively-imported-file errors in a real whole-program build, are
unrelated to this fix and not attempted here.


## Status (updated 2026-08-23 — CORRECTION to the 2026-08-20 entry: the isolated compile was only ever checking the .ci; the .cpp has 72 errors, all pre-existing shapes)

The 2026-08-20 entry's "isolated compile of ipaddress.py's own code now
completely clean" claim checked ONLY the `-fgimple` .ci side. Re-running
the SAME isolated compile and ALSO syntax-checking the companion coroutine
.cpp shows **72 errors** — the two "separate, deeper pre-existing gaps"
the 2026-08-11 entry documented did NOT silently disappear; they live in
the .cpp that entry's methodology never examined. Breakdown (all shapes
already documented in this doc or its siblings):
- `summarize_address_range`'s unannotated `first`/`last` params used as
  objects (`first.version`, `first._ip`, `other.subnet_of` — ×3+ each),
  and `_find_address_range`'s `ip._ip`/`last._ip`: the unannotated-param
  int64_t-defaulting family (tracked hard-bug class).
- `'next' was not declared` + `invalid use of void expression` in
  `_find_address_range`: `it = iter(addresses); first = last = next(it)` —
  the plain-iterator-cursor gap (a); unchanged since 2026-08-11.
- 7× "expected primary-expression before '{'" / 5× "invalid cast from
  'std::function<long long int()>' to int": braced-init text and
  callable-value casts emitted where the surrounding statement can't
  accept them — further instances of the coroutine-expression-emitter
  fallthrough class this doc's history records.
No regression from this session's three generic fixes (own-file .cpp error
count moved only 74 → 72 via them). Both real blockers remain
feature-sized/unannotated-type-family; still not attempted.


## Status (updated 2026-08-20 — unbound-instance-method arity bug FIXED; isolated compile of ipaddress.py's OWN code now fully clean; whole-program build still blocked by unrelated transitively-imported-file errors)

Root-caused and fixed 4 real `too many arguments` errors, all the same
unbound-instance-method idiom: `IPv4Address.__eq__(self, other)` /
`IPv4Address.__lt__(self, other)` / `IPv6Address.__eq__(self, other)` /
`IPv6Address.__lt__(self, other)` (lines 1435, 1447, 2221, 2233) — a
pre-`super()` cooperative-inheritance call to an ORDINARY (non-static,
non-classmethod) instance method with `self` passed explicitly by the
caller. `gimple_codegen.py`'s `_lower_call` "Class/static method call"
gate (~line 13020) previously prepended the class-ref value as an
implicit first arg for every non-`@staticmethod` method — correct for
a real `@classmethod`, wrong here (double-counts `self`). Fixed by
gating the prepend on `self._classmethod_names` (real classmethods
only) instead of `not in self._static_methods`; see
`bugs/CODEGEN_generator_function_Lib_mailbox.md`'s 2026-08-20 entry for
the full root-cause writeup, the same fix, and a related cross-module
`_classmethod_names`/`_static_methods` sharing gap also fixed alongside
it (not ipaddress.py-specific, but relevant since this file's own
`IPv4Address`/`IPv6Address` classes are typically imported by other
modules in a whole-program build).

Verified via isolated `compile_to_gimple(do_imports=False)` +
`gcc-mp-15 -fgimple -fsyntax-only`, A/B'd against the pre-fix code (a
temporary `git checkout --` of `gimple_codegen.py` in this same
worktree, restored after): all 4 named errors present before, zero
after — **the isolated compile of ipaddress.py's own code is now
completely clean** (zero errors, only benign pre-existing
`-Wshift-count-overflow` warnings on 64-bit IPv6 int shifts, unrelated
to this fix). This also means the two "separate, deeper pre-existing
gaps" ((a) `next(it)` on a plain iterator, (b) `summarize_address_range`
unannotated-param typing) recorded in the 2026-08-11 entry below no
longer reproduce — apparently fixed by other work on this codebase
since then; not independently re-investigated here, just honestly
noted as no longer blocking during this session's re-verification.

**ipaddress.py's own code has zero errors, but the file still does not
achieve a full `fire.py build` end-to-end** — the whole-program,
`do_imports=True` build still fails, entirely on errors in
transitively-imported files (`operator.py`, `_collections_abc.py`,
etc.), none attributable to ipaddress.py's own source anywhere in the
log. Not investigated further here (genuinely out of scope for this
fix). Doc kept open — not deleted, since the file still doesn't build
end-to-end via the CLI.

Full mandatory gate (CLAUDE.md): `test_gimple.py` 248/248,
`test_module_cache.py` 76/76, `make check-selfhost` clean, from-scratch
stdlib dylib rebuild 0 skipped before and after (A/B via a separate
`git worktree add` checkout, not `git stash`), `compile_stdlib.py -j8`
664/664 clean before and after — no regression.

## Status (updated 2026-08-11 — MultiAssignStmt declaration gap FIXED; 2 separate, deeper pre-existing gaps confirmed blocking, neither fixed)

Re-verified the exact blocker the 2026-08-10 entry below left open:
`_find_address_range`'s `it = iter(addresses); first = last = next(it)`
— a `MultiAssignStmt` (`a = b = expr`) inside a coroutine body.
Confirmed via direct inspection of the generated `.cpp`: `_cpp_stmt`'s
`MultiAssignStmt` case emitted the assignment (`first = val; last =
val;`) but NEVER actually declared `first`/`last` as real C++ locals at
all (unlike the ordinary `AssignStmt` case, which hoists a `{ctype}
{name};` into `_cpp_func_scope_decls` on first use) — g++: "use of
undeclared identifier 'first'"/"'last'". Also always guessed
`int64_t` for the target's type regardless of the value's real type.

**Fixed** by mirroring `AssignStmt`'s own two-part handling exactly:
for each NEW target, infer its real ctype from the value (same
`_infer_simple_expr_ctype` call AssignStmt already uses, PLUS the same
`self.<method>(...)`/`<struct-ptr-local>.<method>(...)` special case
`_cpp_hoist_walrus_decls` (this session's earlier imaplib.py fix)
already added, for consistency — `_infer_simple_expr_ctype` itself has
no self/struct-method-call case), then hoist the declaration into
`_cpp_func_scope_decls` (function scope, exactly like AssignStmt) so a
target first assigned inside a `try:`/`for:` body stays visible to a
sibling block, matching Python's own function- (not block-) scoping.

Verified via an isolated repro (`first = last = a; yield first; yield
last`) compiling and RUNNING correctly end-to-end (`x`/`x`, matching
Python), and against the real `ipaddress.py`: the "'first'/'last'
undeclared" errors are confirmed gone from `_find_address_range`'s own
generated code.

Full mandatory gate (CLAUDE.md): `test_gimple.py` 247/0,
`test_module_cache.py` 76/0, `make check-selfhost` clean, from-scratch
stdlib dylib rebuild 0 skips, `compile_stdlib.py` 664/664 (0
unexpected).

**ipaddress.py itself still does not build.** Re-verifying the whole
file (both the real `fire.py build` full transitive compile — zero
errors attributable to ipaddress.py's own code anywhere in that log,
same as the 2026-08-10 entry already found — and a direct isolated
`do_imports=False` compile + g++, for a clean read unclouded by other
files' unrelated errors) surfaces TWO separate, deeper, genuinely
distinct gaps, neither attempted here:

**(a) `next(it)` on a plain (non-`self`) stateful iterator is a
different, much harder shape than `next(self)`.** This session's
imaplib.py fix taught `next(x)` to dispatch to `x.__next__()` when `x`
is `self` or a struct-pointer local with a real compiled `__next__`
method — but `_find_address_range`'s `it = iter(addresses)` is a plain
list, and `next(it)` here relies on real Python's stateful iterator
protocol: `next(it)` must consume exactly the FIRST element, and the
following `for ip in it:` must then continue from the SECOND element
onward — genuine iterator-cursor state this narrow coroutine-body model
has no representation for at all (a `for` loop here just does a full
`for (auto x : list)`/indexed-loop over the WHOLE list, with no
separate "already consumed N items" cursor). `next(it)` on it emits
literally the C++ identifier `next` with nothing declared to back it —
g++: "use of undeclared identifier 'next'". A real fix would need to
invent a genuine resumable-list-iterator representation (e.g. an
explicit index cursor threaded alongside the list) for this coroutine-
body model — a materially bigger step than the `self.__next__()`
dispatch fixed this session, not attempted.

**(b) `summarize_address_range(first, last)` — a SEPARATE generator,
own gap.** Confirmed via direct inspection that lines further down in
the same `.cpp` reporting `member reference base type 'int64_t' is not
a structure or union` are NOT from `_find_address_range` at all, but
from this OTHER top-level generator (ipaddress.py:200), whose own
`first`/`last` PARAMETERS are unannotated (`def
summarize_address_range(first, last):`) and default to `int64_t`, then
get used as real objects (`first.version`, `first._ip`, ...) —
the same general "unannotated parameter/field defaults to int64_t"
family; for the ORDINARY-function-parameter half of it — a parameter
used as a real object's receiver, which is what `first.version`
is — see `bugs/hard/CODEGEN_method_call_on_struct_param_mistyped.md`
(verified 2026-09-26: a method call on a struct passed as a
free-function parameter is mis-typed in every case, giving a wrong
value with exit 0 for some method names and SIGSEGV/SIGBUS for
others; the struct-typed-parameter half is
`bugs/hard/CODEGEN_ctor_arg_field_type_scalars_only.md`, which
supersedes the removed
`CODEGEN_unannotated_init_param_field_type_defaults_int64.md`).
Not attempted.

Both (a) and (b) are genuinely separate from the `MultiAssignStmt`
gap this pass fixed, and from each other — `_find_address_range` and
`summarize_address_range` are two different top-level generator
functions, each blocked by its own distinct issue.

## Status (updated 2026-08-10 — tuple-valued yield now FIXED; a separate, pre-existing gap now blocks)

Implemented real tuple-valued-`yield` support this session (see
`gimple_codegen.py`'s `_cpp_yield_tuple`/`_generator_tuple_yield_slot_
ctypes`/`_generator_yield_ctype`'s widened `TupleExpr` handling — boxes
`yield a, b, ...` into a real `MojoList *` at the yield site, unboxed on
the consumer side). Confirmed via an isolated compile +
`g++ -fsyntax-only`: `_find_address_range`'s `yield first, last` (lines
178/181) is no longer refused, and its own tuple-boxing/`co_yield` text
is syntactically valid C++ (verified: no g++ error anywhere in its
`_mojogen__find_address_range_impl` co_yield lines).

**ipaddress.py still does not build**, blocked by an INDEPENDENT,
pre-existing gap in the SAME function, one statement earlier:
`it = iter(addresses); first = last = next(it)` — a `MultiAssignStmt`
(`a = b = expr`) inside a coroutine body. `_cpp_stmt`'s `MultiAssignStmt`
case emits a bare assignment (`first = val; last = val;`) but never
actually DECLARES `first`/`last` as real C++ locals (unlike the ordinary
`AssignStmt` case, which hoists a declaration into `_cpp_func_scope_
decls` on first use) — g++: `'first' was not declared in this scope`.
Confirmed as a genuinely separate, tuple-yield-unrelated bug via a
minimal repro (`a = b = 5; yield a; yield b` — no tuples at all) that
reproduces the identical error. Not attempted here (a distinct,
well-scoped `_cpp_stmt` gap, out of this session's scope).

Doc kept open (not deleted) — tuple-yield is no longer this file's
blocker, but the file genuinely still doesn't build; the previously-
documented `@property`-bound-method/`format`/stray-backslash issues from
the 2026-08-06/07 statuses below appear to be already fixed (not
reproduced in the current whole-program error set, which now shows
zero errors attributable to ipaddress.py's own code — only errors in
transitively-imported files, same pattern as calendar.py's doc).

## Status (updated 2026-08-09 — RECLASSIFIED: real tuple-valued-yield refusal, now the blocking error)

Re-verified against current master (`5ba7d4b`) via a real
`python3 fire.py build /Users/mrs/net/Python-3.14.6/Lib/ipaddress.py`.
The build now fails immediately, BEFORE reaching any GCC-stage error, on
a hard Python-level `RuntimeError` from `gen_module`
(`gimple_codegen.py:30968`):

```
Error building: cannot compile module: function(s) _find_address_range
(generator function(s), contain a `yield`/`yield from`) — this codegen
compiles every function into a single straight-line C function and has
no suspend/resume state-machine transform for generators, ...
```

Root cause, confirmed by reading the source: `_find_address_range`
(ipaddress.py:164) does `yield first, last` (lines 178 and 181) — a real
**tuple-valued yield**. This is the well-known, already-tracked
structural gap for this generator-codegen family (coroutine promises
only support a single scalar `int64_t`/`double`/`_Bool`/`char *`, no
tuple representation) — see `_infer_generator_yield_ctype`'s explicit
`TupleExpr` handling at `gimple_codegen.py:2699-2724`, which
deliberately returns `None` (refuse) rather than let a tuple yield sail
through to broken C++ emission, citing this exact family of real-world
cases (e.g. `Lib/test/libregrtest/save_env.py`'s `resource_info`).

This is a genuine change from the 2026-08-07 status below: back then,
`ipaddress.py`'s 14 generator sites reportedly compiled through the
coroutine path with no refusal at all, and the file failed later at
GCC-stage on unrelated `@property`/`format`/stray-backslash errors.
Since then, another session's work (visible in the current
`gimple_codegen.py`, citing `save_env.py`'s bug doc) tightened the
tuple-yield eligibility check to honestly refuse rather than silently
mis-emit, so `_find_address_range` (which was apparently NOT one of the
14 sites previously scanned/reported, or was previously eligible under
weaker checking) now correctly aborts the whole-module compile before
any of the other, unrelated GCC-stage errors are even reached. Grepping
the file confirms exactly one tuple-yield site — `_find_address_range`
(lines 178, 181); the file's other 12 `yield` sites (lines 249, 300,
690, 696, 846, 849, 857, 859, 951, 975, 2351) are all single-value.

**Classification: matches the tracked "tuple-valued yield" structural
generator-codegen gap** (no coroutine-promise representation for
tuples) — out of scope for a narrow fix per this task's guidance. Not
attempted here. The previously-noted unrelated GCC-stage errors
(`@property`-as-bound-method, `format` implicit-declaration, stray
backslash) are no longer reachable/relevant until tuple-yield support
(or a source-level workaround) unblocks the whole module, so they are
left undisturbed below for reference but are moot for now.

## Status (updated 2026-08-07)

Re-verified against current master with a real rebuild. `MOJO_DEBUG=1`
still shows no "not eligible" refusal for any of ipaddress.py's own 14
generator sites — still classified correctly as **NOT a generator-
codegen-cluster failure**. The error SET has changed significantly since
2026-08-06 though (down to 12 error lines from a much larger batch) —
the `@property`-access-leaves-a-bound-method pattern
(`'MojoBoundMethod' has no member named 'is_multicast'`) described below
is GONE (apparently fixed elsewhere in the meantime). Current errors:

```
/Users/mrs/net/Python-3.14.6/Lib/ipaddress.py:325:17: error: expected ')' before ',' token
/Users/mrs/net/Python-3.14.6/Lib/ipaddress.py:364:4: error: 'first' undeclared (first use in this function)
/Users/mrs/net/Python-3.14.6/Lib/ipaddress.py:364:11: error: 'last' undeclared (first use in this function)
/Users/mrs/net/Python-3.14.6/Lib/ipaddress.py:631:10: error: implicit declaration of function 'format'; did you mean 'normpath'? [-Wimplicit-function-declaration]
/Users/mrs/net/Python-3.14.6/Lib/ipaddress.py:631:28: error: unexpected RHS for assignment before ';' token
/Users/mrs/net/Python-3.14.6/Lib/ipaddress.py:2643:46: error: stray '\' in program
```

None are inside a generator body. Not investigated further here (still
out of scope for this cluster) — the `:325`/`:364` pair looks like a
parser/codegen mishandling of a multi-target or walrus-adjacent
assignment (`first`/`last` never declared before use, plus a parse-
level "expected ')' before ','" right before it), and the `:2643` stray-
backslash error is the same textwrap.py-transitive tokenizer issue noted
in codecs.py's/other files' docs — both worth a dedicated non-generator
pass, not attempted here.

## Status (updated 2026-08-06, superseded above — error set has since changed)

**STILL FAILING**, but re-diagnosed against current master (`2b0c4c5`) —
the 2026-07-30 `'IPv6Address' does not name a type` .cpp error no longer
reproduces. `ipaddress.py` has 14 `yield` sites across several small
generator methods (`_BaseNetwork.__iter__`/`subnets`/`hosts`/etc.) —
**none of them appear in the current error list**, and `MOJO_DEBUG=1`
shows no "not eligible" refusal naming any of them: ipaddress.py's own
generator bodies now appear to compile cleanly through the coroutine
path.

**Classification: NOT a generator-codegen-cluster failure anymore.**
The file currently fails to build for a large number of severe,
unrelated pre-existing bugs — dominant pattern in the current error list
is `@property`-decorated methods (`is_multicast`, `is_reserved`,
`is_link_local`, `is_private`, `is_global`, `is_unspecified`,
`is_loopback`, `is_site_local`, ...) being called as `x.is_multicast`
and the codegen treating the property access as leaving a raw
`MojoBoundMethod` value instead of invoking it / unwrapping it to the
real property value:

```
/Users/mrs/net/Python-3.14.6/Lib/ipaddress.py:1027:23: error: 'MojoBoundMethod' has no member named 'is_multicast'
/Users/mrs/net/Python-3.14.6/Lib/ipaddress.py:631:10: error: implicit declaration of function 'format' [-Wimplicit-function-declaration]
/Users/mrs/net/Python-3.14.6/Lib/ipaddress.py:1959:47: error: passing argument 1 of '_BaseV6__explode_shorthand_ip_string' from incompatible pointer type
```

Also present: the exact same `stray '\' in program` /
`_classattr_TextWrapper__letter` tokenizer error seen in
`bugs/CODEGEN_generator_function_Lib_codecs.md`'s current re-diagnosis
(both transitively reach `textwrap.py`; same likely shared root cause,
not investigated further here). None of this is generator-related. Not
investigated further — genuinely out of scope for this cluster; the
`@property`-access-leaves-a-bound-method pattern looks like it would be
a high-value, separate, non-generator bug report on its own (it recurs
at 15+ call sites in this one file alone).

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/ipaddress.py
