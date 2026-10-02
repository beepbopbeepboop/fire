# HARD BUG: some `lambda` shapes unsupported inside a compiled generator body

**State: PARTIAL.** The variadic SIGSEGV is FIXED, and so are the two shapes this
doc's 2026-09-26 entry called "the definition side is done; the call side is
the whole of what remains" — a variadic lambda now works through EVERY way of
holding the value, and the doc's second named target
(`sorted(key=lambda ...)` with a struct pointer) is already correct on the
current tree and did not need anything. What remains is listed precisely at the
end of the section below: three defects, none of them a variadic one, each
filed with its own doc.

## Status (2026-09-29 — the variadic SIGSEGV is FIXED; the doc's two named targets re-tested; what is left is three OTHER bugs)

### Re-tested first, because the doc is not evidence

Every claim above was re-run against the current tree with CPython alongside.
The variadic SIGSEGV reproduced exactly as documented, for every shape,
including the one the doc says proves the defect is not about captures (a
variadic lambda capturing nothing crashed identically):

| program | CPython | compiled, before | compiled, now |
|---|---|---|---|
| `e = lambda *a: add(a[0], a[1]); e(4, 5)` | `9` | **SIGSEGV** | `9` |
| `e = lambda *a: addall(a); e(1, 2, 3)` | `6` | **SIGSEGV** | `6` |
| `e = lambda *args, **kwargs: add(n, args[0])` (captures `n`) | `8` | **SIGSEGV** | `8` |

22 of a 25-shape matrix now compiles, links, runs and agrees with CPython.

### What the mechanism turned out to be

The doc's diagnosis was right in every particular: the lifted DEFINITION was
correct (`int64_t f (MojoList * a)`), the call site chose its runtime helper by
the number of arguments written at the call and passed them **positionally as
scalars**, and the callee dereferenced address 4. The doc then concluded that
fixing it needed a "signature-carrying callable-value representation with
runtime args/kwargs packing", and called that feature-sized.

It is not feature-sized, and the reason is that this repository **already had
exactly that mechanism, one file over**: `MojoBoundMethod` is a heap value that
carries `(fn, self)`, a runtime registry tells a callable value apart from a
bare function pointer, and `mojo_fnptr_call_N` dispatches on it — precisely so
that a closing lambda works everywhere an ordinary one does, "including as a
map/filter/sorted key, a call straight through `_funcptr_*`, and a lambda handed
to code this compiler never saw". A variadic callable needs the same thing
with packing instead of a leading `self`.

So the fix is that mechanism, reused rather than reinvented:

- **`MojoVarargFn`** (`runtime/fire_runtime.h`, "Variadic callables") records
  the lifted callee, the closure env, how many ordinary leading parameters
  precede the `*args`, which of the three shapes the lambda has (`*args` /
  `*args, **kwargs` / `**kwargs`), and whether the callee declares that
  leading `self` at all. A new `_reg_vararg_fn` registry lets
  `mojo_fnptr_call_N` and `mojo_maybe_bound_call_N` recognise it, exactly as
  they already recognise a bound method.
- **`_lower_LambdaExpr`** materializes such a lambda as a `MojoVarargFn` rather
  than a bare `_funcptr_*` static.
- **The packing happens in the runtime**, because that is the only place that
  knows both the call's arity and the callee's real parameter list. This is
  why one change fixed every call site at once — direct, escaped as an
  argument, returned, stored in a dict, stored in a struct field, rebound
  across branches, and used as a `sorted(key=)` / `map` / `filter` callable.
  `Lib/doctest.py`'s `_colorize.can_colorize = lambda *args, **kwargs: False`
  (an ATTRIBUTE, which the doc correctly called out) is now covered.
- **Keyword arguments** reach the callee through new `_kw_` twins of both
  dispatch families, emitted only when the call site actually writes some. For
  every other kind of callee they behave identically to the helpers they twin,
  so nothing else changed. A `**kwargs` callee is never handed NULL: `k['x']`
  is an ordinary spelling and would segfault.

Two supporting fixes, both load-bearing:

- the **forward declaration** built for a lambda dropped its `*`-prefixed
  parameters, so `lambda f, *a: ...` forward-declared `int64_t f(int64_t)`
  against a definition of `int64_t f(int64_t, MojoList *)` — a hard
  "conflicting types" error. The fixed-prefix variadic shape did not compile at
  all before this;
- the dispatch helpers **stopped at four arguments** and silently dropped the
  rest, which for a `*args` callee means losing elements. They now go to
  eight. The truncation was a silent wrong value for every
  five-or-more-argument indirect call, not only this one.

`lambda a, b, c, d, e, *rest: ...` — five ordinary parameters ahead of a
`*args` — is now **refused** rather than mis-called: the runtime passes at most
four leading scalars through un-packed, so five would be a wrong value, and the
backend's `RuntimeError` makes the module fall back to interpreting from
source, which is right. Four is far past anything real code writes.

### The doc's SECOND named target was already fixed

`sorted(key=lambda m: m.<field>)` where the element is a struct POINTER — the
doc's narrower sub-gap, blamed on `_field_elem_types` being populated after
generator bodies compile — **works on the current tree**, and did before this
session. Verified in all four combinations, each matching CPython: a plain
function, a generator, a `self.<field>` list, and a list passed as a
parameter. The generated C declares the key lambda as
`int64_t f (M * m)` — the struct pointer really is threaded into the parameter
type — and the A3 stack-switch cutover has routed generator bodies through the
gimple path, where that inference works. The doc's 2026-08-23 entry said the
same thing about a subset of these and was not believed; it is now measured
rather than argued.

### What is left, precisely — none of it a variadic defect

| shape | CPython | compiled | doc |
|---|---|---|---|
| `_colorize.can_colorize = lambda *args, **kwargs: False` | `False` | `0` | `bugs/CODEGEN_lambda_bool_return_prints_as_int.md` — a lambda whose body is a bool returns `int64_t` 0/1. Nothing to do with the call convention; an ordinary `def` returning the same value is right. |
| a lambda inside a **nested `def`** | correct | link error, body never emitted | `bugs/CODEGEN_lambda_in_nested_def_body_never_emitted.md` — the lifted function is declared and referenced, never defined. |
| `sorted(key=<any user function>)` | correct | interpreter crash | `bugs/CODEGEN_interpreter_user_function_as_builtin_callback_crashes.md` — so the compiled path cannot be diffed against the interpreter for that shape. |

Two more were found and filed while measuring, and are also not this doc's:
`bugs/CODEGEN_call_through_subscript_callee_stubbed.md` (a callable reached
through a subscript, `d['k'](2, 3)`, prints `0`) and
`bugs/CODEGEN_lambda_bool_return_prints_as_int.md`'s sibling, a named function
with `*args` taken as a value — which WAS this defect and IS fixed, see
`gimple_variadic_named_function_through_a_value`.

### Still deliberately excluded

A capturing or variadic lambda inside a **coroutine/generator body** remains
refused by `_lambdas_ok`, and that refusal is honest: the whole module falls
back to interpreting from source, so the answer is right. Verified with
`fire.py run` (correct) and `fire.py --jit` (refuses, falls back, correct).

## Status (2026-09-26 re-verification — the escape/rebound residue is FIXED; the variadic residue is a SEGFAULT, re-scoped with a precise mechanism)

Both halves of what the 2026-09-26 entry below named as "still open" were
re-tested against the current tree, and one of them is closed.

### CLOSED: a capturing lambda that ESCAPES or is REBOUND no longer loses its capture

The 2026-09-26 entry recorded this as open residue, on the reasoning that it
"needs the env-struct / callable-value representation that nested `def`
closures already use". **That machinery has since landed** for the LIFTED path:
`_lower_LambdaExpr` (`mojo/backend_gimple/emit_calls.py`) now computes a real
capture set from the lambda body's free names, gives the lifted function a
`_env` struct as its first parameter, and materializes the value at the
reference site as `mojo_bound_method_new(fn, env)` — a `MojoBoundMethod`, the
same "self, then N ordinary args" shape every compiled struct method already
uses, so `mojo_fnptr_call_N` dispatches through it unchanged. The env struct is
built from the `_env-><name>` reads scanned out of the EMITTED body, not from
the pre-computed capture list, which is what keeps struct and body in
agreement.

So the escape analysis in `mojo/middle/lambdareduce.py` is now only choosing
between two correct lowerings (inline at the call site, or lifted-with-env),
not deciding correctness at all.

Measured, all compiling, linking and running:

| shape | before | now | CPython |
|---|---|---|---|
| `apply(e, 1)` — passed as an argument (escapes) | `1` | `8` | `8` |
| rebound on a second assignment, then called | `1` | `108` | `108` |

The first row is `gimple_escaping_capturing_lambda_still_lifted` in
`test_gimple_runner.py`, which pinned the WRONG answer (`"1\n"`) on purpose so
this fix would flip it loudly rather than silently. It did — and because
`test_gimple_runner.py` is in no `tools/suite.py` bucket, nothing noticed, so
the expectation was still stale. Corrected to `"8\n"` on 2026-09-26; the file
is 120/120.

### STILL OPEN, and re-scoped: a variadic lambda SEGFAULTS at the call site

The doc recorded this as "still lifted, still loses its captures, and still
returns a wrong value". **The value is right; the call convention is broken, and
it crashes.** Re-measured, 2026-09-26, with `/tmp`-resident files:

| program | CPython | compiled |
|---|---|---|
| `e = lambda *a: add(a[0], a[1]); e(4, 5)` | `9` | **SIGSEGV (139)** |
| `e = lambda *a: addall(a); e(1, 2, 3)` | `6` | **SIGSEGV (139)** |
| `e = lambda *args, **kwargs: add(n, args[0]); e(1)` (captures `n`) | `8` | **SIGSEGV (139)** |

Note the third row: it is not about CAPTURES at all. A variadic lambda with no
capture crashes identically, so this is a separate axis from the capture work
above and would have survived a capture-only fix.

The mechanism, from the emitted C. The lifted DEFINITION is correct — the
varargs are packed into a `MojoList *`, exactly as the code's own comment says
they should be (`mojo/backend_gimple/emit_loops.py`, `_gen_lifted_closure`:
`*args -> one MojoList* param; callers pack the loose args into it`):

```c
int64_t main_lambda_1 (MojoList * a) {
  _t2 = mojo_list_get_int (a, 0);
  _t4 = mojo_list_get_int (a, 1);
  return add_2dbb98 (_t2, _t4);
}
```

The lifted CALL SITE is not. It chooses the runtime helper by the number of
arguments written at the call, and passes them **positionally as scalars** —
they are never packed into the `MojoList *` the callee expects:

```c
_t2 = (int64_t)4;
_t3 = (int64_t)5;
_t4 = mojo_fnptr_call_2 (e, _t2, _t3);   /* callee wants mojo_fnptr_call_1(e, <MojoList*>) */
```

So the callee receives `a = 4`, reads address 4 as a `MojoList *`, and
dereferences it. `mojo_fnptr_call_N` is arity-based, and nothing at the call
site knows the callee's real signature — which is exactly the
"signature-carrying callable-value representation with runtime args/kwargs
packing and named-slot call-site binding" this doc has twice called
feature-sized. The definition side is done; the call side is the whole of what
remains.

Real-corpus occurrences, grepped against the CPython tree at
`/Users/mrs/net/Python-3.14.6` (2026-09-26) — three, not the one this doc
names:

- `Tools/c-analyzer/c_common/fsutil.py:285` — `get_files = (lambda *a, **k: _walk(*a, walk=_files, **k))`, the occurrence this doc has always named. Unreachable today: `fsutil.py` is refused for unrelated reasons (`COMPILE_FAIL_Tools_c-analyzer_c_common_fsutil.md`).
- `Lib/importlib/util.py:247` — LazyLoader's `return lambda *args, **kwargs: cls(loader(*args, **kwargs))`. Returned, so it also escapes.
- `Lib/doctest.py:1566` — `_colorize.can_colorize = lambda *args, **kwargs: False`. Note this one is assigned to an **attribute**, not a local, and its body ignores the arguments entirely — so the value is right and only the (crashing) call convention is wrong. Any fix must therefore also handle a variadic lambda held in a field, not just in a local.

**Not attempted.** The fix is new call-site lowering in shared
call-argument machinery, keyed on a signature, which is the class of change
CLAUDE.md's own history (the "_tuplegetter incidents", the recorded
`gimple_codegen`/interpreter divergence) warns causes broad regressions when
attempted narrowly — and it could not be shown to break nothing without the
full `make gate`, whose `native`/`bootstrap` half is exclusive. A partial fix
here is worse than none: it would turn a loud SIGSEGV into a silent wrong
value. The precedent for the packing convention already exists at
`mojo/backend_gimple/emit_calls.py` (`_vararg_trailing_param_types`, the
`mojo_list_new` + `mojo_list_append_int` sequence), for a *named* function
with a C varargs tail; a lambda's `*a` is the same packing with no
`_vararg_trailing_param_types` entry to key off, which is precisely the
missing piece.

## Status (2026-09-26 — CAPTURING lambdas called through their local now WORK; `*a, **k` still open, with the root cause re-scoped)

The doc's framing was "the parameterized-lambda gap": a `lambda` with
`*args`/`**kwargs` is refused. Chasing that turned up something bigger and
more general underneath it, so this entry is reorganised around what was
actually found.

### The real defect: ANY lambda that captures an enclosing local silently returned 0

A `lambda` lifts to a top-level C function taking only its own declared
parameters — a plain function pointer, with nowhere to put the enclosing
function's locals. A nested `def` closure does not have this problem
because it goes through the env-struct mechanism
(`mojo/middle/closures.py`), which **lambdas never participated in**. So a
lambda reading an enclosing local compiled to a body naming a variable
that does not exist there, and each read stubbed to 0:

```python
var n = 7
var f = lambda: n
print(f())          # printed 0 — silently, exit 0
```

Not the variadic shape, and not specific to generators: every capturing
lambda in the compiled path. `_lower_LambdaExpr`'s `captures` list only
ever picked up the `lambda e, self=self` default-BINDING idiom, never a
body that simply reads a local.

### Landed: inline reduction for the dominant shape

New `mojo/middle/lambdareduce.py` decides, per enclosing function, which
locals hold a lambda that (a) captures something, (b) declares no
`*args`/`**kwargs`, and (c) never escapes — assigned once, never rebound,
and every other occurrence of the name is the callee of a call. Those
lambdas are NOT lifted; their body is lowered at the call site, in the
enclosing scope, where every captured name already resolves. No function
pointer, no env struct, no capture plumbing.

Verified by real compile+link+run: `lambda: n` → 7 (was 0),
`lambda: len(xs)` → 3 (was 0), `lambda x: n + x` → 8 (was 1). Regression
test `gimple_capturing_lambda_inlined_at_call`.

`*args`/`**kwargs` is deliberately EXCLUDED from the reduction: those need
the extra positionals packed into a `MojoList *` and the keywords into a
`MojoDict *` at every call site, and the lifted path already does exactly
that (see `_lower_LambdaExpr`'s `pname.startswith('**')` branches).
Re-implementing the packing in the inliner would be a second,
independently-maintained copy of one convention — worse than leaving the
shape as it is.

### Still open, with the corpus instances named

A capturing lambda that ESCAPES (passed as an argument, returned, stored),
is REBOUND, or declares `*args`/`**kwargs` is still lifted, still loses
its captures, and still returns a wrong value. Measured occurrences of the
escaping/rebound form in real stdlib: `importlib/util.py` 8 sites
(including the `lambda *args, **kwargs: cls(loader(*args, **kwargs))`
LazyLoader factory this doc has always named), `functools.py` 4,
`enum.py` 3. Pinned by `gimple_escaping_capturing_lambda_still_lifted`,
which asserts the current (wrong) value on purpose so a fix flips it
deliberately rather than silently.

The right fix is to put lambdas on the env-struct path nested `def`
closures already use — the machinery is proven (a nested `def` capturing a
local returns 7 today) and `discover_closures` already computes `free`
variables and builds an env struct; lambdas are simply not discovered,
because they are expressions rather than statements. That is a real piece
of work, not a widening of this one.

### A refusal that was written and then deliberately removed

Worth recording, because it is the third time this pattern came up and the
blast radius was different each time. Non-reducible capturing lambdas were
at first made an outright `RuntimeError`, matching what the generator and
nested-async paths do for shapes they cannot represent. It fires on
`functools.py` — a core module. Trading "compiles, with a wrong value
inside" for "this module stops compiling", on the strength of a false
positive in a same-day static escape analysis, is not a good trade, so the
refusal was reverted and the unconditional win kept instead. The escape
analysis is sound as far as it is exercised (the escaping case does NOT
get inlined), but "sound" is not the same as "safe to fail a build on".

## Status (2026-09-25 — `pickletools._genops` lambda occurrence confirmed superseded on A3)

The A3 mixed-arity tuple-yield work now makes real `Lib/pickletools.py`
`_genops` eligible and lowering-capable; its `getpos = data.tell` /
`getpos = lambda: None` callable-local pattern is no longer the active
blocker. The module now compiles and links, and its runtime failure has moved
past lambda/callable lowering to imported module-global and file-object
runtime support. The legacy C++ coroutine-path lambda gaps below remain
scoped to that backend; occurrence #1 is resolved on the default A3 path.

## Status (2026-09-05, A3 stack-switch cutover — mostly RESOLVED, one narrow shape left)

The §5.5 A3 stack-switch cutover (doc/COROUTINE.html) changed the whole
picture: a generator body now desugars to an ordinary function that goes
through the normal `gimple_gen_*.py` codegen path, and that path lifts a
`lambda` to a top-level C function (`_lower_LambdaExpr`). So the shapes
the old `gimple_cpp_core.py` emitter could not represent now just work:

- zero-argument lambda called through a local (`getpos = lambda: 0; ...
  getpos()`) — **works** (occurrence #1, `Lib/pickletools.py`'s
  `_genops`, no longer hits any lambda refusal).
- one- and two-parameter lambda (`lambda m: m+1`, `lambda a, b: a+b`) —
  **works**.
- a lambda re-bound on each branch of an `if`/`else`, then called —
  **works**.
- a lambda passed directly as a call argument — **works**.

Regression tests for all of the above:
`generator_zero_arg_lambda_called`, `generator_one_arg_lambda_over_list`,
`generator_two_arg_lambda_and_lambda_as_arg`,
`generator_lambda_rebound_per_branch` in
`test_gimple_generator_runner.py`.

**Still open — occurrence #2 only** (`Tools/c-analyzer/c_common/
fsutil.py`'s `iter_files`): `get_files = lambda *a, **k: _walk(*a,
walk=_files, **k)` — a `*args`/`**kwargs`-forwarding lambda. The
ordinary codegen path miscompiles this shape (broken forward
declaration), and a `lambda` with a *default* parameter silently reads
garbage for the defaulted slot. Both are now caught by a new
eligibility guard in `gimple_gen_coro.py` (`_lambdas_ok`): a generator
whose body contains a `lambda` with a starred or defaulted parameter is
refused, falling through to the cpp path's own honest refusal instead
of emitting broken/wrong C. Closing occurrence #2 for real needs the
separate variadic-forwarding work tracked in
`bugs/hard/CODEGEN_args_kwargs_signature_assumed_forwarding_only.md` —
and, per the 2026-08-24 note below, `iter_files` has five further
independently-refused generators regardless, so this alone would not
unblock that file.

Two other lambda-adjacent gaps found in the same pass are codegen-wide
(reproduce in a plain non-generator function), so they are NOT this
doc's scope: a `lambda` with a default parameter (garbage for the
default), and `sorted(iterable, key=lambda ...)` silently ignoring
`key=`. A bound-method value stored in a local then called
(`getpos = self.tell; getpos()`) is likewise codegen-wide — tracked in
`bugs/hard/CODEGEN_coro_stackswitch_body_semantics_gaps.md` #3.

## Status (re-verified 2026-08-26, independent check against current master `e60b9cd` — unchanged)

Direct source re-check of `gimple_cpp_core.py`'s `LambdaExpr` case
(now at ~line 1454-1533 after the codegen-backend file split) against
current master `e60b9cd`: the guard is byte-for-byte the same as the
entry immediately below describes — `_CPP_CALLABLE_CTYPE` (0-arg) and
`_CPP_CALLABLE_CTYPE_1ARG` (1 plain param) are still the only two
supported shapes, `len(e.params) > 1 or (e.params and (starts-with-*
or has-default))` still refuses everything wider honestly. No shared
fix from any of the 122 commits landed since the `a913ab8` branch
point touches callable-value representation. Per this task's explicit
instruction (treat hard-bug docs to a genuinely fresh look, given how
much shared machinery has landed): confirmed this remains a real,
deliberate design-level gap — a general parameterized/variadic
callable-value representation (signature-carrying, runtime args/kwargs
packing, named-slot call-site binding) is feature-sized work touching
shared call-argument/lowering machinery this project's history
(CLAUDE.md's own "_tuplegetter incidents") explicitly warns against
attempting narrowly. Not attempted. No code change.

## Status (re-verified 2026-08-26, branch fix/rest-remainder15 — unchanged)

Direct source re-check of `gimple_cpp_core.py`'s `LambdaExpr` case
(~line 1334-1412) against current tree (`a913ab8`): still exactly two
declared-type categories, `_CPP_CALLABLE_CTYPE` (0-arg) and
`_CPP_CALLABLE_CTYPE_1ARG` (1 plain param) — the same
`len(e.params) > 1 or (e.params and (starts-with-* or has-default))`
guard from the 2026-08-21 entry still refuses any wider shape
honestly. No shared fix from this campaign's other recent landings
(generator-consumption fixed-point retry, defaults-aware arg padding,
int()/float() coroutine builtins, map()/getattr investigation for
pkgutil) touches callable-value representation at all. Occurrence #2
(fsutil.py's `lambda *a, **k`) remains open for the same reasons the
2026-08-24 entry gives (feature-sized, needs a real variadic
args/kwargs-forwarding callable-value representation this project's
history warns against attempting narrowly), and remains insufficient
on its own even if fixed (fsutil.py has 5 further independently-refused
generators — see that file's own doc). Not attempted. No code change.

## Status (updated 2026-08-24, occurrence #2 investigated deeper — still open, now with evidence it is ALSO insufficient on its own)

Session task attempted to extend this file's mechanism to fsutil.py's
`lambda *a, **k: _walk(*a, walk=_files, **k)` shape. Not implemented;
investigation (full details in
`COMPILE_FAIL_Tools_c-analyzer_c_common_fsutil.md`'s 2026-08-24 entry)
established two NEW facts beyond the prior assessments:

1. The parameterized-lambda gap is not merely still open for occurrence
   #2 — closing it could not unblock that generator even in principle:
   `iter_files`'s own body contains further independently-refused shapes
   downstream of the lambda assignment (calling a function-valued local,
   with or without kwargs; iterating the call result held in a local),
   and the module hard-fails on five OTHER generators regardless.
2. No narrow specialization of the forwarding lambda is available for
   THIS occurrence: `get_files` is polymorphically assigned across
   branches (incoming keyword-only param default `os.walk` / caller
   callable / `_glob` / the lambda), defeating any closed-world "this
   local is exactly this lambda" rewrite; a general mechanism needs a
   signature-carrying callable-value representation plus runtime
   args/kwargs packing and named-slot call-site binding (`std::function`
   cannot hold variadic signatures at all) — shared call-argument/lowering
   machinery this project's history warns against touching narrowly.

Also discovered while probing: a local-held generator call result
iterated by a `for` loop escapes the eligibility pre-check and emits
invalid C++ (void-value g++ error) instead of an honest refusal — see
the fsutil doc's 2026-08-24 entry, item 4. Doc stays open, unchanged
scope: 0-/1-plain-param shapes supported, `*args`/`**kwargs` forwarding
still refused honestly.

## Status (re-verified 2026-08-23 — no new work)

Re-ran `test_gimple_generator_runner.py`: **42/42 pass**, confirming both
landed phases (zero-arg lambda / bound-method-value; single-param lambda +
`sorted(..., key=...)` + the segfault fix) still hold after the Wave-2
file refactor (`_CPP_CALLABLE_CTYPE`/`_CPP_CALLABLE_CTYPE_1ARG` now
exported via gimple_cpp_core/gimple_codegen re-exports). Both open items
remain open, unchanged: occurrence #2 (fsutil.py's `lambda *a, **k`) is
gated behind the separately-tracked args/kwargs-forwarding gap, and the
struct-pointer-key-field sub-gap below still needs the `_field_elem_types`
pass-ordering change to `gen_module` — reconfirmed there is still NO
confirmed real-corpus occurrence requiring it, and its failure mode stays
a loud g++ error (safe degradation), so the risk/benefit of a shared
pass-ordering change remains unfavorable. Not attempted this session.

## Status (updated 2026-08-21 — single-parameter lambda / `sorted(..., key=...)` FIXED; found+fixed a real SEGFAULT along the way; one narrower sub-gap still open)

Extended the 2026-08-20 zero-argument-lambda mechanism (below) to a
SINGLE plain parameter (`_CPP_CALLABLE_CTYPE_1ARG =
'std::function<int64_t(int64_t)>'`, a sibling constant kept separate
per that constant's own docstring — the two categories have genuinely
different consumer shapes, not just different arities), and implemented
real `sorted(iterable, key=..., reverse=...)` support in the coroutine
body emitter (`_cpp_expr`'s new CallExpr/`'sorted'` case) — previously
totally unhandled there (fell through to the generic bare-name-call
fallback, which drops `key=`/`reverse=` kwargs entirely and emits a
literal undeclared C++ `sorted(...)` call). Motivated by `Lib/enum.py`'s
`Flag._iter_member_by_def_`: `yield from sorted(cls._iter_member_by_
value_(value), key=lambda m: m._sort_order_)`.

`_cpp_expr`'s `LambdaExpr` case now accepts a lambda with 0 params
(unchanged) or exactly 1 plain param (no `*`/`**`, no default) — wider
shapes (2+ params, `*a`/`**k` forwarding, defaults) still refused
honestly, same as before.

**A real, confirmed SEGFAULT was found and fixed in the same pass** (not
present in the original zero-arg-only work — this is new, specific to
the `yield from sorted(...)` consumption path): `_yield_from_delegate_
ctype` (the promise/yield-type inferencer) had no `sorted(...)` case, so
`yield from sorted(...)`'s contributed type fell to the generic "unknown
collection -> char*" default — but the sort codegen ALWAYS stores its
result via `mojo_list_append_int` (an int64_t payload, matching this
codegen's existing "box a struct pointer as int64_t, cast on read"
convention used everywhere else), never as strings. `_cpp_yield_from`'s
matching generic "plain collection" consumer fallback then read every
element back via `mojo_list_get_str` — dereferencing an int64_t bit
pattern as a `char *`. Confirmed via a real end-to-end compile+link+run
repro (`generator_sorted_key_lambda_scalar` in
`test_gimple_generator_runner.py`): **segfaults (SIGSEGV) on unfixed
code**, runs correctly and prints the correct descending-sorted output
on fixed code. Fixed with matching cases in both `_yield_from_delegate_
ctype` (recurses into the inner iterable's own type, defaulting to
int64_t rather than char* when undetermined — since int64_t is what
this list is actually storing either way) and `_cpp_yield_from` (a
dedicated `sorted(...)` drive loop reading via `mojo_list_get_int`,
mirroring the existing `range(...)` case's own pattern, instead of
falling into the generic char*-assuming fallback).

**Verification**: `generator_sorted_key_lambda_scalar` (new,
`test_gimple_generator_runner.py`) — a plain `yield from sorted(xs,
key=lambda m: -m)` — compiles, links, RUNS, and produces the correct
descending order; all 41 pre-existing generator-runner tests
(zero-arg-lambda, bound-method-value, struct-ptr-yield, cls-redirect,
etc.) still pass unchanged (42/42 total). Real corpus: `Lib/enum.py`'s
`Flag._iter_member_by_value_`/`_iter_member_by_def_` remain refused —
but CONFIRMED (via `MOJO_DEBUG=1`) this is exclusively the SEPARATE,
already-documented `cls`-attribute-redirect eligibility gate
(`_flag_mask_`/`_value2member_map_` are set via `EnumMeta`'s dynamic
metaclass machinery, never as literal class-body assignments — see this
file's own 2026-08-21 companion note in
`bugs/CODEGEN_generator_function_Lib_enum.md`) firing BEFORE the
generator body is ever lowered far enough to reach the lambda/sorted
machinery this fix adds — so enum.py's own build status is genuinely
unaffected by this fix either way, confirmed, not assumed. A corpus
sweep (`grep -rl "sorted(.*key=" Lib/*.py`) found `_strptime.py`,
`pprint.py`, `pyclbr.py`, `tarfile.py` all still compile clean
(unaffected — none of their `sorted(..., key=...)` call sites are
inside a compiled generator body); `heapq.py`'s `merge` generator is
refused for a separate, unrelated reason.

**Still open** — a narrower sub-gap found while implementing this: when
the sort's `key=` lambda parameter's real element type is a struct
pointer (e.g. `self.<field>: list[Struct]`, so `m.<field>` inside the
lambda body needs `m` typed as the real struct pointer, not int64_t),
the hint mechanism added to thread that type through
(`self._cpp_pending_lambda_param_ctype`) currently never fires in
practice: it depends on `self._field_elem_types[struct_name]` being
populated by the time a generator METHOD's body is compiled, but that
registry is actually populated by a LATER pass (confirmed by direct
inspection — the same lookup after the whole module finishes compiling
has the right answer, but returns nothing at generator-body-codegen
time). This is a SAFE degradation, not a silent miscompile: the lambda
parameter falls back to plain int64_t, and a body that then tries
`m.<field>` fails loudly with a real g++ "request for member in
non-class type" compile error, consistent with this codegen's
"refuse rather than guess" convention — not the segfault class of bug
above (which affected EVERY `sorted()+key=` generator regardless of
element type and is now fully fixed). Fixing this properly needs
`_field_elem_types` populated before generator-method bodies compile —
a pass-ordering change to `gen_module`, out of scope for this pass. No
confirmed real-corpus occurrence of this narrower shape exists today
(enum.py's own real target doesn't reach it either, per above) — flagged
for whoever next revisits this file's pass ordering, not urgent.

Doc kept open — the LambdaExpr/`sorted(key=...)` mechanism itself is now
complete for 0- and 1-plain-parameter shapes (matching every confirmed
real-corpus need found so far), but occurrence #2 (fsutil.py's `lambda
*a, **k`, below) and the struct-pointer-key-field sub-gap just above
both remain open.

## Status (updated 2026-08-20, FIXED for zero-argument lambdas / bound-method values — one shape still open)

Implemented this doc's own minimal design (the "(1)(2)(3)" list at the
bottom): `gimple_codegen.py` gained

1. A new declared-type category for a callable value inside the
   coroutine (`.cpp`) codegen: `_CPP_CALLABLE_CTYPE = 'std::function<
   int64_t()>'` — a real, nameable C++ type (unlike a raw lambda's
   anonymous closure type), fixed to a zero-argument, int64_t-returning
   signature since neither confirmed occurrence ever needs more (see
   that constant's own docstring for the full rationale, including why
   `std::function` was chosen over the ordinary GIMPLE path's
   `MojoBoundMethod *` bound-method representation).
2. `_cpp_expr`'s new `LambdaExpr` case: a zero-argument `lambda` literal
   lowers to a native, CAPTURING C++ lambda (`[&]() -> int64_t { return
   ...; }`, `[&]` since every local in this coroutine model lives in the
   coroutine's own heap-allocated frame, not an ordinary stack frame —
   safe for as long as the callable value itself is held), implicitly
   convertible to `_CPP_CALLABLE_CTYPE`. A lambda WITH parameters is
   refused honestly (not attempted — see "still open" below).
3. Call-site dispatch needed NO new code: a declared local of type
   `_CPP_CALLABLE_CTYPE` already falls through to `_cpp_expr`'s existing
   bare-name `CallExpr` fallback (`name(args)`), and `std::function`
   supports `operator()` natively. The one real fix needed alongside
   this was in `_infer_simple_expr_ctype`'s CallExpr/IdentExpr branch,
   which conflated "a callable local's own storage type" with "that
   call's RESULT type" (previously harmless, since both happened to be
   `int64_t` for the one pre-existing callable-local idiom it handled) —
   now special-cased so a call through a `_CPP_CALLABLE_CTYPE` local
   always infers `int64_t`, not the callable's own storage type.
4. A bound-method-as-VALUE read (`self.<method>` / `<struct-pointer
   local>.<method>`, NOT immediately called) added to `_cpp_expr`'s
   `MemberExpr` handling: bridges into the coroutine model's EXISTING
   struct-method-call machinery (the method's already-known mangled C
   symbol, via `_struct_method_csym` — the same one `self.method(...)`/
   `<struct-pointer local>.method(...)` CALL sites already use), wrapped
   in a capturing C++ lambda convertible to the same declared type,
   rather than inventing a second runtime representation. Required a
   new `self._struct_method_names: dict[str, set[str]]` (struct name ->
   real method names, straight from each struct's own AST, populated
   alongside the existing `_struct_has_init` pass) as the authoritative
   "is this member a method" signal — `struct_field_types` alone can't
   be trusted for that question, because this file's OWN dynamic-
   attribute pre-pass (`_scan_body_for_local_field_access`) synthesizes
   a phantom `'int'`-typed FIELD entry for any `<known-struct local>.
   <unrecognized member>` read found anywhere in the module, which
   would otherwise misclassify a real bound-method-as-value read (e.g.
   `getpos = self.tell`) as a field access.

Verified: two new real end-to-end compile+link+RUN repros in
`test_gimple_generator_runner.py` (`generator_lambda_and_self_bound_
method_as_value`, `generator_lambda_and_param_bound_method_as_value`),
both mirroring `_genops`'s exact two-branch/same-local shape (a
zero-arg lambda on one branch, a bound-method value on the other,
called via `getpos()`) — one with the bound method read off `self`
inside a generator METHOD, one off a struct-pointer generator
PARAMETER. Both pass. `python3 test_gimple.py` (248/248),
`python3 test_module_cache.py` (76/76), and `make check-selfhost` all
stay green; a from-scratch stdlib dylib rebuild shows 0 skips before
and after (unchanged, already clean).

Confirmed real occurrence #1 (`Lib/pickletools.py`'s `_genops`) no
longer hits ANY `LambdaExpr`/bound-method refusal — `MOJO_DEBUG=1` +
`compile_to_gimple_with_cpp` against the real file shows the
`LambdaExpr` refusal is gone; `_genops` now fails for a completely
different, independent reason (a tuple-valued `yield`, tracked
separately — see `bugs/CODEGEN_generator_function_Lib_pickletools.md`'s
own 2026-08-20 update). This doc's OWN scope (the `LambdaExpr` gap
itself) is fully closed for occurrence #1.

**Still open** — NOT closed for confirmed occurrence #2
(`Tools/c-analyzer/c_common/fsutil.py`'s `iter_files`):
```python
get_files = (lambda *a, **k: _walk(*a, walk=_files, **k))
```
is a lambda WITH parameters (`*a, **k`), which this fix's `_CPP_
CALLABLE_CTYPE` category deliberately does not attempt (fixed 0-arg
signature only — neither confirmed occurrence needed more, and this
project's own convention is not to generalize past what the real
corpus needs). Re-verified: `iter_files` is still refused, now with a
precise "lambda with parameters" message instead of the old generic
"unsupported expression" one. Even if a parameterized-lambda shape
were added, this specific occurrence would likely still need the
separate, deliberately unfixed `bugs/hard/CODEGEN_args_kwargs_
signature_assumed_forwarding_only.md` gap too (unchanged from this
doc's original assessment below). Doc kept open — NOT deleted, since
the LambdaExpr gap is closed for one of its two confirmed occurrences,
not both. A future session adding parameterized-lambda support (a
second, still-narrower callable-value category, or generalizing `_CPP_
CALLABLE_CTYPE` itself) would close this doc for occurrence #2 too,
modulo the separate args/kwargs-forwarding gap.

## Status (added 2026-08-07, investigated, NOT attempted — feature-sized)

This doc was referenced (as a dangling cross-reference — "referenced
elsewhere... but never actually written") by
`bugs/CODEGEN_generator_function_Lib_pickletools.md` and by task #140's
own doc (`COMPILE_FAIL_Tools_c-analyzer_c_common_fsutil.md`). Written
now since it meets this project's own "recurs ≥2 times" bar for a
dedicated hard-bug doc: two independent confirmed real occurrences (see
below), same root cause both times.

**Root cause:** `_cpp_expr` (the coroutine `.cpp` emission path's
expression lowering) has no `LambdaExpr` case at all — any `lambda`
literal used as a value inside a generator body falls straight through
to the generic "unrecognized node shape" refusal:
```
[gimple_codegen] unsupported expression in generator body: LambdaExpr
```
raised at `gimple_codegen.py`'s `_cpp_expr`, around the final
`raise _UnsupportedGeneratorShape(f"unsupported expression in
generator body: {type(e).__name__}")` fallthrough. Same fatal
whole-module escalation pattern as every other sibling gap in this
cluster when the refused generator is module-level (`gen_module`
re-raises as a hard `RuntimeError`, `fire.py build` produces no object
file at all for the file).

## Confirmed occurrences

- `Lib/pickletools.py`'s `_genops`:
  ```python
  def _genops(data, yield_end_pos=False):
      ...
      if hasattr(data, "tell"):
          getpos = data.tell
      else:
          getpos = lambda: None
      while True:
          pos = getpos()
          ...
          yield opcode, arg, pos
  ```
  `getpos = lambda: None` — a zero-argument lambda whose body is a
  single `None` literal, assigned to a local. The SAME local
  (`getpos`) is ALSO assigned `data.tell` (a bound-method value) on
  the other branch of the `if`/`else` — see "Why this is feature-sized,
  not narrow" below for why that specific detail matters.
- `Tools/c-analyzer/c_common/fsutil.py`'s `iter_files` (task #140,
  found once the file's OWN root-cause bug — task #138's self-recursive
  `yield from` arg-forwarding gap — was fixed and this became the new,
  previously-masked blocker):
  ```python
  get_files = (lambda *a, **k: _walk(*a, walk=_files, **k))
  ```
  A lambda with `*args`/`**kwargs` forwarding params, calling a
  module-level function (`_walk`) with those forwarded args plus an
  extra keyword. This shape additionally overlaps
  `bugs/hard/CODEGEN_args_kwargs_signature_assumed_forwarding_only.md`
  (task #142, deliberately held back for separate dedicated attention)
  — even if `LambdaExpr` itself were supported, this specific
  occurrence would likely still need that separate fix too.

## Why this is feature-sized, not narrow (investigated, not a drive-by fix)

The obvious first idea — since the coroutine path's target IS C++20,
unlike the plain GIMPLE path which has to LIFT every lambda to a
top-level C function (see `_lower_LambdaExpr`'s `_gen_lifted_closure`
machinery, a full second code-generation pass with its own
decls/body_lines/var_types save-restore dance) — is to lower a
`LambdaExpr` directly to a native, capturing C++ lambda expression
(`[&](int64_t a) { return ...; }`), which C++ supports natively and the
plain path's much heavier lifting machinery doesn't even apply to here.

That idea doesn't survive contact with this coroutine codegen's actual
value model, though: `declared` (the per-generator name→C-type map
threaded through `_cpp_stmt`/`_cpp_expr`, see e.g. `_cpp_stmt`'s
`AssignStmt` case, `declared[name] = ctype`) is a closed set of a
handful of concrete scalar/pointer C types — `int64_t`, `double`,
`_Bool`, `char *`, `MojoList *`, `MojoDict *`, `MojoSet *` — used
throughout for explicit `<Type> <name>;` declarations, coercions, and
cast decisions. A C++ lambda's type is an anonymous, uniquely-generated
closure type with no such name — it can only be held as `auto` (not
storable as a named type in a variable declared ahead of its
initializer, which is how every local in this codegen is currently
declared: `Type name; ... name = value;`, needed because Python allows
reassignment/multiple-type-flow through a single name that this model
resolves once, at first assignment) or type-erased into
`std::function<...>`, which needs a known, fixed signature — itself
not always available (see the `getpos` example above, where the
consuming call site `pos = getpos()` matters more than either
individual assignment).

`_genops`'s own `getpos` makes the scope of "just add a LambdaExpr
case" concrete: `getpos` is assigned a `lambda: None` on ONE control-flow
branch and `data.tell` — a bound-method VALUE, itself unsupported by
this model (`MemberExpr` reads only support `self.<scalar field>`, not
an arbitrary object's method as a first-class value) — on the OTHER.
Making `getpos()` work at all needs a genuine "callable-typed local
variable" concept added to this model (a `std::function<int64_t()>`-
shaped declared-type category, at minimum), which does not exist today
in any form — not a one-line widening of an existing branch the way
the `sys.stderr`/list-unpack/full-slice-assignment fixes in
`CODEGEN_generator_non_plain_assignment_target_refused.md` were, each
of which reused an already-present runtime/type facility. This is
"introduce a new value category" work, not "recognize an already-
representable value in a new place" work — feature-sized per this
project's own established bar, matching how
`CODEGEN_generator_struct_typed_param_refused.md` (task #147) and
`CODEGEN_args_kwargs_signature_assumed_forwarding_only.md` (task #142)
were each independently assessed and deliberately deferred for the
same "needs new shared machinery, not a narrow widening" reason.

**Not attempted.** A real fix would need, at minimum: (1) a new
declared-type category for "callable value" (`std::function<Ret(...)>`
or similar, with a real signature-inference story — not just "assume
int64_t" the way every other unknown value defaults), (2) `_cpp_expr`'s
`LambdaExpr` case emitting a native capturing C++ lambda body (the
easy part, once (1) exists), and (3) call-site lowering (`_cpp_expr`'s
`CallExpr` handling) recognizing a locally-held callable value and
invoking it via that same category rather than treating every bare-name
call as either a known module function or an undeclared symbol. Fixing
just (2) alone, ungated by (1)/(3), would either not compile (declaring
a lambda-typed local with one of the existing fixed C types) or need an
`auto`-typed special case threaded through every one of `declared`'s
many existing consumers — the exact "confident-looking change to
shared type-inference machinery" this project's own `CLAUDE.md` and
prior session history (see MEMORY.md's `compiled-generator-codegen-
project` and `general-mut-closure-capture-fix` entries) warn carries
real regression risk, and out of proportion with this task's "narrow,
single-instance-but-fixable gaps" scope.
