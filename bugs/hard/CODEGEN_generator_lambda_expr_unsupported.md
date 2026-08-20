# HARD BUG: `lambda` expressions are entirely unsupported inside a compiled generator body

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
re-raises as a hard `RuntimeError`, `mojo.py build` produces no object
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
