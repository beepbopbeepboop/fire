# CODEGEN_generator_function: Lib/imaplib.py

## Status (2026-09-03 — coroutine-body infra landed (VarDecl + body-built strings); this file NOT closed, blocked on cross-method tuple-return coherence)

Fresh isolated `compile_to_gimple_with_cpp(do_imports=False)`: `burst`
still refused, `every yield must carry a value, and all values must
agree on one scalar type`. Root cause is unchanged from the entries
below — `burst` yields both `Idler.__next__(self)` (a real 2-tuple
return, now typed `MojoList *` at the yield site) and `response` from
`while response := self._pop(interval, None)` where `_pop` returns
tuples across multiple return paths and no tuple-return-type
representation exists for an ordinary (non-generator) function. That
cross-method coherence gap is genuinely feature-sized and was not
attempted this session.

This session DID land general compiled-generator/coroutine-body infra
that several of these generator docs need: `var x = <expr>` (Mojo
`VarDecl`) is now lowered inside a coroutine body (it was a hard
refusal), and `String(x)`/`str(x)` in a coroutine body is now
type-dispatched (`mojo_str_from_int`/`mojo_repr_float`/char* passthrough)
so a string assembled from a numeric part before being yielded compiles
and runs correctly (previously `String(0)` mis-stringified to `"None"`).
Full gate clean (test_gimple 266, generator/async runners, check-selfhost,
compile_stdlib 0 unexpected, dylib 0 skip, link-mode). Doc stays open.

## Status (updated 2026-08-26, later same day — the exact symmetric fix this doc anticipated LANDED; blocker (2) resolved into the predicted mixed-yield refusal; ADVANCED, not closed)

Implemented the fix the 2026-08-26 (opencode-genlib2) entry below already
precisely specified: `gimple_exprtypes.py`'s `_infer_simple_expr_ctype`
gained a `next(x)` CallExpr case (a single struct-pointer-typed arg —
`self`, via `self_struct_ctype`, or any other known-struct-typed
local/param) that resolves the same way the emitter's existing `next(x)`
-> `x.__next__()` lowering already does: `method_return_types.get(
f"{struct}___next__")`. First cut only accepted a scalar or a known
user-struct-pointer return; had to widen it once more to also accept
`__next__` returning a real CONTAINER (`MojoList *`/`MojoDict *`/
`MojoSet *` — e.g. this file's own `Idler.__next__`, `return typ, data`,
boxed as `MojoList *` the same way any tuple return already is), since
neither the scalar list nor `_is_known_struct_ptr_ctype` (user structs
only) covered it. Verified via 3 hand-written repros (`next(self)` on a
`__next__` returning int, string, and a real 2-tuple respectively) —
all g++-fsyntax-only-clean, the tuple case's promise correctly typed
`MojoList *` instead of the old wrong `int64_t` default.

Re-verified against the real file: `Idler.__next__`'s call site,
`co_yield Idler___next__(self);`, now correctly types the promise
`MojoList *` — **blocker (2) exactly as diagnosed is gone** (previously
a genuine silent-miscompile risk: the promise was typed `int64_t` while
the emitted expression was a real `MojoList*`, an invalid-pointer-to-int
narrowing that only g++'s own `-fsyntax-only` stage caught, never this
codegen's own Python-level checks). Exactly as the 2026-08-26 (opencode-
genlib2) entry predicted, this immediately exposes `burst`'s OTHER yield
site (`yield response` from `while response := self._pop(interval,
None):`) disagreeing — `_pop` returns tuples across multiple return
paths with no tuple-return-type representation for ordinary (non-
generator) functions, the same structural gap `bugs/CODEGEN_generator_
function_Lib_gettext.md` tracks as its own root cause #3 — so `burst`
now refuses honestly ("every `yield` must carry a value, and all values
must agree on one scalar type") instead of either the old miscompile
risk or a clean compile. Net effect: a real correctness/safety
improvement (miscompile -> honest refusal) plus the `next(x)`-yield-type
mechanism itself is now generally available to any OTHER generator in
the corpus with this shape, but `imaplib.py` itself does not newly
compile — the cross-method tuple-return-coherence gap is feature-sized
and not attempted. Full mandatory gate run clean (`test_gimple.py`
264/264, `test_module_cache.py` 76/76, `make check-selfhost` clean,
stdlib dylib rebuild 0 skip lines, `compile_stdlib.py` unexpected-failure
count unchanged). Doc stays open.

## Status (re-verified 2026-08-26, worktree agent-aac0d33be914873b5 — independent re-verify, byte-identical, no change)

Independent fresh isolated `compile_to_gimple_with_cpp(do_imports=False,
MOJO_DEBUG=1)` repro on the real file: Python-level lowering succeeds
(no `_UnsupportedGeneratorShape` raised), matching the opencode-genlib2
entry's observation that the remaining blocker is a downstream g++
`.cpp`-stage type error (`invalid conversion from 'MojoList*' to
'int64_t'` at `co_yield Idler___next__(self);`), not re-run here (g++
`-fsyntax-only` stage not independently re-executed this pass, but no
mechanism landed since would plausibly change it — the root cause is
yield-site type inference for `next(x)` not consulting
`func_return_types` the way the walrus-hoist path does, compounded by a
separate mixed-yield tuple-return-coherence gap). Feature-sized in
aggregate; not attempted. No code change; doc stays open.

## Status (re-verified 2026-08-26, worktree fix/opencode-genlib2 — exactly ONE .cpp error left (blocker 2); blocker 1's silent constant-fold confirmed in the generated text; inference/emitter asymmetry pinned down)

Fresh strict isolated `compile_to_gimple_with_cpp(do_imports=False)` +
`g++-mp-15 -std=c++20 -fsyntax-only`: the companion `.cpp` is down to
exactly ONE error — `invalid conversion from 'MojoList*' to 'int64_t'`
at `co_yield Idler___next__(self);` (blocker (2)). Direct inspection of
the generated text confirms the 19d entry's observation about blocker
(1): `if not self._imap.sock:` now emits `if ((!0)) {` — a silently
always-false constant-fold, no g++ error — still squarely inside the
excluded HIGH-RISK unannotated-init-param-type family, untouched.

New precision on blocker (2)'s mechanism, derived fresh: `Idler.__next__`
returns `typ, data` (a real 2-tuple), and its compiled return type IS
correctly known (`MojoList *` via `func_return_types['Idler___next__']`)
— but only the EXPRESSION EMITTER consults that registry when lowering
`next(self)` to `Idler___next__(self)`; the YIELD-SITE TYPE INFERENCE
side never resolves the `next(<self/struct-ptr>)` shape, so it types
that yield `int64_t` (its default) and unifies the promise to `int64_t`,
while emission then produces the raw `MojoList *` expression — hence the
conversion error. The symmetric fix (teach yield-site inference the same
`next(x)` -> `func_return_types[f"{struct}___next__"]` lookup the walrus
hoist already uses for self-method calls) would flip this site to
`MojoList *`, at which point burst's OTHER yield (`yield response` from
`self._pop(...)`) still disagrees (`_pop` returns `_idle_responses.pop(0)`
tuples / the `('', None)` default across multiple return paths — no
tuple-return-type representation exists for ordinary functions, the same
gap gettext.py's doc tracks as root cause #3), producing an honest
mixed-yield refusal instead of a working file. So blocker (2) genuinely
needs cross-method tuple-return coherence — feature-sized, unchanged.
Not attempted; doc stays open.

## Status (updated 2026-08-26, worktree fix/rest-remainder19d — checked against today's super()/self.__class__ fix (bdfb825) and generator-value-return-slot fix (326db78); neither applies)

Fresh isolated `compile_to_gimple_with_cpp(do_imports=False)` repro of
`Idler.burst`'s companion `.cpp`. Blocker (2) (cross-method yield-type
unification: `co_yield Idler___next__(self);` — `MojoList*` vs the
promise's unified `int64_t`) reproduces unchanged, byte-identical to
every prior entry. Neither of today's two landed fixes applies —
blocker (2) is a yield-value-type-unification gap, unrelated to
`super()`/`self.__class__` resolution or to a generator's own
value-carrying `return`.

Blocker (1) (`self._imap.sock`, the excluded HIGH-RISK unannotated-
init-param-type family) is explicitly out of scope for this run and not
touched. Noting one observation for whoever next works this file's
excluded blocker: the g++ error text for blocker (1) that every prior
entry quoted (`request for member 'sock' in 'self->Idler::_imap', which
is of non-class type 'int64_t'`) no longer appears in this fresh repro —
the `if not self._imap.sock:` condition now silently constant-folds to
`if ((!0))` in the generated `.cpp` (no g++ error, but a silently-wrong
always-false condition) rather than a hard member-access compile error.
This is still squarely inside the excluded unannotated-init-param-type
family (not investigated or touched, per this run's explicit exclusion)
but is a real behavior shift worth flagging: blocker (1) may have moved
from "hard compile error" to "silent miscompile" at some point in the
recent history, which would need re-confirming before anyone attempts
that hard-bug doc's family. No code change; doc stays open.

Fresh re-verify against this worktree (branched from master `a913ab8`).
Isolated compile (`compile_to_gimple_with_cpp(..., do_imports=False)`)
+ `g++-mp-15 -std=c++20 -fsyntax-only` on the resulting `Idler_burst`
coroutine `.cpp`: byte-for-byte identical pair of errors to the
2026-08-25 entry — `request for member 'sock' in 'self->Idler::_imap',
which is of non-class type 'int64_t'` and `invalid conversion from
'MojoList*' to 'int64_t' [-fpermissive]` at `co_yield Idler___next__
(self)`. This assignment explicitly excludes attempting the
HIGH-RISK unannotated-init-param-type family blocker (1) is filed
under. Blocker (2) (cross-method yield-type unification) remains
unowned/unattempted, still feature-sized. No change; doc stays open.

## Status (updated 2026-08-25, worktree fix/rest-remainder14 — re-verified unchanged, root cause of blocker (1) pinned down precisely)

Fresh re-verify against this worktree (branched from master `f65502d`;
note the codegen backend has since been split from the monolithic
`gimple_codegen.py` into several files — `gimple_module_gen.py` now
carries the ctor-param scalar-inference passes referenced below). Ran
an isolated compile (`gimple_codegen.compile_to_gimple_with_cpp(...,
do_imports=False)`, matching this doc's own established methodology)
and fed the resulting `.cpp` through `g++-mp-15 -std=c++20
-fsyntax-only`. Both previously-documented blockers reproduce
byte-for-byte unchanged:
```
error: request for member 'sock' in 'self->Idler::_imap', which is of non-class type 'int64_t'
error: invalid conversion from 'MojoList*' to 'int64_t' [-fpermissive]  (co_yield Idler___next__(self))
```

Went further than prior passes and checked WHY blocker (1) still isn't
covered by the (meanwhile-landed) IdentExpr-argument extension to
`bugs/hard/CODEGEN_unannotated_init_param_field_type_defaults_int64.md`
(2026-08-18): the one real-source call site, `Idler(self, duration)`
(imaplib.py:685, inside `IMAP4.idle`), passes `self` — an `IdentExpr` —
as the constructor argument. Traced `gimple_module_gen.py`'s ctor
reconciliation pass (`_arg_scalar_type`, ~line 2241, feeding the
`_ctor_scalar_obs`/resolution loop ~line 2608): for an `IdentExpr`
argument it only ever consults `_inferred_var_types`/
`_inferred_param_types`, neither of which records an entry for the bare
name `self` (the "1.3e" struct-method receiver-resolution pass a few
hundred lines above does special-case `recv.name == 'self'`, but that
machinery is for `receiver.method(...)` call sites, not constructor
arguments — a structurally different pass with no shared code path).
So `imap`'s parameter gets ZERO type evidence from this call site at
all, independent of the second, larger problem: even if `self` WERE
recognized as `IMAP4 *`, the resolution loop right below only accepts
a unanimous `{'double'}` or `{'char *'}` observation set (line ~2634:
`if types not in ({'double'}, {'char *'}): continue`) — it has no
representation for "resolve to an arbitrary struct-pointer type" at
all, so a `self`-as-struct-pointer observation wouldn't be actionable
without also widening that acceptance check. Both steps together match
the scope this hard-bug doc's own history has repeatedly and explicitly
declined to extend into (its "Risk" section documents real regressions
from broader attempts) — not attempted here, consistent with that
doc's precedent and this session's mandate to avoid large speculative
widenings of shared inference machinery.

Blocker (2) (`__next__`'s `MojoList *` return vs. `burst`'s
`int64_t`-unified coroutine promise) is unowned by any doc and remains
a real, separate, cross-method yield-type-unification gap in the
coroutine promise-type inference — not attempted (feature-sized: would
need the promise's `yield_value` to become type-polymorphic or the
unification pass to widen the promise to a boxed/tagged representation
whenever cross-method yield sources disagree).

No change; doc stays open.

## Status (updated 2026-08-25, worktree fix/rest-remainder11 — re-verified unchanged)

Re-verified fresh against this worktree. `Idler.burst`'s generated .cpp
still has exactly the 2 documented blockers: (1) `self._imap.sock` blocked
by `bugs/hard/CODEGEN_unannotated_init_param_field_type_defaults_int64.md`
(`Idler.__init__(self, imap, ...)` leaves `imap` unannotated) — that
doc's own history records real regressions from broadening this exact
machinery, not re-attempted; (2) the `__next__`-return/`burst`-promise
scalar-type-unification gap. Neither is addressed by any of the recently
landed shared mechanisms (checked each against this file's specific
shapes: none apply — this isn't a struct-method extern-decl, kwargs-slot,
classmethod-receiver, or chained-assignment shape). No change; doc stays
open.

## Status (updated 2026-08-24 — re-verified unchanged)

Re-ran the isolated `Idler.burst` triage: `ci_errors=0`; the generated
`.cpp` still has exactly the 2 documented blockers, both owned by their
existing write-ups: (1) `self._imap.sock` still blocked by the
ALREADY-TRACKED `bugs/hard/CODEGEN_unannotated_init_param_field_type_
defaults_int64.md` hard bug (`Idler.__init__(self, imap, ...)` leaves
`imap` unannotated) — that doc's own "Risk" section documents a real
history of broad regressions from touching this exact shared call-site/
parameter type-inference machinery, and its most recent (2026-08-18)
extension was itself scoped narrowly (`IdentExpr`-argument constructor
calls only) after two earlier, more ambitious attempts caused real
regressions; not re-attempted here for the same reason. (2) the
`__next__`-return/`burst`-promise scalar-type-unification gap, likewise
unowned by this session. No new work; doc stays open.


## Status (updated 2026-08-23 — re-verified; Idler.burst cpp down to 2 errors, both previously documented, neither new)

Fresh isolated triage: ci_errors=0; `burst`'s generated .cpp has exactly 2
errors, matching the documented open items: (1) line 127
`self->_imap.sock` — still the ALREADY-TRACKED unannotated-`__init__`-param
hard bug (`Idler.__init__(self, imap, duration=None)` types `_imap` as
int64_t, so the two-level field-chain fix can't activate); (2) line 133
`co_yield Idler___next__(self)` — `__next__`'s inferred return type
(MojoList*) disagrees with burst's unified promise type (int64_t), a
yield-type-unification blind spot for cross-method return types that only
matters once (1) stops masking later parts of the body (the walrus/
truthiness items below). Neither attempted; both owned by their existing
write-ups. No regression from this session's three generic fixes (all 48 generator-runner
tests pass, including this session's six new compiled-and-run ones).


## Status (updated 2026-08-20 — a THIRD, distinct occurrence of the dispatch-table "bare unmangled symbol" failure mode FIXED, unrelated to generators)

Investigated a fresh report of 8 "undeclared here (not in a function)"
GCC errors, reproduced via `compile_to_gimple(open(.../imaplib.py).read(),
do_imports=False, filename='imaplib.py')`:

```
imaplib.py:1352:41: error: 'IMAP4_close' undeclared here (not in a function); did you mean 'IMAP4_store'?
imaplib.py:1374:67: error: 'IMAP4_open' undeclared here (not in a function); did you mean 'IMAP4_login'?
imaplib.py:1377:46: error: 'IMAP4_read' undeclared here (not in a function); did you mean 'IMAP4_thread'?
imaplib.py:1380:74: error: 'IMAP4_rename' undeclared here (not in a function); did you mean 'IMAP4_enable'?
imaplib.py:1427:55: error: 'IMAP4_stream_close' undeclared here (not in a function); did you mean 'IMAP4_stream_store'?
imaplib.py:1449:81: error: 'IMAP4_stream_open' undeclared here (not in a function); did you mean 'IMAP4_stream_send'?
imaplib.py:1452:61: error: 'IMAP4_stream_read' undeclared here (not in a function); did you mean 'IMAP4_stream_send'?
imaplib.py:1455:88: error: 'IMAP4_stream_rename' undeclared here (not in a function); did you mean 'IMAP4_stream_enable'?
```

Same "testing artifact" trigger already documented in
`bugs/CODEGEN_generator_function_Lib_subprocess.md`'s 2026-08-20 entry:
a **relative** `filename='imaplib.py'` resolves via `os.path.abspath`
to `<cwd>/imaplib.py`, and running this repro from the repo's own root
makes `_is_selfhost_file` incorrectly evaluate `True`, enabling
`DispatchSolver`'s `allow_assume_all_methods` fallback for `IMAP4`
(which has a `__getattr__(self, attr): return getattr(self,
attr.lower())` — matching the "obj is self" shape, not the inferable
`f'{prefix}_{x}'` shape, so it falls into the "assume all methods"
branch). A real `mojo.py build`/absolute-path `compile_to_gimple` call
never sets `_is_selfhost_file` for `imaplib.py` and produces none of
these 8 errors — confirmed both before and after this fix by diffing
the generated C for `compile_to_gimple(src, do_imports=False,
filename='/Users/mrs/net/Python-3.14.6/Lib/imaplib.py')` (byte-
identical, no dispatch table involved either way).

**But — same as the subprocess.py case — the underlying codegen gap is
real and distinct**, not just a trigger artifact: `IMAP4.close`/
`.open`/`.read`/`.rename` (and their `IMAP4_stream` overrides) are
each real, ordinary (non-generator) methods that DO get compiled to a
real, callable, plain C function — just not under the bare
`IMAP4_close` name the dispatch table's struct initializer references.
`close`/`open`/`read`/`rename` are all libc/system symbols in
`gimple_codegen.py`'s `_C_RESERVED_FUNCS` (a Mojo function definition
with one of these names must not shadow the real libc symbol, so
`_safe_name()` mangles both the definition AND its C symbol to
`mojo_<name>` — e.g. the true emitted symbol is `IMAP4_mojo_close`,
confirmed via `grep IMAP4_mojo_close` on the generated C). But
`DispatchSolver._analyze_call_graph`'s `self.struct_methods` registry
(the source of every dispatch-table callee string) builds its "full
name" via plain string concatenation (`f"{stmt.name}_{method.name}"`),
never applying `_safe_name`'s reserved-symbol mangling — so the
dispatch table ends up referencing the bare, never-emitted
`IMAP4_close` instead of the real `IMAP4_mojo_close`. This is a
different mechanism from the just-fixed (same day, commit `50fa13a`)
generator-method case — there the plain symbol is never emitted AT ALL
(only the `<base>_start/_resume/_value/_destroy` coroutine API exists);
here the plain symbol IS emitted, just under a different (mangled)
name — but it produces the identical GCC "undeclared here (not in a
function)" failure shape.

**Fix** (`gimple_codegen.py`, `DispatchSolver._plan_dispatch_tables`):
added a sibling `continue` next to the existing generator-method skip,
gated on `_real_method_name in _C_RESERVED_FUNCS` (`_real_method_name`
recovered via a new `_callee_to_method` reverse-lookup off
`self.struct_methods`, mirroring the existing `_callee_to_struct`
reverse-lookup already used just above for the same "don't naively
string-split the callee name" reason — `_extract_method_name`'s naive
first-underscore split silently returns the WRONG method name whenever
the owning struct's name itself contains an underscore, e.g. splitting
`"IMAP4_stream_close"` on the first `_` yields `"stream_close"`, not
`"close"`, which would have made the `IMAP4_stream` half of this fix a
no-op without the reverse lookup). Kept as a genuinely SEPARATE check
from `generator_method_api` rather than folding both into one shared
"is this symbol really registered anywhere" lookup: at the point
`_plan_dispatch_tables` runs (Phase 1.5, before any struct method body
is ever codegen'd), `func_return_types`/`func_param_types` are NOT yet
populated for ordinary local struct methods, so a registry-membership
check would false-positive-drop nearly every legitimate entry still
correctly destined for the table. `_C_RESERVED_FUNCS` membership is a
pure syntactic property of the method's own name — decidable with zero
ordering dependency — which is exactly why it stays a small sibling
check rather than a shared lookup helper.

Verified: all 8 reported errors are gone from the isolated repro;
`grep IMAP4_close\|IMAP4_open\|IMAP4_read\|IMAP4_rename` on the fixed
output shows zero "undeclared" hits under `gcc -fgimple -fsyntax-only`;
the real absolute-path build (`compile_to_gimple(...,
filename='/Users/.../imaplib.py')`) is byte-identical before/after (no
dispatch table involved, confirming zero real-world behavior change);
the subprocess.py generator-method regression check
(`compile_to_gimple(..., filename='subprocess.py')`, same self-host-
trigger repro shape) still compiles with zero undeclared-symbol errors,
confirming this fix didn't regress commit `50fa13a`'s fix;
`test_gimple.py` 248/248, `test_module_cache.py` 76/76, `make
check-selfhost` clean, and a from-scratch stdlib dylib rebuild shows 0
skip lines (same as the unmodified baseline). imaplib.py itself still
does not build end-to-end (unrelated blockers documented below/in the
2026-08-18 entry) — this fix only removes these 8 specific errors from
the picture.

## Status (updated 2026-08-18 — blocker (a) below, the `socket___enter__`/`socket___exit__` "undeclared here" symbol clash, is FIXED)

Re-ran `python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/imaplib.py`
after `bugs/hard/CODEGEN_selfhost_getattr_dispatch_heuristic_misfires_
on_ordinary_code.md` landed its fix (the over-eager "assume all
methods" `getattr(self, x)` dispatch-table fallback is now gated to
only fire when compiling this compiler's own self-hosting source).
Blocker (a) below (`socket___enter__`/`socket___exit__` "undeclared
here" from `ssl.py`, the same mechanism/shape as ftplib.py's
`Popen__close_pipe_fds` blocker traced to that hard-bug doc) is GONE:
grepped the full build log for "undeclared" — no `socket___enter__`/
`socket___exit__` hits anywhere.

**imaplib.py still does not build end-to-end** — the build now fails
earlier, in unrelated code (`posixpath.py`'s `_varsubb`/`_varsub`,
`codecs.py`'s `_t3`/`_t5`/etc., `inspect.py`'s
`_mojo_cb_formatannotation_repl`/`_tNN` temporaries, `reprlib.py`'s
`functools__make_key_0c85c9`, `functools.py`'s `hits`/`misses`) —
same unrelated undeclared-identifier errors seen blocking
`ftplib.py` post-fix, not this doc's concern. Blocker (b) (the
unannotated-`__init__`-param field-type bug) and the coroutine-body
truthiness gap noted below are both still unaddressed, unrelated to
this fix.

## Status (updated 2026-08-11 — 3 of the 4 documented `Idler.burst` gaps FIXED; 2 blockers remain, both precisely diagnosed, neither fixed)

Re-verified with a fresh direct minimal repro (`Idler`/`IMAP4` reduced
to just the shapes `burst()` touches, same methodology as the
2026-08-09 entry below). Of the 4 previously-documented gaps, 3 are
FIXED this pass (all in `gimple_codegen.py`, all generic — not
imaplib.py-specific):

1. **`self._imap.sock` (a 2-level `self.<field>.<field>` chain)** —
   `_cpp_expr`'s `MemberExpr` case only ever recognized a single-level
   `self.<field>` read; a chain through an INTERMEDIATE struct-pointer
   field fell to the generic non-self fallback, emitting `self->_imap
   .sock` (`.`, not `->`) on a field this narrow model's own boxing
   convention stores as a raw `int64_t` in the C++ typedef regardless
   of its real pointer type — g++: "member reference base type
   'int64_t' is not a structure or union". Fixed by adding a case that
   recognizes `self.<field1>.<field2>` when `field1`'s type (already
   known via `struct_field_types`) is a registered struct pointer,
   casting through it explicitly: `((Inner *)(self->field1))->field2`.
   Also had to register the INNER struct name (`IMAP4`) into
   `_cpp_param_struct_names` — gen_module's existing "struct layout(s)
   needed by this module's compiled generator method(s)" .cpp-preamble
   typedef collection only knew about a generator method's own
   `self`-struct and a generator's declared parameter structs, neither
   of which covers a struct reached only indirectly through a field's
   pointer type.
2. **`next(self)` (the builtin, not a method call)** — unhandled,
   fell through to a bare undeclared C++ identifier. Fixed: `next(x)`
   now recognized when `x` is `self` or a struct-pointer local,
   dispatching to `x.__next__()` via the exact same struct-method-call
   machinery `self.<method>(...)` already uses (only the common 1-arg
   form; `next(x, default)`'s StopIteration-suppression not attempted).
3. **`self._pop(interval, None)` inside `while response := ...:`** —
   the self-method CALL itself was already correctly forwarding both
   arguments (an EARLIER fix, before this session, already closed that
   half — the doc's 2026-08-09 entry below describing "both real args
   dropped" is now stale). What was still broken: the WALRUS TARGET
   (`response`) was never declared at all — `_cpp_expr`'s `WalrusExpr`
   case only ever emits the assignment, assuming the name is already a
   declared C++ local (true for a walrus used as an ordinary
   statement's RHS, never true for one embedded directly in an `if`/
   `while` condition, which has no separate declaring statement) — g++:
   "use of undeclared identifier 'response'". Fixed with a new
   `_cpp_hoist_walrus_decls` helper, called from both `WhileStmt` and
   `IfStmt` before their condition is lowered: walks the condition
   (via the existing generic `_walk_ast`) for every `name := value`,
   declaring each with its value's inferred ctype — including a new
   special case for `self.<method>(...)`/`<struct-ptr-local>.
   <method>(...)` RHS (resolved via `func_return_types[f"{struct}_
   {method}"]`, mirroring `_quick_type`'s identical struct-method-call
   lookup), since the shared `_infer_simple_expr_ctype` free function
   has no self/struct-method-call case at all and would otherwise
   always default to `int64_t`.

Verified via a direct isolated repro (`Idler`/`IMAP4`/`burst`, all 3
shapes together) compiling clean through g++ and, separately, a real
end-to-end `mojo.py build` + run producing correct output values (not
just exit 0) for a str-returning stand-in `_pop`. Also confirmed
against the REAL `imaplib.py` inside the full transitive `mojo.py
build`: `Idler`/`burst`'s own generated code now shows ZERO gcc/g++
errors anywhere in the log (previously 4) — `MOJO_DEBUG=1` still shows
no "not eligible" refusal either.

Full mandatory gate (CLAUDE.md) re-run after all 3 fixes:
- `python3 test_gimple.py`: 247 passed, 0 failed
- `python3 test_module_cache.py`: 76 passed, 0 failed
- `make check-selfhost`: clean
- From-scratch `build/libmojostdlib.dylib` rebuild: 0 `skip <module>:` lines
- `python3 compile_stdlib.py` (no `-j`): 664/664 passed, 0 unexpected

**imaplib.py itself still does not build**, for two SEPARATE reasons,
neither attempted here:

**(a) A completely unrelated, severe, pre-existing symbol clash,
confirmed via the real full-build log** — GCC bails out ("confused by
earlier errors") partway through `ssl.py`, well before ever reaching
`imaplib.py`'s own code in this whole-program compile:
```
/Users/mrs/net/Python-3.14.6/Lib/ssl.py:6952:44: error: 'socket___enter__' undeclared here (not in a function); did you mean 'Idler___enter__'?
/Users/mrs/net/Python-3.14.6/Lib/ssl.py:6953:50: error: 'socket___exit__' undeclared here (not in a function); did you mean 'Idler___exit__'?
```
A cross-module symbol-resolution bug in `ssl.py`/`socket`-related
struct methods, unrelated to generators or to anything fixed this
session — out of scope for this doc, not investigated further (a
`ssl.py`-specific bug report would be the right place).

**(b) Even setting (a) aside, `self._imap`'s field is STILL wrong.**
`Idler.__init__(self, imap, duration=None):` (imaplib.py:1432) leaves
`imap` unannotated, so `_imap`'s registered field type defaults to
`int64_t` instead of the real `IMAP4 *` — this is the ALREADY-TRACKED
`bugs/hard/CODEGEN_unannotated_init_param_field_type_defaults_int64.md`
hard bug (re-verified unchanged earlier this same session), not
re-attempted here. Confirmed directly: fix (1) above is real and
correct — a minimal repro with `imap: IMAP4` annotated compiles and
runs `self._imap.sock` correctly end-to-end — but doesn't fully
activate for the REAL file until that separate hard bug is fixed.

**Also found, NOT fixed (a genuinely separate, pre-existing gap, not
introduced by any change this session, confirmed via a repro with NO
walrus/self-method/next() involved at all):** the coroutine-body
`_cpp_stmt`'s `if`/`while` condition lowering (`cond = self._cpp_expr
(s.condition)`) never applies Python truthiness coercion to a non-bool
condition value — a `char *`/`MojoList *` condition compiles to a raw
C++ pointer-non-null check (`if ((!s))` for `if not s:`), not
Python's real "is this string/list/tuple EMPTY" semantics. A minimal
repro (`while (s := f()):` where `f()` eventually returns `""`) hangs
forever at runtime instead of terminating, since a non-null pointer to
an empty string is still "truthy" in raw C++. This would matter for
`Idler.burst`'s own `while response := self._pop(interval, None):`
once (a) and (b) above are both resolved — `_pop`'s real return type
is a 2-tuple, which may also hit a SEPARATE representability limit in
this scalar coroutine-body model. Not investigated further or fixed —
a real, but broad, pre-existing gap (Python-truthiness coercion for
pointer/container-typed values is already solved on the ORDINARY
GIMPLE path via `_ensure_bool_cond`/`mojo_truthy_cstr`; porting the
equivalent to the coroutine-body emitter is a bigger, separate step,
not attempted here) — worth its own dedicated bug doc if it recurs
elsewhere.

## Status (updated 2026-08-09, re-verified with a direct minimal repro)

Re-verified against current master (post-merge `7df52a0`). The full
`mojo.py build` on the real `imaplib.py` is currently uninformative on
its own for this specific bug: the whole-transitive-graph build now
fails much earlier, in unrelated code (a severe `ssl.py`/`argparse`
symbol clash causing GCC to bail out early with "confused by earlier
errors") before the log gives a clean read on `Idler.burst`'s own
generated `.cpp`. So this pass isolated the method with a minimal
standalone repro (`Idler`/`IMAP4` classes reduced to just the shapes
`burst()` touches: `self._imap.sock`, `next(self)`, `self._pop(...)`)
and ran `MOJO_DEBUG=1 python3 mojo.py build` on that directly.

Result: no "not eligible" refusal (confirms the `raise self._imap.error
(...)` fix from `bugs/hard/CODEGEN_generator_raise_non_static_
exception_class.md` still holds — the generator reaches real coroutine
`.cpp` generation), and the generated `.cpp` reproduces all three
previously-documented blockers verbatim, unchanged:
```
imaplib_burst_repro_gen.cpp:120:23: error: request for member 'sock' in 'self->Idler::_imap', which is of non-class type 'int64_t' {aka 'long long int'}
imaplib_burst_repro_gen.cpp:126:18: error: 'next' was not declared in this scope
imaplib_burst_repro_gen.cpp:140:13: error: 'response' was not declared in this scope
imaplib_burst_repro_gen.cpp:140:34: error: too many arguments to function 'int64_t Idler__pop(Idler*)'
```
The 4th (`response`/arity) is one symptom, not two: `self._pop(interval,
None)` — a call to a `self`-method from inside a generator body — gets
silently codegen'd as a call to `Idler__pop(self)` (dropping both real
args, per the doc's original "self.<field> reads only, no method calls"
observation), so the `while response := ...` walrus assignment target
is left undeclared when the call shape mismatch cascades.

No change in classification or scope: these are the SAME structural
"coroutine-body expression emitter doesn't model nested struct-field
attribute chains, the `next()` builtin, or `self`-method calls" gaps as
before, not narrow, not attempted here — still worth a dedicated hard-
bug doc for `_cpp_expr`/`_cpp_stmt`'s silent-fallthrough-instead-of-
refusing behavior on unhandled generator-body constructs (a future
session's task, not this one).

## Status (updated 2026-08-07)

**Classification bug FIXED** (`bugs/hard/CODEGEN_generator_raise_
non_static_exception_class.md`, task #149) — `raise self._imap.error
(...)` no longer refuses at the eligibility gate; `_cpp_raise_stmt` now
emits a valid (untyped/lenient-match) `_MojoCppExc` throw for it.

**`Idler.burst` STILL does not compile end-to-end**, for OTHER,
unrelated pre-existing reasons in the same method body, confirmed via a
direct g++ compile of the generated `.cpp`:
- `self._imap` is itself a struct-typed field; `self._imap.sock` (a
  nested attribute chain through it) isn't representable in this
  narrow generator-body model (`self.<scalar field>` reads only) —
  g++: `request for member 'sock' in 'self->Idler::_imap', which is of
  non-class type 'int64_t'`.
- `yield next(self)` calls the builtin `next()`, not supported —
  g++: `'next' was not declared in this scope`.
- `self._pop(interval, None)` calls a method on `self` — also out of
  this narrow model's scope (self.<field> reads only, no method
  calls) — silently emitted as a call to an undeclared function rather
  than refused.

These are NOT new — they were always unsupported, just never reached
because the raise check refused `burst` FIRST. `imaplib.py`'s overall
build outcome is unchanged (still fails, same as before) — only the
internal blocker moved. Worth a dedicated hard-bug doc in a future
session on `_cpp_expr`/`_cpp_stmt`'s silent-fallthrough-instead-of-
refusing gap for unhandled generator-body constructs; not attempted as
part of the raise fix (see that hard-bug doc's own "Important finding"
section for the full analysis, including confirmation via the required
gate that this doesn't affect any currently-passing file).

## Status (updated 2026-08-06, superseded above)

**STILL FAILING**, confirmed reproducing identically against current
master (`2b0c4c5`) — the 2026-07-30 note's diagnosis was correct; this
elaborates it.

```
$ MOJO_DEBUG=1 python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/imaplib.py
[gimple_codegen] generator method Idler.'burst' not eligible (pass 2): unsupported `raise` value expression in generator body (only `raise ExcName(...)`/`raise ExcName` with a statically known exception class name is supported)
Error building: cannot compile module: function(s) burst (generator function(s), contain a `yield`/`yield from`) — ... falling back to interpreting this module from source instead
```

**Root cause:** `Idler.burst`:
```python
def burst(self, interval=0.1):
    if not self._imap.sock:
        raise self._imap.error('burst() requires a socket connection')
    try:
        yield next(self)
    except StopIteration:
        return
    while response := self._pop(interval, None):
        yield response
```
`raise self._imap.error(...)` raises an exception CLASS resolved via a
runtime member-expression (`self._imap.error`, a class stored as an
instance attribute) rather than a statically-known bare class name
(`raise ValueError(...)`). The coroutine codegen's `raise`-lowering
(Milestone D's real-C++-exceptions-in-the-generator's-own-translation-
-unit design) requires the exception class to be resolvable at compile
time to build the corresponding C++ exception object/type — a `raise
<MemberExpr>(...)` shape has no such static class name to work with, so
it's refused outright, and (same escalation pattern as
`bugs/hard/CODEGEN_generator_struct_typed_param_refused.md`) a single
module-level-reachable refusal like this hard-fails the WHOLE file's
`mojo.py build`, not just this one generator method.

**Now folded into `bugs/hard/CODEGEN_generator_raise_non_static_
exception_class.md`** — confirmed recurring twice more (`test.support`'s
`run_with_locale`/`subst_drive`, found while diagnosing
`Lib/test/_test_eintr.py`), so promoted from "single instance" to a full
hard-bug doc. See that doc for the shared root cause and fix-scope
notes.

Not fixed here — same reasoning as the sibling struct-param-refusal
gap: a genuine coroutine-codegen scope boundary (exception-type
resolution needs to happen at C++ compile time), not a narrow accidental
bug.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/imaplib.py
