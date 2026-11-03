# CODEGEN_generator_function: Lib/glob.py

## Status (2026-09-07 — "cluster A" premise re-examined; NOT a callable-value-local wiring gap)

Investigated as part of a batch aimed at "extend the callable-value-local
(`mojo_maybe_bound_call_N`) model into the A3 generator-body path". Finding:
this doc is NOT closeable that way, and the naive wiring would be a silent
miscompile.

- `select_recursive` / `select_recursive_step` / `select_wildcard` are
  nested-closure generators defined *inside methods* of `_GlobberBase`
  (`recursive_selector` / `wildcard_selector`). The A3 pre-pass
  (`gimple_gen_coro._eligible`) only handles top-level defs and direct
  struct methods, so they fall through to the legacy cpp coroutine
  emitter (`gimple_cpp_core.py`), which refuses on `match(...)`.
- `match` is `self.compile(part)` — the emitter has no static symbol for
  it; its runtime value is a bound method of an opaque `re.Pattern`.
  `mojo_maybe_bound_call_1((void*)match, path)` would compile but, since
  that value was never registered via `mojo_bound_method_new`,
  `mojo_is_bound_method` returns false and it is called as a bare
  function pointer — a jump through a garbage address. That is strictly
  worse than the current honest refusal, so it is not an acceptable fix.
- Real blocker: compiled-coroutine support for (a) generators that are
  nested closures inside a struct method (capturing `self` + locals) and
  (b) calling a duck-typed/opaque callable value. This is the same
  opaque-receiver modelling the pickletools doc already concluded is
  feature-sized. `_iterdir` (the doc's other item) is already A3-eligible
  and lowers fine today — bytes value type landing resolved it.

No code change. Hand-off: this is a real feature project (opaque-callable
+ nested-closure-generator codegen), not an incremental dispatch wiring.

## Status (2026-09-05 — A3 stack-switch cutover: still REFUSED, cluster A)

Fresh isolated `compile_to_gimple_with_cpp(do_imports=False)`:

- `_iglob`, `_glob2`, `_iterdir`, `_rlistdir`,
  `_GlobberBase.select_exists` now compile through the A3 path.
- **Still refused:** the nested generator functions `select_recursive`,
  `select_recursive_step`, `select_wildcard` (defined inside
  `_RecursiveGlobber.select_recursive` / `_WildcardGlobber.select_wildcard`).
  Blocker: `a call to unresolved callee 'match(...)' ... in a compiled
  generator/coroutine body`. `match` is a closure-captured callable value
  (`self.compile(part)` — a bound `re.Pattern.match`), which the compiled
  generator-body expression emitter cannot call. This is **cluster A**
  (opaque / closure-captured callable-value dispatch in a generator body),
  shared with `os._fwalk` (`stat`), `pickletools._genops` (`getpos`),
  `test/test_frame` (`nested`). Needs a callable-value local model in the
  A3 generator-body codegen.

## Status (re-verified 2026-08-26, worktree agent-aac0d33be914873b5 — independent re-verify, byte-identical, no change)

Independent fresh isolated `compile_to_gimple_with_cpp(do_imports=False,
MOJO_DEBUG=1)` repro on the real file: byte-identical 5-generator
refusal set — `_iglob` ("unsupported for-loop iterable type: CallExpr"),
`_iterdir` (unresolved `bytes(...)` callee), and `select_recursive`/
`select_recursive_step`/`select_wildcard` (unresolved `match(...)`
callee). Confirms the opencode-genlib2 entry immediately below.
Dominated by the out-of-scope opaque-callable-value/dynamic-generator-
dispatch feature gap; `bytes()` would need a real bytes value
representation. No code change; doc stays open.

## Status (updated 2026-08-26, worktree fix/opencode-genlib2 — re-verified fresh; refusal set byte-identical, `bytes()` absence re-confirmed post-split)

Fresh strict isolated `compile_to_gimple_with_cpp(do_imports=False)`:
byte-for-byte identical 5-generator refusal set — `_iglob` ("unsupported
for-loop iterable type: CallExpr"), `_iterdir` ("a call to unresolved
callee 'bytes(...)' ..."), and `select_recursive`/`select_recursive_step`
/`select_wildcard` (all "a call to unresolved callee 'match(...)' ..." —
the same opaque-callable-value dispatch family as the older
`select_next(...)` wording, exactly as the 2026-08-26 rest-remainder16
entry traced). Also re-confirmed via a fresh grep that the `bytes`
builtin still has ZERO support anywhere in the (now split)
`gimple_*.py` backend. Classification unchanged: dominated by the
out-of-scope opaque-callable-value / dynamic-generator-dispatch feature
gap (`selector()`/`glob_in_dir()` holding dynamically-chosen generator
references); `bytes()` would need a real bytes value representation.
No code change; doc stays open.

## Status (updated 2026-08-26, worktree fix/rest-remainder16 — re-verified; blocker text shifted slightly, same classification)

Fresh re-verify against this worktree (branched from master `a913ab8`).
Isolated compile (`compile_to_gimple_with_cpp(..., do_imports=False)`):
same 5-generator refusal set as 2026-08-25
(`_iglob`/`_iterdir`/`select_recursive`/`select_recursive_step`/
`select_wildcard`), with one wording difference worth recording
precisely: `select_recursive`/`select_recursive_step`/
`select_wildcard` now report an unresolved callee `match(...)` rather
than `select_next(...)`. Traced: this is NOT a new/different gap — both
`select_next` (`self.selector(parts)`, holds a reference to one of
several possible generator functions chosen dynamically) and `match`
(a local bound to `self._compile_pattern(...)`'s `.match`/similar
method, also chosen dynamically) are separate instances of the exact
same "opaque callable-value dispatch" family this doc already
classifies as the dominant blocker — the refusal machinery just surfaces
whichever unresolved-callee site it walks into first inside each
function body; both are real, unrelated to any recently-landed
mechanism. `_iglob`'s "unsupported for-loop iterable type: CallExpr"
and `_iterdir`'s `bytes(...)` gap are unchanged verbatim. Classification
unchanged: dominated by the out-of-scope opaque-callable-value/
dynamic-generator-dispatch feature gap. No change; doc stays open.

## Status (updated 2026-08-25, worktree fix/rest-remainder14 — re-verified; blocker set is BROADER than previously characterized, same underlying feature gap)

Fresh re-verify against this worktree (branched from master `f65502d`;
note the whole codegen backend has since been split from the old
monolithic `gimple_codegen.py` into `gimple_cpp_core.py`/
`gimple_gen_calls.py`/etc. — this is a refactor, not a behavior change,
confirmed by re-deriving the mechanism below directly from the current
files rather than trusting old line-number references). The refusal
surfaced is now DIFFERENT from what the last several passes recorded
(`self.select_exists` returned as a plain value is no longer the first
thing reached — five generators refuse together):

```
_iglob: unsupported for-loop iterable type: CallExpr
_iterdir: a call to unresolved callee 'bytes(...)' is not supported ...
select_recursive, select_recursive_step, select_wildcard:
    a call to unresolved callee 'select_next(...)' is not supported ...
```

Traced each:
- `select_recursive`/`select_recursive_step`/`select_wildcard` (all
  nested inside `_GlobberBase` methods) all do `select_next =
  self.selector(parts)` then later `yield from select_next(...)`.
  `select_next` holds a reference to one of several possible GENERATOR
  functions chosen dynamically at runtime (`select_wildcard`/
  `select_recursive`/`select_exists`, picked inside `selector()`) — this
  is the exact same "bound-generator-value calling convention" gap the
  doc already tracked for `return self.select_exists`, just reached via
  a local variable assignment instead of a `return` statement. Confirmed
  the existing "declared callable-value local" support
  (`_CPP_CALLABLE_CTYPE`/`_CPP_CALLABLE_CTYPE_1ARG`, `gimple_cpp_core.py`
  ~2539-2551) can't cover this: those are fixed `std::function<int64_t()>`
  / `std::function<int64_t(int64_t)>` scalar signatures for calling an
  ordinary function value, with no representation for "the referenced
  value is itself a 4-function coroutine API" at all.
- `_iglob`'s `for name in glob_in_dir(...)` where `glob_in_dir = _glob2`
  (a generator) or `_glob1`/`_glob0` (ordinary functions), picked
  dynamically — the SAME opaque-callable-value-that-might-be-a-generator
  dispatch problem from the for-loop-iterable side instead of the
  yield-from side.
- `_iterdir`'s `bytes(os.curdir, 'ASCII')` is a genuinely separate,
  narrower gap: grepped all of `gimple_cpp_core.py`/`gimple_gen_calls.py`/
  `gimple_gen_exprs.py`/`gimple_exprtypes.py` — the `bytes(...)` builtin
  has ZERO codegen support anywhere (plain or coroutine path), consistent
  with this project representing strings as `char *` with no separate
  bytes/bytearray value representation at all. Also affects `Lib/os.py`
  (`bytes(curdir, 'ASCII')`, line 232) and `Lib/imaplib.py` (three call
  sites) — real but itself feature-sized (would need an actual bytes
  value representation, not just a narrow builtin-dispatch case), and
  wouldn't unblock this file's other, larger callable-value-dispatch
  gap even if added.

**Conclusion**: this file's blocker set is dominated by the
opaque-callable-value / dynamic-generator-dispatch feature gap this
session's mandate explicitly flags as out of scope (large speculative
feature: a real tagged/opaque callable-value representation spanning
both ordinary functions and generators). Not attempted. The doc's
previous characterization ("just `self.select_exists`") undersold the
scope — updating here so a future pass doesn't underestimate it again.
Doc stays open.

## Status (updated 2026-08-25, worktree fix/rest-remainder11 — re-verified unchanged)

Re-verified fresh against this worktree. `_GlobberBase.selector`'s
`return self.select_exists` still hits the honest "compiled GENERATOR
method referenced as a plain value (not called)" refusal — a
bound-generator-value calling-convention gap (would need a new
bound-method-value variant carrying the 4-function coroutine API through
to a later call site, a real feature addition). The `translate_584a43`
kwarg-arity issue (same-bare-name cross-module collision family,
`CODEGEN_same_bare_name_struct_collision_across_modules`)
remains behind it, unreached. Neither is touched by any recently-landed
shared mechanism. No change; doc stays open.

## Status (updated 2026-08-24 — re-verified unchanged)

Fresh isolated compile (`GimpleGen(do_imports=False, relaxed_imports=
True)`): identical refusal — `self.select_exists` on `_GlobberBase` is a
compiled GENERATOR method referenced as a plain value (not called),
which this scalar coroutine-body model has no first-class-value
representation for (only the `<base>_start/_resume/_value/_destroy` API
exists, not a `MojoBoundMethod*`-callable form). Same feature gap as
before; no change. Doc stays open.


## Status (updated 2026-08-23 — re-verified; honest refusal for `self.select_exists` as a plain value unchanged)

Isolated compile reproduces the exact `RuntimeError: cannot compile module:
'self.select_exists' on struct '_GlobberBase' is a compiled GENERATOR
method referenced as a plain value (not called)` refusal the 2026-08-20
entry landed — zero generated C references the undeclared symbol, exactly
as designed. This session's three generic generator-codegen fixes don't
touch the bound-generator-value calling-convention feature gap behind it.
The `translate_584a43` kwarg-arity architectural issue (same-bare-name
collision family) also remains as documented. No change.


## Status (updated 2026-08-20 — a NEW blocker found+fixed: bound-value reference to a generator method crashed with an undeclared-symbol GCC error)

Re-verified against current master (`f0bdc29`). A fresh full build
(`python3 fire.py build .../Lib/glob.py`, transitive `do_imports=True`)
now surfaces a *different* first blocker than the 2026-08-10 entry
below documented (that entry's `translate_584a43` arity bug and the
`_join_abb124` return-type bug are apparently both still latent further
down the file, but never reached — this new bug fires earlier):

```
/Users/mrs/net/Python-3.14.6/Lib/fnmatch.py:3631:61: error: '_GlobberBase_select_exists' undeclared here (not in a function); did you mean '_GlobberBase_lexists'?
```
(the `fnmatch.py` attribution is a `#line`-directive artifact of the
whole-program `do_imports=True` concatenation, same caveat this doc's
own history already documents elsewhere — the real offending statement
is `_GlobberBase.selector`'s `return self.select_exists`, glob.py:399.)

**Root cause**: `select_exists` (glob.py:534, `def select_exists(self,
path, exists=False): ... yield path`) is itself a real generator
method, compiled via the C++20-coroutine path (Milestone C step 3,
`self._generator_method_api`) — its actual callable surface is 4
`extern "C"` functions, `_mojogen_GlobberBase_select_exists_start/
_resume/_value/_destroy` (see `_gen_cpp_generator_unit`'s docstring).
`selector`'s `return self.select_exists` is a bare bound-METHOD
reference used as a plain VALUE (not called) — lowered by
`_lower_bound_method_value` (gimple_codegen.py), which — before this
fix — treated EVERY method the same way regardless of whether it was a
generator: it computed `mangled = self._struct_method_csym(struct_name,
method, overload_id)` (`'_GlobberBase_select_exists'`) and
unconditionally emitted a `static void * _funcptr_{mangled} = (void
*){mangled};` referencing that name as if it were an ordinary compiled
C function. Since `select_exists` compiles via the coroutine path
instead, gen_module's Phase 2a skips emitting any ordinary function
named `_GlobberBase_select_exists` at all (see the `_supported_
generator_methods` skip-check there) — so the `_funcptr_...` static's
own initializer referenced a symbol that plain never exists, producing
GCC's "undeclared here (not in a function)" at `-fgimple` compile time.
This is a generic `gimple_codegen.py` bug (the same mechanism would fire
for ANY bare `self.<generator_method>` value-reference in any file),
not glob.py-specific.

**Fix**: `_lower_bound_method_value` now checks `(struct_name, method)
in self._generator_method_api` up front and refuses cleanly with a
`RuntimeError` (the project's established "fall back to interpreting
this module from source" convention, matching e.g. the `AwaitExpr`
refusal a few hundred lines up in the same file) instead of emitting
the broken forward reference. This is NOT a full fix for the underlying
shape — a `MojoBoundMethod*`'s calling convention
(`mojo_bound_method_call_N`: one call, one scalar `int64_t` return) has
no way to represent "returns an iterable generator" at all; correctly
supporting `return self.<generator_method>` followed by a later
`for x in selector(...)` call would need a NEW bound-method-value
variant that carries the 4-function coroutine API through to the call
site — a real feature addition, out of scope for this narrow refusal.
Declined here deliberately (feature-sized, not a bug fix).

Verified: isolated compile
(`compile_to_gimple(open('glob.py').read(), do_imports=False,
filename=...)`) previously reached `_lower_bound_method_value` and
returned a `'char *'`/temp pair that later produced GCC's undeclared-
symbol error when fed through `gcc-mp-15 -fgimple -fsyntax-only`; now
raises a clear, immediate
`RuntimeError: cannot compile module: 'self.select_exists' on struct
'_GlobberBase' is a compiled GENERATOR method referenced as a plain
value ...` from Python, with ZERO generated C referencing the
undeclared symbol. A real `fire.py build` of glob.py confirms the exact
GCC "'_GlobberBase_select_exists' undeclared" error is gone (0
occurrences in a fresh build log; the build still fails, now via the
honest `RuntimeError` instead). The existing `bound_method_as_value`
regression test in `test_gimple.py` (an ordinary, non-generator bound
method used as a value, then called) still passes — confirms the
ordinary case is unaffected by the new generator-method guard.

Full mandatory gate (CLAUDE.md) re-run after this fix:
- `python3 test_gimple.py`: 248 passed, 0 failed
- `python3 test_module_cache.py`: 76 passed, 0 failed
- `make check-selfhost`: clean (fire.py compiling its own source)
- From-scratch `build/libmojostdlib.dylib` rebuild: 0 `skip <module>:` lines
- `python3 compile_stdlib.py`: 664/664 passed, 0 unexpected

**glob.py itself still does not build.** The `translate_584a43`
keyword-arg-arity gap (line 354, described below, part of the already-
tracked `bugs/hard/CODEGEN_same_bare_name_struct_collision_across_
modules.md` architectural family) is still open and unfixed — not
reached by this pass's fresh build (the `select_exists` bug above fired
first and is fatal to the whole `do_imports=True` compile), so it
couldn't be independently re-confirmed this pass, but nothing in this
fix touches that code path.

## Status (updated 2026-08-10, later same day — 2 of 3 remaining blockers FIXED; 1 precisely diagnosed, not fixed)

Re-verified against current master. Two real, previously-undiagnosed
bugs found and fixed this pass (both in `gimple_codegen.py`, both
generic — not glob.py-specific):

**Fix 1 — self-recursive generator consumed via plain `for`, not
`yield from`, was refused on every pass.** `_glob2`'s `yield from
_rlistdir(...)` compiles fine, but `_rlistdir` itself is recursive via
an ORDINARY consuming loop (`for y in _rlistdir(path, ...): yield
_join(x, y)`, glob.py:224 — the classic `os.walk`-style recursive-
directory-listing shape), not `yield from`. `_cpp_for_generator_
delegate` (the codegen for "plain `for` over an already-compiled
sibling generator") had no self-recursion case at all — only `_cpp_
yield_from` did (added for a previous, `yield from`-only bug). Since a
generator only registers into `self._generator_api`/`self._supported_
generators` AFTER its own body finishes compiling, a genuinely self-
recursive `for` loop inside that SAME body can never find itself there
on any retry pass (unlike an ordinary forward-reference to a sibling
defined later, which the existing multi-pass retry loop already
handles) — `MOJO_DEBUG=1` showed `_rlistdir` permanently refused:
"`for ... in _rlistdir(...)` does not consume a generator this compile
has itself already translated... — the consumed generator must be
defined earlier", taking the whole module's compile down every time.
Fixed by mirroring `_cpp_yield_from`'s existing self-recursion handling
(`self._cpp_gen_self_name`/`_base`/`_params`, the same locally-tracked
context) into `_cpp_for_generator_delegate`: detects `for x in
<this-same-function>(...)`, builds the delegate call from the
in-progress self-context instead of the not-yet-populated real
registry, and declares the per-iteration loop-consumption local via
C++ `auto` (its real type isn't known until AFTER this whole
generator's own body finishes — but `_gen_cpp_generator_unit` already
emits a forward `extern "C"` declaration for `{base}_value` whenever
self-recursion is detected, so `auto` deduction against that forward
declaration is provably correct, not a guess). A tuple-valued
self-recursive loop target is refused honestly (falls through the
existing `tuple_slot_ctypes is None` check) rather than guessed at —
out of scope here.

**Fix 2 — `_func_csym`'s mangled-key mirror used `setdefault`, freezing
a function's return/param type at whatever it was on the FIRST call,
even after later passes corrected it.** `_join`'s return type is
correctly inferred `char *` by Pass 1.3e ("refresh return types now
that param inference is final") — confirmed directly via debug
instrumentation: `func_return_types['_join']` == `'char *'` throughout.
But `_glob0` (which calls `_join`, and is compiled EARLIER in source
order) resolves its OWN call site's C symbol via `_func_csym('_join')`,
which mirrors the bare-name entry into the mangled-symbol key
(`func_return_types['_join_abb124']`) via `setdefault` — so whichever
call happened to run FIRST froze the mangled key's value forever,
regardless of any later correction to the bare key. `_emit_call` (the
GIMPLE call-emission helper) looks up the callee's return type BY THE
MANGLED KEY specifically to decide whether a cast is needed — a stale,
wrong mangled entry there overrides an otherwise-correct `ret_type`
with the wrong one, and then emits the call's real (correct) result
straight into a temp declared with the WRONG type, with no cast at all
(since the whole point of that lookup is "insert a cast when the two
disagree" — it never considered its own answer might itself be stale).
Concretely: `_t8 = _join_abb124(_t5, _t7);` assigned a genuine `char *`
return into an `_t8` declared `int64_t` — GCC's `-Wint-conversion`
"assignment to 'int64_t' from 'char *'" — reported at `glob.py:175`
only because of `-fgimple`'s unreliable un-`#line`-stamped physical-line
counting (the 2026-08-09 entry below already established the real
offending statement is inside `_glob0`, not `_glob2` — this pass
confirms and fixes the actual root cause that entry left open).
Fixed by changing both `func_param_types`/`func_return_types` mirrors in
`_func_csym` from `setdefault` to a plain assignment — always
re-mirroring the CURRENT bare-name value is strictly more correct than
freezing at first use, since later passes only ever have MORE
information than earlier ones, never less.

Verified via a direct isolated compile (both `do_imports=False` and the
full `do_imports=True` build): `_t3 = _join_abb124(_t5, _t7);` now (no
more int64_t detour), `_join`'s own definition/forward-declaration were
already correct (`char * _join_abb124 (char *, char *)`) and unchanged.
Whole-build error count for the SAME full `fire.py build`: 505 → 504
(exactly the one fixed error; a full before/after error-message-set
diff confirms zero new error categories introduced — the other 2
pre-existing `-Wint-conversion` "int64_t from char*" instances
elsewhere in the build, unrelated call sites, are untouched).

Full mandatory gate (CLAUDE.md) re-run after BOTH fixes together:
- `python3 test_gimple.py`: 247 passed, 0 failed
- `python3 test_module_cache.py`: 76 passed, 0 failed
- `make check-selfhost`: clean (fire.py compiling its own source)
- From-scratch `build/libmojostdlib.dylib` rebuild: 0 `skip <module>:` lines
- `python3 compile_stdlib.py` (no `-j`): 664/664 passed, 0 unexpected

**glob.py itself still does not build** — exactly ONE error remains,
precisely diagnosed but NOT fixed this pass (same architectural class
as the already-tracked, deliberately-deferred `bugs/hard/CODEGEN_same_
bare_name_struct_collision_across_modules.md`, just for FREE-FUNCTION
signatures instead of struct layouts):

```
/Users/mrs/net/Python-3.14.6/Lib/glob.py:354:9: error: too few arguments to function 'translate_584a43'; expected 4, have 1
```

Root cause, confirmed by direct inspection of the generated `.ci`:
glob.py's own `translate(pat, *, recursive=False, include_hidden=False,
seps=None)` (glob.py:294, 1 positional + 3 keyword-only params) is
compiled correctly as a real 4-parameter C function
(`char * translate_584a43 (char * pat, int64_t recursive, int64_t
include_hidden, int64_t seps)`). But its ONE call site
(`_compile_pattern`, glob.py:354: `translate(pat, recursive=recursive,
include_hidden=True, seps=seps)`) emits `translate_584a43 (_t11)` — only
`pat`, all 3 keyword arguments silently dropped. `Lib/fnmatch.py`
(transitively imported) has its OWN, UNRELATED top-level `def
translate(pat):` (fnmatch.py:95 — a single-positional-arg, no-kwonly-
param function, mangled separately as `fnmatch_translate_584a43` since
its own module-qualification differs). `_lower_named_call`'s keyword-
argument-padding logic (`expected_params = self.func_param_types.get
(fname_raw, [])`, keyed by the BARE name `'translate'`) reads from
`self.func_param_types` — a dict SHARED across the entire `do_imports=
True` transitive compile, not module-qualified, first/last-write-wins
— so glob.py's own `translate` call site ends up reading fnmatch.py's
`translate`'s signature (1 param) instead of its own (4 params),
padding zero extra arguments instead of the 3 needed. This reproduces
even though `fire.py build`'s PRIMARY path (`driver.py`'s per-module
link mode) would normally make this class of collision unreachable
(each module its own translation unit there) — glob.py's build falls
through to the vulnerable `do_imports=True` WHOLE-PROGRAM inline path
(`build_executable`'s fallback) for unrelated reasons (its own
coroutine-generator content), which is exactly the "structurally
possible when the primary link-mode path is bypassed" caveat the
same-bare-name-collision hard-bug doc already documents for the
struct-layout version of this same architectural gap. Not attempted
here: fixing it properly means module-qualifying `func_param_types`/
`func_return_types`/`_func_kwargs_slot` (or an equivalent conflict-
detection layer) across the whole `do_imports=True` compile — the same
broad, high-blast-radius shared-registry rework the struct-collision
doc already deliberately declined to attempt in a narrow pass, now
confirmed to also affect free-function signature/kwarg-padding
resolution, not just struct field layouts. Flagged here precisely so a
future pass targeting that whole hard-bug family has a second, cleanly
independent confirmed instance to fix alongside the struct one.

## Status (updated 2026-08-10 — re-verified the "struct _X_toplev" pattern task; a related-but-distinct variant found+fixed)

Investigated this session's cross-cutting task tracing a recurring
`invalid use of undefined type 'struct _<modname>_toplev'` GCC error
across 9 bug docs. This file was named in the 2026-08-07 entry below as
"likely another symptom of the same cross-module collision class" —
confirmed via a fresh rebuild that's WRONG (or at least stale): zero
occurrences of that exact error now (already fixed by the mechanism-1/
mechanism-2 fixes referenced there, `bugs/hard/COMPILE_FAIL_module_
toplev_struct_never_fully_defined.md`, deleted as resolved).

Found and fixed one closely related, previously-undocumented bug while
tracing the mechanism, and this file was the one that pinned it down
precisely: `typing.py` (transitively imported) does
```python
class _LazyAnnotationLib:
    def __getattr__(self, attr):
        global _lazy_annotationlib
        import annotationlib
        _lazy_annotationlib = annotationlib
        return getattr(annotationlib, attr)
```
`_gen_struct_method`/`_gen_lifted_closure` (gimple_codegen.py) never
set `self._current_module_ctx` — so this class's methods, compiled
FIRST in typing.py's own recursive do_imports=True compile (before any
ordinary function/toplevel statement had set the context), inherited
stale/default state and routed the `global` write to the wrong
module's struct: `struct '_root_toplev' has no member named
'_lazy_annotationlib'` (should have been `_typing_globals`). Fixed by
setting the context explicitly in both methods, mirroring `gen_func`/
`_gen_toplevel`'s existing identical line. Also fixed a related
`_safe_coerce_emit` bug this exposed: its `is_field` check only
recognized `->`-accessed struct-field LHS (needed to route a cast
through a register temp first, an `-fgimple` requirement), not plain
`.`-accessed ones (a non-pointer globals-struct instance's own field)
— once the write correctly targeted `_typing_globals._lazy_
annotationlib`, it produced an invalid combined cast+store statement,
"non-register as LHS of unary operation". Fixed by recognizing `.` too.

Effect on this file: total build error count dropped 504 -> 502 (both
of the above, confirmed via a full category diff — zero new error
categories introduced, only these 2 disappeared). This file's real
remaining blockers (line 175 / `_join_abb124`'s return-type gap, line
354 / `translate_584a43` keyword-arg-arity gap, described below) are
unaffected. No reclassification — glob.py still does not build.

## Correction (2026-08-09, later same day): the line-175 error's root cause was misattributed

The "updated 2026-08-09" note directly below (from an earlier commit
the same day) claimed `bugs/hard/CODEGEN_cross_module_bare_import_name_
collision.md`'s `_global_to_module` collision was "the real root cause
of the line-175 error" and "still present and unfixed." A careful
re-derivation (not just re-matching the same misleading `glob.py:175`
GCC line number, which this doc's own earlier methodology note already
warns is unreliable for this function) found this was wrong: the
`_global_to_module` read-side misattribution for `contextlib`
(glob.py's own `_listdir`, reading `_subprocess_globals.contextlib`)
was ALREADY fixed as a side effect of `bugs/hard/CODEGEN_module_globals_
cross_contamination_via_imported_stmts.md`'s "Mechanism 3" fix (commit
`21f5f49`, landed before this doc's own "updated 2026-08-09" note was
written — the note re-matched the symptom without re-verifying the
mechanism still applied). Confirmed directly: stripping all `#line`
directives from the generated `.ci` and recompiling shows GCC's real
physical-line error is inside `_glob0_737363` (`_t8 =
_join_abb124(_t5, _t7)` — assigning `_join_abb124`'s `char *` return
into an `int64_t`-declared temp), NOT any `contextlib`/`_global_to_
module` misattribution — a distinct, unrelated return-type-inference
gap in codegen for a path-join-style helper call. Separately confirmed
`_listdir_132aaf`'s own generated code no longer reads `_subprocess_
globals.contextlib` at all (falls through to the safe "unknown
identifier" placeholder, since it correctly recognizes it does not own
that name). `bugs/hard/CODEGEN_cross_module_bare_import_name_collision.
md` has been removed as fixed (see its own former content / this
commit's message for the full evidence). glob.py itself still does not
build — same practical bottom line — but for the `_join_abb124`
return-type bug above (not yet investigated further) and the line-354
`translate()` keyword-arg-arity gap already described below, not this
one.

## Status (updated 2026-08-09, re-verified — unchanged)

Re-verified against current master (post-merge `7df52a0`). Still fails
identically to the 2026-08-07 diagnosis below — exact same two errors,
same lines:
```
/Users/mrs/net/Python-3.14.6/Lib/glob.py:175:7: error: assignment to 'int64_t' {aka 'long long int'} from 'char *' makes integer from pointer without a cast [-Wint-conversion]
/Users/mrs/net/Python-3.14.6/Lib/glob.py:354:9: error: too few arguments to function 'translate_584a43'; expected 4, have 1
```
Confirmed again: `MOJO_DEBUG=1` shows no "not eligible" refusal for any
of glob.py's own generators. (See the correction above — the line-175
root-cause claim in this section is superseded/wrong.)

One addition: pinned down the second error (line 354,
`translate_584a43` arity mismatch) precisely — it is NOT generator-
related either. `translate(pat, *, recursive=False, include_hidden=
False, seps=None)` (glob.py:294) is an ordinary function with 3
keyword-only parameters; its one call site, `_compile_pattern`
(glob.py:354, `translate(pat, recursive=recursive, include_hidden=True,
seps=seps)`), passes all 3 by keyword. `translate` itself contains no
`yield` — this is a plain call-codegen gap in keyword-only-argument
forwarding for an ORDINARY function call, unrelated to the coroutine
generator path this cluster of bug docs is about. Left uninvestigated
further here (out of scope for the generator-codegen cluster; would be
better tracked as its own non-generator `CODEGEN_` doc if it recurs
elsewhere — a quick grep of the other 2 bug docs in this batch,
gettext.py/imaplib.py, found no matching symptom, so not folded into a
shared doc yet).

## Status (updated 2026-08-07, re-diagnosed — previous root cause was WRONG)

**STILL FAILING**, but the 2026-08-06 note's root-cause analysis below
(a generator yield-value forward-reference type-inference bug) has been
**re-investigated and disproven**. Re-confirmed against current master:
`MOJO_DEBUG=1` still shows NO "not eligible" refusal for any of glob.py's
own generators (`_iglob`, `_glob1`/`_glob0`, `_glob2`, `_iterdir`,
`_rlistdir`) — they all still reach real `.cpp` coroutine generation, and
directly inspecting the generated `.cpp` (both in isolation, `do_imports=
False`, and inside the full `do_imports=True` build) confirms
`_mojogen__glob2_value` is correctly typed `char *` in BOTH — i.e.
`_glob2`'s own promise/yield-value type inference is and was already
CORRECT. The forward-reference `_generator_yield_ctype` theory doesn't
hold up: `_yield_from_delegate_ctype` (gimple_codegen.py:2560) already
defaults an unregistered-generator `yield from` target to `'char *'`
(not `int64_t` — that default was fixed by commit `c234efb`, already on
master), so even the forward-reference case was never actually broken
here.

**Real root cause: `bugs/hard/CODEGEN_cross_module_bare_import_name_
collision.md`** (new hard-bug doc, written this session). The failing
line is NOT inside `_glob2` at all — GCC's reported `glob.py:175` is a
red herring (an artifact of un-`#line`-stamped physical-line counting
past the end of the PREVIOUS `#line`-stamped statement; `_glob2`'s own
source-line range never appears in the `.ci` at all, since it compiles
entirely via the `.cpp` coroutine path). The real offending code is
`_listdir` (a plain, non-generator helper a few lines later in the same
`.ci` region):

```python
def _listdir(dirname, dir_fd, dironly):
    with contextlib.closing(_iterdir(dirname, dir_fd, dironly)) as it:
        return list(it)
```

`glob.py` does `import contextlib` at module scope, but the compiled
`.ci` resolves that bare name to `_subprocess_globals.contextlib` —
`Lib/subprocess.py` (transitively reachable from glob.py's own import
graph) ALSO does `import contextlib`, and `self._global_to_module`
(gimple_codegen.py:3907), the name-only "which module owns this bare
global name" map, is SHARED across every module compiled in the same
`do_imports=True` build with first-registration-wins semantics —
subprocess's registration happens first (its own recursive sub-compile
runs before glob.py's own root-level preamble scan), so glob.py's own
`contextlib` reads get silently redirected to subprocess's globals
struct instead of its own. The resulting type mismatch (subprocess's
`contextlib` field's C type vs. what `_listdir`'s locals expect) is what
actually produces the `-Wint-conversion` "assignment to int64_t from
char*" error. See the hard-bug doc for the full trace, breadth (at
least 9 `Lib/*.py` files `import contextlib` alone — this is not
glob.py/contextlib-specific), and why it's deliberately NOT fixed here
(same architectural shape/blast radius as the already-deferred task
#141, `bugs/hard/CODEGEN_same_bare_name_struct_collision_across_
modules.md` — a shared, name-only, first-writer-wins cross-module map
used at 4+ separate read sites project-wide, not a narrow generator-
codegen bug at all).

**Classification: NOT a generator-codegen-cluster failure.** Both of
glob.py's own generators compile correctly; the failure is entirely in
plain (`.ci`) code that happens to consume one, via a totally unrelated
cross-module global-resolution bug.

The two other current errors (`translate_584a43` arity mismatch,
`struct _subprocess_toplev` undefined) were not investigated further —
still look unrelated to the generator-codegen cluster (arity/import-
resolution issues in non-generator code; the `_subprocess_toplev`
naming is likely itself another symptom of the same cross-module
collision class, given the pattern above) and are left for a separate
pass.

## Status (updated 2026-08-06, SUPERSEDED — root cause below was wrong, kept for history)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-30 `'os' was not declared` .cpp error no longer reproduces
(dyld.py's documented "module attribute access not threaded into
generator scope" gap — see `bugs/COMPILE_FAIL_ctypes_macholib_dyld.md`
— appears fixed for glob.py's shape at least). `MOJO_DEBUG=1` shows NO
"not eligible" refusal for any of glob.py's own generators (`_iglob`,
`_glob1`/`_glob0`, `_glob2`, `_iterdir`, `_rlistdir`) — all pass the
eligibility pre-filter and reach real `.cpp` generation.

Current failure, still inside the generator-codegen cluster but a
DIFFERENT, narrower bug than the old one:

```
/Users/mrs/net/Python-3.14.6/Lib/glob.py:175:7: error: assignment to 'int64_t' {aka 'long long int'} from 'char *' makes integer from pointer without a cast [-Wint-conversion]
```

**Root cause (read from `_glob2`'s source) — WRONG, see 2026-08-07 above:**
```python
def _glob2(dirname, pattern, dir_fd, dironly, include_hidden=False):
    assert _isrecursive(pattern)
    if not dirname or _isdir(dirname, dir_fd):
        yield pattern[:0]                                    # char* (empty string slice)
    yield from _rlistdir(dirname, dir_fd, dironly,            # forward reference!
                         include_hidden=include_hidden)
```
`_glob2` has TWO yield sites of apparently different shapes: a direct
`yield pattern[:0]` (a string slice, `char *`) and a `yield from
_rlistdir(...)` — but `_rlistdir` is DEFINED LATER in the file (line
218, vs. `_glob2` at line 170). This is the same forward-reference
caveat already surfaced in this session's `MOJO_DEBUG` output for a
different function in this same file (`tokenize`-style note: *"the
delegated-to generator must be defined earlier"*) — when the overall
generator's yielded-VALUE type is computed (`_generator_yield_ctype`),
the `yield from` to a not-yet-registered generator apparently doesn't
contribute its real element type to the join, so the combined value type
collapses to the `int64_t` default instead of joining to `char *` (the
correct common type, since `_rlistdir` itself ultimately yields strings
too). The result: the coroutine promise's `yield_value` is generated
expecting `int64_t`, but the `yield pattern[:0]` call site still
produces a real `char *` — hence "assignment to int64_t from char*".

This is a variant of the already-documented "generator yielded-value
type inference" gap (`bugs/COMPILE_FAIL_ctypes_macholib_dyld.md`'s
bullet 1, and the untyped-generator-param cousin in
`CODEGEN_generator_struct_typed_param_refused`'s sibling
docs) — specifically the FORWARD-REFERENCE angle of it: a generator with
a `yield from` to a same-file sibling generator defined LATER, combined
with an earlier plain `yield` of a different concrete type, produces a
wrong combined promise type. Not folded into a new hard-bug doc here
(only one clean instance traced end-to-end so far) — flagged for whoever
next hits this shape to fold into a broader "generator yield-value type
inference" hard doc once 2-3 more instances are confirmed.

The two other current errors (`translate_584a43` arity mismatch,
`struct _subprocess_toplev` undefined) were not investigated — they look
unrelated to the generator-codegen cluster (arity/import-resolution
issues in non-generator code) and are left for a separate pass.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/glob.py
