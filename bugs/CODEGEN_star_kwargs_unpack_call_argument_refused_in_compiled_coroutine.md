# A `*`/`**`-unpack call argument through a callable-value local is refused in a compiled generator/coroutine body

## The shape

A `CallExpr` inside a compiled generator/coroutine body whose arguments
include a spread — this project's parser wraps a spread argument in
`UnaryOp(op='*'/'**', operand=...)` — where the callee is a DECLARED
callable-value local of the `*args`/`**kwargs` family (`std::function`
ctype per `gimple_ctypes._cpp_lambda_ctype`, i.e. the local holds a
variadic lambda):

```python
def probe():
    nums = [4, 5]
    f = lambda *a: a[0] + a[1]
    yield f(*nums)        # *x unpack call argument through a declared local
```

`mojo/backend_gimple/cpp_core.py`'s coroutine-body CallExpr handling
refuses EVERY such argument outright ("a `*`/`**`-unpack call argument is
not supported in a compiled generator/coroutine body") — one narrow
exception, `_cpp_try_kwargs_forward_call`, for `f(pos..., **kwargs_var)`
through a STATICALLY-KNOWN local free function (the
`bugs/COMPILE_FAIL_Tools_c-analyzer_c_analyzer___init__.md` shape). A
spread through a callable-value LOCAL never reached any lowering: the
refusal sits ahead of the declared-callable-local branch that the
2026-10-25 session landed for the non-spread call (`e(4, 5)` packs the
arguments into a fresh container in an IIFE).

## Why the refusal is load-bearing, not just a gap

Left unrefused, the argument falls through to the generic UnaryOp case
(`op == '**'` -> literally `(**x)`), which g++ parses as a double
pointer-dereference of a `MojoDict *`/`MojoList *` local — a silent
MISCOMPILE (nonsensical C++), not a missed feature. The refusal comment
at the site names the class; this doc's fix must keep refusing every
shape it cannot PROVE, for the same reason `_cpp_try_kwargs_forward_call`
"never guesses".

## Origin: `Tools/c-analyzer/c_common/fsutil.py`'s `iter_files`

The 2026-10-25 entry in
`bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_fsutil.md` closed the
lambda-VALUE guard (`get_files = lambda *a, **k: _walk(*a, walk=_files,
**k)` now COMPILES as a value) and recorded that the file's refusal moved
one layer down, to the lambda BODY's call:

> a `*`/`**`-unpack call argument is not supported in a compiled
> generator/coroutine body

…calling out the missing piece as "a new, separate capability with a
clean one-line repro once the lambda above is substituted for `_walk`" —
this doc is that capability. Note the fsutil body is the WIDEST form
(`*a` + a named `walk=` keyword + `**k`, through a polymorphic PARAMETER
callee); the one-line repro is the narrow declared-LOCAL form, and fsutil
itself stays blocked on the parameter axis either way (see Scope below).

## The model's convention (why a copy is the right lowering)

C++ cannot subscript a native variadic parameter list, so this model
declares a lambda's `*args`/`**kwargs` as CONTAINER parameters
(`MojoList *`/`MojoDict *`) — the plain (lifted-function) GIMPLE path's
own convention (`emit_calls.py` packs `*args`/`**kwargs` calls into
`MojoList *`/`MojoDict *` the same way). A call `f(*x, **y)` through such
a local therefore passes CONTAINERS, and CPython's own semantics make the
lowering exact: `*x` hands the callee a NEW container holding `x`'s
elements, so the generated C++ passes `mojo_list_copy(x)` /
`mojo_dict_copy(y)` — the runtime's own slot-for-slot / `update`-based
deep copies (the same helpers `copy.copy`'s word emission uses). The copy
is not an optimization: it is what `*` means (a new tuple), and it is what
keeps a body that mutates its own `*args` from writing through the
caller's list.

## Scope landed 2026-10-26 (the pure-spread shape, provably)

`cpp_core.py`'s `_cpp_try_unpack_call` (beside `_cpp_try_kwargs_forward_
call`) returns a lowered C++ expression — or None, never a guess, for
anything else, which falls straight through to the existing honest
refusal. It fires ONLY when ALL of these hold:

1. the callee is an `IdentExpr` name in `gen._cpp_declared` with a
   variadic-family ctype (`_CPP_CALLABLE_CTYPE_STARARGS` / `_KWARGS` /
   `_STAR_KW`);
2. the arguments are PURE spreads — a `*x` and/or a `**y`, at least one,
   `**y` last (CPython orders `f(*x, **y)`; `f(**y, *x)` is a SyntaxError),
   no positional arguments, no named keywords;
3. each spread's operand is a DECLARED container local of the matching
   kind (`MojoList *` for `*x`, `MojoDict *` for `**y` — the runtime kind
   of a boxed `int64_t` local is unproven, and `*`-unpack of a
   non-iterable is a runtime TypeError the model must not manufacture
   into a miscompile);
4. a `*x` is present only where the callee's shape has an `*args` slot
   (STARARGS/STAR_KW) and a `**y` only where it has a `**kwargs` slot
   (KWARGS/STAR_KW) — the combinations CPython itself rejects
   (`TypeError: f() takes keyword arguments` / `positional arguments`);
5. for a `*x` whose SOURCE list's element kind is TRACKED as `char *` or
   `double`, the call is refused instead: the lambda body reads `*args`
   through the int64-box getters (`mojo_list_get_int`), and a copied
   str/double slot would come back as a pointer/bit pattern — the same
   reason the non-spread packing branch (the 2026-10-25 session) refuses
   str/double positional arguments into a `*args` local. Untracked
   element kind is accepted: the copy is slot-for-slot at the runtime,
   so whatever the body's own model says about reading it back, the
   forwarding itself is faithful (the body-side kind limitation is the
   model's documented one, not a forwarding defect).

Lowering (all plain expressions — no IIFE, no new temporaries):

| call | callee shape | generated |
|---|---|---|
| `f(*x)` | STARARGS / STAR_KW | `f(mojo_list_copy(x))` (STAR_KW adds `, mojo_dict_new()` — CPython's empty `**k`) |
| `f(**y)` | KWARGS / STAR_KW | `f(mojo_dict_copy(y))` (STAR_KW adds the `mojo_list_new()` first) |
| `f(*x, **y)` | STAR_KW | `f(mojo_list_copy(x), mojo_dict_copy(y))` |

The call's RESULT typing needs no change: the 2026-10-25 exprtypes fix
already answers the int64 result box for a call through a declared
callable-value local of ANY of the five ctypes, independent of the
arguments.

## Deliberately NOT landed (each an honest refusal, each a named follow-up)

- **Named keywords beside a `**`-spread** (`f(*x, walk=v, **y)`): CPython
  raises `TypeError` at runtime when `y` already holds `walk`; the
  body model cannot raise from generated C++, so merging the dict would
  be a working wrong answer in exactly the class `_cpp_try_kwargs_
  forward_call`'s docstring describes. Refused. (This is what keeps the
  fsutil body itself blocked even with a declared-local callee.)
- **Fixed positional arguments beside a `*`-spread** (`f(1, *x)`): legal
  in CPython, and the lowering is known (append the fixed values, then
  slot-copy `x` — an IIFE), but it is a separate emission with its own
  kind-tracking questions; the pure-spread shape is what the one-line
  repro needs. Refused for now.
- **Spreads through a statically-known MODULE function** (`g(*x)` where
  `g` is a `def g(*a): ...` with a mangled C symbol): the plain path
  forwards this (the fixed-arity slot expansion in `emit_calls.py`), so
  it is a parity case for a follow-up, not a model hole — the callee's
  parameter names/defaults ARE known at compile time there.
- **The fsutil end-to-end shape** (`_walk(*a, walk=_files, **k)` through a
  polymorphic PARAMETER whose call's return a `for` must iterate):
  parameter-callee dispatch + keyword injection + "a `for` over a call
  through a callable-valued local/parameter … what that call RETURNS is
  not knowable" — the OTHER axis the fsutil doc's 2026-10-25 entry
  names, untouched here.

## Tests

`test_gimple_generator_runner.py`, group `run_unpack_call_forward_tests`
(added 2026-10-26): the three lowering shapes (starargs / kwargs /
star-kw, each measured against the interpreter's own answer), the
fsutil-shaped own-parameter spread (`lambda *a, **k: f(*a, **k)`), and
the honest refusals (a named keyword beside a `**`, a positional beside a
`*`, a spread of a boxed `int64_t` local, a `*`-spread of a tracked
str-element list, a `*` through a kwargs-only local, a `**` through a
starargs-only local). Whole runner and `test_gimple.py` re-run green.

## Status 2026-10-26

LANDED (on this branch: `cpp_core.py`'s `_cpp_try_unpack_call` + the
refusal-site dispatch ahead of the one-line refusal, the `GimpleGen`
delegate in `gimple_codegen.py`, the regression group). Measured: the 12
tests above green; whole `test_gimple_generator_runner.py` 253/253
(241 before this group + the 12 above); `test_gimple.py` 396/396,
unchanged. `Tools/c-analyzer/
c_common/fsutil.py` re-measured afterward (same full-package build):
the module-level refusal list is UNCHANGED — the same three generators,
and `iter_files` still at the same one-line refusal, because its callee
is the `_walk` PARAMETER, not a declared local (see Scope); see that
doc's 2026-10-26 entry for the follow-up axis it now names.

Gate verdict 2026-10-26 (commit `a2aedec1`): `make gate` 68 passed, 2
failed of 82 tests (216 jobs, 3210 s wall, peak 37.9 GB). Neither
failure is attributable to this commit:

1. `bootstrap-stage1-transitive` — the documented pre-existing upstream
   red (`elab_intu`'s `next(iter(<dict>))` gap, a separate session's
   file; fails identically on the pre-work baseline and was red on the
   first gate too).
2. `sqliteruntime` — a TIMEOUT, load-induced, not a regression: killed
   at its 600 s wall budget with 6 jobs running in parallel right after
   the 37.9 GB memory check (this gate's wall was 63 % longer than the
   first gate's). A solo re-run on the same tree under the same 4 GB
   memcap is 66/66 checks, exit 0, 68 s, 0.8 GB peak — and emits ZERO
   self-host `# ERROR` lines, where the loaded gate run had emitted six
   transient ones (3× emit_infra's `MojoList*`-to-`MojoSet*` coercion,
   3× elab_intu's dict-iter gap) — all in files this commit does not
   touch, none on the self-compiled `cpp_core.py` itself.
