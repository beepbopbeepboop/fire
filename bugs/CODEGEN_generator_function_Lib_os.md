# CODEGEN_generator_function: Lib/os.py

## Status (updated 2026-08-24 — re-verified; tagged-union conclusion stands, out of scope for this cluster)

Fresh isolated compile (`GimpleGen(do_imports=False, relaxed_imports=
True)`) surfaces `walk`/`fwalk` refused on an EARLIER, shallower symptom
now (`fspath(...)`/`close(...)`/`list(...)` unresolved-callee refusals —
builtins this narrow relaxed-import isolated harness doesn't wire up),
but this doesn't change the underlying diagnosis: per the 2026-08-11/
2026-08-23 entries below, `walk`'s control flow fundamentally depends on
runtime type discrimination over a heterogeneously-typed stack
(`isinstance(top, tuple)` on elements that are sometimes `str`, sometimes
3-tuples), which this codegen's statically-typed value model has no
representation for at all — a tagged-union redesign, not a narrow fix.
Per this session's assignment, deliberately NOT attempted (disproportionate
scope for this cluster). Doc stays open, honestly triaged as out of scope.


## Status (updated 2026-08-23 — re-verified; walk/_fwalk/fwalk refusal unchanged, tagged-union conclusion stands)

Isolated compile reproduces the identical refusal (now naming `walk`,
`_fwalk` AND `fwalk` — the third sibling surfaces now that earlier passes
get further, same shape). This session's three generic generator-codegen
fixes don't approach the core obstacle the 2026-08-11 entry nailed down:
`walk`'s control flow depends on runtime type discrimination over a
heterogeneously-typed stack (`isinstance(top, tuple)` on elements that are
sometimes strings, sometimes 3-tuples), which this codegen's statically-
typed container/value model cannot represent regardless of how much
fixed-shape tuple-yield machinery exists. Tagged-union redesign remains
the prerequisite; documented-not-fixed stands; doc kept open.


## Status (updated 2026-08-11 — re-verified still refused; deepened root cause, confirms (not reverses) prior "needs tagged-union redesign" conclusion)

Re-verified against current master: `python3 mojo.py build
/Users/mrs/net/Python-3.14.6/Lib/os.py` still fails with the identical
`RuntimeError: cannot compile module: function(s) _fwalk, walk ...`,
unchanged from 2026-08-10.

Looked for a possible narrower fix than the "tagged-union promise, much
larger redesign" the previous session concluded was required, since the
2026-08-10 framing ("mixes SCALAR and TUPLE yields") looked, on a closer
read of `walk()`'s actual source, potentially too pessimistic:

`walk()`'s `yield top` (os.py:364) is NOT really a scalar yield in the
way `_generator_yield_ctype` treats it (an unresolvable identifier,
defaulted to `int64_t`). It's reached only inside
`if isinstance(top, tuple): yield top; continue` — and `top` really is
a 3-tuple there at runtime: bottom-up traversal earlier pushes
`stack.append((top, dirs, nondirs))` (os.py:429), and `top =
stack.pop()` (os.py:359) pops it back off. So `yield top` and the
other site's literal `yield top, dirs, nondirs` (os.py:418) are, in
real Python semantics, THE SAME 3-tuple shape — not two genuinely
different yield shapes. `_fwalk` follows the identical idiom (`stack.
append((_fwalk_yield, (toppath, dirs, nondirs, topfd)))` then later
`yield value`). This looked promising: if the codegen could special-case
"a bare-identifier yield inside an `isinstance(x, tuple)`-guarded branch
should adopt the SAME tuple slot ctypes already established by this
function's real tuple-literal yield site(s)," the type-unification
refusal might go away without touching the yield-tuple machinery's core
model.

**But this doesn't actually solve the real problem, it only relocates
it** — traced one level further: `stack` itself (`stack = [fspath(top)]`,
then both `stack.append(new_path)` — a plain string — and `stack.append
((top, dirs, nondirs))` — a 3-tuple — at different points in the same
function) is a genuinely, dynamically HETEROGENEOUSLY-typed Python list
(str elements AND tuple elements in the same list), and `isinstance(top,
tuple)` is a real runtime type-discrimination check on a value popped
from it. This codegen's container/value model has no runtime type tag
for a `MojoList *` element at all — every list's element representation
is a single static C type decided at compile time (`_elem_types`/
`_nested_elem_types`), and every "boxed pointer stored as int64_t"
convention this codebase uses elsewhere (see mailbox.py's/ipaddress.py's
tuple-yield boxing) relies on the STATIC type already being known at
each use site, not on a runtime discriminator recoverable via
`isinstance()`. So even if the yield-type-unification layer were taught
to special-case this idiom, `stack`'s own mixed-element-type list and
the `isinstance(top, tuple)` runtime check one level below it would
still need real tagged/dynamically-typed value representation to
compile correctly — without that, "fixing" just the yield-type mismatch
would most likely just move the failure to a different, less legible
GCC-stage error (or, worse, silently miscompile `isinstance(top,
tuple)` into something that's always true/false, corrupting `walk()`'s
actual traversal order).

**Conclusion: refines but does not reverse** the 2026-08-10 assessment
— `walk`/`_fwalk` don't fail because two *independent, disjoint* yield
shapes coexist by coincidence; they fail because `walk`/`_fwalk`
legitimately need a dynamically/heterogeneously-typed value
representation (the `stack` list's own elements) that this codegen does
not have anywhere in its container or coroutine-promise model. A real
fix is still the same larger tagged-union/variant redesign the prior
session identified, now with the underlying reason nailed down more
precisely (not just "yield shapes disagree" but "the whole function's
control flow depends on runtime type discrimination this codegen's
value model can't represent"). Not attempted — genuinely out of narrow-
fix scope. Doc kept open.

## Status (updated 2026-08-10 — general tuple-valued yield now FIXED; `walk`/`_fwalk` remain refused for a distinct, in-scope reason: they mix SCALAR and TUPLE yields in one function)

Implemented real tuple-valued-`yield` support this session (see
`gimple_codegen.py`'s `_cpp_yield_tuple`/`_generator_tuple_yield_slot_
ctypes`). Re-verified: `walk`/`_fwalk` are STILL refused, unchanged,
with the exact same message as before
(`walk`/`_fwalk`: "every yield must carry a value, and all values must
agree on one scalar type") — this fix does not help them, correctly.

Root cause, unchanged from the analysis below: `walk()` has `yield top`
(a bare scalar, the `topdown=False` branch) AND `yield top, dirs,
nondirs` (a 3-tuple, the `topdown=True` branch) — TWO yield sites in
the SAME function that don't even agree on arity, let alone type.
`_fwalk()` similarly mixes a bare-identifier `yield value` with a direct
`yield toppath, dirs, nondirs, topfd` 4-tuple. `_generator_yield_ctype`
unifies a scalar contribution (`int64_t`, `top`'s inferred default) and
a tuple contribution (`MojoList *`, from the tuple sites) exactly the
same way it unifies any two disagreeing scalar types — since neither
is `char *` (the one type the merge rule tolerates), it correctly
refuses the whole function. This is NOT a case a fixed-arity tuple
design could ever unify, regardless of how much tuple-yield support is
added — `walk`/`_fwalk` fundamentally yield DIFFERENT SHAPES on
different code paths, which no single C++20 coroutine promise value
type can represent. Not attempted here (would need a tagged-union/
variant promise, a much larger redesign). Doc kept open (not deleted).

## Status (updated 2026-08-09 — RECLASSIFIED: real tuple-valued-yield refusal, now the blocking error)

Re-verified against current master (`c79a013`) via a real
`python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/os.py`. The
build now fails IMMEDIATELY, on `os.py`'s OWN top-level module compile
(`gen_module`, before any transitive-closure/GCC-stage work is even
reached), with a hard Python-level `RuntimeError`:

```
Error building: cannot compile module: function(s) _fwalk, walk
(generator function(s), contain a `yield`/`yield from`) — this codegen
compiles every function into a single straight-line C function and has
no suspend/resume state-machine transform for generators, ...
```

`MOJO_DEBUG=1` confirms the precise refusal reason for both:

```
[gimple_codegen] generator 'walk' not eligible for C++ coroutine path,
  falling back to honest refusal: walk: every `yield` must carry a
  value, and all values must agree on one scalar type
  (int64_t/double/_Bool)
[gimple_codegen] generator '_fwalk' not eligible for C++ coroutine path,
  falling back to honest refusal: _fwalk: every `yield` must carry a
  value, and all values must agree on one scalar type
  (int64_t/double/_Bool)
```

Root cause, confirmed by reading the source: `walk()` (os.py:364-418)
has `yield top` (a scalar, line 364, the `topdown=False` post-order
case) AND `yield top, dirs, nondirs` (a real 3-element **tuple-valued
yield**, line 418, the `topdown=True` case) — two yield statements in
the same generator that don't even agree on arity, let alone type.
`_fwalk()` (os.py:465-551) similarly has `yield value` (line 501,
where `value` is itself a 4-tuple assigned earlier via
`stack.append((_fwalk_yield, (toppath, dirs, nondirs, topfd)))`) and
`yield toppath, dirs, nondirs, topfd` directly (line 551, a real
4-element tuple yield).

This is the well-known, already-tracked structural gap for this
generator-codegen family: the coroutine promise only supports a single
scalar `int64_t`/`double`/`_Bool`/`char *` yield type — see
`_infer_generator_yield_ctype`'s explicit `TupleExpr` handling at
`gimple_codegen.py:2699-2724`, which deliberately returns `None`
(refuse) rather than let a tuple yield sail through to broken C++
emission. **Classification: matches the tracked "tuple-valued yield"
structural generator-codegen gap** — out of scope for a narrow fix per
this task's guidance. Not attempted here.

This refusal happens strictly BEFORE the module-qualification fix
(`_gen_cpp_generator_unit`'s `_func_qualifier`-based symbol naming) and
the `relpath`-ambiguity issue documented below ever get exercised for
this file — `os.py`'s own top-level compile now aborts on its own two
generators before any transitive-closure linking is attempted, so
those two previously-documented issues are currently unreachable/moot
for `os.py` specifically (they may still be real for other files, not
re-verified here). The below status entries are kept for history but
no longer describe the current blocking error.

## Status (updated 2026-08-07)

**Classification bug FIXED** (`bugs/hard/CODEGEN_generator_function_
symbol_not_module_qualified.md`, task #146) — `_gen_cpp_generator_unit`'s
free-function base-name computation now module-qualifies via
`_func_qualifier` (the same SB-1 machinery ordinary free functions use).
Confirmed: `python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/os.py`
no longer produces ANY `conflicting types for '_mojogen_walk_start'`
error — the specific collision this doc documents is gone.

**File STILL FAILS to build overall**, for a completely different,
unrelated reason: `RuntimeError: cannot compile module: 'relpath' is
ambiguous — this program transitively imports two different sibling
modules that both define a free function named 'relpath' ...` — an
ORDINARY (non-generator) function ambiguity, hit via `_func_qualifier`'s
own pre-existing `_AMBIGUOUS_FUNC_HOME` honest-refusal path (unrelated
machinery, not touched by the generator-symbol fix). Not investigated
further here — out of scope for the generator/coroutine codegen cluster
this file was originally classified under.

## Status (updated 2026-08-06, superseded above)

**STILL FAILING**, but re-diagnosed from scratch against current master
(`2b0c4c5`) — the 2026-07-31 `_DeprecatedGenericAlias`/`_CallableType`/
`_PlaceholderType` errors no longer reproduce (fixed by unrelated later
work). `python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/os.py`'s
whole-program transitive-closure compile now fails with hundreds of
errors from many different files; the ones that actually implicate
`os.py`'s OWN generator (`os.walk`) are:

```
/Users/mrs/net/Python-3.14.6/Lib/os.py:1553:23: error: conflicting types for '_mojogen_walk_start'; have 'MojoGenerator *(int64_t,  int64_t,  int64_t,  int64_t)' {aka 'MojoGenerator *(long long int,  long long int,  long long int,  long long int)'}
/Users/mrs/net/Python-3.14.6/Lib/threading.py:2160:23: note: previous declaration of '_mojogen_walk_start' with type 'MojoGenerator *(int64_t)' {aka 'MojoGenerator *(long long int)'}
```

(also hit, identically, via `Lib/subprocess.py`, `Lib/genericpath.py`,
`Lib/ntpath.py` — every module in the transitive closure that reaches
BOTH `os.py`'s own `walk` generator and an unrelated, differently-shaped
`walk` generator reachable through `Lib/threading.py`.)

**Classification: this is `bugs/hard/CODEGEN_generator_function_symbol_
not_module_qualified.md`** — `os.py`'s `walk(top, topdown=True,
onerror=None, followlinks=False)` (4 params) is a perfectly ordinary,
independently-compilable generator; it collides purely on the emitted C++
coroutine API's SYMBOL NAME (`_mojogen_walk_start`/`_resume`/`_value`/
`_destroy`) with a completely unrelated generator, also bare-named
`walk`, that some other stdlib module transitively pulls in from
`threading.py`. `_gen_cpp_generator_unit`'s free-function base-name
computation (`f"_mojogen_{_safe_name(fn.name)}"`) never got the SB-1-
style module-qualification treatment ordinary free functions received in
`bf96f55`/`13e6a5c` — see the hard-bug doc for the full root cause,
why the two same-named `walk`s are otherwise unrelated (different
arities, different bodies), and why a fix needs the same care as the
original SB-1 project (two rounds of real regressions there).

Older, likely stale note (session before this re-diagnosis; not
independently re-verified here): the `mkdir`/`rmdir`/`execv`/`execve`/
`fork` "implicit declaration" warnings-turned-errors visible deep in the
current transitive-closure build output appear to be UNRELATED libc-
declaration issues in `os.py`'s own non-generator code, not part of this
generator-codegen cluster; not investigated further as part of this
pass (out of scope — this task is specifically about the generator/
coroutine codegen gaps).

## Build error

```
error: '_DeprecatedGenericAlias' does not name a type
error: '_CallableType' does not name a type
error: '_PlaceholderType' does not name a type
```

## Fixed errors (this session)
- `fork` implicit-decl → fixed (`_NEEDS_SELF_EXTERN` + `_LIBC_SIGS`)
- `execv` incompatible-args → fixed (`_KNOWN_SIGS` arg-padding)
- `waitpid` arg-count → fixed (`_KNOWN_SIGS` arg-padding)
- `execve` conflicting-types → fixed (`_KNOWN_SIGS`)
- `sys` not declared → fixed (package import scan)

Source file: `/Users/mrs/net/Python-3.14.6/Lib/os.py`
