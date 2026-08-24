# CODEGEN_generator_function: Lib/pickletools.py

## Status (updated 2026-08-24, worktree fix/gen-core — the 2026-08-23 "`_genops` now compiles" claim was stale; `_genops` refuses again, honestly, on a real remaining gap)

Re-verified from scratch (a real `python3 mojo.py build .../Lib/
pickletools.py`, and an isolated `compile_to_gimple_with_cpp(do_imports
=False)` matching the exact repro the entry below used). Both now
raise: `` cannot compile module: function(s) _genops (generator
function(s), contain a `yield`/`yield from`) ... Unsupported shape(s):
_genops: a call to unresolved callee 'getpos(...)' is not supported in
a compiled generator/coroutine body (not a builtin this emitter
supports, a known module-level/imported function, a same-module struct
constructor, or a declared callable-value local).`` — i.e. the exact
refusal the entry below says was closed.

This is not a regression of the tuple-yield fix; it's a LATER same-day
commit (`fd909e9`, "generators: refuse unresolved callees honestly")
converting what used to be a silent bare-identifier miscompile into an
honest `_UnsupportedGeneratorShape` refusal. Before `fd909e9`, `_cpp_
expr`'s CallExpr fallback emitted ANY unresolved callee as a bare `name
(...)` C++ call unconditionally — including `getpos()` after `pickletools.
py:2273`'s `getpos = data.tell` (a bound-method-VALUE assignment off a
PARAMETER of unknown/opaque type, not a known struct), which is invalid
C++ whenever `getpos`'s declared type isn't the coroutine model's one
callable-value category (`_CPP_CALLABLE_CTYPE`) — which it wasn't here,
since `_cpp_is_callable_value_expr` only recognizes a bound method off
`self` or an already-known STRUCT-typed local, not an opaque/unknown-
typed one like `data`. So the 2026-08-23 entry's "compiles clean"
verdict was checking only that the Python call didn't raise — it never
ran the emitted text through a real C++ compiler, and would have
produced silently-broken output had the whole-program build reached
codegen for this function before `fd909e9` landed same-day.

**Current, accurate state**: `_genops`'s `getpos = data.tell` /
`getpos = lambda: None` (branch-dependent bound-method-or-lambda local,
then called later as `getpos()`) is a genuine instance of this
codegen's already-documented "opaque callable value has no
representation" structural gap — the same family as `Lib/operator.py`'s
`attrgetter`/`itemgetter` blocker (`bugs/CODEGEN_generator_function_Lib_
tempfile.md`'s 2026-08-11 entry) and `Lib/codecs.py`'s kwargs-spread-
against-dynamic-callee blocker. Extending `_cpp_is_callable_value_expr`
to cover a bound method off an OPAQUE (not statically-known-struct)
receiver would need real runtime bound-method dispatch for arbitrary
values, not a narrow one-spot fix — not attempted here, consistent with
this cluster's established scoping for the sibling cases. Doc stays
open; every prior "generator-codegen gap closed" claim below this entry
about `_genops` specifically should be read as superseded by this one.

## Status (updated 2026-08-23, worktree branch fix/gen-lib-b — the last generator gap (varying-arity tuple yields) FIXED; `_genops` now compiles; file still blocked by transitive-only errors)

Stacked gap 3 from the 2026-08-11/08-20 entries below is now closed:
`_generator_tuple_yield_slot_ctypes` no longer refuses differing element
COUNTS across tuple-yield sites. It unifies to the LONGEST site's shape
(pad shorter sites' slot lists with the longer site's tail types,
first-contributing-site-wins per tail position), and the producer side
(`_cpp_yield_tuple`) boxes every site out to the unified arity using a
pre-body-emission slot pass stashed on the gen (`_cpp_pending_tuple_slots`,
set in `_gen_cpp_generator_unit` before body emission since the post-emission
slot computation runs too late to influence emission) — so every
`co_yield`'d list carries exactly the unified arity and consumer-side
per-slot accessor reads stay in bounds. `(True, None)` now means only an
irreconcilable per-slot TYPE disagreement. Commit f7cf084.

Verified against this file's real `_genops`: the 3-tuple site
(`yield opcode, arg, pos`) now boxes `[opcode, arg, pos, 0]` and the
gated 4-tuple site is unchanged; both eligibility passes unify to 4 slots.
Isolated `compile_to_gimple_with_cpp(do_imports=False)` on pickletools.py:
compiles clean, `_genops` emitted through the coroutine path (previously
the hard refusal). A real `python3 mojo.py build .../Lib/pickletools.py`
now shows **0 errors attributed to pickletools.py's own source** — the
build still exits non-zero solely on the already-documented transitive
cascade (`codecs.py`, `argparse.py`, `enum.py`; e.g. argparse's
`invalid operands to binary %` ×12 / `trunc_mod_expr` ×10 clusters).
Doc kept open per convention (file doesn't build end-to-end), but every
generator-codegen gap this doc was tracking is now closed.

Quality gate for the change: `test_gimple.py` 250/250, `test_module_cache.py`
76/76, `make check-selfhost` clean, from-scratch stdlib dylib rebuild
0 `skip <module>` lines (same as baseline).

## Status (updated 2026-08-20, two of three stacked gaps CLOSED — one remains)

`bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md` is now fixed
for the shape this file needs: `gimple_codegen.py` gained a real
callable-value declared-type category for the coroutine (`.cpp`)
codegen (`_CPP_CALLABLE_CTYPE = 'std::function<int64_t()>'`), a
`LambdaExpr` case in `_cpp_expr` that emits a native, capturing C++
lambda for a zero-argument lambda literal, and a bound-method-as-VALUE
case in the same `MemberExpr` handling (`self.<method>` and
`<struct-pointer local>.<method>`, not immediately called) that wraps
the method's already-known mangled C symbol in an equivalent capturing
lambda — both convertible to the one declared type, and callable at
the use site as a plain `name()` with no separate call-site change
needed (`std::function::operator()`). This closes stacked gaps 1 (the
opaque-callable-value category) and (most of) gap 2's mechanism from
the 2026-08-11 update below — re-verified directly against
`_genops`'s own two-line, two-branch shape.

Re-verified via `MOJO_DEBUG=1` + a direct `compile_to_gimple_with_cpp`
call against the real `Lib/pickletools.py`: the `LambdaExpr` refusal is
GONE. `_genops` now fails for a DIFFERENT, single remaining reason —
stacked gap 3 from the 2026-08-11 update, unchanged and NOT attempted
here (out of this task's scope):
```
[gimple_codegen] generator '_genops' not eligible for C++ coroutine
path, falling back to honest refusal: _genops: every `yield` must
carry a value, and all values must agree on one scalar type
(int64_t/double/_Bool)
```
`_genops` yields both a 3-tuple (`yield opcode, arg, pos`) and a
4-tuple (`yield opcode, arg, pos, getpos()`) at two call sites in the
same body — the tuple-valued/varying-arity-yield structural gap,
entirely independent of `LambdaExpr`/bound-methods. This file's `mojo.py
build` therefore still fails end-to-end; doc kept open (not deleted —
see `bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md`'s own
2026-08-20 update for why THAT doc's LambdaExpr-specific scope IS
closed even though this file as a whole is not yet unblocked).

## Status (updated 2026-08-11, real fix attempted — found genuinely stacked, not narrow)

Re-verified against current master via a real `python3 mojo.py build
/Users/mrs/net/Python-3.14.6/Lib/pickletools.py`: identical `_genops`/
`LambdaExpr` refusal reproduces exactly, unchanged from below.

This time actually attempted a real fix rather than re-confirming the
classification: traced what it would take to make `getpos = lambda:
None` compile (lift the lambda to a real non-capturing C++ function,
give `getpos` the existing "opaque callable pointer" `int64_t`
convention `_cpp_stmt`'s bare-call branch already uses via
`mojo_fnptr_call_N`, and add a matching VALUE-producing-call case to
`_cpp_expr`'s `CallExpr`/`IdentExpr` branch — that call form only
exists today in `_cpp_stmt`'s value-discarding bare-`ExprStmt` case,
around `gimple_codegen.py:24846`, not in `_cpp_expr` itself, so `pos =
getpos()` — a VALUE use — has no path to it either).

That alone would not unblock this file — `_genops` has (at least) two
further, independent stacked gaps in the exact same function body,
confirmed by reading both `gimple_codegen.py` and the real source
(`pickletools.py:2268-2298`):

1. The `if hasattr(data, "tell"): getpos = data.tell` branch (the
   sibling of the `lambda` branch, same `getpos` local) assigns a
   BOUND METHOD reference (`data.tell`, no call parens) as a value.
   `_cpp_expr`'s `MemberExpr` case (`gimple_codegen.py:23972-23982`)
   has no bound-method-value case at all — a non-self `MemberExpr`
   read falls through to the generic `f"{obj}.{member}"` fallback,
   which is invalid/wrong C++ here (`data` is a raw `int64_t`/`char *`
   in this scalar model, not a real object with a `.tell` member —
   `g++`: "member reference base type ... is not a structure or
   union"). Both `if`/`else` branches of the SAME statement are
   compiled unconditionally (this is straight-line C++, not templated
   per-branch), so fixing only the `lambda` side leaves this side
   broken.
2. `_genops` yields BOTH a 3-tuple (`yield opcode, arg, pos`) and a
   4-tuple (`yield opcode, arg, pos, getpos()`, gated by the
   `yield_end_pos` parameter) at two different call sites in the same
   function body. Confirmed directly against
   `_generator_tuple_yield_slot_ctypes` (`gimple_codegen.py:2689-2755`):
   its own docstring and `elif len(slots) != len(site): return True,
   None` make disagreeing ARITY across tuple-yield sites an
   unconditional refusal — "this generator's single promise type can
   only ever carry one fixed shape." This is a third, fully
   independent blocker from the other two.

Net: fixing the `LambdaExpr` gap alone provably would not unblock this
file — `_genops` has three independent, stacked structural gaps (an
opaque-callable-value type category for `_cpp_expr`, a bound-method-
value representation, and varying-arity tuple yields), each on its own
already the class of change this project's process reserves for a
dedicated, carefully-verified pass rather than a drive-by fix bundled
with two others at once. Not implemented — genuinely feature-sized,
confirmed (not assumed) via direct code tracing this session, matching
the existing `bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md`
classification. Doc kept open.

## Status (updated 2026-08-09, re-verified — unchanged)

Re-verified against current master (`c79a013`) via a real
`python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/pickletools.py`.
Identical refusal reproduces exactly:

```
[gimple_codegen] generator '_genops' not eligible for C++ coroutine
  path, falling back to honest refusal: unsupported expression in
  generator body: LambdaExpr
Error building: cannot compile module: function(s) _genops (generator
  function(s), contain a `yield`/`yield from`) — ...
```

Still exactly `_genops`'s `getpos = lambda: None` (pickletools.py:34
in this checkout — the `if hasattr(data, "tell"): ... else: getpos =
lambda: None` fallback). No new information; the 2026-08-07
classification below (`bugs/hard/CODEGEN_generator_lambda_expr_
unsupported.md`, feature-sized, needs a lifted-closure-style value
category for `LambdaExpr` in the coroutine body model) still stands.
Not re-attempted here.

## Status (updated 2026-08-07, classified — doc reference now exists)

**Classification: `bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md`**
— this file's `_genops`/`getpos = lambda: None` is that doc's own
first confirmed occurrence (written 2026-08-07). Investigated there and
assessed feature-sized (needs a new "callable-typed local variable"
value category in the coroutine body model — see that doc's "Why this
is feature-sized, not narrow" section); not re-attempted here, no new
information found that would change that assessment.

## Status (updated 2026-08-06, superseded above)

**STILL FAILING**, confirmed reproducing identically against current
master (`2b0c4c5`) — the 2026-07-30 note's diagnosis was correct; this
elaborates it.

```
$ MOJO_DEBUG=1 python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/pickletools.py
[gimple_codegen] generator '_genops' not eligible for C++ coroutine path, falling back to honest refusal: unsupported expression in generator body: LambdaExpr
Error building: cannot compile module: function(s) _genops (generator function(s), contain a `yield`/`yield from`) — ... falling back to interpreting this module from source instead
```

**Root cause:** `_genops`:
```python
def _genops(data, yield_end_pos=False):
    ...
    if hasattr(data, "tell"):
        getpos = data.tell
    else:
        getpos = lambda: None          # <-- the refused expression
    while True:
        pos = getpos()
        ...
        yield opcode, arg, pos
```
`getpos = lambda: None` assigns a `LambdaExpr` to a local inside the
generator's own body. The coroutine codegen's expression lowering
(`_cpp_expr`) has no case for `LambdaExpr` at all — every AST node shape
it doesn't recognize is refused via `_UnsupportedGeneratorShape` at that
statement, and (same escalation as the struct-typed-param and dynamic-
`raise` gaps found elsewhere in this cluster) refusing a MODULE-LEVEL
generator like this one hard-fails the entire file's `mojo.py build`.

**New, narrow gap — not yet folded into a hard-bug doc** (only one
instance seen in this cluster so far). A `lambda` literal used as a
plain callable value (assigned to a local, later called with `()`) is a
common enough Python idiom that this is likely to recur; if a second/
third instance turns up elsewhere in this cluster, fold into a new
`bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md` — the likely
minimal fix shape (worth noting for whoever picks it up) mirrors how
this codegen already handles ordinary (non-generator) closures elsewhere
via `_gen_lifted_closure`: lower the lambda to a lifted, non-capturing-
or-capturing helper function the SAME way, then have `_cpp_expr`'s
`LambdaExpr` case just reference that lifted function's pointer, rather
than inventing new lambda-specific C++ codegen inside the coroutine path.

Not fixed here — narrow-looking but touches expression-lowering inside
the coroutine `.cpp` emission path, which this task's guidance flags as
warranting its own dedicated verification pass rather than a drive-by
change during cluster classification.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/pickletools.py
