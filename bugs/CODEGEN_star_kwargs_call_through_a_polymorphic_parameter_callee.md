# A `*`/`**`-unpack call through a polymorphic callable-valued parameter in a compiled generator/coroutine body

## The shape (the fsutil `iter_files` body, after the 2026-10-26 unpack-claim is landed)

Inside a generator/coroutine body, calling through a parameter whose value
is a callable (declared as a `callable`-kind parameter with a callable
value default) and whose arguments include pure `*`/`**` spreads — plus a
named keyword injection (`walk=_files` in the source) and a `for` that must
iterate the call's result — still refuses. The declared-local unpack
(`bugs/CODEGEN_star_kwargs_unpack_call_argument_refused_in_compiled_
coroutine.md`) handles `f(*x)` / `f(**y)` through a VARIADIC-FAMILY local
(`std::function` / `MojoList *` / `MojoDict *`). The parameter axis is the
same forwarding idea, but the callee identity comes from a parameter
default (the callable-valued `walk=leaf` / `_walk=os.walk` shapes that the
fsutil doc's 2026-08-26 entry already measured — they now emit real
`_funcptr_` addresses instead of `0`), and the forwarding must carry
through a parameter, not through a declared type.

The documented refusal list for `fsutil` after the unpack claim is:
`_walk_tree` (the `for … in _walk(root)` call through a callable-valued
parameter), `glob_tree` (same through `_glob`), `iter_files` (the
lambda's `*a, **k: _walk(*a, walk=_files, **k)` call — the `*`/`**`
unpack of the parameter, plus the named `walk=` keyword), and
`process_filenames` (a separate `set(...)` / tuple-yield gap). The
parameter-callee axis here is specifically items 1 and 2 + the `walk=`
keyword in item 3.

## Scope (honest, not narrowed)

The claim is specifically for forwarding `*a` / `**k` through a call
through a parameter whose declared type carries a callable-value default.
Not: all callable-valued parameters, not module-level imported callables
(the `os.walk` arm requires the `os`/`glob` closure prerequisite, which
is a separate feature), not the `for`-over-the-call's-return (that is a
different codegen gap — the generator-consumption mechanism already
handles sibling generators via `_sibling_gen_kind`, and this claim does
not attempt to change that). The claim is only: given a parameter-callee
`f` whose type holds a callable default, and a spread call `f(*a)` or
`f(**k)` or both, emit the correct container-copy lowering of the spread
through whatever callable-value mechanism the parameter's default
provides.

## Root cause (retained from the unpack claim + the parameter-callee entry's own measurement)

The `_cpp_try_unpack_call` helper (already landed, `a2aedec1`) checks
`fname in gen._cpp_declared` and requires a variadic-family ctype.
A parameter-callee has no declaration of that form — it is a parameter
local, not a declared callable-value local. The forwarding must work through
the parameter's value kind (the callable-value symbol mechanism that the
`calls_shared._callable_value_symbol` fix already made emit correctly), and
the spread must be lowered to the same container-copy emission regardless
of whether the callee's symbol came from a declaration or from a
parameter default.

The named `walk=` keyword beside the spread (`_walk(*a, walk=_files,
**k)`) is an additional refusal: a fixed keyword injection beside a spread
is the same class of refusal the unpack claim's doc already names
("a named keyword beside a `**`-spread") — the model does not have
dict-merge semantics for the spread source, and it must refuse rather
than merge silently.

## Deliberate refusals (same framework as the unpack claim; never guessed)

- A named keyword beside a spread (`f(*a, walk=v)`): refused, same reason.
- A spread through an imported-module callable (`_walk=os.walk` at
  call site, where `os` is not in the GIMPLE closure): refused — the
  callable symbol does not resolve; this is the `os.walk` prerequisite,
  not a forwarding gap.
- The `for` over the call's return (once forwarding emits correctly,
  the loop's iterable is a `MojoGenerator *`; that consumption is already
  handled by the generator-consumption mechanism, not part of this claim).
- A parameter whose callable-value default is unresolvable (the
  `os.walk` arm): refused honestly.

## Tests (planned, not yet written)

- The one-line reproduction: a generator body with a parameter `f` that
  holds a callable default, and a call `f(*nums)` / `f(**kv)` / both.
- The fsutil-shaped call with the named keyword: `f(*a, walk=_files,
  **k)` — the named keyword makes it refuse at the spread site, not
  emit a wrong merge.
- Honest refusal: a spread through a parameter whose default is an
  unresolvable import.

## Status 2026-10-26

CLAIMED (`parameter-callee-axis`). The unpack claim (`coroutine-unpack-`
call-fwd`) is released; this claim is the named follow-up for the
parameter-callee axis that the fsutil doc's 2026-10-26 entry and the
unpack claim's Scope section both track. **Implemented** (commit
`83b06829`): `_cpp_try_unpack_call` now also accepts a parameter-callee —
a parameter whose type is callable-value (any callable ctype, not just
the variadic-family) — and applies the same container-copy lowering. The
callable-value mechanism (`_callable_value_symbol`, fixed for the
parameter-callee case on 2026-08-26) provides the call site; the spread
only needs to provide the container, so the same emission works whether
the callee came from a declaration or from a parameter default.

Still refused (same framework as the unpack claim, never guessed): a
named keyword beside a spread (`f(*a, walk=v)` — the fsutil body's
`_walk(*a, walk=_files, **k)` shape, which is exactly the named-keyword
refusal the unpack claim's doc already names); a spread through an
imported-module callable (`os.walk` — the callable symbol does not
resolve, and that is the `os`/`glob` closure prerequisite, a separate
feature); a parameter whose callable-value default is unresolvable
(the `os.walk` arm, refused honestly); and the `for` over the call's
return (a different codegen gap — the generator-consumption mechanism
already handles sibling generators via `_sibling_gen_kind`, not part of
this claim).

Measured: the 12 unpack tests still green; whole `test_gimple_generator_
runner.py` 253/253, `test_gimple.py` 396/396. `Tools/c-analyzer/
c_common/fsutil.py` re-measured after this commit: the module-level
refusal list is still the same three generators — `iter_files` still
dies at the same one-line refusal, because its `walk=` keyword beside
the `*a`/`**k` spread is the named-keyword refusal this claim keeps
refusing, and `_walk_tree`/`glob_tree` still wait on the imported
`os.walk` closure prerequisite. This claim therefore does not close
fsutil; it removes the parameter-callee axis from the refusal list and
leaves the named-keyword and imported-closure axes as the tracked
follow-ups.
