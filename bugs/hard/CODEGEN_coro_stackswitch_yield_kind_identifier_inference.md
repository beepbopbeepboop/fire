# CODEGEN (A3 stack-switch): `yield <identifier-or-member-expr>` always
defaults to int64_t, silently truncating float/string values

## Status

PARTIALLY FIXED 2026-09-05. The tractable, purely-syntactic half is
landed; the fully-unannotated call-site-dependent half (repro 1) remains
open as a distinct structural gap (see "Not fixed" below).

Found 2026-09-05 while running `test_gimple_generator_runner.py`'s real
compile+link+run suite against the §5.5 cutover (`MOJO_CORO=stackswitch`
now the default — see doc/COROUTINE.html §5.5).

### Fixed (commit — see Claude-Session)

`gimple_gen_coro.py` gained `_static_env(fn, struct_def)` — a best-effort,
purely-syntactic `name -> yield-kind` map built at pre-pass time from the
type sources that ARE in reach before `GimpleGen` exists — and
`_yield_kind(expr, env)` now consults it. Resolved shapes:

* **bare identifier from the generator's own param annotation** —
  `def echo(s: String): yield s` (repro-4-shaped; repro 2's `n: Int`
  path).
* **`self.<field>` from the enclosing struct** — class-body field
  annotations AND `__init__`'s `self.<f> = <annotated-param | literal>`
  assignments. Fixes repro 2 (`yield self.base + i`, `base: Float64`).
* **local `name = <literal>` / `var name = <literal-or-string-concat>`** —
  incl. `FloatLiteral`/`StringLiteral` and a `BinaryOp` fallthrough.
* **list-typed locals** — `xs = [<homogeneous literals>]` and
  `xs = []` refined by `xs.append(<literal>)` / `.insert(...)`; a
  `yield xs[i]` subscript and a `for s in xs: yield s` loop-var binding
  both resolve to the element kind. Fixes repro 3.

`_eligible` / `_generator_value_kind` / `_generator_tuple_slots` /
`_lower_one` all thread the env; `_eligible`/`_lower_one` gained an
optional `struct_def` param so the method path passes the `StructDef`
down.

Beyond the 4 new regression tests in `test_gimple_generator_runner.py`,
this also flipped 3 previously-failing suite cases to PASS
(`generator_method_self_field_double`, `generator_str_list_local_
roundtrip`, and the yield-kind half of `generator_vardecl_string_built_
in_body` — that last one still fails on an *unrelated* general
`"s" + String(int)` mis-stringification bug, reproducible outside any
generator, not in this doc's scope).

### Not fixed — the fully-unannotated case (repro 1)

`def g(x): yield x` called `g(3.5)`, with no type anywhere in `g`'s own
definition, still yields `3` (truncated). Resolving it needs per-call-site
monomorphization of the generator or a boxed/tagged yield-value
representation — a real feature, deliberately out of scope here (see the
detailed analysis retained below). `MOJO_CORO=cpp` remains a correct
escape hatch for this shape.

## Repro

```mojo
def g(x):
    yield x

def main():
    for v in g(3.5):
        print(v)
```
Expected `3.5`; prints `3` (the float truncated to int64_t at the yield
site).

```mojo
class Sampler:
    def __init__(self, base: Float64):
        self.base = base
    def samples(self, n: Int):
        i = 0
        while i < n:
            yield self.base + i
            i = i + 1

def main():
    s = Sampler(1.5)
    for x in s.samples(3):
        print(x)
```
Expected `1.5\n2.5\n3.5\n`; prints `1\n2\n3\n`.

```mojo
def strs():
    xs = ["alpha", "beta"]
    i = 0
    while i < 3:
        yield xs[i % 2]
        i = i + 1

def main():
    for s in strs():
        print(s)
```
Expected `alpha\nbeta\nalpha\n`; prints three raw pointer VALUES as huge
decimal integers (the string's `char *` bit pattern reinterpreted as
int64_t) — same root cause, `_yield_kind`'s 'p' (pointer/string) branch
never fires either.

## Root cause (traced)

`gimple_gen_coro.py`'s `_yield_kind(expr)` — the Layer-1 pre-pass's
best-effort static type guess for a yielded value, used to pick the
generator's SINGLE fixed C value-kind ('i'/'p'/'d', `_KIND_TO_SLOT_CTYPE`)
— only recognizes `StringLiteral`/`FloatLiteral`/`IntLiteral`/`BoolLiteral`
and a `BinaryOp` of two such kinds (recursing on `.left`/`.right`). It has
**no case at all** for a bare `IdentExpr` (a parameter or local variable
reference) or a `MemberExpr` (`self.<field>`) — both fall through to the
function's final `return None`, which every caller then treats as "can't
tell" and defaults to `'i'` (`_KIND_TO_SLOT_CTYPE[None] == 'int64_t'`).

This module runs as an AST pre-pass **before** `GimpleGen` (the real
type-inferring compiler) exists (see the module's own top-of-file
docstring), so it has no access to `struct_field_types`/inferred local
types — by design, for the whole file's other rewrites. But two narrower,
purely-syntactic type sources ARE available at this stage and currently
unused by `_yield_kind`:

1. **The enclosing function's own parameter type annotations**
   (`fn.params`, a `(name, ann)` list) — `def samples(self, n: Int)`.
   A bare `yield n` (or a `BinaryOp` involving `n`) could resolve `n`'s
   kind from its own annotation, no cross-function work needed.
2. **A struct's own `__init__`-assigned field type**, when the yielded
   identifier is `self.<field>` and `__init__` does `self.<field> =
   <annotated-param>` (or the field itself carries a class-body
   annotation) — resolvable by scanning the enclosing `StructDef`'s
   `__init__` method, which the AST already has fully built at this
   stage.

Neither is wired in: `_eligible(fn, struct_name=None)` (the function that
already threads a `struct_name` string for the "generator method" check)
never passes the struct's own AST or `fn.params`' annotations down into
`_yield_kind`, and `_generator_value_kind(fn)` calls `_yield_kind(n.value)`
with no context parameter at all.

The **fully unannotated** case (`def g(x): yield x` called `g(3.5)`, no
type anywhere in `g`'s own definition) is a **different, harder,
genuinely structural** gap: resolving it needs either (a) per-call-site
monomorphization (a distinct `g` C symbol per distinct argument-type
combination — a real feature, this codegen has no notion of generic/
untyped-param specialization for a *generator* today, unlike ordinary
functions which apparently DO handle a Float64 argument to an untyped
param correctly per a same-shape non-generator repro checked during this
investigation — the ordinary function call path has SOME dynamic-value
mechanism a generator's fixed single-C-type `_KIND_TO_SLOT_CTYPE` model
doesn't share), or (b) a fully boxed/tagged generic yield-value
representation (this codegen's fixed choice of `int64_t`/`char *`/
`double` per generator is deliberately narrower — see this file's own
`_KIND_TO_SLOT_CTYPE` comment). Not attempted here; flagged as the harder
half of this doc's scope, likely deserving its own follow-on once the
narrower annotated cases are fixed.

## Impact

Any stack-switch-lowered generator that `yield`s a bare identifier or
`self.<field>` reference — rather than a literal or a binary expression
between two literals — of `Float64`/`String` type silently produces wrong
output (a truncated integer, or a raw pointer value printed as a huge
integer) with **no compile error, no runtime diagnostic**. This is a real
regression class exposed by doc/COROUTINE.html §5.5's cutover (making
stack-switch the default) — every one of these shapes passed under the
old cpp-path coroutine emitter, which apparently modeled a generator's
per-yield value type independently. `MOJO_CORO=cpp` remains a fully
correct escape hatch for any Mojo program hitting this shape today.

## Still open

Only the fully-unannotated case (repro 1) — see "Not fixed" under Status.
The narrower tractable half described in this doc is now landed.
