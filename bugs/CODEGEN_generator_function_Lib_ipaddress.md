# CODEGEN_generator_function: Lib/ipaddress.py

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
achieve a full `mojo.py build` end-to-end** — the whole-program,
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
file (both the real `mojo.py build` full transitive compile — zero
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
family as the already-tracked, already-repeatedly-re-verified-unchanged
`bugs/hard/CODEGEN_unannotated_init_param_field_type_defaults_int64.md`
hard bug (that doc's own title is about `__init__` params/fields
specifically; this is the same root architecture applying to an
ORDINARY function's own parameters instead — confirmed as the same
class, not re-investigated as a separate hard-bug doc here, per this
session's time budget). Not attempted.

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
`python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/ipaddress.py`.
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
